from __future__ import annotations

import json
from collections import Counter

from .project import SurveyProject


def project_timeline(project: SurveyProject, limit: int = 250) -> list[dict]:
    items = project.db.recent_audit(limit)
    friendly = {
        "PROJECT_CREATED": "Project created", "SOURCE_IMPORTED": "Source imported", "CANONICAL_POINTS_IMPORTED": "Points imported",
        "STAGED_IMPORT_COMMITTED": "Staged import committed", "CONTROL_SOLUTION_CREATED": "Control solution calculated",
        "CONTROL_SOLUTION_RESTORED": "Control revision restored", "LEVEL_SOLUTION_RESTORED": "Level revision restored",
        "DELIVERABLE_CREATED": "Deliverable created", "PROJECT_SNAPSHOT_CREATED": "Project snapshot created",
        "PROJECT_SNAPSHOT_RESTORED": "Project snapshot restored", "PROJECT_HEALTH_RUN": "Project Health Check run",
        "BACKGROUND_TASK_COMPLETED": "Background task completed", "BACKGROUND_TASK_FAILED": "Background task failed",
    }
    for item in items:
        item["label"] = friendly.get(item.get("action"), str(item.get("action", "")).replace("_", " ").title())
    return items


def review_center(project: SurveyProject) -> dict:
    items = []
    with project.db.connect() as conn:
        for r in conn.execute("SELECT * FROM qa_issues WHERE status='OPEN' ORDER BY CASE severity WHEN 'ERROR' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END, ts_utc DESC").fetchall():
            d = dict(r); details = json.loads(d.pop("details_json") or "{}")
            items.append({"id": d["issue_id"], "kind": "qa", "severity": d["severity"], "module": d["module"], "title": d["code"], "message": d["message"], "object_id": d.get("object_id", ""), "details": details})
        rows = conn.execute("SELECT point_id,review_state FROM canonical_points WHERE review_state!='REVIEWED' ORDER BY point_id LIMIT 250").fetchall()
        for r in rows:
            items.append({"id": f"point:{r['point_id']}", "kind": "point_review", "severity": "REVIEW", "module": "Core", "title": f"Point {r['point_id']}", "message": f"Point review state is {r['review_state']}.", "object_id": r["point_id"], "details": {"review_state": r["review_state"]}})
        for r in conn.execute("SELECT stage_id,status,source_path,analysis_json FROM import_staging WHERE status IN ('BLOCKED','READY','COMMITTED_WITH_REVIEW') ORDER BY ts_utc DESC LIMIT 100").fetchall():
            analysis = json.loads(r["analysis_json"] or "{}")
            if r["status"] == "READY" and not analysis.get("issues"): continue
            items.append({"id": r["stage_id"], "kind": "import_stage", "severity": "BLOCKING" if r["status"] == "BLOCKED" else "REVIEW", "module": "Core", "title": "Import staging review", "message": f"{r['status']}: {r['source_path']}", "object_id": r["stage_id"], "details": analysis})
        for r in conn.execute("SELECT task_id,kind,label,status,message FROM background_tasks WHERE status='FAILED' ORDER BY created_utc DESC LIMIT 100").fetchall():
            items.append({"id": r["task_id"], "kind": "background_task", "severity": "WARN", "module": "Core", "title": r["label"] or r["kind"], "message": r["message"], "object_id": r["task_id"], "details": {"status": r["status"]}})
    counts = Counter(str(i["severity"]).upper() for i in items)
    return {"count": len(items), "counts": dict(counts), "items": items}


def explain(project: SurveyProject, kind: str, object_id: str) -> dict:
    kind = str(kind or "").lower()
    if kind == "qa":
        with project.db.connect() as conn:
            row = conn.execute("SELECT * FROM qa_issues WHERE issue_id=?", (object_id,)).fetchone()
        if not row: raise ValueError("QA issue was not found.")
        d = dict(row); details = json.loads(d.pop("details_json") or "{}")
        return {"kind": "qa", "title": d["code"], "why": d["message"], "severity": d["severity"], "module": d["module"], "evidence": details, "guidance": details.get("guidance") or "Review the cited project evidence before accepting or exporting the affected work."}
    if kind == "point":
        with project.db.connect() as conn:
            row = conn.execute("SELECT * FROM canonical_points WHERE point_id=? ORDER BY modified_utc DESC LIMIT 1", (object_id,)).fetchone()
        if not row: raise ValueError("Point was not found.")
        d = dict(row)
        return {"kind": "point", "title": f"Point {object_id}", "why": f"This point is currently marked {d.get('review_state','UNREVIEWED')} and came from source {d.get('source_id') or 'unknown'}.", "evidence": {k: d.get(k) for k in ("northing", "easting", "elevation", "description", "crs", "horizontal_units", "vertical_units", "source_id", "review_state")}}
    if kind == "task":
        with project.db.connect() as conn:
            row = conn.execute("SELECT * FROM background_tasks WHERE task_id=?", (object_id,)).fetchone()
        if not row: raise ValueError("Background task was not found.")
        d = dict(row)
        return {"kind": "task", "title": d["label"] or d["kind"], "why": d["message"], "status": d["status"], "evidence": {"error": d.get("error_text", ""), "payload": json.loads(d.get("payload_json") or "{}")}}
    if kind == "import_stage":
        with project.db.connect() as conn:
            row = conn.execute("SELECT * FROM import_staging WHERE stage_id=?", (object_id,)).fetchone()
        if not row: raise ValueError("Staged import was not found.")
        d = dict(row); analysis = json.loads(d.get("analysis_json") or "{}")
        return {"kind": "import_stage", "title": "Import staging review", "why": f"This import is {d.get('status','READY')} because staging found issues that should be reviewed before or after commit.", "status": d.get("status"), "evidence": {"source_path": d.get("source_path"), "mapping": json.loads(d.get("mapping_json") or "{}"), "analysis": analysis}, "guidance": "Correct the column mapping or source data, re-stage the file, then commit only after the preview matches the intended survey data."}
    raise ValueError("Explain kind must be qa, point, task, or import_stage.")


def project_map_geojson(project: SurveyProject) -> dict:
    features = []
    with project.db.connect() as conn:
        for r in conn.execute("SELECT point_id,northing,easting,elevation,description,review_state FROM canonical_points WHERE northing IS NOT NULL AND easting IS NOT NULL").fetchall():
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["easting"], r["northing"]]}, "properties": {"kind": "survey_point", "id": r["point_id"], "elevation": r["elevation"], "description": r["description"], "review_state": r["review_state"]}})
        for r in conn.execute("SELECT structure_id,point_id,northing,easting,elevation,status,code FROM utility_structures WHERE northing IS NOT NULL AND easting IS NOT NULL").fetchall():
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["easting"], r["northing"]]}, "properties": {"kind": "utility_structure", "id": r["structure_id"], "point_id": r["point_id"], "elevation": r["elevation"], "status": r["status"], "code": r["code"]}})
        for r in conn.execute("SELECT control_id,northing,easting,elevation,pass,revision FROM control_solutions c WHERE c.solution_id = COALESCE((SELECT ss.solution_id FROM solution_selections ss WHERE ss.solution_kind='control' AND ss.object_id=c.control_id),(SELECT x.solution_id FROM control_solutions x WHERE x.control_id=c.control_id ORDER BY x.revision DESC LIMIT 1))").fetchall():
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["easting"], r["northing"]]}, "properties": {"kind": "control", "id": r["control_id"], "elevation": r["elevation"], "status": "PASS" if r["pass"] else "REVIEW", "revision": r["revision"]}})
    return {"type": "FeatureCollection", "crs": project.manifest.get("crs", ""), "horizontal_units": project.manifest.get("horizontal_units", ""), "features": features}
