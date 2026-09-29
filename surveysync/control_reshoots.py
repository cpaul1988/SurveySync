"""Audited, project-local reshoot handoff for ControlSync."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import tempfile
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from .audit import AuditDB, utc_now
from .control import (
    get_control_qc_run,
    import_observations,
    next_reshoot_point_ids,
    parse_control_source,
    run_best_triplet_qc,
)
from .reporting import register_deliverable


def _path(project):
    return project.paths.module_root / "ControlSync" / "reshoots.json"


def _state(project):
    path = _path(project)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"requests": []}


def _save(project, state):
    path = _path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _find(state, identifier):
    item = next((r for r in state["requests"] if r["id"] == identifier), None)
    if item is None:
        raise ValueError("Reshoot request not found in this project.")
    return item


def list_requests(project):
    return _state(project)["requests"]


def _result(run, control_id):
    return next((r for r in run.get("results", []) if r["control_id"] == control_id), None)


def _fingerprint(project):
    # Any concurrent observation or grouping edit can change the best-three choice.
    with project.db.connect() as conn:
        rows = [tuple(r) for r in conn.execute("SELECT * FROM control_observations ORDER BY observation_id")]
        overrides = [tuple(r) for r in conn.execute("SELECT * FROM control_group_overrides ORDER BY observation_id")]
    payload = json.dumps([rows, overrides, project.coordinate_settings()], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def create_request(project, run_id, control_id, crew, instructions):
    if not crew.strip() or len(instructions.strip()) < 3:
        raise ValueError("Crew and field instructions are required.")
    run = get_control_qc_run(project.db, run_id)
    if not run or get_control_qc_run(project.db).get("run_id") != run_id:
        raise ValueError("Run Control QC again and request reshoots from its latest result.")
    if run.get("coordinate_context") != project.coordinate_settings():
        raise ValueError("Project coordinate context changed since this QC run.")
    result = _result(run, control_id)
    if not result or result["status"] != "RESHOOT":
        raise ValueError("Choose a failed control from a stored QC run.")
    state = _state(project)
    if any(r["control_id"] == control_id and r["status"] in {"OPEN", "STAGED"} for r in state["requests"]):
        raise ValueError("This control already has an open reshoot request.")
    with project.db.connect() as conn:
        occupied = [r[0] for r in conn.execute("SELECT point_id FROM control_observations")]
    occupied.extend(p for r in state["requests"] if r["status"] in {"OPEN", "STAGED"} for p in r["reserved_point_ids"])
    count = len(result.get("reshoot_point_ids") or [])
    if not count:
        raise ValueError("The QC run did not propose replacement shot IDs.")
    reserved = next_reshoot_point_ids(control_id, occupied, count)
    item = {"id": uuid4().hex, "status": "OPEN", "created_utc": utc_now(),
            "control_id": control_id, "original_run_id": run_id, "before": result,
            "reserved_point_ids": reserved, "crew": crew.strip(), "instructions": instructions.strip(),
            "coordinate_context": project.coordinate_settings(), "return": None, "review": None}
    state["requests"].append(item)
    _save(project, state)
    project.db.audit("ControlSync", "CONTROL_RESHOOT_REQUESTED", object_type="control_reshoot", object_id=item["id"],
                     details={"control_id": control_id, "run_id": run_id, "reserved_point_ids": reserved, "crew": crew})
    return item


def request_package(project, identifier):
    item = _find(_state(project), identifier)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["PointID", "ControlID", "Northing", "Easting", "Elevation", "ObservedUTC", "EpochCount", "DurationSeconds", "SatelliteCount", "PDOP", "HDOP", "VDOP"])
    for point_id in item["reserved_point_ids"]:
        writer.writerow([point_id, item["control_id"], "", "", "", "", "", "", "", "", "", ""])
    blob = io.BytesIO()
    with ZipFile(blob, "w", ZIP_DEFLATED) as archive:
        archive.writestr("Request.json", json.dumps({k: item[k] for k in ("id", "control_id", "original_run_id", "reserved_point_ids", "crew", "instructions", "coordinate_context", "before")}, indent=2))
        archive.writestr("Returned_Control_Template.csv", output.getvalue())
    return blob.getvalue()


def _qc_settings(run):
    field = run.get("field_requirements") or {}
    return {"horizontal_tolerance": run["horizontal_tolerance"], "vertical_tolerance": run["vertical_tolerance"],
            "coordinate_context": run.get("coordinate_context") or {},
            "require_field_metadata": bool(field.get("enforced")),
            "min_time_separation_minutes": field.get("min_time_separation_minutes", 60),
            "min_epochs": field.get("min_epochs", 300), "min_duration_seconds": field.get("min_duration_seconds", 300),
            "min_satellites": field.get("min_satellites", 5),
            "max_pdop": field.get("max_pdop"), "max_hdop": field.get("max_hdop"), "max_vdop": field.get("max_vdop"),
            "spatial_group_tolerance": (run.get("spatial_grouping") or {}).get("tolerance"),
            "vertical_group_tolerance": (run.get("spatial_grouping") or {}).get("vertical_tolerance")}


def _preview(project, item, rows):
    run = get_control_qc_run(project.db, item["original_run_id"])
    with tempfile.TemporaryDirectory(prefix="control-reshoot-") as folder:
        temporary = Path(folder) / "preview.db"
        with project.db.connect() as source, sqlite3.connect(temporary) as target:
            source.backup(target)
        scratch = AuditDB(temporary)
        if import_observations(scratch, rows) != len(rows):
            raise ValueError("Returned observations duplicate existing project shots.")
        result = run_best_triplet_qc(scratch, only_control_id=item["control_id"], **_qc_settings(run))
    after = _result(result, item["control_id"])
    if not after:
        raise ValueError("Returned observations did not form the requested control group.")
    selected = (after.get("selected") or {}).get("point_ids") or []
    return {"status": after["status"], "reason": after["reason"], "selected": after.get("selected"),
            "uses_returned_shot": bool(set(selected) & set(item["reserved_point_ids"])),
            "before_status": item["before"]["status"], "before_selected": item["before"].get("selected")}


def stage_return(project, identifier, file_path, mapping=None):
    state = _state(project)
    item = _find(state, identifier)
    if item["status"] != "OPEN":
        raise ValueError("Only an open request can receive a returned file.")
    if item["coordinate_context"] != project.coordinate_settings():
        raise ValueError("Project coordinate context changed since the reshoot request.")
    path = Path(file_path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in {".csv", ".txt", ".tsv", ".job", ".jxl", ".xml"}:
        raise ValueError("Choose an existing CSV/TXT/TSV or Trimble JOB/JobXML file.")
    if path.stat().st_size > 25_000_000:
        raise ValueError("Returned file exceeds 25 MB.")
    with tempfile.TemporaryDirectory(prefix="control-return-parse-") as work:
        parsed = parse_control_source(path, Path(work), mapping=mapping)
    rows = parsed["observations"]
    expected = {p.casefold() for p in item["reserved_point_ids"]}
    selected = [r for r in rows if str(r.get("point_id") or "").casefold() in expected]
    actual = [str(r.get("point_id") or "").casefold() for r in selected]
    if len(selected) != len(expected) or set(actual) != expected or len(set(actual)) != len(actual):
        raise ValueError("Return must contain exactly one observation for each reserved PointID.")
    if any(str(r.get("control_id") or "").casefold() != item["control_id"].casefold() for r in selected):
        raise ValueError("A returned shot is assigned to another control group.")
    fingerprint = _fingerprint(project)
    preview = _preview(project, item, selected)
    source = project.import_source(path, "ControlSync", "Staged reshoot source; observations await reviewer approval")
    item["return"] = {"source_id": source["source_id"], "stored_path": source["stored_path"],
                      "sha256": source["sha256"], "filename": path.name, "rows": selected,
                      "ignored_point_ids": [str(r.get("point_id") or "") for r in rows if r not in selected][:100],
                      "fingerprint": fingerprint, "preview": preview, "staged_utc": utc_now()}
    item["status"] = "STAGED"
    _save(project, state)
    project.db.audit("ControlSync", "CONTROL_RESHOOT_STAGED", object_type="control_reshoot", object_id=identifier,
                     details={"source_id": source["source_id"], "sha256": source["sha256"], "preview_status": preview["status"]})
    return item


def review_return(project, identifier, decision, reviewer, note):
    state = _state(project)
    item = _find(state, identifier)
    if item["status"] != "STAGED":
        raise ValueError("Stage a returned file before reviewing it.")
    if decision not in {"APPROVE", "REJECT"} or not reviewer.strip() or len(note.strip()) < 3:
        raise ValueError("Reviewer, decision and a reason of at least three characters are required.")
    staged = item["return"]
    if decision == "REJECT":
        item["status"] = "REJECTED"
        item["review"] = {"decision": decision, "reviewer": reviewer.strip(), "note": note.strip(), "reviewed_utc": utc_now()}
        _save(project, state)
        project.db.audit("ControlSync", "CONTROL_RESHOOT_REJECTED", object_type="control_reshoot", object_id=identifier, details=item["review"])
        return item
    if _fingerprint(project) != staged["fingerprint"]:
        raise ValueError("Control observations or project context changed after staging. Create a new review request.")
    source_path = Path(staged["stored_path"])
    if not source_path.is_absolute():
        source_path = project.paths.root / source_path
    if not source_path.resolve().is_relative_to(project.paths.root.resolve()) or hashlib.sha256(source_path.read_bytes()).hexdigest() != staged["sha256"]:
        raise ValueError("Staged source changed or is outside this project.")
    preview = _preview(project, item, staged["rows"])
    if preview["status"] != "PASS" or not preview["uses_returned_shot"]:
        raise ValueError("Returned shots must pass QC and contribute to the selected triplet before approval.")
    run = get_control_qc_run(project.db, item["original_run_id"])
    with project.db.transaction():
        if import_observations(project.db, staged["rows"], staged["source_id"]) != len(staged["rows"]):
            raise ValueError("Returned observations changed before approval.")
        approved_run = run_best_triplet_qc(project.db, only_control_id=item["control_id"], **_qc_settings(run))
        after = _result(approved_run, item["control_id"])
        if not after or after["status"] != "PASS" or not set(after["selected"]["point_ids"]) & set(item["reserved_point_ids"]):
            raise ValueError("Final Control QC no longer matches the approved preview.")
    item["status"] = "APPROVED"
    item["review"] = {"decision": decision, "reviewer": reviewer.strip(), "note": note.strip(),
                      "reviewed_utc": utc_now(), "approved_run_id": approved_run["run_id"], "after": after}
    _save(project, state)
    project.db.audit("ControlSync", "CONTROL_RESHOOT_APPROVED", object_type="control_reshoot", object_id=identifier,
                     details={"reviewer": reviewer.strip(), "source_id": staged["source_id"], "run_id": approved_run["run_id"], "point_ids": after["selected"]["point_ids"]})
    return item


def approved_package(project, identifier):
    state = _state(project)
    item = _find(state, identifier)
    if item["status"] != "APPROVED":
        raise ValueError("A reviewer must approve a passing return before export.")
    if item.get("export"):
        path = project.paths.reports / f"Control_Reshoot_Approved_{identifier}.zip"
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != item["export"]["sha256"]:
            raise ValueError("Approved package changed since it was created.")
        return content
    after = item["review"]["after"]
    selected = after["selected"]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["ControlID", "Northing", "Easting", "Elevation", "HorizontalResidual", "VerticalResidual", "SourcePointIDs", "QCStatus"])
    writer.writerow([item["control_id"], selected["northing"], selected["easting"], selected.get("elevation"),
                     selected["max_horizontal_residual"], selected["max_vertical_residual"], ";".join(selected["point_ids"]), "PASS"])
    path = project.paths.reports / f"Control_Reshoot_Approved_{identifier}.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("Accepted_Control.csv", output.getvalue())
        archive.writestr("Review.json", json.dumps({"request": {k: item[k] for k in ("id", "control_id", "original_run_id", "reserved_point_ids", "crew", "instructions", "before")},
                                                   "return": {k: item["return"][k] for k in ("source_id", "sha256", "filename", "ignored_point_ids", "preview")},
                                                   "review": item["review"]}, indent=2))
    registered = register_deliverable(project, path, module="ControlSync", kind="approved_reshoot", metadata={"request_id": identifier, "run_id": item["review"]["approved_run_id"]})
    item["export"] = {"sha256": registered["sha256"], "deliverable_id": registered["deliverable_id"]}
    _save(project, state)
    project.db.audit("ControlSync", "CONTROL_RESHOOT_EXPORTED", object_type="control_reshoot", object_id=identifier,
                     details={"path": str(path.relative_to(project.paths.root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return path.read_bytes()
