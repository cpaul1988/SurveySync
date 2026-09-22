from __future__ import annotations

import json
from pathlib import Path

from .coordinate_sanity import inspect_points
from .project import SurveyProject, sha256_file
from .qa_rules import load_rules


def _rule(rules: dict, key: str) -> dict:
    return rules.get(key) or {"enabled": False, "severity": "WARN"}


def run_project_qa(project: SurveyProject) -> dict:
    """Project Health Check + centralized QA rules engine.

    The function remains the compatibility entry point for the original v9
    foundation QA endpoint, but v9.2.1 expands it into a whole-project preflight.
    Checks are descriptive and never silently alter survey data.
    """
    rules = load_rules(project)
    checks: list[dict] = []
    errors = warnings = 0

    def add(code: str, name: str, status: str, message: str, *, details: dict | None = None, rule_key: str | None = None):
        nonlocal errors, warnings
        status = str(status).upper()
        if rule_key:
            r = _rule(rules, rule_key)
            if not r.get("enabled", True):
                checks.append({"code": code, "name": name, "status": "SKIP", "message": "Rule disabled.", "details": details or {}, "rule": rule_key})
                return
            if status in {"WARN", "ERROR"}:
                status = str(r.get("severity") or status).upper()
        checks.append({"code": code, "name": name, "status": status, "message": message, "details": details or {}, "rule": rule_key or ""})
        errors += int(status == "ERROR")
        warnings += int(status == "WARN")

    m = project.manifest
    add("HEALTH_MANIFEST", "manifest", "PASS" if m.get("project_id") else "ERROR", "Project identity is present." if m.get("project_id") else "Project ID is missing.")
    add("HEALTH_CRS", "crs", "PASS" if m.get("crs") else "WARN", f"CRS: {m.get('crs')}" if m.get("crs") else "Project CRS is not set; coordinate-aware exports require review.", rule_key="require_crs")
    add("HEALTH_HORIZONTAL_UNITS", "horizontal_units", "PASS" if m.get("horizontal_units") else "ERROR", f"Horizontal units: {m.get('horizontal_units')}" if m.get("horizontal_units") else "Horizontal units are missing.", rule_key="require_horizontal_units")
    add("HEALTH_VERTICAL_UNITS", "vertical_units", "PASS" if m.get("vertical_units") else "WARN", f"Vertical units: {m.get('vertical_units')}" if m.get("vertical_units") else "Vertical units are missing.", rule_key="require_vertical_units")

    # Immutable source evidence.
    for src in project.sources():
        p = project.paths.root / src["stored_path"]
        if not p.exists():
            add("HEALTH_SOURCE_MISSING", "source_integrity", "ERROR", f"Missing immutable source: {src['stored_path']}", details={"source_id": src["source_id"], "stored_path": src["stored_path"]}, rule_key="source_integrity")
            continue
        digest = sha256_file(p)
        ok = digest == src["sha256"]
        add("HEALTH_SOURCE_HASH", "source_integrity", "PASS" if ok else "ERROR", f"Source verified: {src['original_name']}" if ok else f"Source hash mismatch: {src['original_name']}", details={"source_id": src["source_id"], "expected": src["sha256"], "actual": digest}, rule_key="source_integrity")

    with project.db.connect() as conn:
        point_count = int(conn.execute("SELECT COUNT(*) FROM canonical_points").fetchone()[0])
        dup_rows = conn.execute("SELECT point_id,COUNT(*) n FROM canonical_points GROUP BY point_id HAVING COUNT(*)>1 ORDER BY n DESC,point_id").fetchall()
        missing_xy = int(conn.execute("SELECT COUNT(*) FROM canonical_points WHERE northing IS NULL OR easting IS NULL").fetchone()[0])
        missing_z = int(conn.execute("SELECT COUNT(*) FROM canonical_points WHERE elevation IS NULL").fetchone()[0])
        unreviewed = int(conn.execute("SELECT COUNT(*) FROM canonical_points WHERE review_state!='REVIEWED'").fetchone()[0])
        control_failures = [dict(r) for r in conn.execute("""
            SELECT c.control_id,c.solution_id,c.revision,c.pass FROM control_solutions c
            WHERE c.solution_id=COALESCE(
              (SELECT ss.solution_id FROM solution_selections ss WHERE ss.solution_kind='control' AND ss.object_id=c.control_id),
              (SELECT x.solution_id FROM control_solutions x WHERE x.control_id=c.control_id ORDER BY x.revision DESC LIMIT 1)
            ) AND c.pass=0
        """).fetchall()]
        level_rows = [dict(r) for r in conn.execute("""
            SELECT r.run_id,r.name,s.qc_json FROM level_runs r
            JOIN level_solutions s ON s.solution_id=COALESCE(
              (SELECT ss.solution_id FROM solution_selections ss WHERE ss.solution_kind='level' AND ss.object_id=r.run_id),
              (SELECT x.solution_id FROM level_solutions x WHERE x.run_id=r.run_id ORDER BY x.revision DESC LIMIT 1)
            )
        """).fetchall()]
        attachment_rows = [dict(r) for r in conn.execute("SELECT attachment_id,stored_path FROM attachments").fetchall()]
        failed_tasks = int(conn.execute("SELECT COUNT(*) FROM background_tasks WHERE status='FAILED'").fetchone()[0])
        stale_derived = [dict(r) for r in conn.execute("SELECT result_kind,object_id,reason,changed_utc,source_table,source_record_id FROM derived_result_state WHERE state='STALE' ORDER BY changed_utc DESC").fetchall()]
        latest_deliverable = conn.execute("SELECT ts_utc,filename FROM deliverables ORDER BY ts_utc DESC LIMIT 1").fetchone()
        latest_change = conn.execute("SELECT ts_utc,action FROM audit_events WHERE action IN ('SOURCE_IMPORTED','CANONICAL_POINTS_IMPORTED','STAGED_IMPORT_COMMITTED','CONTROL_SOLUTION_CREATED','LEVEL_SOLUTION_CREATED','TRAVERSE_SOLUTION_CREATED','UTILITY_FIELD_BOOK_SYNCED') ORDER BY ts_utc DESC LIMIT 1").fetchone()

    max_dup = int(_rule(rules, "duplicate_point_ids").get("max_allowed", 0))
    add("HEALTH_DUPLICATE_POINT_IDS", "duplicate_point_ids", "ERROR" if len(dup_rows) > max_dup else "PASS", f"{len(dup_rows)} duplicate PointID value(s) found." if dup_rows else "PointIDs are unique.", details={"duplicates": [{"point_id": r["point_id"], "count": r["n"]} for r in dup_rows[:50]]}, rule_key="duplicate_point_ids")
    max_missing_xy = int(_rule(rules, "missing_point_coordinates").get("max_allowed", 0))
    add("HEALTH_MISSING_COORDINATES", "missing_point_coordinates", "ERROR" if missing_xy > max_missing_xy else "PASS", f"{missing_xy} point(s) are missing Northing/Easting." if missing_xy else "All canonical points have Northing/Easting.", details={"count": missing_xy}, rule_key="missing_point_coordinates")
    max_z_ratio = float(_rule(rules, "missing_elevations").get("max_ratio", 0.25))
    z_ratio = (missing_z / point_count) if point_count else 0.0
    add("HEALTH_MISSING_ELEVATIONS", "missing_elevations", "WARN" if point_count and z_ratio > max_z_ratio else "PASS", f"{missing_z} of {point_count} point(s) are missing elevation." if point_count else "No canonical points are loaded.", details={"missing": missing_z, "total": point_count, "ratio": z_ratio}, rule_key="missing_elevations")
    max_unreviewed = int(_rule(rules, "unreviewed_points").get("max_allowed", 0))
    add("HEALTH_UNREVIEWED_POINTS", "unreviewed_points", "WARN" if unreviewed > max_unreviewed else "PASS", f"{unreviewed} point(s) still require review." if unreviewed else "No canonical points are awaiting review.", details={"count": unreviewed}, rule_key="unreviewed_points")
    add("HEALTH_CONTROL_FAILURES", "control_failures", "ERROR" if control_failures else "PASS", f"{len(control_failures)} active control solution(s) are outside selected tolerance." if control_failures else "No active control solution is currently marked failed.", details={"controls": control_failures}, rule_key="control_failures")

    level_flags = []
    for row in level_rows:
        try: qc = json.loads(row.get("qc_json") or "{}")
        except Exception: qc = {}
        flags = list(qc.get("qc_flags") or [])
        if flags: level_flags.append({"run_id": row["run_id"], "name": row["name"], "flags": flags})
    add("HEALTH_LEVEL_QC", "level_qc_flags", "WARN" if level_flags else "PASS", f"{len(level_flags)} level run(s) have QC flags." if level_flags else "No active level solution has QC flags.", details={"runs": level_flags}, rule_key="level_qc_flags")

    broken_attachments = []
    for row in attachment_rows:
        stored = Path(row["stored_path"])
        if not stored.is_absolute(): stored = project.paths.root / stored
        if not stored.exists(): broken_attachments.append(row)
    add("HEALTH_BROKEN_ATTACHMENTS", "broken_attachments", "WARN" if broken_attachments else "PASS", f"{len(broken_attachments)} attachment file(s) are missing." if broken_attachments else "All registered attachments are available.", details={"attachments": broken_attachments[:50]}, rule_key="broken_attachments")
    add("HEALTH_FAILED_TASKS", "failed_background_tasks", "WARN" if failed_tasks else "PASS", f"{failed_tasks} background task(s) have failed and should be reviewed." if failed_tasks else "No failed background tasks are recorded.", details={"count": failed_tasks}, rule_key="failed_background_tasks")
    add("HEALTH_STALE_DERIVED_RESULTS", "stale_derived_results", "WARN" if stale_derived else "PASS", f"{len(stale_derived)} calculated result set(s) are stale because their source data was edited." if stale_derived else "No calculated results are marked stale.", details={"results": stale_derived[:100]}, rule_key="stale_derived_results")

    sanity = inspect_points(project)
    add("HEALTH_COORDINATE_SANITY", "coordinate_sanity", "WARN" if sanity.get("flags") else "PASS", f"Coordinate sanity raised {len(sanity.get('flags') or [])} review flag(s)." if sanity.get("flags") else "Coordinate ranges are internally plausible for the current project context.", details=sanity, rule_key="coordinate_sanity")

    stale = False
    if latest_change and latest_deliverable:
        stale = str(latest_change["ts_utc"]) > str(latest_deliverable["ts_utc"])
    elif latest_change and not latest_deliverable:
        stale = True
    add("HEALTH_STALE_OUTPUTS", "deliverable_freshness", "WARN" if stale else "PASS", "Project data changed after the most recent deliverable; regenerate outputs before issue." if stale else ("Latest deliverable is not older than the latest tracked data change." if latest_deliverable else "No tracked data changes require a deliverable yet."), details={"latest_change": dict(latest_change) if latest_change else None, "latest_deliverable": dict(latest_deliverable) if latest_deliverable else None})

    fb = project.paths.fieldbook_root
    add("HEALTH_FIELDBOOK_WORKSPACE", "fieldbook_workspace", "PASS" if fb.exists() else "ERROR", "FieldBookSync module workspace is available." if fb.exists() else "FieldBookSync workspace is missing.")

    # Replace the previous automated health findings instead of accumulating the
    # same issue on every preflight run.
    project.db.supersede_qa_by_prefix("QASync", "HEALTH_")
    for c in checks:
        if c["status"] in {"WARN", "ERROR"}:
            project.db.add_qa("QASync", c["status"], c["code"], c["message"], details={**c.get("details", {}), "rule": c.get("rule", ""), "guidance": "Open the Review Center or use Why? for the supporting evidence."})
    readiness = "BLOCKING" if errors else ("REVIEW" if warnings else "READY")
    project.db.audit("QASync", "PROJECT_HEALTH_RUN", object_type="project", object_id=m.get("project_id", ""), revision=m.get("revision", 0), details={"errors": errors, "warnings": warnings, "checks": len(checks), "readiness": readiness})
    return {"status": "FAIL" if errors else ("WARN" if warnings else "PASS"), "readiness": readiness, "errors": errors, "warnings": warnings, "checks": checks, "rules": rules}
