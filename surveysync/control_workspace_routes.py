from __future__ import annotations

import csv
import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .audit import utc_now
from .control import (
    get_control_qc_run,
    list_control_ids,
    list_observations,
    run_best_triplet_qc,
    write_control_qc_deliverables,
    get_control_group_overrides,
    set_control_group_override,
    list_control_qc_profiles,
    save_control_qc_profile,
    list_control_import_diagnostics,
    parse_control_source,
    merge_control_metadata,
    save_control_import_diagnostic,
    import_observations,
    detect_control_import_overlap,
)
from .crs import browse_crs_library, inspect_crs, project_xy_to_target, search_crs_library
from .project import SurveyProject, safe_name
from .control_import_mapping import preview_control_delimited, learn_control_mapping
from .reporting import register_deliverable

router = APIRouter()


def _project() -> SurveyProject:
    # Import lazily to avoid a module-import cycle while keeping the pre-9.3 root
    # router as the single owner of the current-project process state.
    from . import router as root_router

    return root_router.require_project()


class CoordinateSystemIn(BaseModel):
    crs: str
    horizontal_units: str = "us_survey_feet"
    vertical_units: str = "us_survey_feet"
    local_site: dict = Field(default_factory=dict)


class BestTripletQcIn(BaseModel):
    horizontal_tolerance: float = 0.045
    vertical_tolerance: float = 0.045
    reshoot_count: int = Field(default=3, ge=1, le=20)
    spatial_group_tolerance: float | None = Field(default=None, gt=0)
    vertical_group_tolerance: float | None = Field(default=None, gt=0)
    require_field_metadata: bool = True
    min_time_separation_minutes: float = Field(default=60.0, gt=0)
    min_epochs: int = Field(default=300, ge=1)
    min_observation_minutes: float = Field(default=5.0, gt=0)
    min_satellites: int = Field(default=5, ge=1)
    max_pdop: float | None = Field(default=None, gt=0)
    max_hdop: float | None = Field(default=None, gt=0)
    max_vdop: float | None = Field(default=None, gt=0)


class ControlGroupReviewIn(BaseModel):
    observation_id: str
    status: Literal["CONFIRMED", "REJECTED", "REASSIGNED"]
    assigned_control_id: str = ""
    assigned_point_id: str = ""
    reason: str = ""


class ControlQcProfileIn(BaseModel):
    profile_id: str = ""
    name: str = "Ron Control Standard"
    is_default: bool = False
    horizontal_tolerance: float = Field(default=0.045, gt=0)
    vertical_tolerance: float = Field(default=0.045, gt=0)
    spatial_group_tolerance: float | None = Field(default=None, gt=0)
    vertical_group_tolerance: float | None = Field(default=None, gt=0)
    require_field_metadata: bool = True
    min_time_separation_minutes: float = Field(default=60.0, gt=0)
    min_epochs: int = Field(default=300, ge=1)
    min_observation_seconds: float = Field(default=300.0, gt=0)
    min_satellites: int = Field(default=5, ge=1)
    max_pdop: float | None = Field(default=None, gt=0)
    max_hdop: float | None = Field(default=None, gt=0)
    max_vdop: float | None = Field(default=None, gt=0)


class ControlImportPreviewIn(BaseModel):
    file_path: str
    mapping: dict = Field(default_factory=dict)
    preview_rows: int = 12


class ControlMappedImportIn(BaseModel):
    file_path: str
    mapping: dict = Field(default_factory=dict)
    remember_mapping: bool = True


class ControlMetadataMergeIn(BaseModel):
    file_path: str


class ControlExportIn(BaseModel):
    run_id: str = ""
    fields: list[str] = Field(
        default_factory=lambda: [
            "control_id",
            "northing",
            "easting",
            "elevation",
            "code",
            "horizontal_residual",
            "vertical_residual",
            "source_observations",
            "numbering_flags",
            "field_qc_status",
            "minimum_time_gap_minutes",
            "qc_status",
        ]
    )
    coordinate_mode: Literal["project", "geographic", "target"] = "project"
    target_crs: str = ""
    output_format: Literal["csv", "txt"] = "csv"
    profile_name: str = "Control Export"


_ALLOWED_EXPORT_FIELDS = {
    "control_id",
    "northing",
    "easting",
    "elevation",
    "code",
    "latitude",
    "longitude",
    "horizontal_residual",
    "vertical_residual",
    "source_observations",
    "numbering_flags",
    "field_qc_status",
    "minimum_time_gap_minutes",
    "qc_status",
    "project_crs",
    "output_crs",
}


@router.get("/api/v9/crs/library")
def crs_library(query: str = "", limit: int = 80):
    try:
        return {"results": search_crs_library(query, limit=limit, projected_only=False)}
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/v9/crs/browser")
def crs_browser(path: str = "", limit: int = 600):
    try:
        return browse_crs_library(path, limit=limit)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/v9/project/coordinate-system")
def project_coordinate_system():
    return _project().coordinate_settings()


@router.post("/api/v9/project/coordinate-system")
def save_project_coordinate_system(payload: CoordinateSystemIn):
    project = _project()
    try:
        project.set_coordinate_system(payload.crs, payload.horizontal_units, payload.vertical_units, payload.local_site)
        return project.coordinate_settings()
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/v9/control/workspace")
def control_workspace(limit: int = 10000):
    project = _project()
    latest = get_control_qc_run(project.db)
    return {
        "coordinate_system": project.coordinate_settings(),
        "controls": list_control_ids(project.db),
        "observations": list_observations(project.db, limit=limit),
        "latest_qc_run": latest,
        "qc_profiles": list_control_qc_profiles(project.db),
        "import_diagnostics": list_control_import_diagnostics(project.db, 10),
        "group_overrides": list(get_control_group_overrides(project.db).values()),
    }


@router.post("/api/v9/control/qc-best-three")
def control_best_three(payload: BestTripletQcIn):
    project = _project()
    settings = project.coordinate_settings()
    if not settings.get("crs"):
        raise HTTPException(409, "Set the project coordinate system before running Control QC.")
    try:
        result = run_best_triplet_qc(
            project.db,
            payload.horizontal_tolerance,
            payload.vertical_tolerance,
            coordinate_context=settings,
            reshoot_count=payload.reshoot_count,
            spatial_group_tolerance=payload.spatial_group_tolerance,
            vertical_group_tolerance=payload.vertical_group_tolerance,
            require_field_metadata=payload.require_field_metadata,
            min_time_separation_minutes=payload.min_time_separation_minutes,
            min_epochs=payload.min_epochs,
            min_duration_seconds=payload.min_observation_minutes*60.0,
            min_satellites=payload.min_satellites,
            max_pdop=payload.max_pdop,max_hdop=payload.max_hdop,max_vdop=payload.max_vdop,
        )
        deliverables = write_control_qc_deliverables(result, project.paths.reports)
        registered = []
        for kind, value in deliverables.items():
            if not str(kind).endswith(("csv", "xlsx")):
                continue
            path = Path(str(value))
            if path.is_file():
                registered.append(
                    register_deliverable(
                        project,
                        path,
                        module="ControlSync",
                        kind=f"control_qc_{kind}",
                        metadata={"run_id": result["run_id"], "horizontal_tolerance": payload.horizontal_tolerance, "vertical_tolerance": payload.vertical_tolerance, "spatial_group_tolerance": result.get("spatial_grouping",{}).get("tolerance"), "field_requirements": result.get("field_requirements",{})},
                    )
                )
        result["deliverables"] = deliverables
        result["registered_deliverables"] = registered
        return result
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/v9/control/qc-profiles")
def control_qc_profiles():
    return {"profiles": list_control_qc_profiles(_project().db)}


@router.post("/api/v9/control/qc-profiles")
def control_qc_profile_save(payload: ControlQcProfileIn):
    try:
        return save_control_qc_profile(_project().db, payload.model_dump())
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/control/import-preview")
def control_import_preview(payload: ControlImportPreviewIn):
    project=_project(); path=Path(payload.file_path).expanduser().resolve()
    try:
        if path.suffix.lower() in {".job",".jxl",".xml"}:
            return {"format":"trimble","mapping_required":False,"ready":True,"source_path":str(path),"message":"Trimble JOB/JobXML uses structured fields and does not require column mapping."}
        result=preview_control_delimited(project,path,payload.mapping,payload.preview_rows)
        result["mapping_required"]=True
        return result
    except (ValueError,OSError,RuntimeError,sqlite3.Error) as exc:
        raise HTTPException(400,str(exc)) from exc


@router.post("/api/v9/control/import-mapped")
def control_import_mapped(payload: ControlMappedImportIn):
    project=_project(); path=Path(payload.file_path).expanduser().resolve()
    try:
        src=project.import_source(path,"ControlSync","Raw control observations")
        with project.db.connect() as conn:
            prior_count=int(conn.execute("SELECT COUNT(*) FROM control_observations WHERE source_id=?",(src["source_id"],)).fetchone()[0])
        if prior_count:
            return {"count":0,"already_imported":True,"existing_observation_count":prior_count,"source_id":src["source_id"],"controls":list_control_ids(project.db)}
        immutable=Path(src["stored_path"])
        if not immutable.is_absolute(): immutable=(project.paths.root/immutable).resolve()
        parsed=parse_control_source(immutable,project.paths.derived/"ControlSync"/"Trimble"/src["source_id"],mapping=payload.mapping)
        rows=parsed.get("observations") or []
        overlap=detect_control_import_overlap(project.db,rows)
        count=import_observations(project.db,rows,src["source_id"])
        diagnostic=save_control_import_diagnostic(project.db,src["source_id"],parsed)
        if parsed.get("format")=="delimited" and payload.remember_mapping:
            preview=preview_control_delimited(project,path,payload.mapping,3)
            # Never auto-save a headerless mapping under generic Column N names;
            # another headerless file with the same width may use a different order.
            if preview.get("has_header"):
                learn_control_mapping(project,preview.get("headers") or [],preview.get("mapping") or {},label=path.suffix.lower().lstrip(".") or "control")
        project.db.audit("ControlSync","CONTROL_OBSERVATIONS_IMPORTED",object_type="source",object_id=src["source_id"],details={"count":count,"format":parsed.get("format"),"diagnostic":diagnostic,"overlap":overlap,"column_mapping":payload.mapping if parsed.get("format")=="delimited" else {}})
        return {"count":count,"already_imported":False,"source_id":src["source_id"],"controls":list_control_ids(project.db),"format":parsed.get("format"),"trimble_metadata":parsed.get("metadata",{}),"conversion":parsed.get("conversion",{}),"jobxml_path":parsed.get("jobxml_path",""),"field_metadata_counts":parsed.get("field_metadata_counts",{}),"diagnostic":diagnostic,"overlap":overlap}
    except (ValueError,OSError,RuntimeError,sqlite3.Error) as exc:
        raise HTTPException(400,str(exc)) from exc


@router.get("/api/v9/control/import-diagnostics")
def control_import_diagnostics(limit: int=20):
    return {"diagnostics": list_control_import_diagnostics(_project().db, limit)}


@router.get("/api/v9/control/grouping-reviews")
def control_grouping_reviews():
    latest=get_control_qc_run(_project().db)
    flags=((latest.get("spatial_grouping") or {}).get("flags") or []) if latest else []
    overrides=get_control_group_overrides(_project().db)
    return {"flags":[f for f in flags if f.get("type") in {"PROBABLE_MISNUMBER","SPATIAL_ID_CONFLICT"}],"overrides":list(overrides.values())}


@router.post("/api/v9/control/grouping-reviews")
def control_grouping_review_save(payload: ControlGroupReviewIn):
    try:
        return set_control_group_override(_project().db, payload.observation_id, status=payload.status, assigned_control_id=payload.assigned_control_id, assigned_point_id=payload.assigned_point_id, reason=payload.reason)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/control/merge-metadata")
def control_merge_metadata(payload: ControlMetadataMergeIn):
    project=_project(); path=Path(payload.file_path).expanduser().resolve()
    try:
        src=project.import_source(path,"ControlSync","Raw GNSS metadata merge source")
        immutable=Path(src["stored_path"])
        if not immutable.is_absolute(): immutable=(project.paths.root/immutable).resolve()
        parsed=parse_control_source(immutable,project.paths.derived/"ControlSync"/"Trimble"/src["source_id"])
        diagnostic=save_control_import_diagnostic(project.db,src["source_id"],parsed)
        merged=merge_control_metadata(project.db,parsed.get("observations") or [],src["source_id"])
        return {"source_id":src["source_id"],"diagnostic":diagnostic,**merged}
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/control/export-package")
def control_export_package(run_id: str=""):
    project=_project(); result=get_control_qc_run(project.db,run_id)
    if not result: raise HTTPException(404,"Run Control QC before building a control package.")
    try:
        files=write_control_qc_deliverables(result,project.paths.reports)
        stamp=utc_now().replace(":","-")
        package=project.paths.exports/"ControlSync"/f"ControlSync_QC_Package_{stamp}.zip"
        package.parent.mkdir(parents=True,exist_ok=True)
        provenance={"run_id":result.get("run_id"),"coordinate_context":result.get("coordinate_context"),"field_requirements":result.get("field_requirements"),"spatial_grouping":result.get("spatial_grouping"),"algorithm":result.get("algorithm"),"results":result.get("results")}
        with zipfile.ZipFile(package,"w",zipfile.ZIP_DEFLATED) as zf:
            for value in files.values():
                fp=Path(str(value))
                if fp.is_file(): zf.write(fp,fp.name)
            zf.writestr("ControlSync_Provenance.json",json.dumps(provenance,indent=2,sort_keys=True))
        deliverable=register_deliverable(project,package,module="ControlSync",kind="control_qc_package",metadata={"run_id":result.get("run_id")})
        return {"path":str(package),"run_id":result.get("run_id"),"deliverable":deliverable}
    except (ValueError,OSError,RuntimeError,sqlite3.Error) as exc:
        raise HTTPException(400,str(exc)) from exc


@router.get("/api/v9/control/qc-run")
def control_qc_run(run_id: str = ""):
    result = get_control_qc_run(_project().db, run_id)
    if not result:
        raise HTTPException(404, "Control QC run was not found.")
    return result


@router.post("/api/v9/control/qc-deliverables")
def control_qc_deliverables(run_id: str = ""):
    project = _project()
    result = get_control_qc_run(project.db, run_id)
    if not result:
        raise HTTPException(404, "Run Control QC before exporting accepted/reshoot lists.")
    try:
        files = write_control_qc_deliverables(result, project.paths.reports)
        registered = []
        for kind, value in files.items():
            if not str(kind).endswith(("csv", "xlsx")):
                continue
            path = Path(str(value))
            if path.is_file():
                registered.append(register_deliverable(project, path, module="ControlSync", kind=f"control_qc_{kind}", metadata={"run_id": result.get("run_id")}))
        return {"run_id": result.get("run_id"), "files": files, "registered_deliverables": registered}
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc)) from exc


def _accepted_rows(result: dict) -> list[dict]:
    rows = []
    for item in result.get("results", []):
        if item.get("status") != "PASS":
            continue
        selected = item.get("selected") or {}
        rows.append(
            {
                "control_id": item.get("control_id", ""),
                "northing": selected.get("northing"),
                "easting": selected.get("easting"),
                "elevation": selected.get("elevation"),
                "code": selected.get("code", ""),
                "horizontal_residual": selected.get("max_horizontal_residual"),
                "vertical_residual": selected.get("max_vertical_residual"),
                "source_observations": ";".join(selected.get("point_ids") or []),
                "numbering_flags": "; ".join(flag.get("message", "") for flag in item.get("numbering_flags") or []),
                "field_qc_status": (selected.get("field_validation") or {}).get("status", ""),
                "minimum_time_gap_minutes": ((selected.get("field_validation") or {}).get("time_separation") or {}).get("minimum_gap_minutes"),
                "qc_status": "PASS",
            }
        )
    return rows


def _coordinate_values(project: SurveyProject, row: dict, mode: str, target_crs: str) -> dict:
    settings = project.coordinate_settings()
    project_crs = str(settings.get("crs") or "")
    local_site = settings.get("local_site") or {}
    e = float(row["easting"])
    n = float(row["northing"])

    # Geographic columns are always available to custom profiles when a project CRS
    # exists, regardless of the primary output coordinate mode.
    lon, lat = project_xy_to_target(e, n, project_crs=project_crs, local_site=local_site, target_crs="EPSG:4326")
    if mode == "project":
        out_e, out_n = e, n
        output_crs = f"{project_crs} (local site)" if local_site.get("enabled") else project_crs
    elif mode == "geographic":
        out_e, out_n = lon, lat
        output_crs = "EPSG:4326"
    else:
        if not str(target_crs or "").strip():
            raise ValueError("Choose a target CRS for a target-coordinate export.")
        out_e, out_n = project_xy_to_target(e, n, project_crs=project_crs, local_site=local_site, target_crs=target_crs)
        output_crs = target_crs
    return {
        "easting": out_e,
        "northing": out_n,
        "longitude": lon,
        "latitude": lat,
        "project_crs": project_crs,
        "output_crs": output_crs,
    }


@router.get("/api/v9/control/export-profiles")
def control_export_profiles():
    project = _project()
    prefix = "control_export_profile:"
    with project.db.connect() as conn:
        rows = conn.execute("SELECT key,value,updated_utc FROM project_metadata WHERE key LIKE ? ORDER BY key", (f"{prefix}%",)).fetchall()
    profiles = []
    for row in rows:
        try:
            payload = json.loads(row["value"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        profiles.append({"name": row["key"][len(prefix):], "updated_utc": row["updated_utc"], "profile": payload})
    return {"profiles": profiles}


@router.post("/api/v9/control/qc-export")
def control_qc_export(payload: ControlExportIn):
    project = _project()
    result = get_control_qc_run(project.db, payload.run_id)
    if not result:
        raise HTTPException(404, "Run Control QC before exporting accepted controls.")
    fields = [field for field in payload.fields if field in _ALLOWED_EXPORT_FIELDS]
    if payload.coordinate_mode == "geographic":
        # Keep headers semantically correct: a geographic export uses Latitude/Longitude,
        # never columns named Northing/Easting containing angular values.
        mapped=[]
        for field in fields:
            field = "latitude" if field == "northing" else "longitude" if field == "easting" else field
            if field not in mapped:
                mapped.append(field)
        fields=mapped
    elif payload.coordinate_mode == "target":
        if not str(payload.target_crs or "").strip():
            raise HTTPException(400, "Choose a target CRS for a target-coordinate export.")
        target_info=inspect_crs(payload.target_crs)
        if not target_info.get("valid"):
            raise HTTPException(400, target_info.get("message") or "Target CRS is invalid.")
        if not target_info.get("is_projected"):
            raise HTTPException(400, "Target CRS exports using Northing/Easting require a projected CRS. Choose Geographic for latitude/longitude.")
    if not fields:
        raise HTTPException(400, "Choose at least one supported export field.")
    rows = _accepted_rows(result)
    stamp = utc_now().replace(":", "-")
    suffix = ".csv" if payload.output_format == "csv" else ".txt"
    path = project.paths.exports / "ControlSync" / f"{safe_name(payload.profile_name)}_{stamp}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        rendered = []
        for row in rows:
            coord = _coordinate_values(project, row, payload.coordinate_mode, payload.target_crs)
            merged = {**row, **coord}
            rendered.append({field: merged.get(field, "") for field in fields})
        delimiter = "," if payload.output_format == "csv" else "\t"
        with path.open("w", newline="", encoding="utf-8-sig" if payload.output_format == "csv" else "utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter=delimiter)
            writer.writeheader()
            writer.writerows(rendered)
        with project.db.connect() as conn:
            conn.execute(
                "INSERT INTO project_metadata(key,value,updated_utc) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_utc=excluded.updated_utc",
                (
                    f"control_export_profile:{safe_name(payload.profile_name)}",
                    json.dumps(payload.model_dump(), sort_keys=True),
                    utc_now(),
                ),
            )
        project.db.audit(
            "ControlSync",
            "CONTROL_CUSTOM_EXPORT",
            object_type="control_qc_run",
            object_id=str(result.get("run_id") or ""),
            details={"path": str(path), "fields": fields, "coordinate_mode": payload.coordinate_mode, "target_crs": payload.target_crs, "row_count": len(rendered)},
        )
        deliverable = register_deliverable(project, path, module="ControlSync", kind="control_custom_export", metadata={"run_id": result.get("run_id"), "fields": fields, "coordinate_mode": payload.coordinate_mode, "target_crs": payload.target_crs})
        return {"path": str(path), "row_count": len(rendered), "fields": fields, "coordinate_mode": payload.coordinate_mode, "target_crs": payload.target_crs, "deliverable": deliverable}
    except HTTPException:
        raise
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc)) from exc
