from __future__ import annotations
from .control_exports import write_ron_control_deliverables as write_ron_control_deliverables, write_control_qc_deliverables as write_control_qc_deliverables
from .control_math import (
    _candidate_sort_key as _candidate_sort_key,
    _default_spatial_group_tolerance as _default_spatial_group_tolerance,
    _field_observation_checks as _field_observation_checks,
    _letters_to_number as _letters_to_number,
    _norm as _norm,
    _number_to_letters as _number_to_letters,
    _optional_float as _optional_float,
    _optional_int as _optional_int,
    _parse_duration_seconds as _parse_duration_seconds,
    _parse_observed_time as _parse_observed_time,
    _point_label as _point_label,
    _row_code as _row_code,
    _row_point_id as _row_point_id,
    _shot_suffix as _shot_suffix,
    _three_point_candidate as _three_point_candidate,
    _time_gap_minutes as _time_gap_minutes,
    _weighted_mean as _weighted_mean,
    canonical_control_id as canonical_control_id,
    derive_control_group as derive_control_group,
    next_reshoot_point_ids as next_reshoot_point_ids,
)

import csv
import io
import json
import math
import re
from itertools import combinations
from collections import defaultdict
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

from .audit import AuditDB, utc_now
from .revisions import get_active_solution_id, set_active_solution
from .trimble_job import prepare_jobxml, parse_jobxml_points, TrimbleJobError
from .control_import_mapping import CONTROL_ALIASES, read_control_delimited, detect_control_mapping, validate_control_mapping

ALIASES = CONTROL_ALIASES




def _field_map(fieldnames: list[str], rows: list[dict] | None = None, mapping: dict | None = None) -> dict[str,str]:
    detected=detect_control_mapping(fieldnames, rows or []).get("mapping", {})
    if mapping:
        for key,value in mapping.items():
            if key in ALIASES and value in fieldnames:
                detected[key]=value
            elif key in ALIASES and not value:
                detected.pop(key,None)
    missing=validate_control_mapping(detected, fieldnames)
    if missing:
        raise ValueError("Control column mapping is incomplete: " + ", ".join(missing) + ". Review the detected headers in the Column Mapping dialog.")
    return detected

























def parse_control_csv(path: Path, mapping: dict | None = None) -> list[dict]:
    scan=read_control_delimited(Path(path))
    rows=scan["rows"]
    fm=_field_map(list(scan["headers"]), rows, mapping)
    out=[]
    start_row=2 if scan.get("has_header") else 1
    for idx,row in enumerate(rows, start=start_row):
        explicit_control=str(row.get(fm.get("control_id", ""), "") or "").strip()
        source_point=str(row.get(fm.get("point_id", ""), "") or "").strip()
        raw_shot=str(row.get(fm.get("shot_id", ""), "") or "").strip()
        # Some exports put the full shot label (100A/100B/100C) in a column
        # named control_id. Normalize either representation to the base control.
        cid=canonical_control_id(explicit_control or source_point, source_point)
        if not cid:
            continue
        # If the full shot label arrived in control_id (100A/100B/100C), keep
        # that original label as the observation PointID while grouping under 100.
        source_label=source_point
        if not source_label and explicit_control and derive_control_group(explicit_control) != explicit_control:
            source_label=explicit_control
        point_label=_point_label(cid, source_label, raw_shot)
        try:
            n=float(row[fm["northing"]]); e=float(row[fm["easting"]])
            z=float(row[fm["elevation"]]) if fm.get("elevation") and str(row.get(fm["elevation"],"")).strip() else None
            hs=float(row[fm["h_sigma"]]) if fm.get("h_sigma") and str(row.get(fm["h_sigma"],"")).strip() else None
            vs=float(row[fm["v_sigma"]]) if fm.get("v_sigma") and str(row.get(fm["v_sigma"],"")).strip() else None
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"Invalid numeric control value on row {idx}: {exc}") from exc
        if not math.isfinite(n) or not math.isfinite(e) or (z is not None and not math.isfinite(z)):
            raise ValueError(f"Non-finite control coordinate on row {idx} ({point_label or cid}).")
        observed_time=str(row.get(fm.get("observed_utc",""),"") or "").strip()
        observed_date=str(row.get(fm.get("observed_date",""),"") or "").strip()
        observed_time_provided=bool(observed_time)
        observed_raw=observed_time
        if observed_date and observed_time and observed_date not in observed_time:
            observed_raw=f"{observed_date} {observed_time}"
        elif observed_date and not observed_time:
            observed_raw=observed_date
        epoch_count=_optional_int(row.get(fm.get("epoch_count",""),""),field="epoch count",row_no=idx) if fm.get("epoch_count") else None
        satellite_count=_optional_int(row.get(fm.get("satellite_count",""),""),field="satellite count",row_no=idx) if fm.get("satellite_count") else None
        pdop=_optional_float(row.get(fm.get("pdop",""),""),field="PDOP",row_no=idx) if fm.get("pdop") else None
        hdop=_optional_float(row.get(fm.get("hdop",""),""),field="HDOP",row_no=idx) if fm.get("hdop") else None
        vdop=_optional_float(row.get(fm.get("vdop",""),""),field="VDOP",row_no=idx) if fm.get("vdop") else None
        antenna_height=_optional_float(row.get(fm.get("antenna_height",""),""),field="antenna height",row_no=idx) if fm.get("antenna_height") else None
        duration_seconds=None
        if fm.get("duration_seconds"):
            duration_seconds=_parse_duration_seconds(row.get(fm["duration_seconds"],""),units_hint="seconds",row_no=idx)
        elif fm.get("duration_minutes"):
            duration_seconds=_parse_duration_seconds(row.get(fm["duration_minutes"],""),units_hint="minutes",row_no=idx)
        elif fm.get("duration"):
            duration_seconds=_parse_duration_seconds(row.get(fm["duration"],""),row_no=idx)
        out.append({
            "control_id":cid,"point_id":point_label,"northing":n,"easting":e,"elevation":z,"h_sigma":hs,"v_sigma":vs,
            "description":str(row.get(fm.get("description",""),"") or "").strip(),
            "method":str(row.get(fm.get("method",""),"") or ""),
            "observed_utc":observed_raw,"observed_time_provided":1 if observed_time_provided else 0,
            "epoch_count":epoch_count,"duration_seconds":duration_seconds,"satellite_count":satellite_count,
            "pdop":pdop,"hdop":hdop,"vdop":vdop,
            "fix_type":str(row.get(fm.get("fix_type",""),"") or "").strip(),
            "receiver_model":str(row.get(fm.get("receiver_model",""),"") or "").strip(),
            "receiver_serial":str(row.get(fm.get("receiver_serial",""),"") or "").strip(),
            "antenna_type":str(row.get(fm.get("antenna_type",""),"") or "").strip(),
            "antenna_height":antenna_height,
            "shot_id":raw_shot,"session_id":str(row.get(fm.get("session_id",""),"") or "").strip(),
        })
    if not out: raise ValueError("No control observations were found.")
    return out



def parse_control_source(path: Path, work_dir: Path | None = None, mapping: dict | None = None) -> dict:
    """Parse a ControlSync source file without changing the original evidence.

    CSV/TXT/TSV uses the native control parser. Trimble JOB/JXL uses the same
    official JOB -> JobXML conversion path as the rest of SurveySync, then maps
    reduced grid points and any available GNSS occupation metadata into ControlSync
    observations.
    """
    source=Path(path).expanduser().resolve()
    suffix=source.suffix.lower()
    if suffix not in {".job",".jxl",".xml"}:
        rows=parse_control_csv(source, mapping=mapping)
        return {
            "observations":rows,
            "format":"delimited",
            "metadata":{},
            "conversion":{"converted":False,"input_path":str(source)},
            "jobxml_path":"",
        }
    try:
        work=Path(work_dir or (source.parent/".surveysync_trimble_control")).expanduser().resolve()
        jobxml_path,conversion=prepare_jobxml(source,work)
        parsed=parse_jobxml_points(jobxml_path)
    except TrimbleJobError:
        raise
    rows=[]
    parsed_points=list(parsed.get("points") or [])
    label_counts={}
    for point in parsed_points:
        label=str(point.get("point_id") or "").strip()
        if label: label_counts[label]=label_counts.get(label,0)+1
    ignored_reference_points=[]
    for point in parsed_points:
        label=str(point.get("point_id") or "").strip()
        if not label or point.get("northing") is None or point.get("easting") is None:
            continue
        group=derive_control_group(label)
        # ControlSync's repeated-control workflow uses a trailing alpha shot
        # designator (100A/100B/100C). TBC InventoryData can also contain base
        # stations/reference points such as PRS... that are valid project points
        # but are not repeated control occupations. Keep them in the immutable
        # JXL evidence, but do not create false one-shot control/reshoot groups.
        if group == label and label_counts.get(label,0) < 3:
            ignored_reference_points.append(label)
            continue
        rows.append({
            "control_id":group,
            "point_id":label,
            "northing":float(point["northing"]),
            "easting":float(point["easting"]),
            "elevation":point.get("elevation"),
            "description":str(point.get("code") or "").strip(),
            "method":str(point.get("survey_method") or "Trimble JobXML").strip(),
            "observed_utc":str(point.get("observed_utc") or "").strip(),
            "observed_time_provided":int(bool(point.get("observed_time_provided"))),
            "epoch_count":point.get("epoch_count"),
            "duration_seconds":point.get("duration_seconds"),
            "satellite_count":point.get("satellite_count"),
            "pdop":point.get("pdop"),"hdop":point.get("hdop"),"vdop":point.get("vdop"),
            "fix_type":str(point.get("fix_type") or "").strip(),
            "receiver_model":str(point.get("receiver_model") or "").strip(),
            "receiver_serial":str(point.get("receiver_serial") or "").strip(),
            "antenna_type":str(point.get("antenna_type") or "").strip(),
            "antenna_height":point.get("antenna_height"),
            "metadata_json":point.get("metadata") or {},
            "shot_id":label,
            "session_id":str((parsed.get("metadata") or {}).get("job_name") or source.stem),
        })
    if not rows:
        raise ValueError("No usable control point reductions were found in the Trimble JOB/JobXML file.")
    return {
        "observations":rows,
        "format":"trimble_jobxml",
        "metadata":{**(parsed.get("metadata") or {}),"ignored_reference_points":ignored_reference_points,"control_observation_count":len(rows)},
        "conversion":conversion,
        "jobxml_path":str(jobxml_path),
        "field_metadata_counts":{**{
            "shot_time":sum(1 for r in rows if r.get("observed_time_provided")),
            "epochs":sum(1 for r in rows if r.get("epoch_count") is not None),
            "duration":sum(1 for r in rows if r.get("duration_seconds") is not None),
            "satellites":sum(1 for r in rows if r.get("satellite_count") is not None),
        },**{k:v for k,v in {
            "pdop":sum(1 for r in rows if r.get("pdop") is not None),
            "hdop":sum(1 for r in rows if r.get("hdop") is not None),
            "vdop":sum(1 for r in rows if r.get("vdop") is not None),
            "fix_type":sum(1 for r in rows if r.get("fix_type")),
            "receiver":sum(1 for r in rows if r.get("receiver_model") or r.get("receiver_serial")),
            "antenna":sum(1 for r in rows if r.get("antenna_type") or r.get("antenna_height") is not None),
        }.items() if v}},
    }



def detect_control_import_overlap(db: AuditDB, observations: list[dict]) -> dict:
    """Detect duplicates/conflicts against observations already in the project."""
    with db.connect() as conn:
        existing=[dict(r) for r in conn.execute("SELECT observation_id,point_id,control_id,northing,easting,elevation,source_id FROM control_observations").fetchall()]
    by_point=defaultdict(list)
    for row in existing:
        pid=_row_point_id(row)
        if pid:by_point[pid.casefold()].append(row)
    exact=[];conflicts=[]
    for obs in observations:
        pid=str(obs.get("point_id") or _point_label(str(obs.get("control_id") or ""),"",str(obs.get("shot_id") or ""))).strip()
        if not pid:continue
        for row in by_point.get(pid.casefold(),[]):
            same_xy=abs(float(row["northing"])-float(obs["northing"]))<=1e-9 and abs(float(row["easting"])-float(obs["easting"]))<=1e-9
            rz=row.get("elevation");oz=obs.get("elevation");same_z=(rz is None and oz is None) or (rz is not None and oz is not None and abs(float(rz)-float(oz))<=1e-9)
            if same_xy and same_z:
                exact.append({"point_id":pid,"existing_observation_id":row["observation_id"],"existing_source_id":row.get("source_id")});break
            conflicts.append({"point_id":pid,"existing_observation_id":row["observation_id"],"existing_northing":row["northing"],"existing_easting":row["easting"],"incoming_northing":obs["northing"],"incoming_easting":obs["easting"]})
    return {"exact_duplicate_count":len(exact),"point_id_conflict_count":len(conflicts),"exact_duplicates":exact[:100],"point_id_coordinate_conflicts":conflicts[:100]}

def import_observations(db: AuditDB, observations: list[dict], source_id: str | None = None) -> int:
    inserted=0
    with db.connect() as conn:
        existing_rows=[dict(r) for r in conn.execute("SELECT point_id,control_id,northing,easting,elevation FROM control_observations").fetchall()]
        exact_keys=set()
        for row in existing_rows:
            pid=_row_point_id(row).casefold()
            exact_keys.add((pid,round(float(row["northing"]),9),round(float(row["easting"]),9),None if row.get("elevation") is None else round(float(row["elevation"]),9)))
        for obs in observations:
            metadata=[]
            if obs.get("shot_id"): metadata.append(f"Shot {obs['shot_id']}")
            if obs.get("session_id"): metadata.append(f"Session {obs['session_id']}")
            if obs.get("description"): metadata.append(f"Code {obs['description']}")
            note=str(obs.get("notes", "") or "").strip()
            if metadata: note=(note + (" | " if note else "") + " | ".join(metadata))
            point_id=str(obs.get("point_id") or _point_label(str(obs["control_id"]), "", str(obs.get("shot_id") or "")))
            canonical_id=canonical_control_id(str(obs.get("control_id") or ""), point_id)
            key=(point_id.casefold(),round(float(obs["northing"]),9),round(float(obs["easting"]),9),None if obs.get("elevation") is None else round(float(obs["elevation"]),9))
            if key in exact_keys:
                continue
            observed=str(obs.get("observed_utc") or "").strip()
            time_provided=int(bool(obs.get("observed_time_provided", bool(observed))))
            conn.execute(
                """INSERT INTO control_observations(
                       observation_id,control_id,source_id,northing,easting,elevation,h_sigma,v_sigma,
                       observed_utc,method,include,notes,point_id,shot_id,session_id,
                       observed_time_provided,epoch_count,duration_seconds,satellite_count,
                       pdop,hdop,vdop,fix_type,receiver_model,receiver_serial,antenna_type,antenna_height,metadata_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uuid4().hex,canonical_id,obs.get("source_id",source_id),obs["northing"],obs["easting"],obs.get("elevation"),obs.get("h_sigma"),obs.get("v_sigma"),observed,obs.get("method", ""),note,point_id,str(obs.get("shot_id") or ""),str(obs.get("session_id") or ""),time_provided,obs.get("epoch_count"),obs.get("duration_seconds"),obs.get("satellite_count"),obs.get("pdop"),obs.get("hdop"),obs.get("vdop"),str(obs.get("fix_type") or ""),str(obs.get("receiver_model") or ""),str(obs.get("receiver_serial") or ""),str(obs.get("antenna_type") or ""),obs.get("antenna_height"),json.dumps(obs.get("metadata_json") or {},sort_keys=True)),
            )
            exact_keys.add(key);inserted+=1
    return inserted




def solve(db: AuditDB, control_id: str, method: str="arithmetic", horizontal_tolerance: float=0.10, vertical_tolerance: float=0.10) -> dict:
    method=method.lower().strip()
    with db.connect() as conn:
        rows=[dict(r) for r in conn.execute("SELECT * FROM control_observations WHERE control_id=? AND include=1 ORDER BY observed_utc, observation_id", (control_id,)).fetchall()]
    if not rows: raise ValueError(f"No included observations found for control {control_id}.")
    ns=[r["northing"] for r in rows]; es=[r["easting"] for r in rows]
    zs=[r["elevation"] for r in rows if r["elevation"] is not None]
    if method == "weighted":
        n=_weighted_mean(ns,[r["h_sigma"] for r in rows]); e=_weighted_mean(es,[r["h_sigma"] for r in rows])
        z=_weighted_mean(zs,[r["v_sigma"] for r in rows if r["elevation"] is not None]) if zs else None
    elif method == "arithmetic":
        n=sum(ns)/len(ns); e=sum(es)/len(es); z=sum(zs)/len(zs) if zs else None
    elif method == "ron_spreadsheet":
        # Authoritative profile reproduced from "3 Point Control Averaged Template.xlsx".
        # The workbook solves one final control point from exactly three source shots:
        #   K = AVERAGE(Northing A:C)
        #   L = AVERAGE(Easting A:C)
        #   M = AVERAGE(Elevation A:C)
        # and reports each shot's horizontal distance from the average.
        if len(rows) != 3:
            raise ValueError("Ron 3-point control profile requires exactly three included observations for each final control point.")
        if len(zs) != 3:
            raise ValueError("Ron 3-point control profile requires elevations on all three observations.")
        n=sum(ns)/3.0; e=sum(es)/3.0; z=sum(zs)/3.0
    else: raise ValueError("Unknown control averaging method.")
    residuals=[]; passed=True
    labels=("A-Avg","B-Avg","C-Avg")
    for idx,r in enumerate(rows):
        dn=r["northing"]-n; de=r["easting"]-e; h=math.hypot(dn,de)
        dz=(r["elevation"]-z) if (z is not None and r["elevation"] is not None) else None
        ok=h<=horizontal_tolerance and (dz is None or abs(dz)<=vertical_tolerance)
        passed &= ok
        item={"observation_id":r["observation_id"],"dn":dn,"de":de,"horizontal":h,"dz":dz,"pass":ok}
        if method == "ron_spreadsheet":
            # The source workbook labels rows A/B/C. Its VZ display uses Elev-Avg
            # for A/B and Avg-Elev for C. Preserve that exact display value while
            # retaining a conventional signed dz for deterministic QC.
            item["spreadsheet_label"]=labels[idx]
            item["spreadsheet_hz"]=h
            item["spreadsheet_vz"]=(dz if idx < 2 else (-dz if dz is not None else None))
        residuals.append(item)
    result={"control_id":control_id,"method":method,"count":len(rows),"northing":n,"easting":e,"elevation":z,"horizontal_tolerance":horizontal_tolerance,"vertical_tolerance":vertical_tolerance,"pass":passed,"residuals":residuals,
            "formula_status":"VALIDATED_RON_WORKBOOK" if method == "ron_spreadsheet" else "VALIDATED_GENERIC"}
    if method == "ron_spreadsheet":
        result["formula_profile"]={
            "source_workbook":"3 Point Control Averaged Template.xlsx",
            "shots_required":3,
            "northing":"AVERAGE(Northing A, B, C)",
            "easting":"AVERAGE(Easting A, B, C)",
            "elevation":"AVERAGE(Elevation A, B, C)",
            "horizontal_residual":"SQRT((Northing-AvgN)^2+(Easting-AvgE)^2)",
            "vertical_display":"A/B: Elevation-AvgElevation; C: AvgElevation-Elevation",
        }
    # Every solve becomes an immutable solution revision so control averaging can be
    # reproduced and compared later.  Observations remain untouched.
    import json
    with db.connect() as conn:
        revision=int(conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM control_solutions WHERE control_id=?",(control_id,)).fetchone()[0])
        solution_id=uuid4().hex
        conn.execute(
            "INSERT INTO control_solutions(solution_id,control_id,ts_utc,revision,method,northing,easting,elevation,pass,settings_json,residuals_json,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (solution_id,control_id,utc_now(),revision,method,n,e,z,1 if passed else 0,
             json.dumps({"horizontal_tolerance":horizontal_tolerance,"vertical_tolerance":vertical_tolerance},sort_keys=True),
             json.dumps(residuals,sort_keys=True),"")
        )
        conn.execute("INSERT INTO derived_result_state(result_kind,object_id,state,reason,changed_utc) VALUES(?,?,?,?,?) ON CONFLICT(result_kind,object_id) DO UPDATE SET state='CURRENT',reason=excluded.reason,changed_utc=excluded.changed_utc", ("control", control_id, "CURRENT", "Control solution recalculated", utc_now()))
    db.audit("ControlSync","CONTROL_SOLUTION_CREATED",object_type="control_solution",object_id=solution_id,revision=revision,details={"control_id":control_id,"method":method,"pass":passed})
    # New calculations become the active revision automatically. Older solutions
    # stay immutable and can be restored as the active result without deleting
    # or rewriting later revisions.
    set_active_solution(db,"control",control_id,solution_id,note="Newest calculated revision",audit_action="CONTROL_SOLUTION_ACTIVATED")
    result.update({"solution_id":solution_id,"revision":revision,"active":True})
    return result


def normalize_control_groups(db: AuditDB) -> int:
    """Repair legacy observation rows that stored shot suffixes as control IDs.

    This is intentionally metadata-only: coordinates, elevations, point IDs and
    source provenance are untouched. It lets projects imported by older builds
    automatically regroup 100A/100B/100C under control 100.
    """
    updates=[]
    with db.connect() as conn:
        rows=conn.execute(
            "SELECT observation_id,control_id,point_id,shot_id,notes FROM control_observations"
        ).fetchall()
        for row in rows:
            d=dict(row)
            point=_row_point_id(d)
            canonical=canonical_control_id(str(d.get("control_id") or ""), point)
            if canonical and canonical != str(d.get("control_id") or ""):
                updates.append((canonical,d["observation_id"]))
        if updates:
            conn.executemany("UPDATE control_observations SET control_id=? WHERE observation_id=?", updates)
    if updates:
        db.audit(
            "ControlSync",
            "CONTROL_GROUP_IDS_NORMALIZED",
            object_type="control_database",
            object_id="all",
            details={"updated_observation_count":len(updates),"rule":"trailing alpha suffix is shot ID"},
        )
    return len(updates)







def get_control_group_overrides(db: AuditDB) -> dict[str, dict]:
    with db.connect() as conn:
        rows=conn.execute("SELECT * FROM control_group_overrides").fetchall()
    return {str(r["observation_id"]):dict(r) for r in rows}


def set_control_group_override(
    db: AuditDB,
    observation_id: str,
    *,
    status: str,
    assigned_control_id: str="",
    assigned_point_id: str="",
    reason: str="",
) -> dict:
    allowed={"CONFIRMED","REJECTED","REASSIGNED","AUTO"}
    state=str(status or "").upper().strip()
    if state not in allowed:
        raise ValueError(f"Invalid control grouping review status: {status}")
    with db.connect() as conn:
        exists=conn.execute("SELECT point_id,control_id FROM control_observations WHERE observation_id=?",(observation_id,)).fetchone()
        if not exists:
            raise ValueError("Control observation was not found.")
        conn.execute(
            """INSERT INTO control_group_overrides(observation_id,status,assigned_control_id,assigned_point_id,reason,updated_utc)
               VALUES(?,?,?,?,?,?) ON CONFLICT(observation_id) DO UPDATE SET status=excluded.status,assigned_control_id=excluded.assigned_control_id,assigned_point_id=excluded.assigned_point_id,reason=excluded.reason,updated_utc=excluded.updated_utc""",
            (observation_id,state,str(assigned_control_id or ""),str(assigned_point_id or ""),str(reason or ""),utc_now()),
        )
    db.audit("ControlSync","CONTROL_GROUP_OVERRIDE",object_type="control_observation",object_id=observation_id,details={"status":state,"assigned_control_id":assigned_control_id,"assigned_point_id":assigned_point_id,"reason":reason})
    return {"observation_id":observation_id,"status":state,"assigned_control_id":assigned_control_id,"assigned_point_id":assigned_point_id,"reason":reason}


def resolve_spatial_control_groups(
    rows: list[dict],
    spatial_tolerance: float,
    vertical_tolerance: float | None=None,
    *,
    overrides: dict[str,dict] | None=None,
) -> tuple[list[dict], list[dict]]:
    """Resolve likely misnumbered shots from name + XY/Z proximity + manual review.

    Raw IDs never change.  Spatial inference is conservative: ambiguous clusters are
    REVIEW items, and any user Confirm/Reject/Reassign decision overrides automation.
    """
    tol=float(spatial_tolerance)
    if not math.isfinite(tol) or tol <= 0:
        raise ValueError("Spatial grouping tolerance must be a positive finite value.")
    ztol=None if vertical_tolerance is None else float(vertical_tolerance)
    if ztol is not None and (not math.isfinite(ztol) or ztol <= 0):
        raise ValueError("Vertical grouping tolerance must be a positive finite value when supplied.")
    out=[dict(r) for r in rows]
    overrides=overrides or {}
    for row in out:
        base=canonical_control_id(str(row.get("control_id") or ""), _row_point_id(row))
        row["_effective_control_id"]=base
        row["_effective_point_id"]=_row_point_id(row) or base
        row["_grouping_source"]="POINT_ID"

    parent=list(range(len(out))); rank=[0]*len(out)
    def find(i):
        while parent[i] != i:
            parent[i]=parent[parent[i]]; i=parent[i]
        return i
    def union(a,b):
        ra,rb=find(a),find(b)
        if ra==rb:return
        if rank[ra] < rank[rb]:ra,rb=rb,ra
        parent[rb]=ra
        if rank[ra]==rank[rb]:rank[ra]+=1
    def z_compatible(a,b):
        if ztol is None:return True
        za=a.get("elevation");zb=b.get("elevation")
        if za is None or zb is None:return True
        return abs(float(za)-float(zb)) <= ztol

    cells=defaultdict(list)
    for i,row in enumerate(out):
        n=float(row["northing"]);e=float(row["easting"]);key=(math.floor(n/tol),math.floor(e/tol))
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for j in cells.get((key[0]+dx,key[1]+dy),()):
                    other=out[j]
                    if math.hypot(n-float(other["northing"]),e-float(other["easting"])) <= tol and z_compatible(row,other):
                        union(i,j)
        cells[key].append(i)

    clusters=defaultdict(list)
    for i in range(len(out)):clusters[find(i)].append(i)
    flags=[]
    for indices in clusters.values():
        if len(indices)<2:continue
        counts=defaultdict(int);bases={}
        for i in indices:
            base=canonical_control_id(str(out[i].get("control_id") or ""),_row_point_id(out[i]));bases[i]=base;counts[base]+=1
        if len(counts)<=1:continue
        ordered=sorted(counts.items(),key=lambda kv:(-kv[1],str(kv[0])))
        majority,majority_count=ordered[0]
        unique_majority=majority_count>=2 and majority_count>ordered[1][1]
        cluster_points=[_row_point_id(out[i]) or str(out[i].get("control_id") or "") for i in indices]
        if not unique_majority:
            flags.append({"type":"SPATIAL_ID_CONFLICT","severity":"REVIEW","message":"Nearby control observations have conflicting IDs with no clear majority.","point_ids":cluster_points,"control_ids":sorted(counts),"auto_assigned":False})
            continue
        majority_indices=[i for i in indices if bases[i]==majority]
        center_n=sum(float(out[i]["northing"]) for i in majority_indices)/len(majority_indices)
        center_e=sum(float(out[i]["easting"]) for i in majority_indices)/len(majority_indices)
        center_z_vals=[float(out[i]["elevation"]) for i in majority_indices if out[i].get("elevation") is not None]
        center_z=(sum(center_z_vals)/len(center_z_vals)) if center_z_vals else None
        used_suffixes={_shot_suffix(_row_point_id(out[i]),majority) for i in majority_indices};used_suffixes.discard("")
        for i in indices:
            if bases[i]==majority:continue
            row=out[i];oid=str(row.get("observation_id") or "");original_point=_row_point_id(row) or str(row.get("control_id") or "")
            suffix=_shot_suffix(original_point,bases[i]);distance=math.hypot(float(row["northing"])-center_n,float(row["easting"])-center_e)
            vdist=(abs(float(row["elevation"])-center_z) if center_z is not None and row.get("elevation") is not None else None)
            suggested_point=f"{majority}{suffix}" if suffix else ""
            review=overrides.get(oid) or {}
            if review:
                state=str(review.get("status") or "").upper()
                if state in {"CONFIRMED","REASSIGNED"}:
                    assigned_control=str(review.get("assigned_control_id") or majority)
                    assigned_point=str(review.get("assigned_point_id") or suggested_point or original_point)
                    row["_effective_control_id"]=assigned_control;row["_effective_point_id"]=assigned_point;row["_grouping_source"]="MANUAL"
                    flags.append({"type":"MANUAL_GROUPING","severity":"INFO","observation_id":oid,"point_id":original_point,"suggested_control_id":assigned_control,"suggested_point_id":assigned_point,"message":f"{original_point} grouping confirmed/reassigned to Control {assigned_control}.","review_status":state,"auto_assigned":False})
                    continue
                if state=="REJECTED":
                    row["_grouping_source"]="MANUAL_REJECT"
                    flags.append({"type":"PROBABLE_MISNUMBER_REJECTED","severity":"INFO","observation_id":oid,"point_id":original_point,"suggested_control_id":majority,"message":f"Spatial grouping suggestion for {original_point} was rejected.","review_status":state,"auto_assigned":False})
                    continue
            if suffix and suffix not in used_suffixes:
                row["_effective_control_id"]=majority;row["_effective_point_id"]=suggested_point;row["_grouping_source"]="SPATIAL_INFERENCE";used_suffixes.add(suffix)
                flags.append({"type":"PROBABLE_MISNUMBER","severity":"WARNING","observation_id":oid,"message":f"{original_point} is spatially grouped with Control {majority}; probable intended shot is {suggested_point}.","point_id":original_point,"original_control_id":bases[i],"suggested_control_id":majority,"suggested_point_id":suggested_point,"distance_to_group_center":distance,"vertical_distance_to_group_center":vdist,"spatial_tolerance":tol,"vertical_tolerance":ztol,"cluster_point_ids":cluster_points,"auto_assigned":True,"review_status":"PENDING"})
            else:
                flags.append({"type":"SPATIAL_ID_CONFLICT","severity":"REVIEW","observation_id":oid,"message":f"{original_point} is near Control {majority}, but its suffix is ambiguous or already used; review numbering.","point_id":original_point,"original_control_id":bases[i],"suggested_control_id":majority,"distance_to_group_center":distance,"vertical_distance_to_group_center":vdist,"spatial_tolerance":tol,"vertical_tolerance":ztol,"cluster_point_ids":cluster_points,"auto_assigned":False,"review_status":"PENDING"})
    return out,flags


def list_control_ids(db: AuditDB) -> list[dict]:
    normalize_control_groups(db)
    with db.connect() as conn:
        rows=conn.execute(
            """SELECT o.control_id, COUNT(*) AS observation_count, SUM(o.include) AS included_count,
                      MIN(o.observed_utc) AS first_observed_utc, MAX(o.observed_utc) AS last_observed_utc,
                      (SELECT MAX(s.revision) FROM control_solutions s WHERE s.control_id=o.control_id) AS latest_revision
               FROM control_observations o GROUP BY o.control_id ORDER BY o.control_id"""
        ).fetchall()
    return [dict(r) for r in rows]


def list_observations(db: AuditDB, control_id: str | None = None, limit: int = 2000) -> list[dict]:
    normalize_control_groups(db)
    limit=max(1,min(int(limit or 2000),10000))
    with db.connect() as conn:
        if control_id:
            rows=conn.execute(
                "SELECT * FROM control_observations WHERE control_id=? ORDER BY observed_utc, observation_id LIMIT ?",
                (control_id,limit),
            ).fetchall()
        else:
            rows=conn.execute(
                "SELECT * FROM control_observations ORDER BY control_id, observed_utc, observation_id LIMIT ?",
                (limit,),
            ).fetchall()
    out=[]
    for row in rows:
        d=dict(row); d["include"]=bool(d.get("include")); d["point_id"]=_row_point_id(d); out.append(d)
    return out


def classify_control_import(parsed: dict) -> dict:
    """Describe what a control source can actually prove before QC runs."""
    meta=dict(parsed.get("metadata") or {})
    counts=dict(parsed.get("field_metadata_counts") or meta.get("gnss_metadata_counts") or {})
    fmt=str(parsed.get("format") or "")
    point_source=str(meta.get("point_source") or "")
    fieldbook_scan=dict(meta.get("fieldbook_scan") or {})
    fieldbook_present=bool(fieldbook_scan.get("fieldbook_present"))
    metadata_records=int(fieldbook_scan.get("point_metadata_records") or 0)
    if fmt=="trimble_jobxml":
        if fieldbook_present and metadata_records:
            source_kind="TRIMBLE_ACCESS_RAW_JOBXML"
            label="Trimble JobXML with raw FieldBook/GNSS occupation metadata"
        elif point_source=="InventoryData":
            source_kind="TBC_INVENTORY_ONLY_JOBXML"
            label="TBC inventory-only JobXML"
        else:
            source_kind="TRIMBLE_COORDINATE_JOBXML"
            label="Trimble JobXML with coordinate reductions"
    else:
        source_kind="DELIMITED_CONTROL_FILE"
        label="Delimited control observation file"
    expected=("shot_time","epochs","duration","satellites","pdop","hdop","vdop","fix_type","receiver","antenna")
    available={key:int(counts.get(key) or 0) for key in expected}
    missing=[key for key,value in available.items() if not value]
    warnings=[]
    if source_kind=="TBC_INVENTORY_ONLY_JOBXML":
        warnings.append("Raw FieldBook/GNSS occupation records are not included; occupation-quality QC will remain UNVERIFIED unless a raw Access JXL is merged.")
    return {"source_kind":source_kind,"label":label,"point_source":point_source,"fieldbook_present":fieldbook_present,"fieldbook_metadata_records":metadata_records,"metadata_available":available,"missing_metadata":missing,"warnings":warnings}


def save_control_import_diagnostic(db: AuditDB, source_id: str, parsed: dict) -> dict:
    summary=classify_control_import(parsed)
    with db.connect() as conn:
        conn.execute("INSERT INTO control_import_diagnostics(diagnostic_id,source_id,ts_utc,format,source_kind,summary_json) VALUES(?,?,?,?,?,?)",(uuid4().hex,source_id,utc_now(),str(parsed.get("format") or ""),summary["source_kind"],json.dumps(summary,sort_keys=True)))
    return summary


def list_control_import_diagnostics(db: AuditDB, limit: int=20) -> list[dict]:
    with db.connect() as conn:
        rows=conn.execute("SELECT * FROM control_import_diagnostics ORDER BY ts_utc DESC LIMIT ?",(max(1,min(int(limit),100)),)).fetchall()
    out=[]
    for row in rows:
        d=dict(row)
        try:d["summary"]=json.loads(d.pop("summary_json") or "{}")
        except (TypeError,ValueError,json.JSONDecodeError):d["summary"]={}
        out.append(d)
    return out


def list_control_qc_profiles(db: AuditDB) -> list[dict]:
    with db.connect() as conn:
        rows=conn.execute("SELECT * FROM control_qc_profiles ORDER BY is_default DESC,name COLLATE NOCASE").fetchall()
    if not rows:
        save_control_qc_profile(db,{"name":"Ron Control Standard","is_default":True})
        with db.connect() as conn:rows=conn.execute("SELECT * FROM control_qc_profiles ORDER BY is_default DESC,name COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def save_control_qc_profile(db: AuditDB, profile: dict) -> dict:
    name=str(profile.get("name") or "").strip()
    if not name:raise ValueError("QC profile name is required.")
    profile_id=str(profile.get("profile_id") or uuid4().hex)
    is_default=1 if profile.get("is_default") else 0
    values={
        "horizontal_tolerance":float(profile.get("horizontal_tolerance",0.045)),
        "vertical_tolerance":float(profile.get("vertical_tolerance",0.045)),
        "spatial_group_tolerance":profile.get("spatial_group_tolerance"),
        "vertical_group_tolerance":profile.get("vertical_group_tolerance"),
        "require_field_metadata":1 if profile.get("require_field_metadata",True) else 0,
        "min_time_separation_minutes":float(profile.get("min_time_separation_minutes",60.0)),
        "min_epochs":int(profile.get("min_epochs",300)),
        "min_observation_seconds":float(profile.get("min_observation_seconds",300.0)),
        "min_satellites":int(profile.get("min_satellites",5)),
        "max_pdop":profile.get("max_pdop"),"max_hdop":profile.get("max_hdop"),"max_vdop":profile.get("max_vdop"),
    }
    with db.connect() as conn:
        if is_default:conn.execute("UPDATE control_qc_profiles SET is_default=0")
        existing=conn.execute("SELECT profile_id FROM control_qc_profiles WHERE name=?",(name,)).fetchone()
        if existing:profile_id=str(existing[0])
        conn.execute("""INSERT INTO control_qc_profiles(profile_id,name,is_default,horizontal_tolerance,vertical_tolerance,spatial_group_tolerance,vertical_group_tolerance,require_field_metadata,min_time_separation_minutes,min_epochs,min_observation_seconds,min_satellites,max_pdop,max_hdop,max_vdop,updated_utc)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(profile_id) DO UPDATE SET name=excluded.name,is_default=excluded.is_default,horizontal_tolerance=excluded.horizontal_tolerance,vertical_tolerance=excluded.vertical_tolerance,spatial_group_tolerance=excluded.spatial_group_tolerance,vertical_group_tolerance=excluded.vertical_group_tolerance,require_field_metadata=excluded.require_field_metadata,min_time_separation_minutes=excluded.min_time_separation_minutes,min_epochs=excluded.min_epochs,min_observation_seconds=excluded.min_observation_seconds,min_satellites=excluded.min_satellites,max_pdop=excluded.max_pdop,max_hdop=excluded.max_hdop,max_vdop=excluded.max_vdop,updated_utc=excluded.updated_utc""",
            (profile_id,name,is_default,values["horizontal_tolerance"],values["vertical_tolerance"],values["spatial_group_tolerance"],values["vertical_group_tolerance"],values["require_field_metadata"],values["min_time_separation_minutes"],values["min_epochs"],values["min_observation_seconds"],values["min_satellites"],values["max_pdop"],values["max_hdop"],values["max_vdop"],utc_now()))
    db.audit("ControlSync","CONTROL_QC_PROFILE_SAVED",object_type="control_qc_profile",object_id=profile_id,details={"name":name,"is_default":bool(is_default)})
    return next(x for x in list_control_qc_profiles(db) if x["profile_id"]==profile_id)


def merge_control_metadata(db: AuditDB, observations: list[dict], source_id: str) -> dict:
    """Enrich existing coordinate observations by point ID without moving them."""
    updates=0; unmatched=[]; merged_fields=defaultdict(int)
    by_point={str(o.get("point_id") or "").casefold():o for o in observations if str(o.get("point_id") or "").strip()}
    quality_fields=("observed_utc","observed_time_provided","epoch_count","duration_seconds","satellite_count","pdop","hdop","vdop","fix_type","receiver_model","receiver_serial","antenna_type","antenna_height")
    with db.connect() as conn:
        existing=[dict(r) for r in conn.execute("SELECT * FROM control_observations").fetchall()]
        existing_map={_row_point_id(r).casefold():r for r in existing if _row_point_id(r)}
        for key,obs in by_point.items():
            row=existing_map.get(key)
            if not row:
                unmatched.append(str(obs.get("point_id") or ""));continue
            changes={}
            for field in quality_fields:
                value=obs.get(field)
                if value not in (None,"") and row.get(field) in (None,"",0):
                    changes[field]=value;merged_fields[field]+=1
            if changes:
                meta={}
                try:meta=json.loads(row.get("metadata_json") or "{}")
                except (TypeError,ValueError,json.JSONDecodeError):meta={}
                provenance=list(meta.get("metadata_sources") or [])
                if source_id not in provenance:provenance.append(source_id)
                meta["metadata_sources"]=provenance
                changes["metadata_json"]=json.dumps(meta,sort_keys=True)
                cols=list(changes);params=[changes[c] for c in cols]+[row["observation_id"]]
                conn.execute(f"UPDATE control_observations SET {','.join(c+'=?' for c in cols)} WHERE observation_id=?",params)
                updates+=1
    db.audit("ControlSync","CONTROL_METADATA_MERGED",object_type="source",object_id=source_id,details={"updated_observations":updates,"unmatched_point_ids":unmatched,"merged_fields":dict(merged_fields)})
    return {"updated_observations":updates,"unmatched_point_ids":unmatched,"merged_fields":dict(merged_fields)}


def analyze_all(db: AuditDB, method: str="arithmetic", horizontal_tolerance: float=0.10, vertical_tolerance: float=0.10, min_observations: int=2) -> dict:
    """Analyze every stored Control ID with enough included observations.

    This is intentionally generic until a validated TBC report/profile is supplied.
    No observations are rewritten or deleted; each successful solve creates the same
    immutable solution revision used by the single-control workflow.
    """
    min_observations=max(1,int(min_observations or 1))
    controls=list_control_ids(db)
    results=[]; solved=0; passed=0; review=0; skipped=0
    for item in controls:
        cid=str(item["control_id"]); included=int(item.get("included_count") or 0)
        if included < min_observations:
            skipped+=1
            results.append({"control_id":cid,"status":"INSUFFICIENT_SHOTS","observation_count":int(item.get("observation_count") or 0),"included_count":included,"minimum_required":min_observations})
            continue
        try:
            result=solve(db,cid,method,horizontal_tolerance,vertical_tolerance)
            solved+=1; passed+=1 if result.get("pass") else 0; review+=0 if result.get("pass") else 1
            results.append({
                "control_id":cid,"status":"PASS" if result.get("pass") else "REVIEW",
                "observation_count":result.get("count",included),"northing":result.get("northing"),
                "easting":result.get("easting"),"elevation":result.get("elevation"),
                "solution_id":result.get("solution_id"),"revision":result.get("revision"),
                "max_horizontal_residual":max((float(r.get("horizontal") or 0) for r in result.get("residuals",[])),default=0.0),
                "max_vertical_residual":max((abs(float(r.get("dz") or 0)) for r in result.get("residuals",[]) if r.get("dz") is not None),default=0.0),
            })
        except Exception as exc:
            review+=1
            results.append({"control_id":cid,"status":"ERROR","included_count":included,"error":str(exc)})
    return {
        "method":method,"horizontal_tolerance":horizontal_tolerance,"vertical_tolerance":vertical_tolerance,
        "minimum_observations":min_observations,"control_count":len(controls),"solved_count":solved,
        "pass_count":passed,"review_count":review,"skipped_count":skipped,"results":results,
        "analysis_profile":"GENERIC_CONTROL_DATABASE_V1",
        "note":"Generic database analysis; TBC-specific calculations/reporting will be added only after the reference report is validated.",
    }













def _save_triplet_solution(db: AuditDB, control_id: str, candidate: dict, horizontal_tolerance: float, vertical_tolerance: float, run_id: str) -> dict:
    with db.connect() as conn:
        revision=int(conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM control_solutions WHERE control_id=?",(control_id,)).fetchone()[0])
        solution_id=uuid4().hex
        settings={
            "horizontal_tolerance":horizontal_tolerance,
            "vertical_tolerance":vertical_tolerance,
            "qc_run_id":run_id,
            "candidate_point_ids":candidate["point_ids"],
            "candidate_analysis_point_ids":candidate.get("analysis_point_ids") or candidate["point_ids"],
            "candidate_observation_ids":candidate["observation_ids"],
            "candidate_field_validation":candidate.get("field_validation") or {},
            "candidate_selection":"best_three_by_coordinate_and_field_qc",
        }
        conn.execute(
            "INSERT INTO control_solutions(solution_id,control_id,ts_utc,revision,method,northing,easting,elevation,pass,settings_json,residuals_json,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (solution_id,control_id,utc_now(),revision,"ron_best_triplet",candidate["northing"],candidate["easting"],candidate.get("elevation"),1 if candidate.get("pass") else 0,json.dumps(settings,sort_keys=True),json.dumps(candidate.get("residuals") or [],sort_keys=True),"Automated best-three control QC"),
        )
        conn.execute("INSERT INTO derived_result_state(result_kind,object_id,state,reason,changed_utc) VALUES(?,?,?,?,?) ON CONFLICT(result_kind,object_id) DO UPDATE SET state='CURRENT',reason=excluded.reason,changed_utc=excluded.changed_utc",("control",control_id,"CURRENT","Best-three ControlSync QC recalculated",utc_now()))
    db.audit("ControlSync","CONTROL_BEST_TRIPLET_SOLUTION_CREATED",object_type="control_solution",object_id=solution_id,revision=revision,details={"control_id":control_id,"run_id":run_id,"point_ids":candidate["point_ids"],"pass":bool(candidate.get("pass"))})
    set_active_solution(db,"control",control_id,solution_id,note="Best-three QC result",audit_action="CONTROL_SOLUTION_ACTIVATED")
    return {"solution_id":solution_id,"revision":revision,"active":True}


def run_best_triplet_qc(
    db: AuditDB,
    horizontal_tolerance: float=0.045,
    vertical_tolerance: float=0.045,
    *,
    coordinate_context: dict | None=None,
    max_combinations: int=100000,
    reshoot_count: int=3,
    spatial_group_tolerance: float | None=None,
    vertical_group_tolerance: float | None=None,
    require_field_metadata: bool=False,
    min_time_separation_minutes: float=60.0,
    min_epochs: int=300,
    min_duration_seconds: float=300.0,
    min_satellites: int=5,
    max_pdop: float | None=None,
    max_hdop: float | None=None,
    max_vdop: float | None=None,
) -> dict:
    """Run Ronald's validated three-shot arithmetic/residual method over every control.

    Every possible 3-observation combination is evaluated for each control group. The
    selected candidate is the passing combination with the lowest normalized residual
    spread. If none pass, the closest candidate is retained for provenance and the
    control is placed on the reshoot list with the next unused point labels.
    """
    normalize_control_groups(db)
    htol=float(horizontal_tolerance); vtol=float(vertical_tolerance)
    if not math.isfinite(htol) or htol <= 0 or not math.isfinite(vtol) or vtol <= 0:
        raise ValueError("Horizontal and vertical control tolerances must be positive finite values.")
    context=dict(coordinate_context or {})
    spatial_tol=float(spatial_group_tolerance) if spatial_group_tolerance is not None else _default_spatial_group_tolerance(context)
    if not math.isfinite(spatial_tol) or spatial_tol <= 0:
        raise ValueError("Spatial grouping tolerance must be a positive finite value.")
    min_time_separation_minutes=float(min_time_separation_minutes)
    min_duration_seconds=float(min_duration_seconds)
    min_epochs=int(min_epochs); min_satellites=int(min_satellites)
    if not math.isfinite(min_time_separation_minutes) or min_time_separation_minutes <= 0:
        raise ValueError("Minimum time separation must be a positive number of minutes.")
    if not math.isfinite(min_duration_seconds) or min_duration_seconds <= 0:
        raise ValueError("Minimum observation duration must be positive.")
    if min_epochs < 1 or min_satellites < 1:
        raise ValueError("Minimum epochs and satellite count must be at least 1.")
    for label,value in (("Maximum PDOP",max_pdop),("Maximum HDOP",max_hdop),("Maximum VDOP",max_vdop)):
        if value is not None and (not math.isfinite(float(value)) or float(value) <= 0):
            raise ValueError(f"{label} must be a positive finite value when supplied.")
    run_id=uuid4().hex
    now=utc_now()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO control_qc_runs(run_id,ts_utc,method,horizontal_tolerance,vertical_tolerance,crs,horizontal_units,local_site_json,result_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (run_id,now,"ron_best_triplet",htol,vtol,str(context.get("crs") or ""),str(context.get("horizontal_units") or ""),json.dumps(context.get("local_site") or {},sort_keys=True),"{}"),
        )
        all_rows=[dict(r) for r in conn.execute("SELECT * FROM control_observations WHERE include=1 ORDER BY observed_utc,observation_id").fetchall()]
    resolved_rows, spatial_flags=resolve_spatial_control_groups(all_rows,spatial_tol,vertical_group_tolerance,overrides=get_control_group_overrides(db))
    grouped=defaultdict(list)
    for row in resolved_rows:
        grouped[str(row.get("_effective_control_id") or row.get("control_id") or "")].append(row)
    controls=sorted(k for k in grouped if k)
    results=[]; accepted=0; reshoot=0; candidate_total=0
    for control_id in controls:
        rows=grouped[control_id]
        point_ids=[_row_point_id(r) or control_id for r in rows]
        analysis_point_ids=[str(r.get("_effective_point_id") or _row_point_id(r) or control_id) for r in rows]
        numbering_flags=[f for f in spatial_flags if f.get("suggested_control_id")==control_id or (f.get("type")=="SPATIAL_ID_CONFLICT" and control_id in (f.get("control_ids") or []))]
        if len(rows) < 3:
            reshoot+=1
            results.append({
                "control_id":control_id,"status":"RESHOOT","reason":"Fewer than three included observations.",
                "observation_count":len(rows),"candidate_count":0,"selected":None,
                "existing_point_ids":point_ids,"analysis_point_ids":analysis_point_ids,"numbering_flags":numbering_flags,
                "reshoot_point_ids":next_reshoot_point_ids(control_id,analysis_point_ids,reshoot_count),
            })
            continue
        combination_count=math.comb(len(rows),3)
        if combination_count > max_combinations:
            reshoot+=1
            results.append({
                "control_id":control_id,"status":"REVIEW","reason":f"{combination_count:,} three-shot combinations exceed the safety limit of {max_combinations:,}.",
                "observation_count":len(rows),"candidate_count":combination_count,"selected":None,
                "existing_point_ids":point_ids,"analysis_point_ids":analysis_point_ids,"numbering_flags":numbering_flags,"reshoot_point_ids":[],
            })
            continue
        candidates=[_three_point_candidate(
            list(group),htol,vtol,
            min_time_separation_minutes=min_time_separation_minutes,
            min_epochs=min_epochs,
            min_duration_seconds=min_duration_seconds,
            min_satellites=min_satellites,
            max_pdop=max_pdop,max_hdop=max_hdop,max_vdop=max_vdop,
            require_field_metadata=require_field_metadata,
        ) for group in combinations(rows,3)]
        candidates.sort(key=lambda c:_candidate_sort_key(c,htol,vtol))
        candidate_total+=len(candidates)
        selected=candidates[0]
        saved=_save_triplet_solution(db,control_id,selected,htol,vtol,run_id)
        with db.connect() as conn:
            for rank,candidate in enumerate(candidates, start=1):
                conn.execute(
                    """INSERT INTO control_qc_candidates(candidate_id,run_id,control_id,rank_no,selected,passed,point_ids_json,observation_ids_json,northing,easting,elevation,max_horizontal_residual,max_vertical_residual,rms_horizontal_residual,rms_vertical_residual,residuals_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (uuid4().hex,run_id,control_id,rank,1 if rank==1 else 0,1 if candidate.get("pass") else 0,json.dumps(candidate["point_ids"]),json.dumps(candidate["observation_ids"]),candidate["northing"],candidate["easting"],candidate.get("elevation"),candidate.get("max_horizontal_residual"),candidate.get("max_vertical_residual"),candidate.get("rms_horizontal_residual"),candidate.get("rms_vertical_residual"),json.dumps(candidate.get("residuals") or [],sort_keys=True)),
                )
        if selected.get("pass"):
            accepted+=1; status="PASS"; reshoot_ids=[]
            reason="Selected best three-shot combination passing coordinate and field-observation QC."
        else:
            coordinate_candidates=[c for c in candidates if c.get("coordinate_pass")]
            explicit_field_fail=any((c.get("field_validation") or {}).get("failures") for c in coordinate_candidates)
            missing_field_meta=any((c.get("field_validation") or {}).get("status")=="UNVERIFIED" for c in coordinate_candidates)
            if require_field_metadata and coordinate_candidates and missing_field_meta and not explicit_field_fail:
                status="REVIEW"; reshoot_ids=[]
                reason="Coordinate QC passes, but required field metadata is missing or cannot be verified."
            else:
                status="RESHOOT"; reshoot_ids=next_reshoot_point_ids(control_id,analysis_point_ids,reshoot_count)
                if coordinate_candidates and explicit_field_fail:
                    reason="Coordinate QC passes for at least one triplet, but field-observation requirements fail."
                else:
                    reason="No three-shot combination satisfies the required coordinate and field-observation QC."
            reshoot+=1
        results.append({
            "control_id":control_id,"status":status,"reason":reason,
            "observation_count":len(rows),"candidate_count":len(candidates),"selected":selected,
            "solution_id":saved["solution_id"],"revision":saved["revision"],"existing_point_ids":point_ids,"analysis_point_ids":analysis_point_ids,"numbering_flags":numbering_flags,"reshoot_point_ids":reshoot_ids,
            "alternatives":[{
                **{k:c.get(k) for k in ("point_ids","analysis_point_ids","pass","coordinate_pass","max_horizontal_residual","max_vertical_residual","rms_horizontal_residual","rms_vertical_residual")},
                "field_status":(c.get("field_validation") or {}).get("status"),
                "field_failures":(c.get("field_validation") or {}).get("failures",[]),
                "missing_field_metadata":(c.get("field_validation") or {}).get("missing_metadata",[]),
            } for c in candidates[:10]],
        })
    result={
        "run_id":run_id,"ts_utc":now,"method":"ron_best_triplet",
        "horizontal_tolerance":htol,"vertical_tolerance":vtol,
        "control_count":len(controls),"accepted_count":accepted,"reshoot_count":reshoot,
        "candidate_count":candidate_total,"results":results,
        "coordinate_context":context,
        "field_requirements":{
            "enforced":bool(require_field_metadata),
            "min_time_separation_minutes":min_time_separation_minutes,
            "min_epochs":min_epochs,
            "min_duration_seconds":min_duration_seconds,
            "min_satellites":min_satellites,
            "max_pdop":max_pdop,"max_hdop":max_hdop,"max_vdop":max_vdop,
            "policy":"A shot satisfies observation length when either epoch count or duration meets the minimum. Explicit field/DOP failures always disqualify a triplet; missing metadata blocks PASS only when enforcement is enabled.",
        },
        "spatial_grouping":{
            "tolerance":spatial_tol,
            "vertical_tolerance":vertical_group_tolerance,
            "probable_misnumber_count":sum(1 for f in spatial_flags if f.get("type")=="PROBABLE_MISNUMBER"),
            "review_conflict_count":sum(1 for f in spatial_flags if f.get("type")=="SPATIAL_ID_CONFLICT"),
            "flags":spatial_flags,
            "policy":"Spatial grouping may reassign an observation for QC only when a nearby cluster has a unique repeated-ID majority and the shot suffix is unused. Raw IDs are preserved.",
        },
        "algorithm":{
            "shots_per_candidate":3,
            "average":"Arithmetic mean of Northing, Easting and Elevation for each candidate triplet.",
            "horizontal_residual":"2D distance from each shot to candidate average.",
            "vertical_residual":"Absolute elevation difference from candidate average.",
            "selection":"Candidate must satisfy coordinate tolerances and field-observation rules; fully verified field metadata is preferred, then lowest normalized H/V residual spread and RMS residuals.",
        },
    }
    with db.connect() as conn:
        conn.execute("UPDATE control_qc_runs SET result_json=? WHERE run_id=?",(json.dumps(result,sort_keys=True),run_id))
    db.audit("ControlSync","CONTROL_QC_RUN_COMPLETED",object_type="control_qc_run",object_id=run_id,details={"control_count":len(controls),"accepted_count":accepted,"reshoot_count":reshoot,"candidate_count":candidate_total,"horizontal_tolerance":htol,"vertical_tolerance":vtol,"spatial_group_tolerance":spatial_tol,"probable_misnumber_count":sum(1 for f in spatial_flags if f.get("type")=="PROBABLE_MISNUMBER"),"require_field_metadata":bool(require_field_metadata),"min_time_separation_minutes":min_time_separation_minutes,"min_epochs":min_epochs,"min_duration_seconds":min_duration_seconds,"min_satellites":min_satellites,"max_pdop":max_pdop,"max_hdop":max_hdop,"max_vdop":max_vdop,"vertical_group_tolerance":vertical_group_tolerance})
    return result


def get_control_qc_run(db: AuditDB, run_id: str="") -> dict:
    with db.connect() as conn:
        if run_id:
            row=conn.execute("SELECT result_json FROM control_qc_runs WHERE run_id=?",(run_id,)).fetchone()
        else:
            row=conn.execute("SELECT result_json FROM control_qc_runs ORDER BY ts_utc DESC LIMIT 1").fetchone()
    if not row:
        return {}
    return json.loads(row[0] or "{}")




def list_solutions(db: AuditDB, control_id: str | None = None, limit: int = 100) -> list[dict]:
    import json
    with db.connect() as conn:
        if control_id:
            rows=conn.execute("SELECT * FROM control_solutions WHERE control_id=? ORDER BY revision DESC LIMIT ?",(control_id,max(1,min(limit,1000)))).fetchall()
        else:
            rows=conn.execute("SELECT * FROM control_solutions ORDER BY ts_utc DESC LIMIT ?",(max(1,min(limit,1000)),)).fetchall()
    selected_by_control={}
    out=[]
    for row in rows:
        d=dict(row)
        cid=d["control_id"]
        if cid not in selected_by_control:
            selected_by_control[cid]=get_active_solution_id(db,"control",cid)
        d["settings"]=json.loads(d.pop("settings_json") or "{}")
        d["residuals"]=json.loads(d.pop("residuals_json") or "[]")
        d["pass"]=bool(d["pass"])
        # Existing projects created before v9.2.0 have no explicit selection row;
        # in that case the newest revision remains active for compatibility.
        selected=selected_by_control[cid]
        d["active"]=(d["solution_id"]==selected) if selected else not any(x.get("control_id")==cid for x in out)
        out.append(d)
    return out


