from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from .audit import CURRENT_SCHEMA_VERSION, utc_now
from .project import SurveyProject

DATASETS = {
    "survey_points": {"table":"canonical_points","pk":"point_uuid","label":"Survey Points","mode":"controlled","fields":["point_id","northing","easting","elevation","description","point_class","crs","horizontal_units","vertical_units","review_state"]},
    "control_observations": {"table":"control_observations","pk":"observation_id","label":"Control Observations","mode":"controlled","fields":["control_id","point_id","northing","easting","elevation","h_sigma","v_sigma","observed_utc","observed_time_provided","epoch_count","duration_seconds","satellite_count","method","include","notes"]},
    "control_solutions": {"table":"control_solutions","pk":"solution_id","label":"Control Solutions","mode":"readonly","fields":[]},
    "level_runs": {"table":"level_runs","pk":"run_id","label":"Level Runs","mode":"editable","fields":["name","start_point","end_point","start_elevation","known_end_elevation","adjustment_method","status","notes"]},
    "level_observations": {"table":"level_observations","pk":"observation_id","label":"Level Observations","mode":"controlled","fields":["point_id","backsight","foresight","bs_upper","bs_middle","bs_lower","fs_upper","fs_middle","fs_lower","distance_bs","distance_fs","notes"]},
    "level_solutions": {"table":"level_solutions","pk":"solution_id","label":"Level Solutions","mode":"readonly","fields":[]},
    "traverse_runs": {"table":"traverse_runs","pk":"run_id","label":"Traverse Runs","mode":"editable","fields":["name","start_n","start_e","end_n","end_e","adjustment_method","status","notes"]},
    "traverse_courses": {"table":"traverse_courses","pk":"course_id","label":"Traverse Courses","mode":"controlled","fields":["from_point","to_point","azimuth_deg","distance","notes"]},
    "utility_structures": {"table":"utility_structures","pk":"structure_id","label":"Utility Structures","mode":"controlled","fields":["point_id","northing","easting","elevation","code","status","attributes_json"]},
    "utility_pipes": {"table":"utility_pipes","pk":"pipe_id","label":"Utility Pipes","mode":"controlled","fields":["dip","invert_elevation","diameter_in","material","azimuth_deg","connected_structure_id","grade_percent","status","attributes_json"]},
    "source_files": {"table":"source_registry","pk":"source_id","label":"Source Files","mode":"readonly","fields":[]},
    "attachments": {"table":"attachments","pk":"attachment_id","label":"Attachments","mode":"editable","fields":["caption"]},
    "qa_findings": {"table":"qa_issues","pk":"issue_id","label":"QA / QC Findings","mode":"readonly","fields":[]},
    "deliverables": {"table":"deliverables","pk":"deliverable_id","label":"Deliverables / Export History","mode":"readonly","fields":[]},
    "audit_history": {"table":"audit_events","pk":"event_id","label":"Audit History","mode":"readonly","fields":[]},
    "edit_history": {"table":"data_edit_history","pk":"edit_id","label":"Data Edit History","mode":"readonly","fields":[]},
}


def _dataset(key: str) -> dict:
    if key not in DATASETS:
        raise ValueError("Unknown Project Data Manager dataset.")
    return DATASETS[key]


def _count(project: SurveyProject, table: str) -> int:
    with project.db.connect() as conn:
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def overview(project: SurveyProject) -> dict:
    datasets=[]
    for key, meta in DATASETS.items():
        datasets.append({"id":key,"label":meta["label"],"mode":meta["mode"],"count":_count(project,meta["table"])})
    with project.db.connect() as conn:
        stale=int(conn.execute("SELECT COUNT(*) FROM derived_result_state WHERE state='STALE'").fetchone()[0])
    return {"schema_version":project.db.schema_version(),"required_schema_version":CURRENT_SCHEMA_VERSION,"database_path":str(project.paths.db),"size_bytes":project.paths.db.stat().st_size if project.paths.db.exists() else 0,"datasets":datasets,"stale_results":stale}


def list_rows(project: SurveyProject, dataset_id: str, *, search: str="", limit: int=200, offset: int=0) -> dict:
    meta=_dataset(dataset_id); table=meta["table"]; pk=meta["pk"]
    limit=max(1,min(int(limit),500)); offset=max(0,int(offset))
    with project.db.connect() as conn:
        cols=[r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
        where=""; args=[]
        if search.strip():
            searchable=[c for c in cols if c not in {"details_json","residuals_json","results_json","settings_json","metadata_json"}]
            where=" WHERE "+" OR ".join([f'CAST("{c}" AS TEXT) LIKE ?' for c in searchable])
            args=[f"%{search.strip()}%"]*len(searchable)
        total=int(conn.execute(f'SELECT COUNT(*) FROM "{table}"'+where,args).fetchone()[0])
        rows=[dict(r) for r in conn.execute(f'SELECT * FROM "{table}"'+where+f' ORDER BY rowid DESC LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()]
    return {"dataset":dataset_id,"label":meta["label"],"mode":meta["mode"],"pk":pk,"editable_fields":meta["fields"],"columns":cols,"rows":rows,"total":total,"limit":limit,"offset":offset}


def mark_derived_stale(project: SurveyProject, result_kind: str, object_id: str, *, reason: str, source_table: str="", source_record_id: str="", details: dict|None=None) -> None:
    if not object_id:
        return
    with project.db.connect() as conn:
        conn.execute("INSERT INTO derived_result_state(result_kind,object_id,state,reason,changed_utc,source_table,source_record_id,details_json) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(result_kind,object_id) DO UPDATE SET state=excluded.state,reason=excluded.reason,changed_utc=excluded.changed_utc,source_table=excluded.source_table,source_record_id=excluded.source_record_id,details_json=excluded.details_json",(result_kind,object_id,"STALE",reason,utc_now(),source_table,source_record_id,json.dumps(details or {},ensure_ascii=False)))


def clear_derived_stale(project: SurveyProject, result_kind: str, object_id: str, *, reason: str="Recalculated") -> None:
    if not object_id: return
    with project.db.connect() as conn:
        conn.execute("INSERT INTO derived_result_state(result_kind,object_id,state,reason,changed_utc) VALUES(?,?,?,?,?) ON CONFLICT(result_kind,object_id) DO UPDATE SET state='CURRENT',reason=excluded.reason,changed_utc=excluded.changed_utc",(result_kind,object_id,"CURRENT",reason,utc_now()))


def update_record(project: SurveyProject, dataset_id: str, record_id: str, changes: dict, reason: str="") -> dict:
    meta=_dataset(dataset_id)
    if meta["mode"]=="readonly": raise ValueError("This dataset is read-only in Project Data Manager.")
    if meta["mode"]=="controlled" and not str(reason).strip(): raise ValueError("Controlled survey-data edits require a reason.")
    allowed=set(meta["fields"]); clean={k:v for k,v in changes.items() if k in allowed}
    if not clean: raise ValueError("No editable fields were supplied.")
    table=meta["table"]; pk=meta["pk"]
    safety=None
    if meta["mode"]=="controlled":
        from .continuity import create_snapshot
        safety=create_snapshot(project,label=f"Before Project Data Manager edit: {meta['label']} {record_id}",kind="manual")
    with project.db.connect() as conn:
        old=conn.execute(f'SELECT * FROM "{table}" WHERE "{pk}"=?',(record_id,)).fetchone()
        if not old: raise ValueError("Record was not found.")
        old=dict(old)
        update_values=dict(clean)
        if table=="canonical_points":
            update_values["modified_utc"]=utc_now(); update_values["revision"]=int(old.get("revision") or 0)+1
        elif table=="utility_structures":
            update_values["modified_utc"]=utc_now()
        assignments=", ".join([f'"{k}"=?' for k in update_values])
        conn.execute(f'UPDATE "{table}" SET {assignments} WHERE "{pk}"=?',list(update_values.values())+[record_id])
        for field,new_value in clean.items():
            if old.get(field)==new_value: continue
            conn.execute("INSERT INTO data_edit_history(edit_id,ts_utc,actor,table_name,record_id,field_name,old_value_json,new_value_json,reason,details_json) VALUES(?,?,?,?,?,?,?,?,?,?)",(uuid4().hex,utc_now(),"local-user",table,record_id,field,json.dumps(old.get(field),ensure_ascii=False),json.dumps(new_value,ensure_ascii=False),str(reason or ""),json.dumps({"dataset":dataset_id},ensure_ascii=False)))
    stale=[]
    if table=="control_observations": stale=[("control",str(clean.get("control_id") or old.get("control_id") or ""))]
    elif table=="level_observations": stale=[("level",str(old.get("run_id") or ""))]
    elif table=="traverse_courses": stale=[("traverse",str(old.get("run_id") or ""))]
    elif table in {"utility_structures","utility_pipes"}: stale=[("utility",str(old.get("structure_id") or old.get("point_id") or record_id))]
    elif table=="canonical_points": stale=[("project_points",str(project.manifest.get("project_id") or ""))]
    for kind,obj in stale: mark_derived_stale(project,kind,obj,reason=f"Source data edited in {meta['label']}",source_table=table,source_record_id=record_id,details={"fields":list(clean),"edit_reason":reason})
    project.db.audit("Core","PROJECT_DATA_EDITED",object_type=dataset_id,object_id=record_id,revision=int(project.manifest.get("revision",0)),details={"changes":list(clean),"reason":reason,"mode":meta["mode"],"snapshot_id":(safety or {}).get("snapshot_id","")})
    return {"ok":True,"dataset":dataset_id,"record_id":record_id,"changes":clean,"reason":reason,"stale_results":[{"kind":k,"object_id":o} for k,o in stale],"snapshot":safety}


def database_health(project: SurveyProject) -> dict:
    conn=sqlite3.connect(str(project.paths.db),timeout=30)
    try:
        integrity=[r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
        fk=[list(r) for r in conn.execute("PRAGMA foreign_key_check").fetchall()]
        version=int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
        journal=str(conn.execute("PRAGMA journal_mode").fetchone()[0])
        stale=int(conn.execute("SELECT COUNT(*) FROM derived_result_state WHERE state='STALE'").fetchone()[0])
    finally: conn.close()
    return {"integrity_ok":integrity==["ok"],"integrity":integrity,"foreign_key_issues":fk,"schema_version":version,"required_schema_version":CURRENT_SCHEMA_VERSION,"schema_current":version==CURRENT_SCHEMA_VERSION,"journal_mode":journal,"size_bytes":project.paths.db.stat().st_size if project.paths.db.exists() else 0,"stale_results":stale}


def maintain_database(project: SurveyProject) -> dict:
    from .continuity import create_snapshot
    snapshot=create_snapshot(project,label="Automatic safety snapshot before database maintenance",kind="manual")
    conn=sqlite3.connect(str(project.paths.db),timeout=30)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("ANALYZE")
        conn.execute("PRAGMA optimize")
        conn.commit()
    finally: conn.close()
    health=database_health(project)
    project.db.audit("Core","DATABASE_MAINTENANCE_RUN",object_type="project_database",object_id=str(project.manifest.get("project_id") or ""),details={"snapshot_id":snapshot.get("snapshot_id"),"health":health})
    return {"ok":health["integrity_ok"] and not health["foreign_key_issues"],"snapshot":snapshot,"health":health}
