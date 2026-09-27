"""Atomic manual three-shot workflow; workbook arithmetic stays in control.solve."""
import json
import re
import shutil
from uuid import uuid4
from . import control
from .survey_validation import finite_number


def from_project_points(project, payload):
    final_id = str(payload.control_id or "").strip()
    point_ids = [str(p or "").strip() for p in payload.point_ids]
    if not final_id or len(point_ids) != 3 or len(set(point_ids)) != 3 or not all(point_ids):
        raise ValueError("A final control ID and exactly three distinct source PointIDs are required.")
    report_dir = None
    try:
        with project.db.transaction() as conn:
            observations = []
            selection_id = uuid4().hex
            for index, point_id in enumerate(point_ids):
                rows = conn.execute("SELECT * FROM canonical_points WHERE point_id=?", (point_id,)).fetchall()
                if len(rows) != 1:
                    raise ValueError(f"PointID {point_id} is missing or duplicated; resolve before averaging.")
                row = dict(rows[0])
                obs_id = uuid4().hex
                coordinates = [finite_number(row.get(k), f"{point_id} {k}") for k in ("northing", "easting", "elevation")]
                observations.append(obs_id)
                metadata = json.dumps({"selection_id": selection_id, "selection_index": index,
                                       "source_code": row.get("description", ""), "canonical_point": row}, sort_keys=True)
                conn.execute("""INSERT INTO control_observations
                    (observation_id,control_id,source_id,northing,easting,elevation,observed_utc,method,include,notes,point_id,shot_id,metadata_json)
                    VALUES(?,?,?,?,?,?,?,'RON_3_POINT_WORKBOOK',0,?,?,?,?)""",
                    (obs_id, final_id, row.get("source_id"), *coordinates, "", f"Source survey PointID {point_id}", point_id, "ABC"[index], metadata))
            conn.execute("UPDATE control_observations SET include=0 WHERE control_id=? AND method='RON_3_POINT_WORKBOOK'", (final_id,))
            conn.executemany("UPDATE control_observations SET include=1 WHERE observation_id=?", [(i,) for i in observations])
            result = control.solve(project.db, final_id, "ron_spreadsheet", payload.horizontal_tolerance,
                                   payload.vertical_tolerance, observation_ids=observations)
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", final_id).strip(".") or "Control"
            report_dir = project.paths.reports / f"Ron_Control_{safe}_{result['solution_id']}"
            report_dir.mkdir(exist_ok=False)
            result["deliverables"] = control.write_ron_control_deliverables(result, point_ids, report_dir)
            project.db.audit("ControlSync", "RON_3_POINT_FROM_PROJECT_POINTS", object_type="control", object_id=final_id,
                             revision=result["revision"], details={"source_point_ids": point_ids, "solution_id": result["solution_id"], "deliverables": result["deliverables"]})
        return result
    except BaseException:
        if report_dir is not None:
            shutil.rmtree(report_dir, ignore_errors=True)
        raise
