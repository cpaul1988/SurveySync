"""Project-bound, reviewed three-wire level-loop rechecks."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from .audit import utc_now
from .leveling import _load_observations, apply_recheck_sight, solution_history, solve_level_run, solve_saved_run
from .reporting import register_deliverable
from .survey_validation import finite_number


def _path(project):
    return project.paths.module_root / "ControlSync" / "level_rechecks.json"


def _state(project):
    path = _path(project)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"requests": []}


def _save(project, state):
    path = _path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _find(state, identifier):
    item = next((x for x in state["requests"] if x["id"] == identifier), None)
    if item is None:
        raise ValueError("Level recheck request was not found in this project.")
    return item


def list_requests(project):
    return _state(project)["requests"]


def _active_solution(project, run_id):
    return next((x for x in solution_history(project.db, run_id) if x["active"]), None)


def _fingerprint(project, run_id):
    with project.db.connect() as conn:
        run = tuple(conn.execute("SELECT * FROM level_runs WHERE run_id=?", (run_id,)).fetchone() or [])
        rows = [tuple(x) for x in conn.execute("SELECT * FROM level_observations WHERE run_id=? ORDER BY sequence_no", (run_id,))]
        sights = [tuple(x) for x in conn.execute("SELECT * FROM level_recheck_sights WHERE run_id=? AND active=1 ORDER BY sequence_no,side", (run_id,))]
    active = _active_solution(project, run_id)
    value = json.dumps([run, rows, sights, active["solution_id"] if active else None], sort_keys=True, default=str)
    return hashlib.sha256(value.encode()).hexdigest()


def _sights_for_setup(layout, setup_no, rows):
    if layout == "differential_setups":
        keys = [(setup_no, "BS"), (setup_no, "FS")]
    elif layout == "separate_sights":
        keys = [(2 * setup_no - 1, "BS"), (2 * setup_no, "FS")]
    elif layout == "station_rows":
        keys = [(setup_no, "BS"), (setup_no + 1, "FS")]
    else:
        raise ValueError("Solve the level run with an explicit row layout before requesting a recheck.")
    by_seq = {row["sequence_no"]: row for row in rows}
    if any(seq not in by_seq or not (by_seq[seq].get("backsight" if side == "BS" else "foresight") is not None
                                       or by_seq[seq].get(("bs" if side == "BS" else "fs") + "_middle") is not None) for seq, side in keys):
        raise ValueError("The selected setup has no complete BS/FS sight pair.")
    return [{"sequence_no": seq, "side": side, "point_id": by_seq[seq]["point_id"]} for seq, side in keys]


def create_request(project, run_id, setup_no, closure_tolerance, crew, instructions):
    if not crew.strip() or len(instructions.strip()) < 3:
        raise ValueError("Crew and field instructions are required.")
    tol = finite_number(closure_tolerance, "Closure tolerance")
    if tol <= 0:
        raise ValueError("Set a positive closure tolerance for this run.")
    active = _active_solution(project, run_id)
    if not active:
        raise ValueError("Solve the level run before issuing a recheck.")
    run, rows = _load_observations(project.db, run_id)
    if run["known_end_elevation"] is None:
        raise ValueError("A known ending benchmark is required to review level closure.")
    layout = active["settings"]["row_layout"]
    count = len(rows) if layout == "differential_setups" else len(rows) // 2 if layout == "separate_sights" else len(rows) - 1
    if not 1 <= setup_no <= count:
        raise ValueError("Choose an existing setup number in this level run.")
    state = _state(project)
    if any(x["run_id"] == run_id and x["setup_no"] == setup_no and x["status"] in {"OPEN", "STAGED"} for x in state["requests"]):
        raise ValueError("This setup already has an open recheck request.")
    sights = _sights_for_setup(layout, setup_no, rows)
    item = {"id": uuid4().hex, "status": "OPEN", "created_utc": utc_now(), "run_id": run_id,
            "run_name": run["name"], "setup_no": setup_no, "sights": sights, "row_layout": layout,
            "base_solution_id": active["solution_id"], "before": {"closure": active["closure"], "qc": active["qc"], "revision": active["revision"]},
            "settings": {**active["settings"], "closure_tolerance": tol}, "start_elevation": run["start_elevation"],
            "known_end_elevation": run["known_end_elevation"], "adjustment_method": active["method"],
            "crew": crew.strip(), "instructions": instructions.strip(), "return": None, "review": None}
    state["requests"].append(item)
    _save(project, state)
    project.db.audit("ControlSync", "LEVEL_RECHECK_REQUESTED", object_type="level_recheck", object_id=item["id"],
                     details={"run_id": run_id, "setup_no": setup_no, "sights": sights, "closure_tolerance": tol})
    return item


def request_package(project, identifier):
    item = _find(_state(project), identifier)
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["SequenceNo", "PointID", "Side", "Upper", "Middle", "Lower", "Distance", "Notes"])
    for sight in item["sights"]:
        writer.writerow([sight["sequence_no"], sight["point_id"], sight["side"], "", "", "", "", ""])
    data = io.BytesIO()
    with ZipFile(data, "w", ZIP_DEFLATED) as archive:
        archive.writestr("Request.json", json.dumps({k: item[k] for k in ("id", "run_id", "run_name", "setup_no", "sights", "before", "settings", "crew", "instructions")}, indent=2))
        archive.writestr("Returned_Level_Template.csv", out.getvalue())
    return data.getvalue()


def _parse_return(path, item):
    if path.suffix.lower() not in {".csv", ".txt", ".tsv"} or not path.is_file() or path.stat().st_size > 5_000_000:
        raise ValueError("Choose an existing level return CSV/TXT/TSV under 5 MB.")
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")
        required = {"SequenceNo", "PointID", "Side", "Upper", "Middle", "Lower"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("Return must use the crew template columns, including all three wires.")
        expected = {(x["sequence_no"], x["side"]): x["point_id"] for x in item["sights"]}
        rows = []
        seen = set()
        for raw in reader:
            key = (int(raw["SequenceNo"]), (raw["Side"] or "").strip().upper())
            if key not in expected or key in seen or (raw["PointID"] or "").strip() != expected[key]:
                raise ValueError("Returned sights must match each requested sequence, side and PointID exactly once.")
            seen.add(key)
            values = {wire.lower(): finite_number(raw[wire], wire) for wire in ("Upper", "Middle", "Lower")}
            if not values["upper"] > values["middle"] > values["lower"]:
                raise ValueError("Three-wire readings must be ordered upper > middle > lower.")
            distance = (raw.get("Distance") or "").strip()
            values["distance"] = finite_number(distance, "Distance") if distance else None
            if values["distance"] is not None and values["distance"] < 0:
                raise ValueError("Sight distance cannot be negative.")
            rows.append({"sequence_no": key[0], "side": key[1], "point_id": expected[key], "readings": values,
                         "notes": (raw.get("Notes") or "").strip()})
        if seen != set(expected):
            raise ValueError("Return must contain both requested BS and FS sights.")
    return rows


def _preview(project, item, sights):
    _, rows = _load_observations(project.db, item["run_id"])
    by_seq = {r["sequence_no"]: r for r in rows}
    for sight in sights:
        apply_recheck_sight(by_seq[sight["sequence_no"]], sight["side"], sight["readings"])
    settings = item["settings"]
    result = solve_level_run(rows, start_elevation=item["start_elevation"], known_end_elevation=item["known_end_elevation"],
                             adjustment_method=item["adjustment_method"], middle_wire_tolerance=settings.get("middle_wire_tolerance", .005),
                             max_distance_imbalance=settings.get("max_distance_imbalance"), closure_tolerance=settings["closure_tolerance"],
                             stadia_multiplier=settings.get("stadia_multiplier", 100), calculation_profile=settings.get("calculation_profile", "ron_workbook"),
                             row_layout=item["row_layout"])
    return {"status": "PASS" if result["closure_pass"] and not result["qc_flags"] else "REVIEW",
            "closure": result["closure"], "closure_pass": result["closure_pass"], "distance_imbalance": result["distance_imbalance"],
            "qc_flags": result["qc_flags"], "rows": [r for r in result["results"] if r["sequence_no"] in {s["sequence_no"] for s in sights}]}


def stage_return(project, identifier, file_path):
    state = _state(project)
    item = _find(state, identifier)
    if item["status"] != "OPEN":
        raise ValueError("Only an open level recheck can receive a return.")
    if _active_solution(project, item["run_id"])["solution_id"] != item["base_solution_id"]:
        raise ValueError("Active level solution changed since this request.")
    path = Path(file_path).expanduser().resolve()
    sights = _parse_return(path, item)
    fingerprint = _fingerprint(project, item["run_id"])
    preview = _preview(project, item, sights)
    source = project.import_source(path, "ControlSync", "Staged level recheck; readings await approval")
    item["return"] = {"source_id": source["source_id"], "stored_path": source["stored_path"],
                      "sha256": source["sha256"], "filename": path.name, "sights": sights,
                      "fingerprint": fingerprint, "preview": preview, "staged_utc": utc_now()}
    item["status"] = "STAGED"
    _save(project, state)
    project.db.audit("ControlSync", "LEVEL_RECHECK_STAGED", object_type="level_recheck", object_id=identifier,
                     details={"source_id": source["source_id"], "sha256": source["sha256"], "preview": preview["status"]})
    return item


def review_return(project, identifier, decision, reviewer, note):
    state = _state(project)
    item = _find(state, identifier)
    if item["status"] != "STAGED":
        raise ValueError("Stage the returned level readings before review.")
    if decision not in {"APPROVE", "REJECT"} or not reviewer.strip() or len(note.strip()) < 3:
        raise ValueError("Reviewer, decision and a reason of at least three characters are required.")
    if decision == "REJECT":
        item["status"] = "REJECTED"
        item["review"] = {"decision": decision, "reviewer": reviewer.strip(), "note": note.strip(), "reviewed_utc": utc_now()}
        _save(project, state)
        project.db.audit("ControlSync", "LEVEL_RECHECK_REJECTED", object_type="level_recheck", object_id=identifier, details=item["review"])
        return item
    returned = item["return"]
    if _fingerprint(project, item["run_id"]) != returned["fingerprint"]:
        raise ValueError("Level run or active solution changed after staging. Create a new recheck request.")
    path = Path(returned["stored_path"])
    if not path.is_absolute():
        path = project.paths.root / path
    if not path.resolve().is_relative_to(project.paths.root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != returned["sha256"]:
        raise ValueError("Staged level source changed or is outside this project.")
    preview = _preview(project, item, returned["sights"])
    if preview["status"] != "PASS":
        raise ValueError("Returned level loop must pass closure and sight QC before approval.")
    settings = item["settings"]
    with project.db.transaction() as conn:
        for sight in returned["sights"]:
            conn.execute("UPDATE level_recheck_sights SET active=0 WHERE run_id=? AND sequence_no=? AND side=? AND active=1",
                         (item["run_id"], sight["sequence_no"], sight["side"]))
            conn.execute("INSERT INTO level_recheck_sights(sight_id,run_id,sequence_no,side,request_id,source_id,readings_json,approved_utc,active) VALUES(?,?,?,?,?,?,?,?,1)",
                         (uuid4().hex, item["run_id"], sight["sequence_no"], sight["side"], identifier, returned["source_id"],
                          json.dumps(sight["readings"], sort_keys=True), utc_now()))
        solved = solve_saved_run(project.db, item["run_id"], start_elevation=item["start_elevation"],
                                 known_end_elevation=item["known_end_elevation"], adjustment_method=item["adjustment_method"],
                                 middle_wire_tolerance=settings.get("middle_wire_tolerance", .005),
                                 max_distance_imbalance=settings.get("max_distance_imbalance"), closure_tolerance=settings["closure_tolerance"],
                                 stadia_multiplier=settings.get("stadia_multiplier", 100), calculation_profile=settings.get("calculation_profile", "ron_workbook"),
                                 row_layout=item["row_layout"])
        if solved["closure_pass"] is not True or solved["qc_flags"]:
            raise ValueError("Final level solution no longer matches the passing preview.")
    item["status"] = "APPROVED"
    item["review"] = {"decision": decision, "reviewer": reviewer.strip(), "note": note.strip(), "reviewed_utc": utc_now(),
                      "solution_id": solved["solution_id"], "revision": solved["revision"], "after": preview}
    _save(project, state)
    project.db.audit("ControlSync", "LEVEL_RECHECK_APPROVED", object_type="level_recheck", object_id=identifier,
                     details={"run_id": item["run_id"], "solution_id": solved["solution_id"], "source_id": returned["source_id"]})
    return item


def approved_package(project, identifier):
    state = _state(project)
    item = _find(state, identifier)
    if item["status"] != "APPROVED":
        raise ValueError("Approve a passing level return before export.")
    path = project.paths.reports / f"Level_Recheck_Approved_{identifier}.zip"
    if item.get("export"):
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != item["export"]["sha256"]:
            raise ValueError("Approved level package changed since creation.")
        return content
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["RunID", "SetupNo", "BeforeClosure", "AfterClosure", "ClosureTolerance", "Revision", "QCStatus"])
    writer.writerow([item["run_id"], item["setup_no"], item["before"]["closure"], item["review"]["after"]["closure"],
                     item["settings"]["closure_tolerance"], item["review"]["revision"], "PASS"])
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("Accepted_Level.csv", output.getvalue())
        archive.writestr("Review.json", json.dumps({"request": {k: item[k] for k in ("id", "run_id", "setup_no", "sights", "before", "settings", "crew", "instructions")},
                                                   "return": {k: item["return"][k] for k in ("source_id", "sha256", "filename", "sights", "preview")},
                                                   "review": item["review"]}, indent=2))
    registered = register_deliverable(project, path, module="ControlSync", kind="approved_level_recheck", metadata={"request_id": identifier, "solution_id": item["review"]["solution_id"]})
    item["export"] = {"sha256": registered["sha256"], "deliverable_id": registered["deliverable_id"]}
    _save(project, state)
    project.db.audit("ControlSync", "LEVEL_RECHECK_EXPORTED", object_type="level_recheck", object_id=identifier,
                     details={"sha256": registered["sha256"], "path": str(path.relative_to(project.paths.root))})
    return path.read_bytes()
