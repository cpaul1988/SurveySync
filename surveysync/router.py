from __future__ import annotations
from .api_models import (
    CreateProjectIn as CreateProjectIn,
    OpenProjectIn as OpenProjectIn,
    ProjectForgetIn as ProjectForgetIn,
    ProjectDeleteIn as ProjectDeleteIn,
    EnvIn as EnvIn,
    BrandSelectIn as BrandSelectIn,
    BrandProfileIn as BrandProfileIn,
    CrsUnitsIn as CrsUnitsIn,
    CogoInverseIn as CogoInverseIn,
    CogoBDIn as CogoBDIn,
    CogoIntersectIn as CogoIntersectIn,
    CrsInspectIn as CrsInspectIn,
    CrsTransformIn as CrsTransformIn,
    RangeIn as RangeIn,
    ControlImportIn as ControlImportIn,
    ControlAnalyzeAllIn as ControlAnalyzeAllIn,
    ControlImportAnalyzeIn as ControlImportAnalyzeIn,
    ControlSolveIn as ControlSolveIn,
    RonControlFromPointsIn as RonControlFromPointsIn,
    ControlRevisionSelectIn as ControlRevisionSelectIn,
    FeedbackIn as FeedbackIn,
    SourceImportIn as SourceImportIn,
    PointImportIn as PointImportIn,
    TrimbleJobImportIn as TrimbleJobImportIn,
    UpdateConfigIn as UpdateConfigIn,
    UpdateInstallIn as UpdateInstallIn,
    FeedbackConfigIn as FeedbackConfigIn,
    ErrorLogSyncIn as ErrorLogSyncIn,
    AiConfigIn as AiConfigIn,
    UiConfigIn as UiConfigIn,
    LevelImportIn as LevelImportIn,
    LevelSolveIn as LevelSolveIn,
    LevelRevisionSelectIn as LevelRevisionSelectIn,
    TraverseImportIn as TraverseImportIn,
    TraverseSolveIn as TraverseSolveIn,
    ScaleSampleIn as ScaleSampleIn,
    ScaleFitIn as ScaleFitIn,
    ProjectionSamplesIn as ProjectionSamplesIn,
    SpatialImportIn as SpatialImportIn,
    FieldToFinishIn as FieldToFinishIn,
    UtilitySyncIn as UtilitySyncIn,
    UtilityAnalyzeIn as UtilityAnalyzeIn,
    UtilityInvertIn as UtilityInvertIn,
    UtilityKmlIn as UtilityKmlIn,
    AttachmentIn as AttachmentIn,
    AutoPhotoIn as AutoPhotoIn,
    SurveyReportIn as SurveyReportIn,
    NotificationPolicyIn as NotificationPolicyIn,
    EmailNotificationIn as EmailNotificationIn,
    TrimbleProjectsIn as TrimbleProjectsIn,
    CloudImportIn as CloudImportIn,
    AnnotatedFieldbookIn as AnnotatedFieldbookIn,
    QaRulesIn as QaRulesIn,
    QaIssueStatusIn as QaIssueStatusIn,
    StageImportIn as StageImportIn,
    CommitStageIn as CommitStageIn,
    LearnMappingIn as LearnMappingIn,
    SnapshotCreateIn as SnapshotCreateIn,
    SnapshotRestoreIn as SnapshotRestoreIn,
    CompareFileIn as CompareFileIn,
    ExportProfileIn as ExportProfileIn,
    ExportRunIn as ExportRunIn,
    PackageBuildIn as PackageBuildIn,
    BatchIn as BatchIn,
    TaskCancelIn as TaskCancelIn,
    DataEditIn as DataEditIn,
)

import csv
import json
import os
import shutil
import urllib.request
import urllib.error
import threading
import time
from pathlib import Path
from threading import RLock
from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import __version__
from .audit import utc_now
from .config import AppConfig, ConfigStore, ENVIRONMENTS, RELEASE_CHANNELS, DEFAULT_UPDATE_MANIFEST_URL
from .project import SurveyProject, safe_name
from .project_templates import list_templates as list_project_templates
from .data_manager import overview as data_overview, list_rows as data_rows, update_record as update_data_record, database_health, maintain_database
from .cogo import inverse, bearing_distance, line_intersection
from .reports import (
    parse_point_ids_file, available_ranges, ranges_csv, crew_range_recommendations,
    crew_ranges_csv, crew_ranges_txt, write_crew_ranges_xlsx,
)
from .control import parse_control_csv, parse_control_source, import_observations, solve as solve_control, list_control_ids, list_observations as list_control_observations, analyze_all as analyze_all_controls, write_ron_control_deliverables, save_control_import_diagnostic, detect_control_import_overlap
from .qa import run_project_qa
from .qa_rules import load_rules as load_qa_rules, save_rules as save_qa_rules
from .staging import stage_import, list_stages, commit_stage, learn_mapping, load_mapping_profiles
from .continuity import create_snapshot, list_snapshots, compare_snapshot, restore_snapshot, autosave_tick
from .comparison import compare_point_file, compare_point_source
from .delivery import load_profiles as load_export_profiles, save_profile as save_export_profile, export_points as run_export_profile, build_deliverable_package
from .operations import project_timeline, review_center, explain as explain_item, project_map_geojson
from .task_queue import submit as submit_background_task, list_tasks as list_background_tasks, cancel as cancel_background_task
from .updater import check as update_check, stage as update_stage
from .crs import inspect_crs, transform_xy
from .ai_runtime import DEFAULT_FOUNDRY_VISION_MODEL, enable_foundry_model, ensure_windows_feature, get_local_ai_status
from .control import list_solutions as list_control_solutions
from .leveling import parse_level_csv, import_run as import_level_run, solve_saved_run as solve_level_saved, list_runs as list_level_runs, solution_history as level_solution_history
from .revisions import set_active_solution, compare_control_solutions, compare_level_solutions
from .traverse import parse_traverse_csv, import_run as import_traverse_run, solve_saved_run as solve_traverse_saved, list_runs as list_traverse_runs
from .scale_factor import ScaleSample, fit_project_factor, projection_scale_samples, save_solution as save_scale_solution, list_solutions as list_scale_solutions
from .spatial import import_spatial, list_layers as list_spatial_layers
from .field_to_finish import parse_coded_points, build_linework, to_geojson
from .utility import sync_fieldbook_results, score_supplemental_gis, pipe_grades, completion_status, export_completion_kmz
from .attachments import attach_file, list_attachments, auto_attach_photos
from .reporting import project_report, control_report, list_deliverables, register_deliverable
from .notifications import send_deliverable_notification, list_notifications, load_policy as load_notification_policy, save_policy as save_notification_policy
from .field_cloud import trimble_list_projects, import_cloud_file, list_sync_log
from .trimble_job import prepare_jobxml, parse_jobxml_points, trimble_runtime_status, TrimbleJobError
from .logging_config import configure_logging as configure_core_logging
from .control_workspace_routes import router as control_workspace_router
from .diagnostics import (
    build_diagnostic_bundle,
    error_log_path,
    list_errors as list_diagnostic_errors,
    record_error as record_diagnostic_error,
    submit_error_log,
)

STATIC = Path(__file__).resolve().parent / "static"
router = APIRouter()
router.include_router(control_workspace_router)
from .topo.routes import router as topo_router
router.include_router(topo_router)
config_store = ConfigStore()
core_logger = configure_core_logging(config_store.root / "logs")
project_lock = RLock()
current_project: SurveyProject | None = None

SURVEYSYNC_RELEASE_NOTES = [
    "9.3.0: unified release checks, hashed dependency locks, modularized processing and visible recovery diagnostics.",
    "TopoSync adds standalone rod-height range detection, code-list review, chain evidence and separate reviewed correction exports; supplied SurveySync branding is integrated.",
    "Coordinate sanity now keeps Northing/Easting/PointID row-aligned, excludes non-finite pairs explicitly, and reports the correct point when a remote coordinate is flagged.",
    "SurveySync core persistence/configuration fallbacks now log diagnostic context instead of silently swallowing broad exceptions; FieldBook state persistence received the same treatment.",
    "A new static-quality build gate blocks new blind broad-exception passes, dangerous eval/exec or shell=True use, committed key patterns, duplicate routes/functions, mutable defaults, and further growth of the two pre-9.3 API monoliths.",
    "Each SurveySync project now owns an independent versioned SQLite database bootstrapped from the SurveySync master project template.",
    "New Project templates can seed module availability and QA defaults for Standard, EDSI Engineering/Topo, Boundary, Sewer/Utility, Control Network, and Construction Staking workflows.",
    "Project Data Manager provides a survey-friendly table browser with search, controlled edits, edit history, and read-only protection for immutable/system records.",
    "Controlled survey-data edits create a safety snapshot, require a reason, write field-level audit history, and mark dependent calculations stale for review.",
    "Database Health reports integrity, foreign-key status, schema version, stale results and database size; maintenance creates a safety snapshot before WAL checkpoint/optimization.",
    "ControlSync now provides a TBC-inspired Control Survey workspace: choose the project CRS/local-site ground settings, load all observations, view them spatially, and run Ronald's best-three QC across the complete database.",
    "Control QC evaluates every valid three-shot combination at project tolerances (0.045 ft H/V by default), preserves candidate provenance, exports accepted control plus reshoot lists, and proposes the next unused shot labels.",
    "ControlSync custom exports can select output fields and default to the active project/local-site coordinate system or deliberately transform to WGS84/another CRS.",
    "Every SurveySync file/folder path field now has a native Browse control, including multi-file batch paths; users no longer need to type Windows paths manually.",
    "Project Health Check now runs project-wide preflight for duplicate PointIDs, missing coordinates/elevations, CRS/units, control/level QC, source integrity, attachments, stale outputs, failed tasks, and coordinate sanity.",
    "Central QA rules make tolerances and guardrails reusable across SurveySync instead of hard-coding review logic separately in each module.",
    "Import Staging previews survey point files, detects/learns column mappings, identifies conflicts before commit, and never overwrites an existing PointID silently.",
    "Project Timeline, automatic crash-recovery snapshots, manual snapshots, snapshot comparison/restore, and file comparison improve traceability and recovery.",
    "Smart export profiles and the Deliverable Package Builder create repeatable point exports plus checksum-backed ZIP manifests.",
    "Background task queue, batch staging/comparison, unified Review Center, project visual-QC map, and Why? explanations make outstanding work easier to find and understand.",
]



def _fieldbook_app_module():
    from fieldbook_sync import app as field_app
    return field_app


def _bind_fieldbook(project: SurveyProject) -> dict:
    field_app = _fieldbook_app_module()
    result = field_app.rebind_project_storage(project.paths.fieldbook_root)
    # AI provider is a workstation-wide SurveySync preference, not survey data.
    try:
        cfg = config_store.load()
        field_app.runtime.provider = cfg.ai_provider
        saved = field_app.runtime.storage.load_settings()
        saved["provider"] = cfg.ai_provider
        saved["provider_user_set"] = True
        saved["auto_ai_default_migrated_v901"] = True
        field_app.runtime.storage.save_settings(saved)
    except Exception:
        core_logger.warning("FieldBookSync provider settings could not be rebound for project %s.", project.paths.root, exc_info=True)
    return result


def _path_key(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(value))))


def _remember_project(path: Path) -> None:
    cfg = config_store.load()
    text = str(Path(path).expanduser().resolve())
    key = _path_key(text)
    cfg.last_project = text
    cfg.recent_projects = [text] + [p for p in cfg.recent_projects if _path_key(p) != key]
    cfg.recent_projects = cfg.recent_projects[:24]
    config_store.save(cfg)


def _forget_project(path: Path, *, clear_last: bool = True) -> None:
    cfg = config_store.load()
    key = _path_key(path)
    cfg.recent_projects = [p for p in cfg.recent_projects if _path_key(p) != key]
    if clear_last and cfg.last_project and _path_key(cfg.last_project) == key:
        cfg.last_project = ""
    config_store.save(cfg)


def _set_current(project: SurveyProject) -> SurveyProject:
    global current_project
    with project_lock:
        _bind_fieldbook(project)
        current_project = project
        _remember_project(project.paths.root)
    return project


def _project_list_item(path_value: str | Path) -> dict:
    root = Path(path_value).expanduser().resolve()
    active = bool(current_project and _path_key(current_project.paths.root) == _path_key(root))
    manifest_path = root / "survey_sync_project.json"
    item = {
        "path": str(root),
        "name": root.name,
        "exists": root.is_dir(),
        "valid": False,
        "active": active,
        "project_id": "",
        "modified_utc": "",
        "crs": "",
        "horizontal_units": "",
    }
    if not manifest_path.is_file():
        return item
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if raw.get("product") != "SurveySync" or int(raw.get("format_version", 0)) != 1:
            return item
        item.update({
            "name": str(raw.get("name") or root.name),
            "valid": True,
            "project_id": str(raw.get("project_id") or ""),
            "modified_utc": str(raw.get("modified_utc") or ""),
            "crs": str(raw.get("crs") or ""),
            "horizontal_units": str(raw.get("horizontal_units") or ""),
        })
    except Exception:
        core_logger.debug("Could not enrich recent-project metadata for %s.", root, exc_info=True)
    return item


def _clear_current_for_delete(root: Path) -> bool:
    """Detach the embedded FieldBookSync runtime before deleting the active project."""
    global current_project
    if not current_project or _path_key(current_project.paths.root) != _path_key(root):
        return False
    field_app = _fieldbook_app_module()
    neutral = config_store.root / "runtime" / "NoProject" / "FieldBookSync"
    field_app.rebind_project_storage(neutral)
    current_project = None
    return True


def _remove_project_tree(root: Path) -> None:
    # Imported source evidence is intentionally made read-only. Windows refuses to
    # delete those files unless the writable bit is restored during rmtree.
    import stat
    def onerror(func, path, exc_info):
        try:
            os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR)
            func(path)
        except Exception:
            raise exc_info[1]
    shutil.rmtree(root, onerror=onerror)


def require_project() -> SurveyProject:
    if current_project is None:
        raise HTTPException(409, "No SurveySync project is open.")
    return current_project








@router.get("/", response_class=HTMLResponse)
def shell():
    return HTMLResponse((STATIC/"index.html").read_text(encoding="utf-8"), headers={"Cache-Control":"no-store"})

@router.get("/api/v9/release-notes")
def release_notes():
    return {"version": __version__, "notes": list(SURVEYSYNC_RELEASE_NOTES)}


@router.get("/surveysync-static/{name}")
def static_asset(name: str):
    if "/" in name or "\\" in name or ".." in name: raise HTTPException(404)
    path=STATIC/name
    if not path.is_file(): raise HTTPException(404)
    return FileResponse(path)

@router.get("/api/v9/status")
def status():
    cfg=config_store.load(); brand=config_store.get_brand(cfg.branding_profile)
    recovery=None
    if current_project:
        try: recovery=autosave_tick(current_project)
        except Exception as exc: recovery={"created":False,"reason":"error","message":str(exc)}
    return {"product":"SurveySync","version":__version__,"environment":cfg.environment,"release_channel":cfg.release_channel,"branding":brand,"project": current_project.summary() if current_project else None,
            "modules":["FieldBookSync","UtilitySync","ControlSync","TopoSync","COGOSync","BoundarySync","GISSync","ReportSync","QASync","CrewSync"],
            "recovery":recovery,
            "control_formula_note":"Ron 3-point control averaging and Ron 3-wire level reduction profiles are validated against the supplied authoritative workbooks; generic arithmetic/weighted alternatives remain available."}

@router.post("/api/v9/project/create")
def project_create(payload: CreateProjectIn):
    cfg=config_store.load()
    try: p=SurveyProject.create(Path(payload.parent_folder),payload.name,crs=payload.crs,horizontal_units=payload.horizontal_units,vertical_units=payload.vertical_units,environment=cfg.environment,branding_profile=cfg.branding_profile,template_id=payload.template_id,client=payload.client,project_number=payload.project_number)
    except Exception as exc: raise HTTPException(400,str(exc))
    _set_current(p)
    return p.summary()

@router.post("/api/v9/project/open")
def project_open(payload: OpenProjectIn):
    try: p=SurveyProject(Path(payload.path)); _set_current(p); return p.summary()
    except Exception as exc: raise HTTPException(400,str(exc))

@router.get("/api/v9/projects/recent")
def project_recent():
    cfg = config_store.load()
    paths = list(cfg.recent_projects)
    if current_project:
        active_path = str(current_project.paths.root)
        if not any(_path_key(x) == _path_key(active_path) for x in paths):
            paths.insert(0, active_path)
    items = [_project_list_item(x) for x in paths]
    return {"projects": items, "active_path": str(current_project.paths.root) if current_project else ""}

@router.post("/api/v9/project/forget")
def project_forget(payload: ProjectForgetIn):
    path = Path(payload.path).expanduser().resolve()
    if current_project and _path_key(current_project.paths.root) == _path_key(path):
        raise HTTPException(409, "The active project cannot be removed from the project list. Switch projects first, or delete the project.")
    _forget_project(path)
    return {"ok": True, "path": str(path), "deleted": False}

@router.post("/api/v9/project/delete")
def project_delete(payload: ProjectDeleteIn):
    global current_project
    root = Path(payload.path).expanduser().resolve()
    manifest_path = root / "survey_sync_project.json"
    if not manifest_path.is_file():
        raise HTTPException(400, "The selected folder is not a valid SurveySync project.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise HTTPException(400, f"Could not read the SurveySync project manifest: {exc}")
    if manifest.get("product") != "SurveySync" or int(manifest.get("format_version", 0)) != 1:
        raise HTTPException(400, "The selected folder is not a supported SurveySync project.")
    project_name = str(manifest.get("name") or root.name)
    if str(payload.confirm_name or "").strip() != project_name:
        raise HTTPException(400, f'Type the project name exactly to delete it: {project_name}')
    was_active = False
    try:
        with project_lock:
            was_active = _clear_current_for_delete(root)
            _remove_project_tree(root)
            _forget_project(root)
            # Keep a lightweight workstation audit entry without retaining survey data.
            log = config_store.root / "deleted_projects.jsonl"
            with log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts_utc": utc_now(), "project_id": str(manifest.get("project_id") or ""), "name": project_name, "path": str(root)}, ensure_ascii=False) + "\n")
    except HTTPException:
        raise
    except Exception as exc:
        # If deletion failed after detaching the active runtime, restore the project
        # when enough of it remains to be opened safely.
        if was_active and manifest_path.is_file():
            try:
                _set_current(SurveyProject(root))
            except Exception:
                core_logger.warning("Project deletion failed and the previous active project could not be reopened: %s", root, exc_info=True)
        raise HTTPException(400, f"Could not delete project: {exc}")
    return {"ok": True, "deleted": True, "name": project_name, "path": str(root), "was_active": was_active}

@router.get("/api/v9/project")
def project_summary(): return require_project().summary()

@router.get("/api/v9/project-templates")
def project_templates(): return {"templates": list_project_templates()}

@router.get("/api/v9/data-manager/overview")
def project_data_overview():
    try: return data_overview(require_project())
    except Exception as exc: raise HTTPException(400, str(exc))

@router.get("/api/v9/data-manager/rows")
def project_data_rows(dataset: str, search: str="", limit: int=200, offset: int=0):
    try: return data_rows(require_project(), dataset, search=search, limit=limit, offset=offset)
    except Exception as exc: raise HTTPException(400, str(exc))

@router.post("/api/v9/data-manager/edit")
def project_data_edit(payload: DataEditIn):
    try: return update_data_record(require_project(), payload.dataset, payload.record_id, payload.changes, payload.reason)
    except Exception as exc: raise HTTPException(400, str(exc))

@router.get("/api/v9/database/health")
def project_database_health():
    try: return database_health(require_project())
    except Exception as exc: raise HTTPException(400, str(exc))

@router.post("/api/v9/database/maintenance")
def project_database_maintenance():
    try: return maintain_database(require_project())
    except Exception as exc: raise HTTPException(400, str(exc))

@router.post("/api/v9/project/crs-units")
def project_crs(payload: CrsUnitsIn):
    p=require_project(); p.set_crs_units(payload.crs,payload.horizontal_units,payload.vertical_units); return p.summary()

@router.get("/api/v9/dialog/select-folder")
def select_folder(title: str="Choose SurveySync Project Location", initial_directory: str=""):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
        path=filedialog.askdirectory(title=title, initialdir=initial_directory or None, mustexist=True); root.destroy()
        return {"path":path or ""}
    except Exception as exc:
        return {"path":"","available":False,"message":f"Native folder picker unavailable: {exc}"}

@router.get("/api/v9/dialog/select-file")
def select_file(title: str="Choose Survey File", initial_directory: str=""):
    """Local browser-fallback file picker.

    The installed desktop shell normally uses pywebview's native picker. This
    fallback keeps ReportSync/Trimble file selection usable when SurveySync is
    launched through the local browser fallback on Windows.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
        path=filedialog.askopenfilename(title=title, initialdir=initial_directory or None)
        root.destroy()
        return {"path":path or ""}
    except Exception as exc:
        return {"path":"","available":False,"message":f"Native file picker unavailable: {exc}"}

@router.get("/api/v9/dialog/select-files")
def select_files(title: str="Choose Survey Files", initial_directory: str=""):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
        paths=filedialog.askopenfilenames(title=title, initialdir=initial_directory or None)
        root.destroy()
        return {"paths":[str(x) for x in paths]}
    except Exception as exc:
        return {"paths":[],"available":False,"message":f"Native multi-file picker unavailable: {exc}"}


@router.post("/api/v9/source/import")
def source_import(payload: SourceImportIn):
    p=require_project()
    try: return p.import_source(Path(payload.file_path),payload.module,payload.notes)
    except Exception as exc: raise HTTPException(400,str(exc))

@router.get("/api/v9/sources")
def sources(): return require_project().sources()

@router.post("/api/v9/fieldbook/migrate")
def migrate_fieldbook(file_path: str):
    p=require_project(); bundle=Path(file_path).expanduser().resolve()
    if not bundle.is_file(): raise HTTPException(400,"Legacy .fbs project file was not found.")
    try:
        source=p.import_source(bundle,"FieldBookSync","Original v8 project bundle retained immutably during v9 migration.")
        field_app=_fieldbook_app_module()
        from fieldbook_sync.project_files import load_project_bundle
        state, profile=load_project_bundle(bundle, field_app.runtime.storage.page_dir, field_app.runtime.storage.examples_dir)
        field_app.runtime.storage.state=state
        field_app.runtime.storage.save()
        if profile is not None:
            from fieldbook_sync.profiles import save_profile
            save_profile(field_app.runtime.storage.profile_dir, profile)
        p.manifest["fieldbook_migration"]={"status":"MIGRATED","source":source["source_id"],"legacy_project_name":state.project_name,"migrated_utc":utc_now()}
        p.save_manifest(action="FIELDBOOK_V8_MIGRATED",details={"source_id":source["source_id"],"legacy_project_name":state.project_name})
        return {"ok":True,"legacy_project_name":state.project_name,"fieldbook_url":"/fieldbook","source_id":source["source_id"]}
    except Exception as exc: raise HTTPException(400,str(exc))

@router.get("/api/v9/audit")
def audit(limit: int=100): return require_project().db.recent_audit(limit)



























@router.post("/api/v9/crs/inspect")
def crs_inspect(payload: CrsInspectIn):
    return inspect_crs(payload.crs)

@router.post("/api/v9/crs/transform")
def crs_transform(payload: CrsTransformIn):
    p=require_project()
    try: result=transform_xy(payload.x,payload.y,payload.source_crs,payload.target_crs)
    except Exception as exc: raise HTTPException(400,str(exc))
    p.db.audit("Core","CRS_TRANSFORM",details={**payload.model_dump(),"result":result})
    return result

@router.post("/api/v9/cogo/inverse")
def cogo_inverse(payload: CogoInverseIn):
    p=require_project(); result=inverse(payload.n1,payload.e1,payload.n2,payload.e2); p.db.audit("COGOSync","INVERSE",details=payload.model_dump()|{"result":result}); return result

@router.post("/api/v9/cogo/bearing-distance")
def cogo_bd(payload: CogoBDIn):
    p=require_project(); result=bearing_distance(payload.northing,payload.easting,payload.azimuth_deg,payload.distance); p.db.audit("COGOSync","BEARING_DISTANCE",details=payload.model_dump()|{"result":result}); return result

@router.post("/api/v9/cogo/intersection")
def cogo_intersection(payload: CogoIntersectIn):
    p=require_project();
    try: result=line_intersection(payload.n1,payload.e1,payload.az1,payload.n2,payload.e2,payload.az2)
    except ValueError as exc: raise HTTPException(400,str(exc))
    p.db.audit("COGOSync","LINE_INTERSECTION",details=payload.model_dump()|{"result":result}); return result

def _project_numeric_point_ids(project: SurveyProject) -> tuple[list[int], int]:
    ids: list[int] = []
    ignored = 0
    with project.db.connect() as conn:
        rows = conn.execute("SELECT point_id FROM canonical_points ORDER BY point_id").fetchall()
    for row in rows:
        raw = str(row[0] or "").strip()
        if not raw:
            continue
        if raw.isdigit():
            ids.append(int(raw))
        else:
            ignored += 1
    return sorted(set(ids)), ignored


@router.post("/api/v9/reports/point-ranges")
def point_ranges(payload: RangeIn):
    p=require_project()
    mode=str(payload.source_mode or "project").strip().lower()
    try:
        if mode == "project":
            ids, ignored = _project_numeric_point_ids(p)
            source_label = "Current SurveySync project points"
        elif mode == "file":
            if not str(payload.file_path or "").strip():
                raise ValueError("Choose a point file or switch Point Range source to Current Project Points.")
            point_path=Path(payload.file_path).expanduser().resolve()
            if not point_path.exists():
                raise FileNotFoundError(f"Point file was not found: {point_path}")
            if point_path.suffix.lower() in {".job", ".jxl", ".xml"}:
                prepared_path,_conversion=prepare_jobxml(point_path,p.paths.cache/"trimble_point_range")
                trimble_points=parse_jobxml_points(prepared_path)
                raw_ids=[str(row.get("point_id") or "").strip() for row in trimble_points.get("points",[])]
                ids=[int(v) for v in raw_ids if v.isdigit()]
                ignored=sum(1 for v in raw_ids if v and not v.isdigit())
            else:
                ids=parse_point_ids_file(point_path)
                ignored=0
            source_label=str(point_path)
        else:
            raise ValueError("Point-range source_mode must be project or file.")
        if not ids:
            raise ValueError("No numeric PointIDs were found in the selected source.")
        if payload.start is not None or payload.end is not None:
            ranges=available_ranges(ids,payload.start,payload.end,payload.min_run)
        else:
            ranges=available_ranges(ids,include_open_ended=True)
        summary=crew_range_recommendations(ids,min_capacity=payload.min_capacity,sort_order=payload.sort_order)
    except Exception as exc:
        raise HTTPException(400,str(exc))

    stamp=utc_now().replace(':','-')
    base=p.paths.reports/f"Point_Ranges_{stamp}"
    csv_path=base.with_suffix('.csv')
    txt_path=base.with_suffix('.txt')
    xlsx_path=base.with_suffix('.xlsx')
    csv_path.write_text(crew_ranges_csv(summary),encoding="utf-8-sig")
    txt_path.write_text(crew_ranges_txt(summary),encoding="utf-8")
    try:
        write_crew_ranges_xlsx(summary,xlsx_path)
    except Exception as exc:
        raise HTTPException(500,f"Point ranges were calculated, but the Excel report could not be created: {exc}")
    report_paths={"csv":str(csv_path),"txt":str(txt_path),"xlsx":str(xlsx_path)}
    p.db.audit("ReportSync","POINT_RANGE_REPORT",object_type="report",object_id=csv_path.name,details={
        "source_mode":mode,"source":source_label,"used_count":len(ids),"ignored_non_numeric":ignored,
        "recommended_count":summary["recommended_count"],"minimum_capacity":summary["minimum_capacity"],
        "smaller_gap_count":summary["smaller_gap_count"],"report_paths":report_paths,
    })
    return {**summary,"ranges":ranges,"ignored_point_ids":ignored,"source_mode":mode,"source_label":source_label,
            "report_path":str(csv_path),"report_paths":report_paths}

@router.post("/api/v9/control/import")
def control_import(payload: ControlImportIn):
    p=require_project(); path=Path(payload.file_path).expanduser().resolve()
    try:
        src=p.import_source(path,"ControlSync","Raw control observations")
        with p.db.connect() as conn:
            prior_count=int(conn.execute("SELECT COUNT(*) FROM control_observations WHERE source_id=?",(src["source_id"],)).fetchone()[0])
        if prior_count:
            return {"count":0,"already_imported":True,"existing_observation_count":prior_count,"source_id":src["source_id"],"controls":list_control_ids(p.db)}
        immutable_source=Path(src["stored_path"])
        if not immutable_source.is_absolute():
            immutable_source=(p.paths.root/immutable_source).resolve()
        parsed=parse_control_source(immutable_source,p.paths.derived/"ControlSync"/"Trimble"/src["source_id"])
        rows=parsed["observations"]; overlap=detect_control_import_overlap(p.db,rows); count=import_observations(p.db,rows,src["source_id"]); diagnostic=save_control_import_diagnostic(p.db,src["source_id"],parsed)
        details={"count":count,"format":parsed.get("format"),"conversion":parsed.get("conversion",{}),"field_metadata_counts":parsed.get("field_metadata_counts",{}),"diagnostic":diagnostic,"overlap":overlap}
        p.db.audit("ControlSync","CONTROL_OBSERVATIONS_IMPORTED",object_type="source",object_id=src["source_id"],details=details)
        return {"count":count,"already_imported":False,"source_id":src["source_id"],"controls":list_control_ids(p.db),"format":parsed.get("format"),"trimble_metadata":parsed.get("metadata",{}),"conversion":parsed.get("conversion",{}),"jobxml_path":parsed.get("jobxml_path",""),"field_metadata_counts":parsed.get("field_metadata_counts",{}),"diagnostic":diagnostic,"overlap":overlap}
    except Exception as exc: raise HTTPException(400,str(exc))
@router.get("/api/v9/control")
def controls(): return list_control_ids(require_project().db)

@router.get("/api/v9/control/observations")
def control_observation_database(control_id: str="", limit: int=2000):
    p=require_project()
    return {"observations":list_control_observations(p.db,control_id or None,limit),"controls":list_control_ids(p.db)}

def _write_control_database_summary(p: SurveyProject, result: dict) -> str:
    report=p.paths.reports/f"Control_Database_Analysis_{utc_now().replace(':','-')}.csv"
    with report.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f)
        w.writerow(["control_id","status","observations","northing","easting","elevation","max_horizontal_residual","max_vertical_residual","revision","error"])
        for row in result.get("results",[]):
            w.writerow([row.get("control_id",""),row.get("status",""),row.get("observation_count",row.get("included_count","")),row.get("northing",""),row.get("easting",""),row.get("elevation",""),row.get("max_horizontal_residual",""),row.get("max_vertical_residual",""),row.get("revision",""),row.get("error","")])
    return str(report)

@router.post("/api/v9/control/analyze-all")
def control_analyze_all(payload: ControlAnalyzeAllIn):
    p=require_project()
    try:
        result=analyze_all_controls(p.db,payload.method,payload.horizontal_tolerance,payload.vertical_tolerance,payload.min_observations)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    result["report_path"]=_write_control_database_summary(p,result)
    p.db.audit("ControlSync","CONTROL_DATABASE_ANALYZED",object_type="control_database",object_id="all",details={k:result[k] for k in ("method","control_count","solved_count","pass_count","review_count","skipped_count","report_path")})
    return result

@router.post("/api/v9/control/import-analyze")
def control_import_and_analyze(payload: ControlImportAnalyzeIn):
    p=require_project(); path=Path(payload.file_path).expanduser().resolve()
    try:
        src=p.import_source(path,"ControlSync","Bulk control survey shots")
        with p.db.connect() as conn:
            prior_count=int(conn.execute("SELECT COUNT(*) FROM control_observations WHERE source_id=?",(src["source_id"],)).fetchone()[0])
        if prior_count:
            count=0; control_count=0; already_imported=True
        else:
            immutable_source=Path(src["stored_path"])
            if not immutable_source.is_absolute():
                immutable_source=(p.paths.root/immutable_source).resolve()
            parsed=parse_control_source(immutable_source,p.paths.derived/"ControlSync"/"Trimble"/src["source_id"])
            rows=parsed["observations"]; count=import_observations(p.db,rows,src["source_id"]); control_count=len({r['control_id'] for r in rows}); already_imported=False
            p.db.audit("ControlSync","CONTROL_DATABASE_IMPORTED",object_type="source",object_id=src["source_id"],details={"count":count,"control_count":control_count,"format":parsed.get("format"),"conversion":parsed.get("conversion",{}),"field_metadata_counts":parsed.get("field_metadata_counts",{})})
        result=analyze_all_controls(p.db,payload.method,payload.horizontal_tolerance,payload.vertical_tolerance,payload.min_observations)
        result.update({"imported_count":count,"already_imported":already_imported,"existing_observation_count":prior_count,"source_id":src["source_id"],"report_path":_write_control_database_summary(p,result)})
        p.db.audit("ControlSync","CONTROL_DATABASE_IMPORTED_AND_ANALYZED",object_type="source",object_id=src["source_id"],details={"imported_count":count,"control_count":result.get("control_count"),"solved_count":result.get("solved_count"),"report_path":result.get("report_path")})
        return result
    except Exception as exc:
        raise HTTPException(400,str(exc))

@router.post("/api/v9/control/ron-three-point")
def control_ron_three_point(payload: RonControlFromPointsIn):
    p=require_project()
    final_id=str(payload.control_id or "").strip()
    point_ids=[str(x or "").strip() for x in (payload.point_ids or []) if str(x or "").strip()]
    if not final_id:
        raise HTTPException(400,"Final control ID is required.")
    if len(point_ids)!=3 or len(set(point_ids))!=3:
        raise HTTPException(400,"Ron 3-point control profile requires exactly three distinct source survey PointIDs.")
    observations=[]
    with p.db.connect() as conn:
        for source_pid in point_ids:
            rows=conn.execute("SELECT * FROM canonical_points WHERE point_id=? ORDER BY modified_utc DESC, created_utc DESC",(source_pid,)).fetchall()
            if not rows:
                raise HTTPException(400,f"Survey PointID {source_pid} was not found in the current project.")
            if len(rows)>1:
                # Duplicate PointIDs are unsafe for an averaging workflow because the spreadsheet VLOOKUP
                # assumes one authoritative source row. Require review rather than silently choosing one.
                raise HTTPException(400,f"Survey PointID {source_pid} is duplicated in the project; resolve the duplicate before control averaging.")
            r=dict(rows[0])
            if r.get("elevation") is None:
                raise HTTPException(400,f"Survey PointID {source_pid} has no elevation; the Ron workbook profile requires N/E/Z for all three shots.")
            observations.append({
                "control_id":final_id,"northing":r["northing"],"easting":r["easting"],"elevation":r["elevation"],
                "h_sigma":None,"v_sigma":None,"method":"RON_3_POINT_WORKBOOK","source_id":r.get("source_id"),
                "notes":f"Source survey PointID {source_pid}",
            })
    # Each press intentionally creates a new auditable observation set and immutable solution revision.
    # Prior Ron-profile shots remain in history but are excluded so the active solution always mirrors
    # the workbook's exactly-three-shot assumption.
    with p.db.connect() as conn:
        conn.execute("UPDATE control_observations SET include=0 WHERE control_id=? AND method='RON_3_POINT_WORKBOOK' AND include=1",(final_id,))
    import_observations(p.db,observations)
    result=solve_control(p.db,final_id,"ron_spreadsheet",payload.horizontal_tolerance,payload.vertical_tolerance)
    result["source_point_ids"]=point_ids
    deliverables=write_ron_control_deliverables(result,point_ids,p.paths.reports)
    result["deliverables"]=deliverables
    p.db.audit("ControlSync","RON_3_POINT_FROM_PROJECT_POINTS",object_type="control",object_id=final_id,details={"source_point_ids":point_ids,"solution_id":result.get("solution_id"),"revision":result.get("revision"),"pass":result.get("pass"),"deliverables":deliverables})
    return result

@router.post("/api/v9/control/solve")
def control_solve(payload: ControlSolveIn):
    p=require_project()
    try: result=solve_control(p.db,payload.control_id,payload.method,payload.horizontal_tolerance,payload.vertical_tolerance)
    except ValueError as exc: raise HTTPException(400,str(exc))
    report=p.paths.reports/f"Control_QC_{safe_name(payload.control_id)}_{utc_now().replace(':','-')}.csv"
    with report.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f); w.writerow(["control_id","method","count","northing","easting","elevation","pass","h_tolerance","v_tolerance"]); w.writerow([result['control_id'],result['method'],result['count'],result['northing'],result['easting'],result['elevation'],result['pass'],result['horizontal_tolerance'],result['vertical_tolerance']]); w.writerow([]); w.writerow(["observation_id","dn","de","horizontal","dz","pass"]); [w.writerow([r['observation_id'],r['dn'],r['de'],r['horizontal'],r['dz'],r['pass']]) for r in result['residuals']]
    result['report_path']=str(report)
    p.db.audit("ControlSync","CONTROL_AVERAGE_QC",object_type="control",object_id=payload.control_id,details={"method":payload.method,"pass":result["pass"],"count":result["count"],"report":str(report)})
    return result

@router.post("/api/v9/points/import")
def points_import(payload: PointImportIn):
    p=require_project(); path=Path(payload.file_path).expanduser().resolve()
    if not path.is_file(): raise HTTPException(400,"Point file was not found.")
    source_id=payload.source_id
    if not source_id:
        try: source_id=p.import_source(path,"Core","Canonical point import")["source_id"]
        except Exception as exc: raise HTTPException(400,str(exc))
    text=path.read_text(encoding="utf-8-sig",errors="replace")
    try: dialect=csv.Sniffer().sniff(text[:4096],delimiters=",\t;")
    except Exception: dialect=csv.excel
    reader=csv.DictReader(text.splitlines(),dialect=dialect)
    fields={str(f).strip().lower().replace(' ','_'):f for f in (reader.fieldnames or [])}
    def pick(*names):
        for n in names:
            if n in fields:return fields[n]
        return None
    fp=pick('point_id','point','pt','name'); fn=pick('northing','north','n','y'); fe=pick('easting','east','e','x'); fz=pick('elevation','elev','z'); fd=pick('description','desc','code')
    if not fp or not fn or not fe: raise HTTPException(400,"Point file requires Point ID, Northing and Easting columns.")
    now=utc_now(); count=0
    with p.db.connect() as conn:
        for row in reader:
            pid=str(row.get(fp,'')).strip()
            if not pid: continue
            try: n=float(row[fn]); e=float(row[fe]); z=float(row[fz]) if fz and str(row.get(fz,'')).strip() else None
            except Exception: continue
            conn.execute("INSERT INTO canonical_points(point_uuid,point_id,northing,easting,elevation,description,point_class,source_id,derived_from_json,crs,horizontal_units,vertical_units,review_state,revision,created_utc,modified_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uuid4().hex,pid,n,e,z,str(row.get(fd,'') if fd else ''),payload.point_class,source_id,'[]',p.manifest.get('crs',''),p.manifest.get('horizontal_units',''),p.manifest.get('vertical_units',''),'UNREVIEWED',1,now,now)); count+=1
    p.db.audit("Core","CANONICAL_POINTS_IMPORTED",object_type="source",object_id=source_id,details={"count":count})
    return {"count":count,"source_id":source_id}

@router.get("/api/v9/control/solutions")
def control_solution_history(control_id: str=""):
    p=require_project()
    return {"solutions": list_control_solutions(p.db, control_id or None)}

@router.post("/api/v9/control/activate")
def control_activate_revision(payload: ControlRevisionSelectIn):
    p=require_project()
    try:
        return set_active_solution(p.db,"control",payload.control_id,payload.solution_id,note=payload.note,audit_action="CONTROL_SOLUTION_RESTORED")
    except ValueError as exc:
        raise HTTPException(400,str(exc))

@router.get("/api/v9/control/compare")
def control_compare_revisions(control_id: str, solution_a: str, solution_b: str):
    p=require_project()
    try:
        return compare_control_solutions(p.db,control_id,solution_a,solution_b)
    except ValueError as exc:
        raise HTTPException(400,str(exc))











































@router.get("/api/v9/config")
def config():
    c=config_store.load(); return {**c.__dict__,"environments":ENVIRONMENTS,"release_channels":RELEASE_CHANNELS,"brands":config_store.list_brands()}


@router.get("/api/v9/config/ui")
def ui_config_get():
    c=config_store.load()
    return {"appearance":c.ui_appearance,"theme":c.ui_theme,"accent":c.ui_accent}

@router.post("/api/v9/config/ui")
def ui_config_save(payload: UiConfigIn):
    c=config_store.load()
    if payload.appearance is not None:
        value=str(payload.appearance).strip().lower()
        if value not in {"system","light","dark"}: raise HTTPException(400,"Appearance must be system, light, or dark.")
        c.ui_appearance=value
    if payload.theme is not None:
        value=str(payload.theme).strip().lower()
        allowed={"classic","edsi","slate","midnight","lightpro","contrast","carbon","obsidian","teal","violet","graphite","frost","arctic","sandstone","edsidark","edsilight"}
        if value not in allowed: raise HTTPException(400,"Unknown SurveySync theme.")
        c.ui_theme=value
    if payload.accent is not None:
        value=str(payload.accent).strip().lower()
        if value not in {"default","azure","teal","emerald","violet","amber","rose"}: raise HTTPException(400,"Unknown SurveySync accent.")
        c.ui_accent=value
    config_store.save(c)
    return {"appearance":c.ui_appearance,"theme":c.ui_theme,"accent":c.ui_accent}

@router.get("/api/v9/ai/status")
def ai_status(refresh: bool=False):
    base = get_local_ai_status(force=bool(refresh))
    try:
        field_app = _fieldbook_app_module()
        detailed = field_app._automatic_ai_status(force=bool(refresh))
    except Exception:
        detailed = base
    cfg = config_store.load()
    return {**detailed, "configured_provider": cfg.ai_provider}

@router.post("/api/v9/ai/windows/enable")
def ai_windows_enable(feature: str="ocr"):
    feature = str(feature or "ocr").strip().lower()
    if feature not in {"ocr", "language"}: raise HTTPException(400,"Windows AI feature must be ocr or language.")
    try: result=ensure_windows_feature(feature)
    except Exception as exc: raise HTTPException(503,str(exc))
    return {"ok":True,**result,"status":ai_status(refresh=True)}

@router.post("/api/v9/ai/foundry/enable")
def ai_foundry_enable():
    try: result=enable_foundry_model(DEFAULT_FOUNDRY_VISION_MODEL)
    except Exception as exc: raise HTTPException(503,str(exc))
    return {"ok":True,**result,"status":ai_status(refresh=True)}

@router.post("/api/v9/config/ai")
def ai_config(payload: AiConfigIn):
    provider=str(payload.ai_provider or "auto").strip().lower()
    if provider not in {"auto","hybrid","gemini","openai","anthropic","manual"}: raise HTTPException(400,"AI provider must be auto, hybrid, gemini, openai, anthropic, or manual.")
    cfg=config_store.load();cfg.ai_provider=provider;config_store.save(cfg)
    try:
        field_app=_fieldbook_app_module();field_app.runtime.provider=provider
        saved=field_app.runtime.storage.load_settings();saved["provider"]=provider;saved["provider_user_set"]=True;saved["auto_ai_default_migrated_v901"]=True;field_app.runtime.storage.save_settings(saved)
    except Exception:
        core_logger.warning("AI provider preference changed in SurveySync but could not be persisted to FieldBookSync.", exc_info=True)
    return {"ai_provider":provider}

@router.post("/api/v9/config/environment")
def environment(payload: EnvIn):
    env=payload.environment.lower()
    if env not in ENVIRONMENTS: raise HTTPException(400,"Environment must be developer, beta, or production.")
    c=config_store.load(); c.environment=env
    c.release_channel=payload.release_channel or {"developer":"developer","beta":"beta","production":"stable"}[env]
    if c.release_channel not in RELEASE_CHANNELS: raise HTTPException(400,"Invalid release channel.")
    config_store.save(c)
    if current_project: current_project.db.audit("Core","ENVIRONMENT_CHANGED",details={"environment":env,"release_channel":c.release_channel})
    return c.__dict__

@router.post("/api/v9/config/branding")
def branding(payload: BrandSelectIn):
    if payload.branding_profile not in {b['id'] for b in config_store.list_brands()}: raise HTTPException(400,"Brand profile does not exist.")
    c=config_store.load(); c.branding_profile=payload.branding_profile; config_store.save(c)
    if current_project: current_project.db.audit("Core","BRANDING_CHANGED",details={"branding_profile":payload.branding_profile})
    return config_store.get_brand(payload.branding_profile)

@router.post("/api/v9/config/branding/profile")
def branding_profile(payload: BrandProfileIn):
    try:return config_store.save_brand(payload.model_dump())
    except ValueError as exc: raise HTTPException(400,str(exc))


@router.post("/api/v9/feedback/config")
def feedback_config(payload: FeedbackConfigIn):
    c=config_store.load(); url=payload.feedback_endpoint.strip()
    if url and not url.lower().startswith("https://"):
        raise HTTPException(400,"Feedback endpoint must use HTTPS.")
    c.feedback_endpoint=url; c.resource_environment=c.environment; config_store.save(c)
    return {"feedback_endpoint":url,"environment":c.environment}

@router.post("/api/v9/update/config")
def update_config(payload: UpdateConfigIn):
    c=config_store.load()
    url=payload.update_manifest_url.strip() or DEFAULT_UPDATE_MANIFEST_URL
    if not url.lower().startswith("https://"):
        raise HTTPException(400,"Update manifest URL must use HTTPS.")
    c.update_manifest_url=url; c.resource_environment=c.environment; config_store.save(c)
    return {"update_manifest_url":url,"release_channel":c.release_channel}

@router.get("/api/v9/update/check")
def update_check_api():
    try:return update_check(config_store)
    except Exception as exc:raise HTTPException(400,str(exc))

@router.post("/api/v9/update/stage")
def update_stage_api():
    try:return update_stage(config_store)
    except Exception as exc:
        record_diagnostic_error(
            config_store.root,
            component="updater",
            code="UPD-STAGE-001",
            message=str(exc),
            recoverable=True,
            context={"route": "/api/v9/update/stage"},
        )
        raise HTTPException(400,str(exc))


@router.post("/api/v9/update/check-and-install")
def update_check_and_install_api(payload: UpdateInstallIn=UpdateInstallIn()):
    """One-button SurveySync update flow used by every module.

    The route checks the active SurveySync release channel, downloads and verifies
    a newer installer when available, writes the single native-launcher handoff in
    ``%LOCALAPPDATA%/SurveySync``, then requests a graceful application shutdown only
    after the caller confirms that Setup should install now.
    """
    try:
        field_app = _fieldbook_app_module()
        if field_app.runtime.job.running:
            raise ValueError("Finish or cancel the active FieldBookSync analysis before installing an update.")
        status = update_check(config_store)
        if not status.get("update_available"):
            return {
                "ok": True,
                "action": "up_to_date",
                "message": f"SurveySync v{__version__} is up to date.",
                **status,
            }
        if not payload.confirm_install:
            return {
                "ok": True,
                "action": "confirmation_required",
                "message": f"SurveySync v{status.get('version')} is available. Confirm install when you are ready for SurveySync to close and Setup to open.",
                **status,
            }
        staged = update_stage(config_store)
    except Exception as exc:
        record_diagnostic_error(
            config_store.root,
            component="updater",
            code="UPD-INSTALL-001",
            message=str(exc),
            recoverable=True,
            context={"route": "/api/v9/update/check-and-install"},
        )
        raise HTTPException(400, str(exc))

    def _shutdown_for_update() -> None:
        time.sleep(0.35)
        try:
            _fieldbook_app_module().request_application_shutdown(
                f"Updating SurveySync to v{staged.get('version', '')}."
            )
        except Exception:
            core_logger.warning("Could not request FieldBookSync shutdown for staged update; installer shutdown handling will continue.", exc_info=True)

    threading.Thread(target=_shutdown_for_update, name="SurveySync-update-exit", daemon=True).start()
    return {
        "ok": True,
        "action": "installing",
        "message": f"SurveySync v{staged['version']} was downloaded and verified. SurveySync is closing so Setup can install the update.",
        **staged,
    }


@router.get("/api/v9/diagnostics/errors")
def diagnostics_errors(limit: int=100):
    errors = list_diagnostic_errors(config_store.root, limit=limit)
    return {
        "ok": True,
        "count": len(errors),
        "errors": errors,
        "local_log": str(error_log_path(config_store.root)),
    }


@router.get("/api/v9/diagnostics/error-log")
def diagnostics_error_log():
    path = error_log_path(config_store.root)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return FileResponse(path, media_type="application/x-ndjson", filename="SurveySync_Error_Log.jsonl", headers={"Cache-Control":"no-store"})


@router.post("/api/v9/diagnostics/export")
def diagnostics_export():
    c = config_store.load()
    project_summary = {}
    if current_project:
        project_summary = {
            "name": current_project.manifest.get("name", ""),
            "project_id": current_project.manifest.get("project_id", ""),
            "crs": current_project.manifest.get("crs", ""),
            "horizontal_units": current_project.manifest.get("horizontal_units", ""),
            "root": str(current_project.paths.root),
        }
    try:
        path = build_diagnostic_bundle(
            config_root=config_store.root,
            output_dir=config_store.root / "diagnostics",
            app_version=__version__,
            config=c.__dict__,
            project_summary=project_summary,
        )
    except Exception as exc:
        event = record_diagnostic_error(
            config_store.root,
            component="diagnostics",
            code="DGN-EXPORT-001",
            message=str(exc),
            recoverable=True,
            context={"route": "/api/v9/diagnostics/export"},
        )
        raise HTTPException(500, f"Could not build diagnostics bundle. Error reference {event['error_id']}.") from exc
    return FileResponse(path, media_type="application/zip", filename=path.name, headers={"Cache-Control":"no-store"})


@router.post("/api/v9/diagnostics/error-log/sync")
def diagnostics_error_log_sync(payload: ErrorLogSyncIn):
    c = config_store.load()
    endpoint = (payload.endpoint_url or c.feedback_endpoint or "").strip()
    errors = list_diagnostic_errors(config_store.root, limit=payload.limit)
    if not errors:
        return {"ok": True, "action": "nothing_to_sync", "message": "No SurveySync error-log entries are waiting locally.", "count": 0}
    try:
        result = submit_error_log(endpoint, errors, app_version=__version__)
    except Exception as exc:
        event = record_diagnostic_error(
            config_store.root,
            component="diagnostics",
            code="DGN-SYNC-001",
            message=str(exc),
            recoverable=True,
            context={"route": "/api/v9/diagnostics/error-log/sync", "count": len(errors)},
        )
        raise HTTPException(400, f"Error-log sync is pending locally: {exc} (reference {event['error_id']})") from exc
    return {"ok": True, "count": len(errors), **result}

@router.post("/api/v9/feedback")
def feedback(payload: FeedbackIn):
    """Project-independent, local-first feedback capture.

    The full SurveySync Feedback Wizard uses the richer /api/feedback/report route,
    but this endpoint remains safe for integrations and never requires an open project.
    """
    c=config_store.load(); fid=uuid4().hex
    project_id=current_project.manifest['project_id'] if current_project else ""
    metadata={"version":__version__,"environment":c.environment,"release_channel":c.release_channel,"branding_profile":c.branding_profile,"module":payload.module,"project_id":project_id}
    item={"feedback_id":fid,"ts_utc":utc_now(),"kind":payload.kind,"title":payload.title,"description":payload.description,**metadata,"survey_data_attached":False,"sync_status":"LOCAL_ONLY"}
    feedback_dir=config_store.root / "feedback"
    feedback_dir.mkdir(parents=True,exist_ok=True)
    log_path=feedback_dir / "feedback_log.jsonl"
    with log_path.open("a",encoding="utf-8") as fh:
        fh.write(json.dumps(item,ensure_ascii=False)+"\n")
    if current_project:
        p=current_project
        with p.db.connect() as conn:
            conn.execute("INSERT INTO feedback_items(feedback_id,ts_utc,kind,title,description,module,version,build,environment,release_channel,branding_profile,project_id,include_project_data,sync_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (fid,item['ts_utc'],payload.kind,payload.title,payload.description,payload.module,__version__,__version__,c.environment,c.release_channel,c.branding_profile,project_id,0,'LOCAL_ONLY'))
        p.db.audit("Core","FEEDBACK_CAPTURED",object_type="feedback",object_id=fid,details={"kind":payload.kind,"module":payload.module,"survey_data_attached":False,"sync_status":"LOCAL_ONLY"})
    return {"feedback_id":fid,"status":"LOCAL_ONLY","message":"Saved locally. Open the Feedback Wizard for shared Intake sync and attachments.","metadata":metadata,"survey_data_attached":False,"local_log":str(log_path)}

# Restore last project when safe, but never make import failure fatal.

from .operations_routes import router as operations_routes_router
from .operations_routes import (
    batch as batch,
    compare_points as compare_points,
    deliverable_package as deliverable_package,
    explain as explain,
    export_profile_run as export_profile_run,
    export_profile_save as export_profile_save,
    export_profiles as export_profiles,
    import_commit as import_commit,
    import_mapping_learn as import_mapping_learn,
    import_mappings as import_mappings,
    import_stage as import_stage,
    import_stages as import_stages,
    project_map as project_map,
    qa_issue_status as qa_issue_status,
    qa_issues as qa_issues,
    qa_rules_get as qa_rules_get,
    qa_rules_save as qa_rules_save,
    qa_run as qa_run,
    review_items as review_items,
    snapshot_compare as snapshot_compare,
    snapshot_create as snapshot_create,
    snapshot_restore as snapshot_restore,
    snapshots as snapshots,
    task_cancel as task_cancel,
    tasks as tasks,
    timeline as timeline,
)
router.include_router(operations_routes_router)


from .survey_routes import router as survey_routes_router
from .survey_routes import (
    _utility_state_structures as _utility_state_structures,
    attachment_add as attachment_add,
    attachments as attachments,
    attachments_auto_photos as attachments_auto_photos,
    cloud_history as cloud_history,
    cloud_import as cloud_import,
    cloud_trimble_projects as cloud_trimble_projects,
    deliverables as deliverables,
    field_to_finish as field_to_finish,
    geodesy_project_factor as geodesy_project_factor,
    geodesy_project_factors as geodesy_project_factors,
    geodesy_projection_samples as geodesy_projection_samples,
    level_activate_revision as level_activate_revision,
    level_compare_revisions as level_compare_revisions,
    level_extract_fieldbook as level_extract_fieldbook,
    level_history as level_history,
    level_import as level_import,
    level_runs as level_runs,
    level_solve as level_solve,
    notification_email as notification_email,
    notification_policy_get as notification_policy_get,
    notification_policy_save as notification_policy_save,
    notifications as notifications,
    report_control_pdf as report_control_pdf,
    report_fieldbook_pdf as report_fieldbook_pdf,
    report_survey_pdf as report_survey_pdf,
    spatial_import as spatial_import,
    spatial_layers as spatial_layers,
    traverse_import as traverse_import,
    traverse_runs as traverse_runs,
    traverse_solve as traverse_solve,
    trimble_job_import as trimble_job_import,
    trimble_status as trimble_status,
    utility_analyze as utility_analyze,
    utility_completion as utility_completion,
    utility_completion_kmz as utility_completion_kmz,
    utility_recalculate_inverts as utility_recalculate_inverts,
    utility_sync as utility_sync,
)
router.include_router(survey_routes_router)

def restore_last_project() -> None:
    c=config_store.load()
    if c.last_project:
        try:
            p=SurveyProject(Path(c.last_project)); _set_current(p)
        except Exception:
            core_logger.warning("Could not restore last SurveySync project %s; starting without an active project.", c.last_project, exc_info=True)
