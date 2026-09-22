from __future__ import annotations
import logging
from .api_models import (
    SettingsIn as SettingsIn,
    SelectProfileIn as SelectProfileIn,
    ProfileSaveIn as ProfileSaveIn,
    FieldNoteProfileSaveIn as FieldNoteProfileSaveIn,
    FieldNoteProfileSelectIn as FieldNoteProfileSelectIn,
    FieldBookProfileAssignmentIn as FieldBookProfileAssignmentIn,
    FieldNotePageOverrideIn as FieldNotePageOverrideIn,
    FieldNoteProfileDuplicateIn as FieldNoteProfileDuplicateIn,
    FieldNoteTrainingSaveIn as FieldNoteTrainingSaveIn,
    TeachCorrectionIn as TeachCorrectionIn,
    UpdateSourceIn as UpdateSourceIn,
    UpdateInstallIn as UpdateInstallIn,
    FeedbackOpenIn as FeedbackOpenIn,
    FeedbackRetryIn as FeedbackRetryIn,
    ResultEditIn as ResultEditIn,
    ProjectNameIn as ProjectNameIn,
    ProjectSaveAsIn as ProjectSaveAsIn,
    MapCrsIn as MapCrsIn,
    MapAlignmentIn as MapAlignmentIn,
    MapControlPairIn as MapControlPairIn,
    MapAlignmentSolveIn as MapAlignmentSolveIn,
    MapLayerSettingsIn as MapLayerSettingsIn,
    MapLayerOrderIn as MapLayerOrderIn,
    MapBookmarkIn as MapBookmarkIn,
    MapTransformIn as MapTransformIn,
    ManualEdgeIn as ManualEdgeIn,
    ValidationNameIn as ValidationNameIn,
    BatchAddIn as BatchAddIn,
    ArcGISMapsIn as ArcGISMapsIn,
    ArcGISExportIn as ArcGISExportIn,
    ImportJob as ImportJob,
)

import asyncio
import csv
import io
import math
import hashlib
import os
import shutil
import re
import json
import tempfile
import zipfile
from datetime import datetime
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import urllib.request
import urllib.error
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, List, Optional
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .aggregate import aggregate_results, apply_status_rule_to_existing
from .batch_pairing import pair_batch_files
from .ai_reader import (
    ProviderUsage,
    list_gemini_models,
    list_ollama_models,
    ollama_running_models,
    warm_ollama_model,
    read_page_openai,
    read_page_anthropic,
    read_pages_gemini,
    read_pages_ollama,
    read_pages_foundry,
)
from .exporter import create_export_zip, direct_export_text
from .arcgis_integration import export_to_arcgis, find_arcgis_products, list_project_maps
from .image_processing import crop_normalized_bbox, ensure_enhanced_pages, ensure_enhanced_pages_parallel
from .intelligence import infer_network, refresh_intelligence, refresh_result_intelligence
from .ocr_local import (
    PaddleCancelled, clear_ocr_cache, compare_ocr_to_evidence, locate_target_ids,
    ocr_cache_stats, paddle_bridge_path, paddle_status, run_paddle_page, run_paddle_pages,
)
from .project_files import create_project_bundle, load_project_bundle
from .search_index import search_project
from .fieldbook import clear_fieldbook_workspace, ingest_fieldbook_file, ingest_fieldbook_path
from .models import (
    AnalysisJob,
    AppState,
    BatchJob,
    CodeProfile,
    DipStatus,
    EvidenceBasis,
    FieldBookPage,
    FieldNoteProfile,
    FieldNoteTrainingAnnotation,
    FieldNoteTrainingExample,
    HistoryEvent,
    ImportedFileRecord,
    MapBookmark,
    MapLayer,
    CustomCoordinateSystem,
    MapAlignmentSettings,
    ManualNetworkEdge,
    OcrCandidate,
    PageEvidence,
    PipeMeasurement,
    ReviewState,
    ResultRecord,
    StatusRule,
    UnmatchedEvidence,
    VerifiedExample,
    utc_now_iso,
)
from .profiles import (
    delete_profile,
    ensure_default_profiles,
    export_profile_csv,
    get_profile,
    import_profile_csv,
    import_profile_file,
    list_profiles,
    save_profile,
)
from .field_note_profiles import (
    AUTO_PROFILE_ID,
    BRT_PROFILE_ID,
    build_profile_prompt,
    delete_field_note_profile,
    delete_training_example,
    duplicate_field_note_profile,
    ensure_default_field_note_profiles,
    export_profile_bundle,
    get_field_note_profile,
    import_profile_bundle,
    list_field_note_profiles,
    list_training_examples,
    safe_profile_id as safe_field_note_profile_id,
    save_field_note_profile,
    save_training_example,
)
from .storage import AppStorage
from .logging_config import configure_logging
from .performance import build_performance_plan, detect_hardware
from .interpret_cache import (
    clear_interpretation_cache, interpretation_cache_key, interpretation_cache_stats,
    load_interpretation_cache, save_interpretation_cache,
)
from .job_engine import AnalysisJobStore
from .errors import classify_exception
from .evidence_pipeline import (
    apply_assessment, classify_page_text, paddle_payload_text, windows_payload_text,
    windows_anchor_can_skip_paddle,
)
from .rod_height_qc import detect_rod_height_busts
from .validation import save_baseline, load_baseline, compare_to_baseline
from .diagnostics import build_diagnostic_bundle
from .feedback import (
    create_report as create_feedback_report,
    list_reports as list_feedback_reports,
    report_log_path as feedback_log_path,
    submit_to_tracker_endpoint,
    update_report_sync as update_feedback_sync,
    valid_tracker_endpoint,
)
from .global_mapper import (
    status as global_mapper_status, convert_vector_to_geojson, run_conversion as run_global_mapper_conversion,
    output_name as global_mapper_output_name, find_global_mapper,
)
from .survey import (
    available_point_ranges, extract_numeric_point_ids_file, merge_survey_points,
    parse_survey_bytes, parse_survey_file,
)
from surveysync import __version__ as SURVEYSYNC_VERSION
from surveysync.reports import crew_range_recommendations, crew_ranges_csv
from surveysync.config import ConfigStore as SurveySyncConfigStore, DEFAULT_UPDATE_MANIFEST_URL
from surveysync.updater import check as surveysync_update_check, stage as surveysync_update_stage
from surveysync.diagnostics import record_error as record_diagnostic_error
from surveysync.ai_runtime import (
    DEFAULT_FOUNDRY_VISION_MODEL,
    enable_foundry_model,
    ensure_windows_feature,
    get_local_ai_status,
    resolve_automatic_plan,
    windows_ocr,
)
from .map_gis import (
    crs_unit_label, import_map_files, normalize_crs, xy_to_wgs84, wgs84_to_xy,
    crs_details, search_coordinate_systems, parse_custom_crs_text,
    apply_similarity_alignment, invert_similarity_alignment, solve_similarity_alignment, crs_area_warning,
)


ENGINE_VERSION = "8.1.22"
APP_NAME = f"FieldBookSync module · SurveySync v{SURVEYSYNC_VERSION}"
STARTUP_STARTED = time.perf_counter()
STARTUP_METRICS: dict[str, float | str | bool] = {"app_import_started": True}

def _startup_mark(name: str, started: float) -> None:
    elapsed = time.perf_counter() - started
    STARTUP_METRICS[name] = round(elapsed, 4)
    print(f"[FieldBook Sync startup] {name}={elapsed:.3f}s", flush=True)

BASE_DIR = Path(__file__).resolve().parent
APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else BASE_DIR.parent
STATIC_DIR = BASE_DIR / "static"
BUNDLED_PROFILES_DIR = BASE_DIR / "profiles"
CURRENT_VERSION = SURVEYSYNC_VERSION
UPDATE_MANIFEST_URL = DEFAULT_UPDATE_MANIFEST_URL
UPDATE_RELEASES_URL = "https://github.com/cpaul1988/SurveySync/releases"
FEEDBACK_CONFIG_URL = "https://raw.githubusercontent.com/cpaul1988/SurveySync/main/feedback.json"
FEEDBACK_TRACKER_URL = "https://docs.google.com/spreadsheets/d/1OvFje-9m8yFWTz6h73ZXmVcRdXKU6zRE6HQ2qPtlAa4/edit"
FAST_OLLAMA_MODEL = "qwen3-vl:2b-instruct"
DEFAULT_OLLAMA_MODEL = "qwen3-vl:4b-instruct"
MAX_ACCURACY_OLLAMA_MODEL = "qwen3-vl:8b-instruct"
LEGACY_OLLAMA_MODELS = ["qwen2.5vl:3b", "qwen2.5vl:7b", "qwen3.8:27b"]
OLLAMA_PROFILE_VALUES = {"auto", "fast", "balanced", "maximum", "custom"}
RELEASE_NOTES = [
    "FieldBookSync is fully managed by the SurveySync application shell and SurveySync updater.",
    "The global SurveySync ribbon, themes, feedback wizard, AI settings, and release channel are shared across modules.",
    "Automatic local AI uses the adaptive SurveySync document pipeline with explicit cloud backups available when selected.",
]



def _default_feedback_config() -> dict:
    return {
        "form_url": "",  # legacy key; direct tracker no longer uses Google Forms
        "submit_url": "https://script.google.com/macros/s/AKfycbzmpUudERiJUXb5TuJzTd-G1TrtujD6XnZQ2PKpn-x6mXrcgAz34-sWZS4HHaTUnYZVlw/exec",  # official SurveySync shared Intake endpoint
        "intake_url": "https://script.google.com/macros/s/AKfycbzmpUudERiJUXb5TuJzTd-G1TrtujD6XnZQ2PKpn-x6mXrcgAz34-sWZS4HHaTUnYZVlw/exec",
        "transport": "google_apps_script",
        "tracker_url": FEEDBACK_TRACKER_URL,
        "config_url": FEEDBACK_CONFIG_URL,
        "message": "Submit bugs, feature requests, improvements, or questions directly to the FieldBook Sync Intake tracker.",
    }


def _feedback_config() -> dict:
    cfg = _default_feedback_config()
    try:
        req = urllib.request.Request(
            FEEDBACK_CONFIG_URL,
            headers={"User-Agent": f"FieldBookSync/{CURRENT_VERSION}", "Accept": "application/json,text/plain;q=0.9,*/*;q=0.1", "Cache-Control": "no-cache"},
        )
        with urllib.request.urlopen(req, timeout=6) as response:
            if int(getattr(response, "status", 200) or 200) != 200:
                return cfg
            body = response.read(64 * 1024 + 1)
        if len(body) > 64 * 1024:
            return cfg
        remote = json.loads(body.decode("utf-8-sig"))
        if isinstance(remote, dict):
            for key in ("form_url", "submit_url", "intake_url", "transport", "tracker_url", "message"):
                value = remote.get(key)
                if isinstance(value, str):
                    cfg[key] = value.strip()
    except Exception:
        logger.debug("Feedback configuration unavailable; using local fallback.", exc_info=True)
    return cfg


def _valid_feedback_url(value: str) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except Exception:
        return False
    if parsed.scheme.lower() != "https":
        return False
    host = (parsed.hostname or "").lower()
    if host in {"docs.google.com", "script.google.com"}:
        return True
    return host == "github.com" and parsed.path.lower().startswith("/cpaul1988/surveysync")


































































def rebind_project_storage(storage_root: Path | str) -> dict:
    """Move the embedded FieldBookSync engine to one SurveySync project workspace.

    Project switching is refused while analysis/import work is active. Every cache,
    recovery file and SQLite job ledger is recreated beneath the selected project so
    state cannot leak between projects.
    """
    global runtime, logger
    old = runtime
    with old.lock:
        if old.job.running or old.import_job.running:
            raise RuntimeError("Cannot switch SurveySync projects while FieldBookSync is processing data.")
    try:
        old.job_store.close()
    except Exception:
        logging.getLogger(__name__).warning("Recovery fallback in app; operation did not complete.", exc_info=True)
    runtime = Runtime(storage_root)
    logger = configure_logging(runtime.storage.root / "logs")
    return {
        "root": str(runtime.storage.root),
        "state_path": str(runtime.storage.state_path),
        "job_database": str(runtime.job_store.path),
        "ocr_cache": str(runtime.ocr_cache_dir),
        "interpretation_cache": str(runtime.interpretation_cache_dir),
    }

class Runtime:
    def __init__(self, storage_root: Path | str | None = None) -> None:
        _t = time.perf_counter()
        self.storage = AppStorage(storage_root)
        _startup_mark("project_state_load", _t)
        _t = time.perf_counter()
        ensure_default_profiles(self.storage.profile_dir)
        ensure_default_field_note_profiles(self.storage.field_note_profile_dir)
        _startup_mark("default_profiles", _t)
        self.provider: str = "auto"
        self.gemini_api_key: Optional[str] = os.environ.get("GEMINI_API_KEY")
        self.openai_api_key: Optional[str] = os.environ.get("OPENAI_API_KEY")
        self.anthropic_api_key: Optional[str] = os.environ.get("ANTHROPIC_API_KEY")
        self.ollama_model: str = DEFAULT_OLLAMA_MODEL
        self.ollama_profile: str = "auto"
        self.ollama_base_url: str = "http://127.0.0.1:11434"
        self.ollama_batch_pages: int = 1
        self.gemini_model: str = "gemini-3.8-flash"
        self.openai_model: str = "gpt-5.6-luna"
        self.anthropic_model: str = "claude-sonnet-5"
        self.gemini_batch_pages: int = 4
        self.confidence_threshold: float = 0.85
        self.status_rule: StatusRule = StatusRule.POINT_ID_FOUND
        self.elevation_is_rim: bool = False
        self.network_max_distance: float = 1500.0
        self.network_bearing_tolerance: float = 25.0
        self.performance_mode: str = "auto"
        _t = time.perf_counter()
        self.hardware_profile = detect_hardware(include_gpu=False)
        _startup_mark("hardware_core_profile", _t)
        self.ocr_cache_dir = self.storage.root / "ocr_cache_v1"
        self.ocr_cache_dir.mkdir(parents=True, exist_ok=True)
        self.interpretation_cache_dir = self.storage.root / "qwen_interpret_cache_v2"
        self.interpretation_cache_dir.mkdir(parents=True, exist_ok=True)
        self.interpretation_crop_dir = self.storage.root / "analysis_crop_cache_v2"
        self.interpretation_crop_dir.mkdir(parents=True, exist_ok=True)
        # v8.0.11 persistent job/error ledger.  Heavy AI already runs outside the
        # FastAPI event loop (Paddle is an isolated subprocess; Ollama is a separate
        # local service).  This ledger makes the coordinator crash-safe/resumable.
        _t = time.perf_counter()
        self.job_store = AnalysisJobStore(self.storage.root / "analysis_jobs.sqlite3")
        _startup_mark("job_store_open", _t)
        # Recovery and full GPU probing are useful but not prerequisites for showing the UI.
        # They are refreshed in a daemon thread immediately after app construction.
        self.recovered_interrupted_jobs = 0
        self.current_job_id: Optional[str] = None
        self.resume_job_id_pending: Optional[str] = None
        self.worker_watchdog_seconds: float = 1200.0
        self.worker_watchdog_thread: Optional[threading.Thread] = None
        self.worker_last_heartbeat_monotonic: float = 0.0
        self.analysis_heartbeat_stop = threading.Event()
        self.ollama_runtime_info: dict[str, Any] = {}
        self.qwen_last_persist_monotonic: float = 0.0
        self.validation_baseline_path = self.storage.root / "validation_baseline.json"
        self.diagnostic_dir = self.storage.root / "diagnostics"
        self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
        saved = self.storage.load_settings()
        saved_provider = str(saved.get("provider", self.provider)).strip().lower()
        # Existing v8/v9.0 installs used Hybrid as an implicit default. Migrate that
        # implicit default once to Automatic, while preserving providers a user explicitly
        # saves after 9.1.3.
        if saved_provider == "hybrid" and not bool(saved.get("provider_user_set", False)) and not bool(saved.get("auto_ai_default_migrated_v902", False)):
            self.provider = "auto"
            saved["provider"] = "auto"
            saved["auto_ai_default_migrated_v902"] = True
            self.storage.save_settings(saved)
        else:
            self.provider = saved_provider if saved_provider in {"auto", "hybrid", "ollama", "paddle", "gemini", "openai", "anthropic", "manual"} else "auto"
        self.ollama_model = str(saved.get("ollama_model", self.ollama_model))
        self.ollama_profile = str(saved.get("ollama_profile", "auto")).lower()
        if self.ollama_profile not in OLLAMA_PROFILE_VALUES:
            self.ollama_profile = "auto"
        self.ollama_base_url = str(saved.get("ollama_base_url", self.ollama_base_url))
        self.gemini_model = str(saved.get("gemini_model", self.gemini_model))
        self.openai_model = str(saved.get("openai_model", self.openai_model))
        self.anthropic_model = str(saved.get("anthropic_model", self.anthropic_model))
        self.confidence_threshold = float(saved.get("confidence_threshold", self.confidence_threshold))
        status_rule_missing = "status_rule" not in saved
        try:
            self.status_rule = StatusRule(saved.get("status_rule", self.status_rule.value))
        except Exception:
            self.status_rule = StatusRule.POINT_ID_FOUND
        if status_rule_missing:
            # v6.3 migration: preserve all extracted detail/manual review data while changing
            # only the primary deliverable to the new default PointID-found YES/NO rule.
            apply_status_rule_to_existing(self.storage.state.results, self.status_rule)
            if self.storage.state.results:
                self.storage.save()
            saved["status_rule"] = self.status_rule.value
            self.storage.save_settings(saved)
        self.elevation_is_rim = bool(saved.get("elevation_is_rim", self.elevation_is_rim))
        self.network_max_distance = float(saved.get("network_max_distance", self.network_max_distance))
        self.network_bearing_tolerance = float(saved.get("network_bearing_tolerance", self.network_bearing_tolerance))
        self.performance_mode = str(saved.get("performance_mode", self.performance_mode)).lower()
        self.rod_bust_enabled = bool(saved.get("rod_bust_enabled", True))
        self.rod_bust_search_radius = float(saved.get("rod_bust_search_radius", 15.0))
        self.rod_bust_max_slope_percent = float(saved.get("rod_bust_max_slope_percent", 8.0))
        self.rod_bust_increment_tolerance = float(saved.get("rod_bust_increment_tolerance", 0.08))
        self.rod_bust_min_neighbors = int(saved.get("rod_bust_min_neighbors", 2))
        if self.performance_mode not in {"auto", "safe", "balanced", "high"}:
            self.performance_mode = "auto"
        self.session_requests: dict[str, int] = {"foundry": 0, "ollama": 0, "gemini": 0, "openai": 0, "anthropic": 0}
        self.job = AnalysisJob(provider=self.provider)
        self.import_job = ImportJob()
        self.import_started_monotonic: float = 0.0
        self.batch_thread: Optional[threading.Thread] = None
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()
        self.analysis_thread: Optional[threading.Thread] = None
        self.lock = threading.RLock()
        # Monotonic in-process generation for analysis inputs. Any mutation that can
        # change the meaning of an analysis bumps this value. Workers refuse to commit
        # results if their starting revision is no longer current.
        self.project_revision: int = 0
        # v8.0.12: memoize the expensive resume/input SHA-256.  The cache key
        # includes project_revision plus the two small identity fields that are
        # part of the signature, so ordinary /api/state reads and result edits do
        # not re-serialize/re-hash thousands of points/pages.
        self.input_signature_cache_key: tuple | None = None
        self.input_signature_cache_value: str = ""
        # v8.0.8 live-analysis working snapshot.  These objects are intentionally
        # kept separate from AppStorage so an in-progress analysis can populate
        # Review/Map/Index without overwriting the last committed project result.
        self.live_active: bool = False
        self.live_analysis_revision: int = -1
        self.live_update_seq: int = 0
        self.live_survey_points = []
        self.live_candidates: list[OcrCandidate] = []
        self.live_interpreted_evidence: list[PageEvidence] = []
        self.live_unmatched: list[UnmatchedEvidence] = []
        self.live_results: list[ResultRecord] = []
        self.live_network_edges = []
        self.live_interpreted_candidate_keys: set[tuple] = set()
        self.live_interpreted_ids: set[str] = set()
        # v8.0.10: live network inference is throttled and performed outside
        # runtime.lock so /api/job, /api/network and Cancel stay responsive.
        self.live_network_dirty_seq: int = 0
        self.live_network_timer: Optional[threading.Timer] = None
        self.live_network_rebuild_running: bool = False
        self.live_network_debounce_seconds: float = 0.8
        # v8.1.21: one process-wide shutdown signal used by both the native WebView
        # shell and browser-fallback server.  This gives the File > Exit command a
        # real application shutdown path instead of relying on window.close().
        self.shutdown_event = threading.Event()
        # Nonessential startup work is launched only after the browser/WebView has
        # rendered the usable shell. Keeping this separate prevents GPU/SQLite
        # probes from competing with pywebview bridge injection during first paint.
        self.deferred_startup_lock = threading.Lock()
        self.deferred_startup_started = False
        self.deferred_startup_complete = False


runtime = Runtime()
logger = configure_logging(runtime.storage.root / "logs")
app = FastAPI(title=f"SurveySync v{CURRENT_VERSION}", version=CURRENT_VERSION)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _deferred_startup_checks(delay_seconds: float = 1.5) -> None:
    """Run optional recovery/GPU probes only after the UI has become usable.

    v8.1.17 started this daemon thread while the application module was still being
    imported. On Windows that overlapped with pywebview/WebView2 initialization.
    v8.1.21 waits for an explicit UI-ready signal instead.
    """
    try:
        # Recovery can run as soon as the UI explicitly says it is ready. The slow
        # NVIDIA probe is intentionally delayed so it cannot compete with WebView2's
        # first interactive frames / release-note dismissal.
        try:
            t = time.perf_counter()
            runtime.recovered_interrupted_jobs = runtime.job_store.recover_interrupted_jobs()
            _startup_mark("recover_interrupted_jobs_background", t)
        except Exception as exc:
            STARTUP_METRICS["recover_interrupted_jobs_error"] = str(exc)
            print(f"[FieldBook Sync startup] recovery check failed: {exc}", flush=True)
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            t = time.perf_counter()
            runtime.hardware_profile = detect_hardware(include_gpu=True)
            _startup_mark("hardware_gpu_probe_background", t)
        except Exception as exc:
            STARTUP_METRICS["hardware_gpu_probe_error"] = str(exc)
            print(f"[FieldBook Sync startup] GPU probe failed: {exc}", flush=True)
    finally:
        runtime.deferred_startup_complete = True
        STARTUP_METRICS["deferred_startup_complete"] = True


def start_deferred_startup_checks(delay_seconds: float = 1.5) -> bool:
    """Start the optional startup probes once; return True only for the starter."""
    with runtime.deferred_startup_lock:
        if runtime.deferred_startup_started:
            return False
        runtime.deferred_startup_started = True
        STARTUP_METRICS["deferred_startup_started"] = True
    threading.Thread(
        target=_deferred_startup_checks,
        args=(max(0.0, float(delay_seconds)),),
        name="FBS-startup-probes",
        daemon=True,
    ).start()
    return True


_startup_mark("app_import_ready", STARTUP_STARTED)


def request_application_shutdown(reason: str = "Application exit requested.") -> None:
    """Request a crash-safe application shutdown.

    The desktop shell, File > Exit command, and browser fallback all converge here.
    Any active analysis is checkpointed as resumable and asked to cancel; live network
    timers are stopped; the server runner observes ``runtime.shutdown_event``.
    """
    with runtime.lock:
        if runtime.shutdown_event.is_set():
            return
        if runtime.live_network_timer is not None:
            try:
                runtime.live_network_timer.cancel()
            except Exception:
                logging.getLogger(__name__).warning("Recovery fallback in app; operation did not complete.", exc_info=True)
            runtime.live_network_timer = None
        if runtime.job.running:
            runtime.cancel_event.set()
            # Invalidate the worker revision so a delayed AI response cannot commit
            # fresh results while the application is already shutting down.
            runtime.project_revision += 1
            runtime.job.message = f"{reason} Analysis checkpointed for resume."
            runtime.job.resumable = True
            try:
                _persist_job_snapshot_locked(status="INTERRUPTED")
            except Exception:
                logger.exception("Could not persist interrupted analysis during shutdown")
        runtime.shutdown_event.set()


def finalize_application_shutdown() -> None:
    """Best-effort cleanup after the local HTTP server has stopped."""
    try:
        runtime.job_store.close()
    except Exception:
        logger.exception("Could not close the persistent analysis job store")

@app.middleware("http")
async def _disable_ui_asset_cache(request: Request, call_next):
    """Prevent stale WebView2 JS/CSS from surviving an in-place SurveySync update."""
    response = await call_next(request)
    path = request.url.path.lower()
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.middleware("http")
async def _log_unhandled_requests(request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        if elapsed >= 2.0:
            logger.warning("Slow request %.2fs %s %s", elapsed, request.method, request.url.path)
        return response
    except HTTPException:
        raise
    except Exception as exc:
        ref = _error_reference("HTTP")
        logger.exception("Unhandled request failure [%s] %s %s", ref, request.method, request.url.path)
        info = classify_exception(exc, component="http")
        try:
            runtime.job_store.record_error(
                job_id=runtime.current_job_id, component="http", code=f"HTTP-{info.code}",
                message=f"{request.method} {request.url.path}: {info.user_message}", detail=info.detail,
                severity=info.severity, recoverable=info.recoverable,
            )
        except Exception:
            logging.getLogger(__name__).warning("Recovery fallback in app; operation did not complete.", exc_info=True)
        try:
            record_diagnostic_error(
                SurveySyncConfigStore().root,
                component="http",
                code=f"HTTP-{info.code}",
                message=f"{request.method} {request.url.path}: {info.user_message}",
                detail=info.detail,
                severity=info.severity,
                recoverable=info.recoverable,
                context={"route": request.url.path, "method": request.method, "reference": ref},
            )
        except Exception:
            logging.getLogger(__name__).warning("Recovery fallback in app; operation did not complete.", exc_info=True)
        raise



def _project_input_signature_locked() -> str:
    """Stable resume signature, memoized until analysis inputs change.

    v8.0.11 rebuilt and SHA-256 hashed every survey point and field-book page on
    every /api/state summary.  Large projects made that ordinary UI polling/action
    path unnecessarily O(points + pages).  project_revision already changes for
    survey/page/profile mutations; project/profile names are included explicitly in
    the cache key because they are also part of the persisted resume signature.
    """
    state = runtime.storage.state
    cache_key = (
        runtime.project_revision,
        state.project_name,
        state.selected_profile,
        len(state.survey_points),
        len(state.fieldbook_pages),
    )
    if runtime.input_signature_cache_key == cache_key:
        return runtime.input_signature_cache_value

    payload = {
        "project": state.project_name,
        "profile": state.selected_profile,
        "points": [
            [p.point_id, p.code, p.category, p.northing, p.easting, p.elevation]
            for p in state.survey_points
        ],
        "pages": [
            [p.page_id, p.source_name, p.page_number, p.image_path, p.enhanced_image_path]
            for p in state.fieldbook_pages
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    runtime.input_signature_cache_key = cache_key
    runtime.input_signature_cache_value = digest
    return digest


def _touch_worker_locked(message: str | None = None) -> None:
    runtime.worker_last_heartbeat_monotonic = time.monotonic()
    runtime.job.worker_heartbeat_at = utc_now_iso()
    if message is not None:
        runtime.job.message = message
    _persist_job_snapshot_locked()


def _persist_job_snapshot_locked(*, status: str | None = None) -> None:
    job_id = runtime.current_job_id or runtime.job.job_id
    if not job_id:
        return
    runtime.job.job_id = job_id
    if status is None:
        if runtime.job.running:
            status = "CANCELLING" if runtime.cancel_event.is_set() else "RUNNING"
        elif runtime.job.cancelled:
            status = "CANCELLED"
        elif runtime.job.complete:
            status = "COMPLETE"
        elif runtime.job.stage == "error":
            status = "ERROR"
        else:
            status = "INTERRUPTED"
    runtime.job_store.update_job(
        job_id,
        status=status,
        stage=runtime.job.stage,
        started_at=runtime.job.started_at,
        completed_at=utc_now_iso() if status in {"COMPLETE", "ERROR", "CANCELLED"} else None,
        total_pages=runtime.job.total_pages,
        current_page=runtime.job.current_page,
        total_requests=runtime.job.total_requests,
        current_request=runtime.job.current_request,
        message=runtime.job.message,
        error_code=runtime.job.error_code,
        error_message=runtime.job.error,
        retry_count=runtime.job.retry_count,
        failed_pages=runtime.job.failed_page_count,
        cancelled=1 if runtime.job.cancelled else 0,
    )


def _record_job_error(
    exc: BaseException,
    *,
    component: str,
    page: FieldBookPage | None = None,
    retry_number: int = 0,
    severity: str | None = None,
) -> tuple[str, str, bool]:
    info = classify_exception(exc, component=component)
    runtime.job_store.record_error(
        job_id=runtime.current_job_id,
        component=info.component,
        code=info.code,
        message=info.user_message,
        detail=info.detail,
        severity=severity or info.severity,
        recoverable=info.recoverable,
        page_id=page.page_id if page else None,
        retry_number=retry_number,
    )
    return info.code, info.user_message, info.recoverable


def _analysis_preflight_locked() -> list[str]:
    """Fast resource checks before launching heavyweight local workers."""
    warnings: list[str] = []
    try:
        disk = shutil.disk_usage(runtime.storage.root)
        free_gb = disk.free / (1024 ** 3)
        if free_gb < 1.0:
            raise HTTPException(507, f"Only {free_gb:.1f} GB of free disk space remains. Free at least 1 GB before analysis.")
        if free_gb < 4.0:
            warnings.append(f"Low disk space: {free_gb:.1f} GB free")
    except HTTPException:
        raise
    except Exception:
        logging.getLogger(__name__).warning("Recovery fallback in app; operation did not complete.", exc_info=True)
    hp = detect_hardware()
    runtime.hardware_profile = hp
    if hp.available_ram_bytes and hp.available_ram_bytes < 2 * 1024 ** 3:
        warnings.append("Less than 2 GB of RAM is currently available; Auto mode will use conservative concurrency")
    return warnings


def _start_worker_watchdog(job_id: str) -> None:
    """Watch the coordinator heartbeat without blocking FastAPI or AI subprocesses."""
    def _watch() -> None:
        while True:
            time.sleep(5.0)
            with runtime.lock:
                if runtime.current_job_id != job_id or not runtime.job.running:
                    return
                idle = time.monotonic() - runtime.worker_last_heartbeat_monotonic
                if idle <= runtime.worker_watchdog_seconds:
                    continue
                exc = TimeoutError(f"Analysis worker produced no coordinator heartbeat for {int(idle)} seconds.")
                code, message, recoverable = _record_job_error(exc, component="watchdog")
                runtime.job.error_code = code
                runtime.job.error = message
                runtime.job.recoverable = recoverable
                runtime.job.resumable = True
                runtime.job.warning_count += 1
                runtime.cancel_event.set()
                runtime.job.message = "Worker watchdog requested a safe stop. Completed checkpoints are preserved for resume."
                _persist_job_snapshot_locked(status="CANCELLING")
                return
    thread = threading.Thread(target=_watch, name=f"FBS-watchdog-{job_id[:8]}", daemon=True)
    runtime.worker_watchdog_thread = thread
    thread.start()


def _retry_operation(
    func,
    *,
    component: str,
    attempts: int = 3,
    page: FieldBookPage | None = None,
):
    """Retry only recoverable failures; checkpoints make retries idempotent locally."""
    last_exc: BaseException | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            code, message, recoverable = _record_job_error(
                exc, component=component, page=page, retry_number=attempt,
                severity="WARNING" if attempt < attempts else None,
            )
            with runtime.lock:
                runtime.job.error_code = code
                runtime.job.recoverable = recoverable
                runtime.job.retry_count += 1 if attempt < attempts and recoverable else 0
                runtime.job.warning_count += 1
                _touch_worker_locked(
                    f"{component.title()} attempt {attempt}/{attempts} failed: {message}"
                    + (" · retrying…" if attempt < attempts and recoverable else "")
                )
            if not recoverable or attempt >= attempts:
                raise
            time.sleep(min(4.0, 0.75 * (2 ** (attempt - 1))))
    if last_exc:
        raise last_exc



def _run_paddle_supervised(
    pages: list[FieldBookPage],
    app_root: Path,
    *,
    progress_callback=None,
    page_callback=None,
    page_error_callback=None,
    cancel_check=None,
    cache_dir=None,
    performance_mode: str = "auto",
    max_worker_attempts: int = 3,
):
    """Restart a crashed Paddle worker without repeating checkpointed pages."""
    for worker_attempt in range(1, max_worker_attempts + 1):
        try:
            return run_paddle_pages(
                pages, app_root,
                progress_callback=progress_callback,
                page_callback=page_callback,
                page_error_callback=page_error_callback,
                cancel_check=cancel_check,
                cache_dir=cache_dir,
                performance_mode=performance_mode,
            )
        except PaddleCancelled:
            raise
        except Exception as exc:
            code, message, recoverable = _record_job_error(
                exc, component="paddle-worker", retry_number=worker_attempt
            )
            with runtime.lock:
                runtime.job.error_code = code
                runtime.job.recoverable = recoverable
                runtime.job.resumable = True
                runtime.job.warning_count += 1
                if recoverable and worker_attempt < max_worker_attempts:
                    runtime.job.retry_count += 1
                    _touch_worker_locked(
                        f"Paddle worker stopped unexpectedly · restart {worker_attempt}/{max_worker_attempts - 1} · completed page checkpoints preserved."
                    )
                else:
                    _persist_job_snapshot_locked(status="RUNNING")
            if not recoverable or worker_attempt >= max_worker_attempts:
                raise
            time.sleep(min(5.0, 1.5 * worker_attempt))
    raise RuntimeError("Paddle worker restart limit reached.")



_AUTO_AI_CACHE_LOCK = threading.RLock()
_AUTO_AI_CACHE: tuple[float, str, dict[str, Any]] | None = None


def _automatic_ai_status(*, force: bool = False) -> dict[str, Any]:
    """Return shared Microsoft/local AI readiness plus the current Automatic plan."""
    global _AUTO_AI_CACHE
    now = time.monotonic()
    base_url = runtime.ollama_base_url
    with _AUTO_AI_CACHE_LOCK:
        if not force and _AUTO_AI_CACHE and _AUTO_AI_CACHE[1] == base_url and now - _AUTO_AI_CACHE[0] < 15:
            return deepcopy(_AUTO_AI_CACHE[2])
    status = get_local_ai_status(force=force)
    try:
        pstat = paddle_status(APP_ROOT)
        bridge_ready = paddle_bridge_path(APP_ROOT).exists()
        paddle_ready = bool(pstat.installed and bridge_ready)
        paddle_detail = (
            pstat.message if bridge_ready else
            "SurveySync's PaddleOCR bridge is missing. Repair or reinstall SurveySync; Automatic will use another ready local engine until it is restored."
        )
    except Exception as exc:
        paddle_ready = False
        paddle_detail = str(exc)
    try:
        models = list_ollama_models(base_url=base_url, timeout_seconds=0.8)
        ollama_ready = bool(models)
        ollama_detail = f"{len(models)} local model(s) installed" if models else "Ollama is running but no local model is installed."
    except Exception as exc:
        models = []
        ollama_ready = False
        ollama_detail = str(exc)
    plan = resolve_automatic_plan(
        status,
        hybrid_ready=bool(paddle_ready and ollama_ready),
        paddle_ready=paddle_ready,
        ollama_ready=ollama_ready,
    )
    payload = {
        **status,
        "paddle": {"ready": paddle_ready, "detail": paddle_detail},
        "ollama": {"ready": ollama_ready, "detail": ollama_detail, "models": models},
        "automatic_plan": plan.to_dict(),
        "requested_provider": runtime.provider,
        "no_cloud_fallback": True,
        "downloads_require_consent": True,
    }
    with _AUTO_AI_CACHE_LOCK:
        _AUTO_AI_CACHE = (now, base_url, deepcopy(payload))
    return payload

def _effective_page_profile_id(page: FieldBookPage) -> str:
    """Return explicit page/book profile without inventing one for AUTO mode."""
    page_override = str(getattr(page, "field_note_profile_override", "") or "").strip().upper()
    if page_override and page_override != AUTO_PROFILE_ID:
        return page_override
    book_default = str(getattr(page, "field_note_profile_book", "") or "").strip().upper()
    if book_default and book_default != AUTO_PROFILE_ID:
        return book_default
    return ""


def _field_note_profile_context(selected_profile_id: str | None = None) -> str:
    """Build the current profile catalog/instructions for AI interpretation.

    This is advisory prompt context only. PointID evidence, OCR provenance and deterministic
    QA gates remain authoritative. Profile selection cannot create a survey observation.
    """
    try:
        selected = selected_profile_id or runtime.storage.state.selected_field_note_profile or AUTO_PROFILE_ID
        return build_profile_prompt(runtime.storage.field_note_profile_dir, selected, runtime.storage.field_note_training_dir)
    except Exception:
        logger.warning("Could not build field-note profile prompt; continuing with generic rules.", exc_info=True)
        return ""


def _summary() -> dict:
    ai_status = _automatic_ai_status()
    active_provider = (ai_status.get("automatic_plan") or {}).get("effective_provider") if runtime.provider == "auto" else runtime.provider
    active_label = (ai_status.get("automatic_plan") or {}).get("label") if runtime.provider == "auto" else runtime.provider
    # Always acquire runtime.lock before storage.lock when both are needed.
    with runtime.lock, runtime.storage.lock:
        state = runtime.storage.state
        status_counts = {s.value: 0 for s in DipStatus}
        review_counts = {s.value: 0 for s in ReviewState}
        qa_review_count = 0
        for result in state.results:
            status_counts[result.status.value] = status_counts.get(result.status.value, 0) + 1
            review_counts[result.review_state.value] = review_counts.get(result.review_state.value, 0) + 1
            if result.qa_needs_review:
                qa_review_count += 1
        target_chunks = max(1, math.ceil(len(state.survey_points) / 220)) if state.survey_points else 0
        if active_provider in {"ollama", "hybrid", "windows_ocr_ollama"}:
            estimated_requests = math.ceil(len(state.fieldbook_pages) / runtime.ollama_batch_pages) * target_chunks if target_chunks else 0
        elif active_provider == "gemini":
            estimated_requests = math.ceil(len(state.fieldbook_pages) / runtime.gemini_batch_pages) * target_chunks if target_chunks else 0
        elif active_provider in {"openai", "anthropic"}:
            estimated_requests = len(state.fieldbook_pages) * target_chunks if target_chunks else 0
        else:
            estimated_requests = 0
        resumable_job = None
        input_signature = ""
        # Hashing every point/page can be expensive on a large project. Only do it when
        # the ledger actually contains a resumable job that could match this project.
        try:
            has_resumable = runtime.job_store.has_resumable_jobs()
        except Exception:
            has_resumable = False
        if has_resumable and state.survey_points and state.fieldbook_pages:
            input_signature = _project_input_signature_locked()
            resumable_job = runtime.job_store.latest_resumable(input_signature)
        return {
            "app_name": APP_NAME,
            "project_name": state.project_name,
            "project_created_at": state.project_created_at,
            "project_modified_at": state.project_modified_at,
            "autosave_path": str(runtime.storage.state_path),
            "recovery_available": runtime.storage.recovery_path.exists(),
            "selected_profile": state.selected_profile,
            "selected_field_note_profile": state.selected_field_note_profile or AUTO_PROFILE_ID,
            "field_note_profile_count": len(list_field_note_profiles(runtime.storage.field_note_profile_dir)),
            "field_note_training_example_count": len(list_training_examples(runtime.storage.field_note_training_dir)),
            "survey_files": [x.model_dump(mode="json") for x in state.survey_files],
            "fieldbook_files": [x.model_dump(mode="json") for x in state.fieldbook_files],
            "survey_count": len(state.survey_points),
            "survey_issue_count": len(state.survey_issues),
            "rod_height_bust_count": len(state.rod_height_busts),
            "page_count": len(state.fieldbook_pages),
            "ocr_candidate_count": len(state.ocr_candidates),
            "network_edge_count": len(state.network_edges),
            "verified_example_count": len(state.verified_examples),
            "history_count": len(state.history),
            "redo_count": len(state.redo_stack),
            "batch_count": len(state.batch_jobs),
            "result_count": len(state.results),
            "unmatched_count": len(state.unmatched),
            "status_counts": status_counts,
            "review_counts": review_counts,
            "qa_review_count": qa_review_count,
            "settings": {
                "provider": runtime.provider,
                "active_provider": active_provider or runtime.provider,
                "active_provider_label": active_label or runtime.provider,
                "ai_status": ai_status,
                "ollama_model": runtime.ollama_model,
                "ollama_profile": runtime.ollama_profile,
                "ollama_base_url": runtime.ollama_base_url,
                "ollama_batch_pages": runtime.ollama_batch_pages,
                "has_gemini_key": bool(runtime.gemini_api_key),
                "has_openai_key": bool(runtime.openai_api_key),
                "has_anthropic_key": bool(runtime.anthropic_api_key),
                "has_api_key": bool(runtime.gemini_api_key if runtime.provider == "gemini" else runtime.openai_api_key if runtime.provider == "openai" else runtime.anthropic_api_key if runtime.provider == "anthropic" else True),
                "gemini_model": runtime.gemini_model,
                "openai_model": runtime.openai_model,
                "anthropic_model": runtime.anthropic_model,
                "model": runtime.ollama_model if active_provider in {"ollama", "hybrid", "windows_ocr_ollama"} else DEFAULT_FOUNDRY_VISION_MODEL if active_provider == "microsoft_auto" else runtime.gemini_model if active_provider == "gemini" else runtime.openai_model if active_provider == "openai" else runtime.anthropic_model if active_provider == "anthropic" else "manual",
                "gemini_batch_pages": runtime.gemini_batch_pages,
                "confidence_threshold": runtime.confidence_threshold,
                "status_rule": runtime.status_rule.value,
                "estimated_requests": estimated_requests,
                "session_requests": dict(runtime.session_requests),
                "elevation_is_rim": runtime.elevation_is_rim,
                "network_max_distance": runtime.network_max_distance,
                "network_bearing_tolerance": runtime.network_bearing_tolerance,
                "performance_mode": runtime.performance_mode,
                "rod_bust_enabled": runtime.rod_bust_enabled,
                "rod_bust_search_radius": runtime.rod_bust_search_radius,
                "rod_bust_max_slope_percent": runtime.rod_bust_max_slope_percent,
                "rod_bust_increment_tolerance": runtime.rod_bust_increment_tolerance,
                "rod_bust_min_neighbors": runtime.rod_bust_min_neighbors,
            },
            "performance": {
                "hardware": runtime.hardware_profile.as_dict(),
                "plan": build_performance_plan(runtime.performance_mode, runtime.hardware_profile).as_dict(),
                "ocr_cache": ocr_cache_stats(runtime.ocr_cache_dir),
                "interpretation_cache": interpretation_cache_stats(runtime.interpretation_cache_dir),
                "ollama_runtime": dict(runtime.ollama_runtime_info),
                "startup": dict(STARTUP_METRICS),
            },
            "job": runtime.job.model_dump(mode="json"),
            "import_job": runtime.import_job.model_dump(mode="json"),
            "project_revision": runtime.project_revision,
            "reliability": {
                "job_database": str(runtime.job_store.path),
                "job_status_counts": runtime.job_store.status_counts(),
                "recovered_interrupted_jobs": runtime.recovered_interrupted_jobs,
                "resumable_job": resumable_job,
                "validation_baseline_exists": runtime.validation_baseline_path.exists(),
                "watchdog_seconds": int(runtime.worker_watchdog_seconds),
            },
        }


def _begin_import(kind: str, total_files: int) -> None:
    with runtime.lock:
        if runtime.import_job.running:
            raise HTTPException(409, f"A {runtime.import_job.kind or 'file'} import is already running.")
        runtime.import_started_monotonic = time.perf_counter()
        runtime.import_job = ImportJob(
            running=True, kind=kind, phase="uploading", percent=0,
            current_file=0, total_files=max(1, total_files), message=f"Preparing {kind} import…",
            started_at=utc_now_iso(),
        )


def _update_import(**changes) -> None:
    with runtime.lock:
        for key, value in changes.items():
            if hasattr(runtime.import_job, key):
                setattr(runtime.import_job, key, value)


def _complete_import(message: str) -> None:
    _update_import(running=False, phase="complete", percent=100, message=message, error=None)


def _fail_import(message: str) -> None:
    _update_import(running=False, phase="error", message=message, error=message)


@app.get("/api/import-job")
def api_import_job() -> dict:
    with runtime.lock:
        data = runtime.import_job.model_dump(mode="json")
        data["elapsed_seconds"] = round(time.perf_counter() - runtime.import_started_monotonic, 1) if runtime.import_started_monotonic else 0.0
        return data


UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = int(os.environ.get("FIELDBOOK_SYNC_MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))


def _safe_upload_filename(name: str, fallback: str = "upload.bin") -> str:
    base = Path(name or fallback).name
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in base).strip()
    return (safe or fallback)[:180]


async def _stream_upload_to_path(upload: UploadFile, path: Path, max_bytes: int = MAX_UPLOAD_BYTES) -> int:
    """Stream an UploadFile to disk in bounded chunks instead of buffering it in RAM."""
    path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with path.open("wb") as out:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(413, f"{upload.filename or 'Upload'} exceeds the configured {max_bytes / 1024**3:.1f} GB per-file limit.")
                out.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return total


def _error_reference(prefix: str = "ERR") -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6].upper()}"


def _copy_bundled_profiles_once() -> None:
    if not BUNDLED_PROFILES_DIR.exists():
        return
    for src in BUNDLED_PROFILES_DIR.glob("*.json"):
        dst = runtime.storage.profile_dir / src.name
        if not dst.exists():
            try:
                shutil.copy2(src, dst)
            except Exception:
                logging.getLogger(__name__).warning("Recovery fallback in app; operation did not complete.", exc_info=True)


_copy_bundled_profiles_once()

def _assert_analysis_idle_locked() -> None:
    if runtime.job.running:
        raise HTTPException(409, "Wait for the current analysis to finish or cancel it before changing project data.")


def _assert_analysis_idle_or_paused_locked() -> None:
    if runtime.job.running and not runtime.job.paused:
        raise HTTPException(409, "Pause the active analysis before changing this setting.")


def _analysis_pause_checkpoint(analysis_revision: int, context: str = "safe checkpoint") -> bool:
    if not runtime.pause_event.is_set():
        return True
    with runtime.lock:
        if runtime.cancel_event.is_set() or runtime.project_revision != analysis_revision:
            return False
        runtime.job.pause_requested = False
        runtime.job.paused = True
        runtime.job.message = f"Analysis paused at {context}. You can adjust coordinate-system/GIS settings, then Resume."
        _persist_job_snapshot_locked(status="PAUSED")
    while runtime.pause_event.is_set():
        if runtime.cancel_event.wait(0.15):
            return False
        with runtime.lock:
            if runtime.project_revision != analysis_revision:
                return False
            _touch_worker_locked()
    with runtime.lock:
        runtime.job.paused = False
        runtime.job.pause_requested = False
        runtime.job.message = "Resuming analysis from the saved checkpoint…"
        _persist_job_snapshot_locked(status="RUNNING")
    return True


def _refresh_rod_height_busts_locked() -> None:
    if not runtime.rod_bust_enabled:
        runtime.storage.state.rod_height_busts = []
        return
    runtime.storage.state.rod_height_busts = detect_rod_height_busts(
        runtime.storage.state.survey_points,
        search_radius=runtime.rod_bust_search_radius,
        max_slope_percent=runtime.rod_bust_max_slope_percent,
        increment_tolerance=runtime.rod_bust_increment_tolerance,
        min_neighbors=runtime.rod_bust_min_neighbors,
    )


def _ensure_analysis_idle() -> None:
    with runtime.lock:
        _assert_analysis_idle_locked()


def _bump_project_revision_locked() -> int:
    runtime.project_revision += 1
    return runtime.project_revision


def _clear_profile_dependent_state_locked() -> bool:
    """Clear data whose validity depends on the selected code profile.

    Caller must hold runtime.storage.lock. Returns True when any dependent data existed.
    """
    state = runtime.storage.state
    had_data = bool(state.survey_points or state.survey_issues or state.results or state.unmatched or state.ocr_candidates or state.network_edges)
    state.survey_points = []
    state.survey_issues = []
    state.results = []
    state.unmatched = []
    state.ocr_candidates = []
    state.network_edges = []
    return had_data


def _mark_analysis_stale_locked(message: str) -> None:
    runtime.job.running = False
    runtime.job.complete = False
    runtime.job.error_code = "JOB-STALE-001"
    runtime.job.error = "Project data changed while analysis was running; stale AI results were discarded."
    runtime.job.message = message
    runtime.job.resumable = False
    _persist_job_snapshot_locked(status="ERROR")
    _end_live_analysis_locked()


def _ollama_model_is_installed(selected: str, installed: list[str]) -> bool:
    selected = (selected or "").strip()
    if not selected:
        return False
    if selected in installed:
        return True
    # Ollama treats an untagged name as :latest. Do not assume one explicit tag
    # satisfies another (e.g. :latest vs :27b), even if they may share a digest.
    if ":" not in selected:
        return f"{selected}:latest" in installed
    return False

def _recommend_ollama_model(
    installed: list[str],
    *,
    profile: str = "auto",
    selected: str = "",
    vram_bytes: int = 0,
) -> tuple[str, str]:
    """Choose a local vision model conservatively from models already installed."""
    installed = [str(x).strip() for x in installed if str(x).strip()]
    profile = (profile or "auto").strip().lower()
    selected = (selected or "").strip()
    if profile == "custom":
        return (selected or DEFAULT_OLLAMA_MODEL), "Custom model selection is enabled."

    def first_available(candidates: list[str]) -> str:
        for candidate in candidates:
            if _ollama_model_is_installed(candidate, installed):
                return candidate
        return ""

    legacy = [m for m in LEGACY_OLLAMA_MODELS if m]
    if profile == "fast":
        chosen = first_available([FAST_OLLAMA_MODEL, DEFAULT_OLLAMA_MODEL, selected, *legacy])
        return (chosen or selected or FAST_OLLAMA_MODEL), "Fast prefers Qwen3-VL 2B for low-memory local document vision."
    if profile == "maximum":
        chosen = first_available([MAX_ACCURACY_OLLAMA_MODEL, DEFAULT_OLLAMA_MODEL, selected, *legacy])
        return (chosen or selected or MAX_ACCURACY_OLLAMA_MODEL), "Maximum Accuracy prefers Qwen3-VL 8B before legacy large models."
    if profile == "balanced":
        chosen = first_available([DEFAULT_OLLAMA_MODEL, FAST_OLLAMA_MODEL, selected, *legacy, MAX_ACCURACY_OLLAMA_MODEL])
        return (chosen or selected or DEFAULT_OLLAMA_MODEL), "Balanced prefers Qwen3-VL 4B for strong document vision at a much smaller local footprint."

    vram_gb = (vram_bytes or 0) / (1024 ** 3)
    if not vram_gb:
        order = [FAST_OLLAMA_MODEL, DEFAULT_OLLAMA_MODEL, selected, *legacy, MAX_ACCURACY_OLLAMA_MODEL]
        reason = "Auto selected the smallest preferred vision model because dedicated GPU VRAM was not detected."
    elif vram_gb < 6:
        order = [FAST_OLLAMA_MODEL, DEFAULT_OLLAMA_MODEL, selected, *legacy, MAX_ACCURACY_OLLAMA_MODEL]
        reason = f"Auto selected Qwen3-VL 2B first for {vram_gb:.1f} GB of VRAM."
    elif vram_gb < 10:
        order = [DEFAULT_OLLAMA_MODEL, FAST_OLLAMA_MODEL, selected, *legacy, MAX_ACCURACY_OLLAMA_MODEL]
        reason = f"Auto selected Qwen3-VL 4B first for {vram_gb:.1f} GB of VRAM."
    else:
        order = [MAX_ACCURACY_OLLAMA_MODEL, DEFAULT_OLLAMA_MODEL, selected, *legacy, FAST_OLLAMA_MODEL]
        reason = "Auto selected Qwen3-VL 8B first for the detected GPU class."
    chosen = first_available(order)
    if not chosen:
        chosen = selected if selected else (installed[0] if installed else DEFAULT_OLLAMA_MODEL)
        reason = "Auto could not find a preferred model and kept the available selection."
    return chosen, reason


def _ollama_warning_for_model(model: str, vram_bytes: int) -> str:
    vram_gb = (vram_bytes or 0) / (1024 ** 3)
    if model == MAX_ACCURACY_OLLAMA_MODEL and vram_gb and vram_gb < 8:
        return f"{model} may spill to system RAM on {vram_gb:.1f} GB VRAM. Balanced (Qwen3-VL 4B) is recommended."
    if model == "qwen3.8:27b" and vram_gb and vram_gb < 16:
        return f"Legacy {model} is very large for {vram_gb:.1f} GB VRAM. Qwen3-VL 4B or 8B is recommended."
    return ""


def _refresh_ollama_runtime_info(base_url: str, model: str) -> dict[str, Any]:
    running = ollama_running_models(base_url=base_url)
    match = next((x for x in running if str(x.get("name")) == model), None)
    info = dict(match or {})
    info["model"] = model
    info["loaded"] = bool(match)
    with runtime.lock:
        runtime.ollama_runtime_info = info
        if match and runtime.job.running:
            runtime.job.qwen_cpu_percent = float(match.get("cpu_percent") or 0.0)
            runtime.job.qwen_gpu_percent = float(match.get("gpu_percent") or 0.0)
    return info


def _qwen_progress(info: dict[str, Any]) -> None:
    """Lightweight streaming telemetry; persist at most once every two seconds."""
    now = time.monotonic()
    with runtime.lock:
        if not runtime.job.running:
            return
        runtime.job.qwen_model = str(info.get("model") or runtime.job.qwen_model or runtime.ollama_model)
        state = str(info.get("state") or "working")
        runtime.job.qwen_state = state
        runtime.job.qwen_elapsed_seconds = float(info.get("elapsed_seconds") or 0.0)
        if state in {"requesting", "loading"}:
            runtime.job.qwen_output_tokens = 0
            runtime.job.qwen_output_chars = 0
        else:
            if "output_tokens" in info:
                runtime.job.qwen_output_tokens = int(info.get("output_tokens") or 0)
            if "output_chars" in info:
                runtime.job.qwen_output_chars = int(info.get("output_chars") or 0)
        runtime.worker_last_heartbeat_monotonic = now
        runtime.job.worker_heartbeat_at = utc_now_iso()
        if now - runtime.qwen_last_persist_monotonic >= 2.0:
            runtime.qwen_last_persist_monotonic = now
            _persist_job_snapshot_locked()


def _start_analysis_heartbeat(job_id: str) -> None:
    """Independent coordinator pulse so long model inference never looks like a dead worker."""
    runtime.analysis_heartbeat_stop.set()
    runtime.analysis_heartbeat_stop = threading.Event()
    stop_event = runtime.analysis_heartbeat_stop

    def _pulse() -> None:
        while not stop_event.wait(10.0):
            with runtime.lock:
                if runtime.current_job_id != job_id or not runtime.job.running:
                    return
                runtime.worker_last_heartbeat_monotonic = time.monotonic()
                runtime.job.worker_heartbeat_at = utc_now_iso()
    threading.Thread(target=_pulse, name=f"FBS-heartbeat-{job_id[:8]}", daemon=True).start()


@app.get("/fieldbook", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-store, no-cache, max-age=0, must-revalidate", "Pragma": "no-cache", "Expires": "0"})


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.ico", media_type="image/x-icon")


@app.get("/api/state")
def api_state() -> dict:
    return _summary()


@app.get("/api/profiles")
def api_profiles() -> list[dict]:
    return [p.model_dump(mode="json") for p in list_profiles(runtime.storage.profile_dir)]


@app.post("/api/profiles")
def api_save_profile(payload: ProfileSaveIn) -> dict:
    profile = CodeProfile(
        name=payload.name.strip(),
        client=payload.client,
        notes=payload.notes,
        codes=payload.codes,
    )
    original_name = (payload.original_name or profile.name).strip()
    if not profile.name:
        raise HTTPException(400, "Profile name is required.")
    if any(ch in profile.name for ch in "/\\"):
        raise HTTPException(400, "Profile names cannot contain slash characters.")
    if original_name in {"MSD", "MoDOT", "Ameren", "IDOT", "Lambert"} and original_name != profile.name:
        raise HTTPException(400, "Built-in client profiles cannot be renamed. Create a new custom profile instead.")

    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        try:
            save_profile(runtime.storage.profile_dir, profile, original_name=original_name)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

        state = runtime.storage.state
        affects_active = state.selected_profile in {original_name, profile.name}
        renamed_active = original_name != profile.name and state.selected_profile == original_name
        if renamed_active:
            state.selected_profile = profile.name

        invalidated = False
        if affects_active:
            invalidated = _clear_profile_dependent_state_locked()
            _bump_project_revision_locked()
            runtime.storage.save()
        elif renamed_active:
            runtime.storage.save()

    return {
        "ok": True,
        "profile": profile.model_dump(mode="json"),
        "original_name": original_name,
        "renamed": original_name != profile.name,
        "survey_invalidated": invalidated,
    }


@app.delete("/api/profiles/{name}")
def api_delete_profile(name: str) -> dict:
    if name in {"MSD", "MoDOT", "Ameren", "IDOT", "Lambert"}:
        raise HTTPException(400, "Built-in client placeholders cannot be deleted; edit them instead.")
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        try:
            delete_profile(runtime.storage.profile_dir, name)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

        invalidated = False
        if runtime.storage.state.selected_profile == name:
            runtime.storage.state.selected_profile = None
            invalidated = _clear_profile_dependent_state_locked()
            _bump_project_revision_locked()
            runtime.storage.save()
    return {"ok": True, "survey_invalidated": invalidated}


async def _api_import_profile_file_impl(
    file: UploadFile,
    name: str,
    client: str,
    *,
    force_csv: bool = False,
) -> dict:
    _ensure_analysis_idle()
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(400, "Profile name is required.")
    if any(ch in clean_name for ch in "/\\"):
        raise HTTPException(400, "Profile names cannot contain slash characters.")

    original_name = Path(file.filename or "codes.csv").name
    suffix = ".csv" if force_csv else (Path(original_name).suffix.lower() or ".bin")
    tmp = runtime.storage.root / f"profile_upload_{uuid4().hex}{suffix}"
    try:
        await _stream_upload_to_path(file, tmp, max_bytes=10 * 1024 * 1024)
        raw = tmp.read_bytes()  # profile code lists are intentionally capped at 10 MB
        if force_csv:
            profile = import_profile_csv(name=clean_name, client=client.strip(), raw=raw)
        else:
            profile = import_profile_file(
                name=clean_name, client=client.strip(), raw=raw, filename=original_name
            )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        tmp.unlink(missing_ok=True)

    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        try:
            save_profile(runtime.storage.profile_dir, profile)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

        invalidated = False
        if runtime.storage.state.selected_profile == profile.name:
            invalidated = _clear_profile_dependent_state_locked()
            _bump_project_revision_locked()
            runtime.storage.save()

    return {
        "ok": True,
        "profile": profile.model_dump(mode="json"),
        "survey_invalidated": invalidated,
        "source_file": original_name,
    }


@app.post("/api/profiles/import")
async def api_import_profile_file(
    file: UploadFile = File(...),
    name: str = Form(...),
    client: str = Form(""),
) -> dict:
    return await _api_import_profile_file_impl(file, name, client)


@app.post("/api/profiles/import-csv")
async def api_import_profile_csv(
    file: UploadFile = File(...),
    name: str = Form(...),
    client: str = Form(""),
) -> dict:
    # Backward-compatible endpoint retained for existing automation/scripts.
    return await _api_import_profile_file_impl(file, name, client, force_csv=True)


@app.get("/api/profiles/{name}/export-csv")
def api_export_profile_csv(name: str) -> StreamingResponse:
    try:
        profile = get_profile(runtime.storage.profile_dir, name)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    data = export_profile_csv(profile)
    headers = {"Content-Disposition": f'attachment; filename="{name}_codes.csv"'}
    return StreamingResponse(iter([data]), media_type="text/csv", headers=headers)


@app.post("/api/select-profile")
def api_select_profile(payload: SelectProfileIn) -> dict:
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        try:
            get_profile(runtime.storage.profile_dir, payload.name)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        changed = runtime.storage.state.selected_profile != payload.name
        runtime.storage.state.selected_profile = payload.name
        if changed:
            _clear_profile_dependent_state_locked()
            _bump_project_revision_locked()
        runtime.storage.save()
    return _summary()

































@app.post("/api/settings")
def api_settings(payload: SettingsIn) -> dict:
    provider = payload.provider.strip().lower()
    if provider not in {"auto", "hybrid", "ollama", "paddle", "gemini", "openai", "anthropic", "manual"}:
        raise HTTPException(400, "Analysis provider must be Automatic, Hybrid Local, Qwen Local, Paddle OCR, Gemini, OpenAI, Anthropic Claude, or Manual Review.")
    with runtime.lock:
        _assert_analysis_idle_locked()
        previous_status_rule = runtime.status_rule
        runtime.provider = provider
        try:
            shared_cfg_store = SurveySyncConfigStore()
            shared_cfg = shared_cfg_store.load()
            shared_cfg.ai_provider = provider if provider in {"auto", "hybrid", "gemini", "openai", "anthropic", "manual"} else "auto"
            shared_cfg_store.save(shared_cfg)
        except Exception:
            logger.debug("Could not synchronize the shared SurveySync AI preference.", exc_info=True)
        if payload.gemini_api_key is not None:
            key = payload.gemini_api_key.strip()
            if key:
                runtime.gemini_api_key = key
            elif not os.environ.get("GEMINI_API_KEY"):
                runtime.gemini_api_key = None
        if payload.openai_api_key is not None:
            key = payload.openai_api_key.strip()
            if key:
                runtime.openai_api_key = key
            elif not os.environ.get("OPENAI_API_KEY"):
                runtime.openai_api_key = None
        if payload.anthropic_api_key is not None:
            key = payload.anthropic_api_key.strip()
            if key:
                runtime.anthropic_api_key = key
            elif not os.environ.get("ANTHROPIC_API_KEY"):
                runtime.anthropic_api_key = None
        if payload.api_key is not None:
            key = payload.api_key.strip()
            if key:
                runtime.openai_api_key = key
            elif not os.environ.get("OPENAI_API_KEY"):
                runtime.openai_api_key = None
        if payload.model is not None and payload.model.strip():
            runtime.openai_model = payload.model.strip()

        local_url = payload.ollama_base_url.strip().rstrip("/") or "http://127.0.0.1:11434"
        if not local_url.startswith(("http://", "https://")):
            raise HTTPException(400, "Ollama server URL must start with http:// or https://")
        runtime.ollama_model = payload.ollama_model.strip() or DEFAULT_OLLAMA_MODEL
        runtime.ollama_profile = (payload.ollama_profile or "auto").strip().lower()
        if runtime.ollama_profile not in OLLAMA_PROFILE_VALUES:
            raise HTTPException(400, "Local AI profile must be Auto, Fast, Balanced, Maximum Accuracy, or Custom.")
        runtime.ollama_base_url = local_url
        runtime.ollama_batch_pages = payload.ollama_batch_pages
        runtime.gemini_model = payload.gemini_model.strip().removeprefix("models/") or "gemini-3.8-flash"
        runtime.openai_model = payload.openai_model.strip() or runtime.openai_model or "gpt-5.6-luna"
        runtime.anthropic_model = payload.anthropic_model.strip() or runtime.anthropic_model or "claude-sonnet-5"
        runtime.gemini_batch_pages = payload.gemini_batch_pages
        runtime.confidence_threshold = payload.confidence_threshold
        runtime.status_rule = payload.status_rule
        runtime.elevation_is_rim = payload.elevation_is_rim
        runtime.network_max_distance = payload.network_max_distance
        runtime.network_bearing_tolerance = payload.network_bearing_tolerance
        runtime.rod_bust_enabled = payload.rod_bust_enabled
        runtime.rod_bust_search_radius = payload.rod_bust_search_radius
        runtime.rod_bust_max_slope_percent = payload.rod_bust_max_slope_percent
        runtime.rod_bust_increment_tolerance = payload.rod_bust_increment_tolerance
        runtime.rod_bust_min_neighbors = payload.rod_bust_min_neighbors
        perf_mode = (payload.performance_mode or "auto").lower()
        if perf_mode not in {"auto", "safe", "balanced", "high"}:
            raise HTTPException(400, "Performance mode must be Auto, Safe, Balanced, or High Performance.")
        runtime.performance_mode = perf_mode
        runtime.storage.save_settings({
            "provider": runtime.provider,
            "provider_user_set": True,
            "auto_ai_default_migrated_v902": True,
            "ollama_model": runtime.ollama_model,
            "ollama_profile": runtime.ollama_profile,
            "ollama_base_url": runtime.ollama_base_url,
            "ollama_batch_pages": runtime.ollama_batch_pages,
            "gemini_model": runtime.gemini_model,
            "openai_model": runtime.openai_model,
            "anthropic_model": runtime.anthropic_model,
            "gemini_batch_pages": runtime.gemini_batch_pages,
            "confidence_threshold": runtime.confidence_threshold,
            "status_rule": runtime.status_rule.value,
            "elevation_is_rim": runtime.elevation_is_rim,
            "network_max_distance": runtime.network_max_distance,
            "network_bearing_tolerance": runtime.network_bearing_tolerance,
            "performance_mode": runtime.performance_mode,
            "rod_bust_enabled": runtime.rod_bust_enabled,
            "rod_bust_search_radius": runtime.rod_bust_search_radius,
            "rod_bust_max_slope_percent": runtime.rod_bust_max_slope_percent,
            "rod_bust_increment_tolerance": runtime.rod_bust_increment_tolerance,
            "rod_bust_min_neighbors": runtime.rod_bust_min_neighbors,
        })
        # Status-rule changes re-map the existing primary deliverable without re-running AI.
        # Manual overrides remain untouched. Other derived QC/network results are recomputed.
        with runtime.storage.lock:
            _refresh_rod_height_busts_locked()
            if runtime.storage.state.results:
                if previous_status_rule != runtime.status_rule:
                    apply_status_rule_to_existing(runtime.storage.state.results, runtime.status_rule)
                runtime.storage.state.network_edges = refresh_intelligence(
                    runtime.storage.state.results, runtime.storage.state.ocr_candidates,
                    elevation_is_rim=runtime.elevation_is_rim,
                    network_max_distance=runtime.network_max_distance,
                    network_bearing_tolerance=runtime.network_bearing_tolerance,
                )
                runtime.storage.save()
            else:
                runtime.storage.save()
    return _summary()["settings"]


@app.get("/api/ai/status")
def api_ai_status(refresh: bool = False) -> dict:
    return _automatic_ai_status(force=bool(refresh))


@app.post("/api/ai/windows/enable")
def api_ai_windows_enable(feature: str = "ocr") -> dict:
    feature = str(feature or "ocr").strip().lower()
    if feature not in {"ocr", "language"}:
        raise HTTPException(400, "Windows AI feature must be 'ocr' or 'language'.")
    try:
        result = ensure_windows_feature(feature)
        return {"ok": True, **result, "status": _automatic_ai_status(force=True)}
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/ai/foundry/enable")
def api_ai_foundry_enable() -> dict:
    try:
        result = enable_foundry_model(DEFAULT_FOUNDRY_VISION_MODEL)
        return {"ok": True, **result, "status": _automatic_ai_status(force=True)}
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/ollama/models")
def api_ollama_models() -> dict:
    with runtime.lock:
        base_url = runtime.ollama_base_url
        selected = runtime.ollama_model
        profile = runtime.ollama_profile
        hardware = runtime.hardware_profile
    try:
        models = list_ollama_models(base_url=base_url)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    recommended_model, reason = _recommend_ollama_model(
        models, profile=profile, selected=selected, vram_bytes=hardware.nvidia_vram_bytes
    )
    effective_model = selected if profile == "custom" else recommended_model
    if effective_model:
        selected = effective_model
        with runtime.lock:
            runtime.ollama_model = selected
    running = ollama_running_models(base_url=base_url)
    match = next((x for x in running if x.get("name") == selected), None)
    with runtime.lock:
        runtime.ollama_runtime_info = dict(match or {"model": selected, "loaded": False})
    return {
        "ok": True,
        "base_url": base_url,
        "models": models,
        "recommended": [recommended_model] if recommended_model else [],
        "recommended_model": recommended_model,
        "recommendation_reason": reason,
        "selected": selected,
        "profile": profile,
        "selected_installed": _ollama_model_is_installed(selected, models),
        "warning": _ollama_warning_for_model(selected, hardware.nvidia_vram_bytes),
        "running": running,
        "hardware": {
            "gpu": hardware.nvidia_gpu_name,
            "vram_gb": round(hardware.nvidia_vram_bytes / (1024 ** 3), 1) if hardware.nvidia_vram_bytes else 0.0,
        },
    }


@app.post("/api/ollama/warmup")
def api_ollama_warmup() -> dict:
    with runtime.lock:
        _assert_analysis_idle_locked()
        base_url = runtime.ollama_base_url
        selected = runtime.ollama_model
        profile = runtime.ollama_profile
        hardware = runtime.hardware_profile
    try:
        models = list_ollama_models(base_url=base_url)
        model, reason = _recommend_ollama_model(
            models, profile=profile, selected=selected, vram_bytes=hardware.nvidia_vram_bytes
        )
        if not _ollama_model_is_installed(model, models):
            raise HTTPException(400, f"Local vision model '{model}' is not installed. Run: ollama pull {model}")
        warm_ollama_model(model=model, base_url=base_url, timeout_seconds=180)
        info = _refresh_ollama_runtime_info(base_url, model)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"ok": True, "model": model, "reason": reason, "runtime": info}


@app.get("/api/paddle/status")
def api_paddle_status(verify: bool = False, refresh: bool = False) -> dict:
    # Normal UI refreshes use a fast environment check. The explicit Check installation
    # button requests verify=true and performs the real isolated Paddle import.
    status = paddle_status(APP_ROOT, verify_import=verify, force=refresh)
    bridge_ready = paddle_bridge_path(APP_ROOT).exists()
    engine_ready = bool(status.installed and bridge_ready)
    message = (
        status.message if bridge_ready else
        "SurveySync's PaddleOCR bridge is missing. Repair or reinstall SurveySync before using PaddleOCR."
    )
    return {
        "installed": engine_ready,
        "environment_installed": status.installed,
        "bridge_ready": bridge_ready,
        "verified": bool(status.verified and bridge_ready),
        "python_path": status.python_path,
        "message": message,
        "version": "PaddleOCR-VL 1.6",
        "device": status.device,
        "cuda_available": status.cuda_available,
        "paddle_version": status.paddle_version,
    }


@app.post("/api/paddle/install")
def api_paddle_install() -> dict:
    """Open the bundled hardware-aware PaddleOCR installer in its own Windows console."""
    _ensure_analysis_idle()
    if os.name != "nt":
        raise HTTPException(400, "The PaddleOCR installer button is available on Windows only.")
    script = APP_ROOT / "install_paddleocr_auto.bat"
    if not script.exists():
        raise HTTPException(404, "install_paddleocr_auto.bat is missing from this FieldBook Sync folder.")
    try:
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(
            ["cmd.exe", "/c", str(script)],
            cwd=str(APP_ROOT),
            creationflags=flags,
            close_fds=False,
        )
    except OSError as exc:
        raise HTTPException(500, f"Could not launch the PaddleOCR installer: {exc}") from exc
    return {
        "ok": True,
        "message": "PaddleOCR installer opened in a separate window. Complete it there, then click Check installation.",
    }


@app.get("/api/performance")
def api_performance() -> dict:
    with runtime.lock:
        return {
            "hardware": runtime.hardware_profile.as_dict(),
            "plan": build_performance_plan(runtime.performance_mode, runtime.hardware_profile).as_dict(),
            "ocr_cache": ocr_cache_stats(runtime.ocr_cache_dir),
            "interpretation_cache": interpretation_cache_stats(runtime.interpretation_cache_dir),
        }


@app.post("/api/ocr-cache/clear")
def api_clear_ocr_cache() -> dict:
    _ensure_analysis_idle()
    clear_ocr_cache(runtime.ocr_cache_dir)
    return {"ok": True, "ocr_cache": ocr_cache_stats(runtime.ocr_cache_dir)}


@app.post("/api/analysis-cache/clear")
def api_clear_analysis_cache() -> dict:
    """Clear both expensive local-AI caches; retained separately for backwards compatibility."""
    _ensure_analysis_idle()
    clear_ocr_cache(runtime.ocr_cache_dir)
    clear_interpretation_cache(runtime.interpretation_cache_dir)
    shutil.rmtree(runtime.interpretation_crop_dir, ignore_errors=True)
    runtime.interpretation_crop_dir.mkdir(parents=True, exist_ok=True)
    return {
        "ok": True,
        "ocr_cache": ocr_cache_stats(runtime.ocr_cache_dir),
        "interpretation_cache": interpretation_cache_stats(runtime.interpretation_cache_dir),
    }


@app.get("/api/gemini/models")
def api_gemini_models() -> dict:
    with runtime.lock:
        if not runtime.gemini_api_key:
            raise HTTPException(400, "Save a Gemini API key first.")
        key = runtime.gemini_api_key
    try:
        models = list_gemini_models(api_key=key)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    preferred = [m for m in models if "flash" in m.lower() and "image" not in m.lower()]
    return {"ok": True, "models": models, "recommended": preferred[:12]}


@app.post("/api/survey/point-range-summary")
async def api_point_range_summary(files: List[UploadFile] = File(...)):
    """Return crew-friendly PointID allocation recommendations from raw survey uploads."""
    summary, skipped = await _analyze_point_range_uploads(files)
    return {**summary, "ignored_point_ids": skipped}


@app.post("/api/survey/available-ranges")
async def api_available_point_ranges(files: List[UploadFile] = File(...)):
    """Generate a crew-allocation CSV from every numeric PointID in the uploads.

    The report recommends a clean open-ended thousand-series block above the
    highest occupied point and ranks useful internal gaps by capacity. Small gaps
    under 100 points are deliberately omitted from the default crew table.
    """
    summary, skipped = await _analyze_point_range_uploads(files)
    payload = crew_ranges_csv(summary).encode("utf-8-sig")
    headers = {
        "Content-Disposition": 'attachment; filename="available_point_ranges.csv"',
        "X-FBS-Numeric-Points": str(summary["used_count"]),
        "X-FBS-Ignored-PointIDs": str(skipped),
        "X-FBS-Smaller-Gaps": str(summary["smaller_gap_count"]),
    }
    return StreamingResponse(iter([payload]), media_type="text/csv; charset=utf-8", headers=headers)


async def _analyze_point_range_uploads(files: List[UploadFile], min_capacity: int = 100) -> tuple[dict, int]:
    if not files:
        raise HTTPException(400, "Choose at least one survey TXT/CSV/TSV or Trimble JOB/JXL file.")
    upload_dir = runtime.storage.root / f"point_range_upload_{uuid4().hex}"
    upload_dir.mkdir(parents=True, exist_ok=False)
    all_ids: list[int] = []
    skipped = 0
    try:
        for i, upload in enumerate(files):
            display_name = upload.filename or f"survey_{i+1}.txt"
            suffix = Path(display_name).suffix.lower()
            if suffix not in {".txt", ".csv", ".tsv", ".pnezd", ".asc", ".job", ".jxl", ".xml"}:
                raise HTTPException(400, f"{display_name}: point-range analysis supports TXT, CSV, TSV/PNEZD, Trimble JOB, and JobXML/JXL survey files.")
            path = upload_dir / f"{i:04d}_{_safe_upload_filename(display_name, 'survey.txt')}"
            await _stream_upload_to_path(upload, path)
            ids, ignored = await asyncio.to_thread(extract_numeric_point_ids_file, path)
            all_ids.extend(ids)
            skipped += ignored
        if not all_ids:
            raise HTTPException(400, "No numeric PointIDs were found in the selected survey file(s).")
        try:
            summary = crew_range_recommendations(all_ids, min_capacity=min_capacity)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return summary, skipped
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


@app.post("/api/import-survey")
async def api_import_survey(files: List[UploadFile] = File(...)) -> dict:
    _ensure_analysis_idle()
    _begin_import("survey", len(files))
    with runtime.lock, runtime.storage.lock:
        start_revision = runtime.project_revision
        profile_name = runtime.storage.state.selected_profile
    if not profile_name:
        _fail_import("Select a client code profile before importing survey files.")
        raise HTTPException(400, "Select a client code profile before importing survey files.")
    try:
        profile = get_profile(runtime.storage.profile_dir, profile_name)
    except KeyError as exc:
        _fail_import(str(exc))
        raise HTTPException(400, str(exc)) from exc
    if not any(rule.include for rule in profile.codes):
        msg = f"The {profile.name} profile has no included codes. Add the client's storm/sewer codes first."
        _fail_import(msg)
        raise HTTPException(400, msg)

    groups = []
    issues = []
    imported_files: list[ImportedFileRecord] = []
    upload_dir = runtime.storage.root / f"survey_upload_{uuid4().hex}"
    upload_dir.mkdir(parents=True, exist_ok=False)
    try:
        total_files = max(1, len(files))
        for i, upload in enumerate(files):
            display_name = upload.filename or f"survey_{i+1}.txt"
            _update_import(phase="uploading", current_file=i + 1, percent=max(1, round((i / total_files) * 45)), message=f"Uploading {display_name}…")
            path = upload_dir / f"{i:04d}_{_safe_upload_filename(display_name, 'survey.txt')}"
            size_bytes = await _stream_upload_to_path(upload, path)
            _update_import(phase="parsing", percent=45 + round(((i + 0.25) / total_files) * 45), message=f"Parsing {display_name}…")
            try:
                points, file_issues = await asyncio.to_thread(parse_survey_file, path, display_name, profile)
            except ValueError as exc:
                raise HTTPException(400, f"{display_name}: {exc}") from exc
            groups.append(points)
            issues.extend(file_issues)
            imported_files.append(ImportedFileRecord(name=display_name, kind="survey", size_bytes=size_bytes, records=len(points)))
            _update_import(phase="parsing", percent=45 + round(((i + 1) / total_files) * 45), message=f"Parsed {i+1}/{len(files)} survey file(s)")
        _update_import(phase="merging", percent=92, message="Merging survey points and checking duplicates…")
        merged, merge_issues = await asyncio.to_thread(merge_survey_points, groups)
        issues.extend(merge_issues)

        with runtime.lock, runtime.storage.lock:
            _assert_analysis_idle_locked()
            if runtime.project_revision != start_revision or runtime.storage.state.selected_profile != profile_name:
                raise HTTPException(409, "Project data changed while the survey files were being imported. Retry the import.")
            runtime.storage.state.survey_points = merged
            runtime.storage.state.survey_issues = issues
            runtime.storage.state.survey_files = imported_files
            runtime.storage.state.results = []
            runtime.storage.state.unmatched = []
            runtime.storage.state.ocr_candidates = []
            runtime.storage.state.network_edges = []
            _refresh_rod_height_busts_locked()
            _bump_project_revision_locked()
            runtime.storage.save()
        _complete_import(f"Survey import complete · {len(imported_files)} file(s) · {len(merged)} target point(s)")
        return {"ok": True, **_summary()}
    except HTTPException as exc:
        _fail_import(str(exc.detail))
        raise
    except Exception as exc:
        _fail_import(f"Survey import failed: {exc}")
        raise
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


@app.get("/api/survey/issues")
def api_survey_issues() -> list[dict]:
    with runtime.storage.lock:
        return [x.model_dump(mode="json") for x in runtime.storage.state.survey_issues]


@app.get("/api/survey/rod-height-busts")
def api_rod_height_busts() -> dict:
    with runtime.lock, runtime.storage.lock:
        _refresh_rod_height_busts_locked()
        runtime.storage.save()
        return {
            "enabled": runtime.rod_bust_enabled,
            "survey_point_count": len(runtime.storage.state.survey_points),
            "project_units": crs_unit_label(runtime.storage.state.map_project_crs),
            "count": len(runtime.storage.state.rod_height_busts),
            "settings": {
                "search_radius": runtime.rod_bust_search_radius,
                "max_slope_percent": runtime.rod_bust_max_slope_percent,
                "increment_tolerance": runtime.rod_bust_increment_tolerance,
                "min_neighbors": runtime.rod_bust_min_neighbors,
                "round_increments": [0.5, 1.0, 2.0],
            },
            "items": list(runtime.storage.state.rod_height_busts),
        }


@app.post("/api/import-fieldbook")
async def api_import_fieldbook(files: List[UploadFile] = File(...)) -> dict:
    _ensure_analysis_idle()
    _begin_import("field book", len(files))
    with runtime.lock:
        start_revision = runtime.project_revision

    request_dir = runtime.storage.root / f"fieldbook_import_tmp_{uuid4().hex}"
    upload_dir = request_dir / "uploads"
    temp_dir = request_dir / "pages"
    upload_dir.mkdir(parents=True, exist_ok=False)
    clear_fieldbook_workspace(temp_dir)
    all_pages = []
    imported_files: list[ImportedFileRecord] = []
    try:
        total_files = max(1, len(files))
        for i, upload in enumerate(files):
            display_name = upload.filename or f"fieldbook_{i+1}.pdf"
            _update_import(phase="uploading", current_file=i + 1, percent=max(1, round((i / total_files) * 30)), message=f"Uploading {display_name}…")
            src = upload_dir / f"{i:04d}_{_safe_upload_filename(display_name, 'fieldbook.pdf')}"
            size_bytes = await _stream_upload_to_path(upload, src)
            _update_import(phase="rendering", percent=30 + round((i / total_files) * 25), message=f"Rendering {display_name} into review pages…")
            pages = await asyncio.to_thread(ingest_fieldbook_path, src, display_name, temp_dir)
            selected_book_profile = str(runtime.storage.state.selected_field_note_profile or AUTO_PROFILE_ID).strip().upper()
            selected_profile_obj = None
            if selected_book_profile != AUTO_PROFILE_ID:
                try:
                    selected_profile_obj = get_field_note_profile(runtime.storage.field_note_profile_dir, selected_book_profile)
                except KeyError:
                    selected_book_profile = AUTO_PROFILE_ID
            for page in pages:
                page.field_note_profile_book = "" if selected_book_profile == AUTO_PROFILE_ID else selected_book_profile
            all_pages.extend(pages)
            imported_files.append(ImportedFileRecord(
                name=display_name, kind="fieldbook", size_bytes=size_bytes, pages=len(pages),
                field_note_profile=selected_book_profile,
                field_note_profile_version=int(selected_profile_obj.version) if selected_profile_obj else 0,
                field_note_profile_mode="auto" if selected_book_profile == AUTO_PROFILE_ID else "user",
                field_note_profile_reason=(
                    "Auto-detect during analysis using installed field-note profiles."
                    if selected_book_profile == AUTO_PROFILE_ID else f"{selected_profile_obj.name} selected at import."
                ),
                representative_page_ids=[p.page_id for p in pages[:5]],
            ))
            _update_import(phase="rendering", percent=30 + round(((i + 1) / total_files) * 25), message=f"Rendered {i+1}/{len(files)} field-book file(s) · {len(all_pages)} page(s)")

        total_pages = len(all_pages)
        plan = build_performance_plan(runtime.performance_mode, runtime.hardware_profile)
        _update_import(
            phase="enhancing", total_pages=total_pages, current_page=0, percent=56,
            message=f"Enhancing {total_pages} page(s) with {plan.enhancement_workers} CPU worker(s)…",
        )
        enhanced_dir = temp_dir / "enhanced"

        def _enhance_progress(done: int, total: int) -> None:
            _update_import(
                current_page=done,
                percent=56 + round((done / max(1, total)) * 39),
                message=f"Enhancing pages {done}/{total} · {plan.enhancement_workers} worker(s) · {plan.effective_mode.title()} performance",
            )

        await asyncio.to_thread(
            ensure_enhanced_pages_parallel, all_pages, enhanced_dir,
            max_workers=plan.enhancement_workers, progress_callback=_enhance_progress,
        )

        deduped = []
        seen_page_ids = set()
        for page in all_pages:
            if page.page_id not in seen_page_ids:
                seen_page_ids.add(page.page_id)
                deduped.append(page)
        all_pages = deduped
        _update_import(phase="saving", percent=97, message="Saving imported field book to the project…")

        with runtime.lock, runtime.storage.lock:
            _assert_analysis_idle_locked()
            if runtime.project_revision != start_revision:
                raise HTTPException(409, "Project data changed while the field book was being imported. Retry the import.")

            if runtime.storage.page_dir.exists():
                shutil.rmtree(runtime.storage.page_dir)
            temp_dir.replace(runtime.storage.page_dir)
            runtime.storage.enhanced_dir = runtime.storage.page_dir / "enhanced"
            for page in all_pages:
                page.image_path = str(runtime.storage.page_dir / Path(page.image_path).name)
                if page.enhanced_image_path:
                    page.enhanced_image_path = str(runtime.storage.enhanced_dir / Path(page.enhanced_image_path).name)

            runtime.storage.state.fieldbook_pages = all_pages
            runtime.storage.state.fieldbook_files = imported_files
            runtime.storage.state.results = []
            runtime.storage.state.unmatched = []
            runtime.storage.state.ocr_candidates = []
            runtime.storage.state.network_edges = []
            _bump_project_revision_locked()
            runtime.storage.save()
        _complete_import(f"Field-book import complete · {len(imported_files)} file(s) · {len(all_pages)} page(s)")
        return {"ok": True, **_summary()}
    except HTTPException as exc:
        _fail_import(str(exc.detail))
        raise
    except Exception as exc:
        msg = f"Could not import field book: {exc}"
        _fail_import(msg)
        raise HTTPException(400, msg) from exc
    finally:
        shutil.rmtree(request_dir, ignore_errors=True)


@app.get("/api/pages")
def api_pages() -> list[dict]:
    with runtime.storage.lock:
        return [
            {
                "page_id": p.page_id,
                "source_name": p.source_name,
                "page_number": p.page_number,
                "url": f"/api/page/{p.page_id}",
                "enhanced_url": f"/api/page/{p.page_id}?enhanced=1" if p.enhanced_image_path else None,
                "field_note_profile_book": p.field_note_profile_book or "AUTO",
                "field_note_profile_override": p.field_note_profile_override or "AUTO",
                "effective_field_note_profile": _effective_page_profile_id(p) or "AUTO",
            }
            for p in runtime.storage.state.fieldbook_pages
        ]


@app.put("/api/pages/{page_id}/field-note-profile")
def api_page_field_note_profile(page_id: str, payload: FieldNotePageOverrideIn) -> dict:
    selected = (payload.profile_id or AUTO_PROFILE_ID).strip().upper()
    if selected != AUTO_PROFILE_ID:
        try:
            get_field_note_profile(runtime.storage.field_note_profile_dir, selected)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        page = next((p for p in runtime.storage.state.fieldbook_pages if p.page_id == page_id), None)
        if page is None:
            raise HTTPException(404, "Page not found.")
        page.field_note_profile_override = "" if selected == AUTO_PROFILE_ID else selected
        runtime.storage.save()
    return {"ok": True, "page_id": page_id, "profile_id": selected}


@app.get("/api/page/{page_id}")
def api_page_image(page_id: str, enhanced: int = 0) -> FileResponse:
    with runtime.storage.lock:
        page = next((p for p in runtime.storage.state.fieldbook_pages if p.page_id == page_id), None)
    if page is None:
        raise HTTPException(404, "Page not found.")
    chosen = page.enhanced_image_path if enhanced and page.enhanced_image_path else page.image_path
    path = Path(chosen)
    if not path.exists():
        raise HTTPException(404, "Page image is missing from the local workspace.")
    media = "image/jpeg" if enhanced else page.mime_type
    return FileResponse(path, media_type=media, headers={"Cache-Control": "no-store"})





























def _refresh_intelligence_locked() -> None:
    state = runtime.storage.state
    state.network_edges = refresh_intelligence(
        state.results,
        state.ocr_candidates,
        elevation_is_rim=runtime.elevation_is_rim,
        network_max_distance=runtime.network_max_distance,
        network_bearing_tolerance=runtime.network_bearing_tolerance,
    )


def _check_worker_revision(analysis_revision: int, message: str) -> bool:
    with runtime.lock:
        if runtime.project_revision != analysis_revision:
            _mark_analysis_stale_locked(message)
            return False
        if runtime.cancel_event.is_set():
            runtime.job.cancelled = True
            runtime.job.running = False
            runtime.job.resumable = True
            runtime.job.message = "Analysis cancelled. Completed checkpoints were preserved and the job can be resumed."
            _persist_job_snapshot_locked(status="CANCELLED")
            _end_live_analysis_locked()
            return False
    return True









def _analysis_worker(
    provider: str,
    api_key: str,
    model: str,
    threshold: float,
    analysis_revision: int,
    gemini_batch_pages: int,
    local_base_url: str = "http://127.0.0.1:11434",
) -> None:
    # The sixth positional argument remains for compatibility with Beta v4/v5 tests.
    batch_pages = gemini_batch_pages
    with runtime.lock:
        runtime.worker_last_heartbeat_monotonic = time.monotonic()
        runtime.job.worker_heartbeat_at = utc_now_iso()
        _persist_job_snapshot_locked(status="RUNNING")
    try:
        with runtime.lock, runtime.storage.lock:
            if runtime.project_revision != analysis_revision:
                _mark_analysis_stale_locked("Analysis stopped because project data changed before the worker could start.")
                return
            pages = deepcopy(runtime.storage.state.fieldbook_pages)
            survey_points = deepcopy(runtime.storage.state.survey_points)
        targets = [p.point_id for p in survey_points]
        if not pages or not targets:
            raise RuntimeError("Survey structures and field-book pages are both required.")
        if not _analysis_pause_checkpoint(analysis_revision, "before engine startup"):
            return

        if provider in {"hybrid", "ollama", "windows_ocr_ollama"}:
            with runtime.lock:
                runtime.job.stage = "warming_ai"
                runtime.job.qwen_model = model
                runtime.job.qwen_state = "loading"
                runtime.job.message = f"Loading local vision model {model}…"
                _touch_worker_locked()
            warm_timeout = 600 if model == MAX_ACCURACY_OLLAMA_MODEL else 180
            try:
                warm_usage = warm_ollama_model(
                    model=model, base_url=local_base_url, timeout_seconds=warm_timeout,
                    progress_callback=_qwen_progress,
                )
                with runtime.lock:
                    _record_usage_locked("ollama", warm_usage)
                runtime_info = _refresh_ollama_runtime_info(local_base_url, model)
                with runtime.lock:
                    runtime.job.qwen_state = "ready"
                    runtime.job.qwen_cpu_percent = float(runtime_info.get("cpu_percent") or 0.0)
                    runtime.job.qwen_gpu_percent = float(runtime_info.get("gpu_percent") or 0.0)
                    split = ""
                    if runtime_info.get("loaded"):
                        split = f" · {runtime.job.qwen_cpu_percent:.0f}% CPU / {runtime.job.qwen_gpu_percent:.0f}% GPU"
                    runtime.job.message = f"{model} ready{split}. Starting analysis…"
                    _touch_worker_locked()
            except Exception as exc:
                # Preserve the qwen component so structured errors distinguish loading/service/timeout failures.
                info = classify_exception(exc, component="qwen")
                raise RuntimeError(f"{info.code}: {info.user_message}") from exc

        ocr_candidates: list[OcrCandidate] = []
        if provider == "microsoft_auto":
            all_evidence, all_unmatched, ocr_candidates = _windows_local_analysis(
                pages=pages, targets=targets, vision_provider="foundry", model=DEFAULT_FOUNDRY_VISION_MODEL,
                local_base_url=local_base_url, analysis_revision=analysis_revision,
            )
        elif provider == "windows_ocr_ollama":
            all_evidence, all_unmatched, ocr_candidates = _windows_local_analysis(
                pages=pages, targets=targets, vision_provider="ollama", model=model,
                local_base_url=local_base_url, analysis_revision=analysis_revision,
            )
        elif provider == "windows_ocr":
            all_evidence, all_unmatched, ocr_candidates = _windows_local_analysis(
                pages=pages, targets=targets, vision_provider="manual", model=model,
                local_base_url=local_base_url, analysis_revision=analysis_revision,
            )
        elif provider == "hybrid":
            all_evidence, all_unmatched, ocr_candidates = _hybrid_local_analysis(
                pages=pages, targets=targets, model=model, local_base_url=local_base_url,
                batch_pages=batch_pages, analysis_revision=analysis_revision,
            )
        elif provider == "paddle":
            pstat = paddle_status(APP_ROOT)
            if not pstat.installed:
                raise RuntimeError(pstat.message)
            with runtime.lock:
                runtime.job.stage = "ocr"
                runtime.job.message = "PaddleOCR-VL 1.6: building PointID index…"
            def _paddle_only_progress(done: int, total: int, message: str) -> None:
                with runtime.lock:
                    if runtime.project_revision == analysis_revision and not runtime.cancel_event.is_set():
                        runtime.job.current_page = max(0, min(done, total))
                        runtime.job.total_pages = total
                        runtime.job.message = message
                        _touch_worker_locked()

            def _paddle_only_should_stop() -> bool:
                if runtime.pause_event.is_set() and not _analysis_pause_checkpoint(analysis_revision, "between OCR pages"):
                    return True
                with runtime.lock:
                    return runtime.cancel_event.is_set() or runtime.project_revision != analysis_revision

            all_evidence = []
            all_unmatched = []
            paddle_seen: set[tuple] = set()

            def _paddle_only_page(page_number: int, page: FieldBookPage, payload: dict, from_cache: bool) -> None:
                if runtime.current_job_id:
                    runtime.job_store.mark_page(
                        runtime.current_job_id, page.page_id, status="COMPLETE", stage="ocr_complete", cache_hit=from_cache
                    )
                with runtime.lock:
                    _touch_worker_locked()
                cs = locate_target_ids(page, payload, targets)
                fresh: list[OcrCandidate] = []
                fresh_evidence: list[PageEvidence] = []
                for c in cs:
                    key = _live_candidate_key(c)
                    if key in paddle_seen:
                        continue
                    paddle_seen.add(key)
                    ocr_candidates.append(c)
                    fresh.append(c)
                    fresh_evidence.append(PageEvidence(
                        matched_point_id=c.point_id, source_name=c.source_name, page_number=c.page_number,
                        page_id=c.page_id, point_id_raw=c.point_id, point_id_confidence=c.confidence,
                        dipped=DipStatus.REVIEW, basis=EvidenceBasis.AMBIGUOUS, dipped_confidence=0.0,
                        evidence="Exact PointID located by PaddleOCR-VL. Semantic dip interpretation disabled in OCR-only mode.",
                        bbox=c.bbox, primary_engine="PaddleOCR-VL 1.6", ocr_text=c.raw_text,
                    ))
                if fresh:
                    all_evidence.extend(fresh_evidence)
                    _publish_live_candidates(fresh, analysis_revision)
                    # OCR-only mode is fully interpreted as soon as the exact hit is found.
                    for c, ev in zip(fresh, fresh_evidence):
                        _publish_live_interpretation(c, [ev], [], analysis_revision)

            def _paddle_only_error(page_number: int, page: FieldBookPage, error_text: str, attempts: int) -> None:
                code, message, _ = _record_job_error(
                    RuntimeError(error_text), component="paddle", page=page, retry_number=max(1, attempts)
                )
                if runtime.current_job_id:
                    runtime.job_store.mark_page(
                        runtime.current_job_id, page.page_id, status="FAILED", stage="ocr_failed",
                        error_code=code, error_message=message,
                    )
                with runtime.lock:
                    runtime.job.failed_page_count += 1
                    runtime.job.warning_count += 1
                    runtime.job.retry_count += max(0, attempts - 1)
                    runtime.job.resumable = True
                    _touch_worker_locked(f"Page {page_number}/{len(pages)} failed OCR after {attempts} attempts; continuing to the next page.")

            try:
                payloads = _run_paddle_supervised(
                    pages, APP_ROOT,
                    progress_callback=_paddle_only_progress,
                    page_callback=_paddle_only_page, page_error_callback=_paddle_only_error,
                    cancel_check=_paddle_only_should_stop,
                    cache_dir=runtime.ocr_cache_dir, performance_mode=runtime.performance_mode,
                )
            except PaddleCancelled:
                _check_worker_revision(analysis_revision, "Analysis stopped during OCR because project data changed.")
                return
            del payloads
        else:
            all_evidence, all_unmatched = _direct_vision_analysis(
                provider=provider, pages=pages, targets=targets, api_key=api_key, model=model,
                batch_pages=batch_pages, local_base_url=local_base_url, analysis_revision=analysis_revision,
            )

        if not _check_worker_revision(analysis_revision, "Analysis finished, but project data changed. Stale results were discarded."):
            return
        results = aggregate_results(survey_points, all_evidence, confidence_threshold=threshold, status_rule=runtime.status_rule)
        all_unmatched = _dedupe_unmatched(all_unmatched)
        # Derived intelligence uses only deterministic rules.
        network_edges = refresh_intelligence(
            results, ocr_candidates,
            elevation_is_rim=runtime.elevation_is_rim,
            network_max_distance=runtime.network_max_distance,
            network_bearing_tolerance=runtime.network_bearing_tolerance,
        )
        with runtime.lock, runtime.storage.lock:
            if runtime.project_revision != analysis_revision:
                _mark_analysis_stale_locked("Analysis finished, but project data changed. Stale results were discarded.")
                return
            runtime.storage.state.results = results
            runtime.storage.state.unmatched = all_unmatched
            runtime.storage.state.ocr_candidates = ocr_candidates
            runtime.storage.state.network_edges = network_edges
            runtime.storage.save()
            runtime.job.running = False
            runtime.job.complete = True
            runtime.job.current_page = len(pages)
            runtime.job.stage = "complete"
            if provider in {"microsoft_auto", "windows_ocr_ollama", "windows_ocr", "hybrid", "ollama", "paddle"}:
                runtime.job.message = (
                    f"Local analysis complete. {len(ocr_candidates)} OCR PointID location(s), "
                    f"{len(results)} structure result(s), {len(network_edges)} suggested network connection(s). "
                    "Primary Status uses the selected PointID/dip rule. No billable cloud API was required."
                )
            else:
                runtime.job.message = f"Analysis complete using {runtime.job.api_requests} {provider.title()} API request(s). Review anything marked REVIEW."
            runtime.job.resumable = False
            _persist_job_snapshot_locked(status="COMPLETE")
            _end_live_analysis_locked()
    except Exception as exc:
        ref = _error_reference("ANL")
        logger.exception("Analysis failed [%s]", ref)
        info = classify_exception(exc, component="analysis")
        runtime.job_store.record_error(
            job_id=runtime.current_job_id, component=info.component, code=info.code,
            message=info.user_message, detail=info.detail, severity=info.severity,
            recoverable=info.recoverable,
        )
        with runtime.lock:
            runtime.job.running = False
            runtime.job.complete = False
            runtime.job.stage = "error"
            runtime.job.error_code = info.code
            runtime.job.recoverable = info.recoverable
            runtime.job.resumable = bool(info.recoverable or runtime.job.current_page > 0 or runtime.job.ocr_cache_hits > 0)
            runtime.job.error = f"{info.user_message} (reference {ref})"
            runtime.job.message = (
                "Analysis stopped safely. Completed OCR/Qwen checkpoints were preserved; use Resume after correcting the problem."
                if runtime.job.resumable else
                "Analysis failed before a safe checkpoint. Existing committed project results were left unchanged."
            )
            _persist_job_snapshot_locked(status="ERROR")
            _end_live_analysis_locked()
    finally:
        runtime.analysis_heartbeat_stop.set()


@app.post("/api/analyze")
def api_analyze() -> dict:
    with runtime.lock, runtime.storage.lock:
        if runtime.job.running:
            raise HTTPException(409, "Analysis is already running.")
        if not runtime.storage.state.survey_points:
            raise HTTPException(400, "Import survey data first.")
        if not runtime.storage.state.fieldbook_pages:
            raise HTTPException(400, "Import a field book first.")

        requested_provider = runtime.provider
        provider = requested_provider
        threshold = runtime.confidence_threshold
        analysis_revision = runtime.project_revision
        preflight_warnings = _analysis_preflight_locked()
        input_signature = _project_input_signature_locked()

        if requested_provider == "auto":
            auto_status = _automatic_ai_status(force=True)
            auto_plan = auto_status.get("automatic_plan") or {}
            provider = str(auto_plan.get("effective_provider") or "manual")
            preflight_warnings.append(f"Automatic local AI selected: {auto_plan.get('label') or provider}.")

        if provider == "manual":
            results = aggregate_results(runtime.storage.state.survey_points, [], confidence_threshold=threshold, status_rule=runtime.status_rule)
            for result in results:
                result.status = DipStatus.REVIEW
                result.confidence = 0.0
                result.review_state = ReviewState.UNREVIEWED
                result.notes = "Manual Review mode: no AI was used. Locate the field-book entry and enter the observed status/pipe measurements."
            runtime.storage.state.results = results
            runtime.storage.state.unmatched = []
            runtime.storage.state.network_edges = refresh_intelligence(
                results, runtime.storage.state.ocr_candidates,
                elevation_is_rim=runtime.elevation_is_rim,
                network_max_distance=runtime.network_max_distance,
                network_bearing_tolerance=runtime.network_bearing_tolerance,
            )
            runtime.storage.save()
            manual_job_id = runtime.job_store.create_job(
                provider="manual", input_signature=input_signature, project_name=runtime.storage.state.project_name,
                pages=runtime.storage.state.fieldbook_pages, metadata={"mode": "manual", "requested_provider": requested_provider},
            )
            runtime.current_job_id = manual_job_id
            runtime.job_store.update_job(
                manual_job_id, status="COMPLETE", stage="complete", current_page=len(runtime.storage.state.fieldbook_pages),
                completed_at=utc_now_iso(), message=f"Manual Review workspace prepared for {len(results)} survey structure(s)."
            )
            runtime.job = AnalysisJob(
                job_id=manual_job_id, running=False, complete=True, provider="manual",
                total_pages=len(runtime.storage.state.fieldbook_pages),
                current_page=len(runtime.storage.state.fieldbook_pages), stage="complete", started_at=utc_now_iso(),
                message=f"Manual Review workspace prepared for {len(results)} survey structure(s). No API requests were made.",
            )
            return runtime.job.model_dump(mode="json")

        local_base_url = runtime.ollama_base_url
        api_key = ""
        model = runtime.ollama_model
        batch_pages = runtime.ollama_batch_pages
        total_requests = 0

        if provider == "microsoft_auto":
            ai_status = _automatic_ai_status(force=True)
            if not bool((ai_status.get("windows_ocr") or {}).get("ready")):
                raise HTTPException(503, "Windows AI OCR is no longer ready. Refresh AI status or choose another local provider.")
            if not bool((ai_status.get("foundry_local") or {}).get("ready")):
                raise HTTPException(503, "Microsoft Foundry Local vision model is not ready. Enable Microsoft Local AI first or let Automatic use another local fallback.")
            model = DEFAULT_FOUNDRY_VISION_MODEL
            batch_pages = 1
            total_requests = 0
        elif provider == "windows_ocr":
            ai_status = _automatic_ai_status(force=True)
            if not bool((ai_status.get("windows_ocr") or {}).get("ready")):
                raise HTTPException(503, "Windows AI OCR is not ready on this PC.")
            model = "Windows AI TextRecognizer"
            batch_pages = 1
            total_requests = 0
        elif provider in {"hybrid", "ollama", "windows_ocr_ollama"}:
            if provider == "windows_ocr_ollama":
                ai_status = _automatic_ai_status(force=True)
                if not bool((ai_status.get("windows_ocr") or {}).get("ready")):
                    raise HTTPException(503, "Windows AI OCR is not ready on this PC.")
            try:
                installed_models = list_ollama_models(base_url=local_base_url)
            except RuntimeError as exc:
                raise HTTPException(503, str(exc)) from exc
            model, model_reason = _recommend_ollama_model(
                installed_models, profile=runtime.ollama_profile, selected=model,
                vram_bytes=runtime.hardware_profile.nvidia_vram_bytes,
            )
            runtime.ollama_model = model
            if not _ollama_model_is_installed(model, installed_models):
                raise HTTPException(400, f"Qwen local model '{model}' is not installed. Run: ollama pull {model}")
            warning = _ollama_warning_for_model(model, runtime.hardware_profile.nvidia_vram_bytes)
            if warning:
                preflight_warnings.append(warning)
            if model_reason:
                preflight_warnings.append(model_reason)
            # Hybrid does not know its Qwen request count until Paddle finds candidates.
            # Starting at zero keeps the live progress denominator truthful.
            if provider == "ollama":
                total_requests = math.ceil(len(runtime.storage.state.fieldbook_pages) / batch_pages) * max(1, math.ceil(len(runtime.storage.state.survey_points) / 220))
            else:
                total_requests = 0
        elif provider == "paddle":
            ps = paddle_status(APP_ROOT)
            if not ps.installed:
                raise HTTPException(503, ps.message)
            model = "PaddleOCR-VL-1.6"
            batch_pages = 1
            total_requests = 0
        elif provider == "gemini":
            if not runtime.gemini_api_key:
                raise HTTPException(400, "Enter a Gemini API key for this session or use a local/manual mode.")
            api_key = runtime.gemini_api_key
            model = runtime.gemini_model
            batch_pages = runtime.gemini_batch_pages
            total_requests = math.ceil(len(runtime.storage.state.fieldbook_pages) / batch_pages) * max(1, math.ceil(len(runtime.storage.state.survey_points) / 220))
        elif provider == "openai":
            if not runtime.openai_api_key:
                raise HTTPException(400, "Enter an OpenAI API key for this session or use a local/manual mode.")
            api_key = runtime.openai_api_key
            model = runtime.openai_model
            batch_pages = 1
            total_requests = len(runtime.storage.state.fieldbook_pages) * max(1, math.ceil(len(runtime.storage.state.survey_points) / 220))
        elif provider == "anthropic":
            if not runtime.anthropic_api_key:
                raise HTTPException(400, "Enter an Anthropic API key for this session or use a local/manual mode.")
            api_key = runtime.anthropic_api_key
            model = runtime.anthropic_model
            batch_pages = 1
            total_requests = len(runtime.storage.state.fieldbook_pages) * max(1, math.ceil(len(runtime.storage.state.survey_points) / 220))
        else:
            raise HTTPException(400, "Unknown analysis provider.")

        runtime.cancel_event.clear()
        runtime.pause_event.clear()
        label = {
            "microsoft_auto": "Windows AI OCR + Microsoft Foundry Local",
            "windows_ocr_ollama": "Windows AI OCR + SurveySync Local Vision",
            "windows_ocr": "Windows AI OCR + Manual Review",
            "hybrid": "Hybrid Local (PaddleOCR + Qwen)", "ollama": "Qwen Local",
            "paddle": "PaddleOCR Local", "gemini": "Gemini", "openai": "OpenAI", "anthropic": "Anthropic Claude"
        }.get(provider, provider.title())
        resume_job_id = runtime.resume_job_id_pending
        runtime.resume_job_id_pending = None
        if resume_job_id:
            prior = runtime.job_store.get_job(resume_job_id)
            if not prior or prior.get("input_signature") != input_signature:
                raise HTTPException(409, "The interrupted job no longer matches the current project inputs. Start a new analysis instead.")
            runtime.job_store.resume_job(resume_job_id)
            job_id = resume_job_id
            starting_message = f"Resuming {label} analysis from persistent checkpoints…"
        else:
            job_id = runtime.job_store.create_job(
                provider=provider, input_signature=input_signature, project_name=runtime.storage.state.project_name,
                pages=runtime.storage.state.fieldbook_pages,
                metadata={
                    "app_version": CURRENT_VERSION, "performance_mode": runtime.performance_mode,
                    "model": model, "requested_provider": requested_provider, "warnings": preflight_warnings,
                },
            )
            starting_message = f"Starting {label} analysis…"
        runtime.current_job_id = job_id
        runtime.worker_last_heartbeat_monotonic = time.monotonic()
        runtime.job = AnalysisJob(
            job_id=job_id, running=True, cancelled=False, complete=False, provider=provider,
            total_pages=len(runtime.storage.state.fieldbook_pages), current_page=0,
            total_requests=total_requests, current_request=0, stage="starting", started_at=utc_now_iso(),
            message=starting_message, error=None, warning_count=len(preflight_warnings), resumable=True,
            worker_heartbeat_at=utc_now_iso(), qwen_model=model if provider in {"hybrid", "ollama", "windows_ocr_ollama"} else "",
            qwen_state="queued" if provider in {"hybrid", "ollama", "windows_ocr_ollama"} else "idle",
        )
        _persist_job_snapshot_locked(status="RUNNING")
        _begin_live_analysis_locked(runtime.storage.state.survey_points, analysis_revision)
        thread = threading.Thread(
            target=_analysis_worker,
            args=(provider, api_key, model, threshold, analysis_revision, batch_pages, local_base_url),
            daemon=True,
        )
        runtime.analysis_thread = thread
        thread.start()
        _start_analysis_heartbeat(job_id)
        _start_worker_watchdog(job_id)
    return runtime.job.model_dump(mode="json")


@app.post("/api/application/exit")
def api_application_exit() -> dict:
    # Return the HTTP response before stopping the local server so browser fallback
    # receives a clean acknowledgement instead of a connection-reset error.
    def _delayed_shutdown() -> None:
        time.sleep(0.15)
        request_application_shutdown("Exit requested from the FieldBook Sync UI.")

    t = threading.Thread(target=_delayed_shutdown, name="FBS-ui-exit", daemon=True)
    t.start()
    return {"ok": True, "message": "FieldBook Sync is closing."}


@app.get("/api/release-notes")
def api_release_notes() -> dict:
    return {"version": CURRENT_VERSION, "notes": list(RELEASE_NOTES)}


@app.post("/api/startup/ready")
def api_startup_ready() -> dict:
    """Signal that the JS shell is interactive and optional probes may begin."""
    started = start_deferred_startup_checks()
    return {
        "ok": True,
        "started": started,
        "complete": bool(runtime.deferred_startup_complete),
    }


@app.get("/api/feedback/config")
def api_feedback_config() -> dict:
    cfg = _feedback_config()
    return {"ok": True, "current_version": CURRENT_VERSION, **cfg}


@app.post("/api/feedback/open")
def api_feedback_open(payload: FeedbackOpenIn) -> dict:
    url = str(payload.url or "").strip()
    if not _valid_feedback_url(url):
        raise HTTPException(400, "Feedback links must be the shared Google Sheet, a deployed Apps Script endpoint, or the FieldBook Sync GitHub project.")
    try:
        opened = webbrowser.open(url)
    except Exception as exc:
        raise HTTPException(500, f"Could not open the feedback link: {exc}") from exc
    return {"ok": True, "opened": bool(opened), "url": url}


def _feedback_report_context() -> dict[str, Any]:
    with runtime.lock:
        state = runtime.storage.state
        job = runtime.job
        try:
            hardware = runtime.hardware_profile.as_dict()
        except Exception:
            hardware = {}
        if bool(job.running):
            job_state = "Paused" if bool(job.paused) else "Running"
        elif runtime.current_job_id:
            job_state = str(job.phase or job.message or "Idle")
        else:
            job_state = "Idle"
        return {
            "project_name": state.project_name,
            "provider": runtime.provider,
            "results_count": len(state.results),
            "survey_point_count": len(state.survey_points),
            "fieldbook_page_count": len(state.fieldbook_pages),
            "job_state": job_state,
            "current_job_id": runtime.current_job_id or "",
            "startup_metrics": dict(STARTUP_METRICS),
            "hardware": {
                "cpu_count": hardware.get("cpu_count"),
                "ram_gb": hardware.get("ram_gb"),
                "gpu_name": hardware.get("gpu_name"),
                "gpu_vram_gb": hardware.get("gpu_vram_gb"),
            },
        }


def _feedback_report_file(report_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "", str(report_id or ""))
    if not safe or safe != str(report_id or ""):
        raise ValueError("Invalid feedback report ID.")
    return runtime.storage.feedback_dir / "reports" / safe / "report.json"


def _sync_feedback_report(report_id: str, endpoint_url: str) -> None:
    """Sync a locally saved report without ever risking the local feedback record.

    The shared Apps Script endpoint is allowed to be temporarily unavailable. Transient
    HTTP 5xx/network failures are retried in the background; after the final attempt the
    report remains PENDING locally with a human-readable error and can be retried later.
    """
    path = _feedback_report_file(report_id)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Feedback report %s could not be loaded for sync: %s", report_id, exc)
        return

    delays = (0, 3, 12)
    last_error = ""
    for attempt, delay in enumerate(delays, start=1):
        if delay:
            time.sleep(delay)
        try:
            update_feedback_sync(runtime.storage.root, report_id, {
                "status": "syncing",
                "provider": "google_apps_script",
                "attempt": attempt,
                "started_utc": utc_now_iso(),
            })
            result = submit_to_tracker_endpoint(endpoint_url, report, path.parent)
            result["attempt"] = attempt
            update_feedback_sync(runtime.storage.root, report_id, result)
            logger.info("Feedback report %s synced directly to Intake as %s on attempt %s.", report_id, result.get("intake_id"), attempt)
            return
        except Exception as exc:
            last_error = str(exc)[:1000]
            logger.warning("Feedback report %s sync attempt %s/%s failed: %s", report_id, attempt, len(delays), exc)

    try:
        update_feedback_sync(runtime.storage.root, report_id, {
            "status": "pending",
            "provider": "google_apps_script",
            "attempts": len(delays),
            "last_attempt_utc": utc_now_iso(),
            "error": last_error,
            "message": "Saved locally. Shared Intake sync is pending and can be retried later.",
        })
    except Exception:
        logger.exception("Could not update feedback sync status for %s", report_id)


def _queue_feedback_sync(report_id: str, endpoint_url: str) -> bool:
    url = str(endpoint_url or "").strip()
    if not url:
        return False
    if not valid_tracker_endpoint(url):
        raise ValueError("Shared tracker sync requires a deployed HTTPS Google Apps Script /exec URL.")
    threading.Thread(
        target=_sync_feedback_report,
        args=(report_id, url),
        name=f"FBS-feedback-sync-{report_id[-6:]}",
        daemon=True,
    ).start()
    return True


@app.post("/api/feedback/report")
def api_feedback_report(
    report_type: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    reporter_name: str = Form(""),
    importance: str = Form("Normal"),
    severity: str = Form("Not applicable"),
    steps: str = Form(""),
    expected: str = Form(""),
    actual: str = Form(""),
    additional: str = Form(""),
    include_diagnostics: bool = Form(False),
    endpoint_url: str = Form(""),
    form_url: str = Form(""),  # legacy alias
    attachments: List[UploadFile] = File(default=[]),
) -> dict:
    kind = str(report_type or "").strip()
    allowed_types = {"Bug", "Feature Request", "Improvement", "Question"}
    if kind not in allowed_types:
        raise HTTPException(400, "Choose Bug, Feature Request, Improvement, or Question.")
    clean_title = str(title or "").strip()
    clean_description = str(description or "").strip()
    if len(clean_title) < 3:
        raise HTTPException(400, "Add a short title for the report.")
    if len(clean_description) < 5:
        raise HTTPException(400, "Describe the problem or idea before submitting.")
    if len(clean_title) > 180 or len(clean_description) > 12000:
        raise HTTPException(400, "The feedback title or description is too long.")

    diagnostic_path: Path | None = None
    if bool(include_diagnostics):
        with runtime.lock:
            settings = runtime.storage.load_settings()
            current_job_id = runtime.current_job_id
            hardware = runtime.hardware_profile.as_dict()
        try:
            diagnostic_path = build_diagnostic_bundle(
                output_dir=runtime.diagnostic_dir,
                app_version=CURRENT_VERSION,
                storage_root=runtime.storage.root,
                hardware=hardware,
                settings=settings,
                job_store=runtime.job_store,
                current_job_id=current_job_id,
            )
        except Exception as exc:
            logger.warning("Feedback diagnostic bundle could not be created: %s", exc)

    payload = {
        "report_type": kind,
        "reporter_name": str(reporter_name or "").strip()[:160],
        "title": clean_title,
        "description": clean_description,
        "importance": str(importance or "Normal").strip()[:40],
        "severity": str(severity or "Not applicable").strip()[:40] if kind == "Bug" else "Not applicable",
        "steps": str(steps or "").strip()[:12000],
        "expected": str(expected or "").strip()[:12000],
        "actual": str(actual or "").strip()[:12000],
        "additional": str(additional or "").strip()[:12000],
        "app_version": CURRENT_VERSION,
        "context": _feedback_report_context(),
        "sync": {"status": "queued" if str(endpoint_url or form_url or "").strip() else "local_only"},
    }
    try:
        saved = create_feedback_report(
            storage_root=runtime.storage.root,
            report=payload,
            attachments=attachments,
            diagnostic_bundle=diagnostic_path,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Could not create local feedback report")
        raise HTTPException(500, f"Could not create the feedback log: {exc}") from exc

    sync_queued = False
    sync_error = ""
    try:
        sync_queued = _queue_feedback_sync(saved["report_id"], endpoint_url or form_url)
    except Exception as exc:
        sync_error = str(exc)
        update_feedback_sync(runtime.storage.root, saved["report_id"], {
            "status": "pending",
            "error": sync_error[:1000],
        })

    return {
        "ok": True,
        "report_id": saved["report_id"],
        "created_utc": saved.get("created_utc"),
        "local_log": str(feedback_log_path(runtime.storage.root)),
        "sync_queued": sync_queued,
        "sync_error": sync_error,
        "message": "Feedback saved locally" + (" and queued directly for the shared Intake tracker." if sync_queued else "."),
    }


@app.get("/api/feedback/reports")
def api_feedback_reports(limit: int = 50) -> dict:
    reports = list_feedback_reports(runtime.storage.root, limit=limit)
    return {"ok": True, "reports": reports, "count": len(reports)}


@app.post("/api/feedback/retry")
def api_feedback_retry(payload: FeedbackRetryIn) -> dict:
    report_id = str(payload.report_id or "").strip()
    path = _feedback_report_file(report_id)
    if not path.exists():
        raise HTTPException(404, "Feedback report not found.")
    url = str(payload.endpoint_url or payload.form_url or "").strip()
    if not url:
        cfg = _feedback_config()
        url = str(cfg.get("intake_url") or cfg.get("submit_url") or "").strip()
    if not url:
        raise HTTPException(400, "The direct shared tracker endpoint is not configured yet.")
    try:
        queued = _queue_feedback_sync(report_id, url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "queued": queued, "report_id": report_id}


@app.get("/api/feedback/log")
def api_feedback_log() -> FileResponse:
    path = feedback_log_path(runtime.storage.root)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return FileResponse(path, media_type="application/x-ndjson", filename="FieldBookSync_Feedback_Log.jsonl", headers={"Cache-Control": "no-store"})


@app.post("/api/feedback/open-folder")
def api_feedback_open_folder() -> dict:
    folder = runtime.storage.feedback_dir
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(folder))
        else:
            webbrowser.open(folder.as_uri())
    except Exception as exc:
        raise HTTPException(500, f"Could not open the feedback log folder: {exc}") from exc
    return {"ok": True, "path": str(folder)}


@app.get("/api/global-mapper/status")
def api_global_mapper_status() -> dict:
    return {"ok": True, **global_mapper_status()}


@app.post("/api/global-mapper/convert")
async def api_global_mapper_convert(
    file: UploadFile = File(...),
    export_type: str = Form(...),
    extension: str = Form(...),
) -> FileResponse:
    if not find_global_mapper():
        raise HTTPException(503, "Global Mapper was not found on this PC. Native FieldBook Sync imports and exports are still available.")
    root = runtime.storage.export_dir / "GlobalMapper"
    root.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex[:10]
    original = Path(file.filename or "input.dat").name
    input_path = root / f"{token}_{original}"
    try:
        await _stream_upload_to_path(file, input_path)
        output_file = global_mapper_output_name(original, export_type, extension)
        output_path = root / f"{token}_{output_file}"
        await asyncio.to_thread(run_global_mapper_conversion, input_path, output_path, export_type=export_type)
    except (ValueError, RuntimeError) as exc:
        input_path.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception:
            logging.getLogger(__name__).warning("Recovery fallback in app; operation did not complete.", exc_info=True)
    input_path.unlink(missing_ok=True)
    return FileResponse(output_path, media_type="application/octet-stream", filename=output_file, headers={"Cache-Control": "no-store"})


@app.get("/api/update/source")
def api_update_source() -> dict:
    """Compatibility view of the single SurveySync-owned update source."""
    cfg = SurveySyncConfigStore().load()
    manifest = str(cfg.update_manifest_url or UPDATE_MANIFEST_URL)
    return {
        "provider": "surveysync",
        "manifest_url": manifest,
        "release_url": UPDATE_RELEASES_URL,
        "drive_folder_url": UPDATE_RELEASES_URL,
        "manifest_file_id": "",
        "managed_by_surveysync": True,
    }


@app.post("/api/update/source")
def api_update_source_save(payload: UpdateSourceIn) -> dict:
    """Compatibility endpoint; writes the shared SurveySync configuration."""
    manifest = (payload.manifest_url or UPDATE_MANIFEST_URL).strip()
    if not re.match(r"^https://", manifest, flags=re.IGNORECASE):
        raise HTTPException(400, "The update manifest URL must use HTTPS.")
    store = SurveySyncConfigStore()
    cfg = store.load()
    cfg.update_manifest_url = manifest
    cfg.resource_environment = cfg.environment
    store.save(cfg)
    return {
        "ok": True,
        "provider": "surveysync",
        "update_manifest_url": manifest,
        "update_release_url": UPDATE_RELEASES_URL,
        "managed_by_surveysync": True,
    }


@app.get("/api/update/check")
def api_check_for_updates() -> dict:
    """Compatibility endpoint backed by the SurveySync platform updater."""
    try:
        info = surveysync_update_check(SurveySyncConfigStore())
    except Exception as exc:
        return {
            "ok": False,
            "mode": "managed_by_surveysync",
            "current_version": CURRENT_VERSION,
            "available": False,
            "update_available": False,
            "release_url": UPDATE_RELEASES_URL,
            "message": str(exc),
        }
    available = bool(info.get("update_available"))
    return {
        "ok": True,
        "mode": "managed_by_surveysync",
        "provider": "surveysync",
        "current_version": CURRENT_VERSION,
        "latest_version": str(info.get("version") or CURRENT_VERSION),
        "available": available,
        "update_available": available,
        "required": bool(info.get("required", False)),
        "channel": str(info.get("channel") or "stable"),
        "release_notes": str(info.get("release_notes") or ""),
        "download_ready": available,
        "manifest_url": str(SurveySyncConfigStore().load().update_manifest_url or UPDATE_MANIFEST_URL),
        "release_url": UPDATE_RELEASES_URL,
        "message": "SurveySync manages updates for every module.",
    }


@app.post("/api/update/open-folder")
def api_open_update_folder() -> dict:
    try:
        webbrowser.open(UPDATE_RELEASES_URL)
    except Exception as exc:
        raise HTTPException(500, f"Could not open the SurveySync releases page: {exc}")
    return {"ok": True, "url": UPDATE_RELEASES_URL}


@app.post("/api/update/download-install")
def api_download_and_install_update(payload: UpdateInstallIn=UpdateInstallIn()) -> dict:
    """Legacy route retained as a safe proxy to the SurveySync updater."""
    if runtime.job.running:
        raise HTTPException(409, "Finish or cancel the active analysis before installing an update.")
    try:
        info = surveysync_update_check(SurveySyncConfigStore())
        if not bool(info.get("update_available")):
            return {
                "ok": True,
                "action": "up_to_date",
                "message": f"SurveySync v{CURRENT_VERSION} is up to date.",
                **info,
            }
        if not payload.confirm_install:
            return {
                "ok": True,
                "action": "confirmation_required",
                "message": f"SurveySync v{info.get('version')} is available. Confirm install when you are ready for SurveySync to close and Setup to open.",
                **info,
            }
        staged = surveysync_update_stage(SurveySyncConfigStore())
    except Exception as exc:
        try:
            record_diagnostic_error(
                SurveySyncConfigStore().root,
                component="updater",
                code="UPD-LEGACY-001",
                message=str(exc),
                recoverable=True,
                context={"route": "/api/update/download-install"},
            )
        except Exception:
            logging.getLogger(__name__).warning("Recovery fallback in app; operation did not complete.", exc_info=True)
        raise HTTPException(400, str(exc))

    def _delayed_update_shutdown() -> None:
        time.sleep(0.35)
        request_application_shutdown(f"Updating SurveySync to v{staged.get('version', '')}.")

    threading.Thread(target=_delayed_update_shutdown, name="SurveySync-update-exit", daemon=True).start()
    return {
        "ok": True,
        "message": f"SurveySync v{staged['version']} is downloaded and verified. SurveySync is closing so Setup can install the update.",
        "handoff": "surveysync_native_launcher",
        **staged,
    }


@app.post("/api/pause-analysis")
def api_pause_analysis() -> dict:
    with runtime.lock:
        if not runtime.job.running:
            raise HTTPException(409, "No analysis is running.")
        if runtime.job.paused or runtime.pause_event.is_set():
            return runtime.job.model_dump(mode="json")
        runtime.pause_event.set()
        runtime.job.pause_requested = True
        runtime.job.message = "Pause requested — finishing the current OCR/AI operation and stopping at the next safe checkpoint…"
        _persist_job_snapshot_locked(status="PAUSING")
        return runtime.job.model_dump(mode="json")


@app.post("/api/resume-paused-analysis")
def api_resume_paused_analysis() -> dict:
    with runtime.lock:
        if not runtime.job.running:
            raise HTTPException(409, "No analysis is running.")
        if not runtime.pause_event.is_set() and not runtime.job.paused:
            return runtime.job.model_dump(mode="json")
        runtime.pause_event.clear()
        runtime.job.pause_requested = False
        runtime.job.message = "Resume requested…"
        return runtime.job.model_dump(mode="json")


@app.post("/api/cancel-analysis")
def api_cancel_analysis() -> dict:
    with runtime.lock:
        if runtime.job.running:
            runtime.cancel_event.set()
            runtime.pause_event.clear()
            runtime.job.paused = False
            runtime.job.pause_requested = False
            runtime.job.message = "Cancelling analysis and stopping the active OCR/AI worker at a safe checkpoint…"
            runtime.job.resumable = True
            _persist_job_snapshot_locked(status="CANCELLING")
    return runtime.job.model_dump(mode="json")


@app.get("/api/job")
def api_job() -> dict:
    with runtime.lock:
        return runtime.job.model_dump(mode="json")


@app.post("/api/resume-analysis")
def api_resume_analysis() -> dict:
    with runtime.lock, runtime.storage.lock:
        if runtime.job.running:
            raise HTTPException(409, "Analysis is already running.")
        if not runtime.storage.state.survey_points or not runtime.storage.state.fieldbook_pages:
            raise HTTPException(400, "Import the survey and field book before resuming analysis.")
        signature = _project_input_signature_locked()
        resumable = runtime.job_store.latest_resumable(signature)
        if not resumable:
            raise HTTPException(404, "No interrupted/cancelled job matches the current project inputs.")
        if resumable.get("provider") != runtime.provider:
            raise HTTPException(
                409,
                f"The resumable job used {resumable.get('provider')}; select that provider or start a new analysis.",
            )
        runtime.resume_job_id_pending = str(resumable["job_id"])
    return api_analyze()


@app.get("/api/job-history")
def api_job_history(limit: int = 25) -> dict:
    return {"jobs": runtime.job_store.list_jobs(limit=limit)}


@app.get("/api/error-history")
def api_error_history(job_id: str | None = None, limit: int = 100) -> dict:
    return {"errors": runtime.job_store.list_errors(job_id=job_id, limit=limit)}


@app.get("/api/job/{job_id}")
def api_job_detail(job_id: str) -> dict:
    item = runtime.job_store.get_job(job_id)
    if not item:
        raise HTTPException(404, "Analysis job not found.")
    return item


@app.post("/api/diagnostics/export")
def api_export_diagnostics() -> FileResponse:
    with runtime.lock:
        settings = runtime.storage.load_settings()
        current_job_id = runtime.current_job_id
        hardware = runtime.hardware_profile.as_dict()
    try:
        path = build_diagnostic_bundle(
            output_dir=runtime.diagnostic_dir,
            app_version=CURRENT_VERSION,
            storage_root=runtime.storage.root,
            hardware=hardware,
            settings=settings,
            job_store=runtime.job_store,
            current_job_id=current_job_id,
        )
    except Exception as exc:
        code, message, _ = _record_job_error(exc, component="diagnostics")
        raise HTTPException(500, f"{code}: {message}") from exc
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.get("/api/validation/status")
def api_validation_status() -> dict:
    if not runtime.validation_baseline_path.exists():
        return {"exists": False}
    try:
        baseline = load_baseline(runtime.validation_baseline_path)
        return {
            "exists": True,
            "name": baseline.get("name"),
            "project_name": baseline.get("project_name"),
            "app_version": baseline.get("app_version"),
            "record_count": len(baseline.get("records") or []),
        }
    except Exception as exc:
        return {"exists": True, "corrupt": True, "error": str(exc)}


@app.post("/api/validation/baseline")
def api_validation_baseline(body: ValidationNameIn) -> dict:
    with runtime.lock, runtime.storage.lock:
        results = deepcopy(runtime.storage.state.results)
        project_name = runtime.storage.state.project_name
    if not results:
        raise HTTPException(400, "Complete an analysis and review its results before creating a validation baseline.")
    unresolved = [r.point_id for r in results if r.review_state == ReviewState.UNREVIEWED or r.qa_needs_review]
    if unresolved:
        raise HTTPException(
            409,
            f"Review all uncertain structures before freezing ground truth. {len(unresolved)} result(s) are still unreviewed/flagged.",
        )
    payload = save_baseline(
        runtime.validation_baseline_path,
        name=(body.name or "Reviewed Ground Truth").strip()[:120],
        project_name=project_name,
        results=results,
        app_version=CURRENT_VERSION,
    )
    return {"ok": True, "name": payload["name"], "record_count": len(payload["records"])}


@app.post("/api/validation/compare")
def api_validation_compare() -> dict:
    if not runtime.validation_baseline_path.exists():
        raise HTTPException(404, "Create a reviewed validation baseline first.")
    baseline = load_baseline(runtime.validation_baseline_path)
    with runtime.lock, runtime.storage.lock:
        results = deepcopy(runtime.storage.state.results)
        project_name = runtime.storage.state.project_name
    metrics = compare_to_baseline(results, baseline)
    run_id = runtime.job_store.record_validation_run(
        app_version=CURRENT_VERSION, project_name=project_name,
        baseline_name=str(baseline.get("name") or "Baseline"), metrics=metrics,
    )
    return {"run_id": run_id, "metrics": metrics}


def _record_history_locked(
    action: str, point_id: str | None = None, before: dict | None = None,
    after: dict | None = None, detail: str = "",
    related_before: dict[str, dict] | None = None,
    related_after: dict[str, dict] | None = None,
) -> None:
    state = runtime.storage.state
    state.history.append(HistoryEvent(
        event_id=uuid4().hex,
        action=action,
        point_id=point_id,
        before=before,
        after=after,
        detail=detail,
        related_before=related_before or {},
        related_after=related_after or {},
    ))
    # A new edit invalidates the redo branch.
    state.redo_stack = []
    if len(state.history) > 500:
        state.history = state.history[-500:]


def _capture_verified_example_locked(result) -> None:
    if not result.evidence_records:
        return
    ev = result.evidence_records[0]
    if not ev.bbox:
        return
    page = next((p for p in runtime.storage.state.fieldbook_pages if p.page_id == ev.page_id), None)
    if not page:
        return
    src = page.enhanced_image_path if page.enhanced_image_path and Path(page.enhanced_image_path).exists() else page.image_path
    dst = runtime.storage.examples_dir / f"{result.point_id}_{ev.page_id}_{uuid4().hex[:8]}.jpg"
    try:
        crop = crop_normalized_bbox(src, ev.bbox, dst, padding=0.2)
    except Exception:
        crop = None
    if crop:
        runtime.storage.state.verified_examples.append(VerifiedExample(
            example_id=uuid4().hex,
            point_id=result.point_id,
            page_id=ev.page_id,
            crop_path=str(crop),
            accepted_result=result.model_dump(mode="json"),
        ))


@app.get("/api/results")
def api_results() -> list[dict]:
    with runtime.lock:
        if runtime.job.running and runtime.live_active:
            return [_live_result_dict_locked(r) for r in runtime.live_results]
    with runtime.storage.lock:
        return [r.model_dump(mode="json") for r in runtime.storage.state.results]


def _result_has_user_or_fieldbook_content(result: ResultRecord) -> bool:
    """Return True when reassignment would overwrite meaningful target work."""
    return bool(
        result.evidence_records
        or result.pipes
        or result.manually_overridden
        or result.review_state != ReviewState.UNREVIEWED
        or result.point_id_reassigned_from
        or result.point_id_reassigned_to
    )


def _baseline_result_for_survey_point_locked(point_id: str) -> ResultRecord:
    point = next((p for p in runtime.storage.state.survey_points if p.point_id == point_id), None)
    if point is None:
        raise HTTPException(400, f"PointID {point_id!r} is not in the imported survey points.")
    return aggregate_results(
        [point], [], confidence_threshold=runtime.confidence_threshold, status_rule=runtime.status_rule
    )[0]


def _reassign_result_locked(source_point_id: str, target_point_id: str, reason: str = "") -> tuple[ResultRecord, dict[str, dict]]:
    """Move reviewed interpretation to another imported survey PointID without losing raw evidence.

    The source and target survey identities (coordinates/code/category) never move. Only
    derived FieldBook interpretation is transferred. The original association is retained
    in the atomic history event and in the target's reassignment provenance fields.
    """
    source = next((r for r in runtime.storage.state.results if r.point_id == source_point_id), None)
    if source is None:
        raise HTTPException(404, "Result not found.")
    if target_point_id == source_point_id:
        return source, {}

    # Only real imported survey points may become authoritative from normal review.
    _baseline_result_for_survey_point_locked(target_point_id)
    target = next((r for r in runtime.storage.state.results if r.point_id == target_point_id), None)
    if target is None:
        target = _baseline_result_for_survey_point_locked(target_point_id)
        runtime.storage.state.results.append(target)
    if _result_has_user_or_fieldbook_content(target):
        raise HTTPException(409, f"Point {target_point_id} already has field-book evidence or reviewed edits. Resolve that record before reassigning another result to it.")

    related_before = {
        source_point_id: source.model_dump(mode="json"),
        target_point_id: target.model_dump(mode="json"),
    }
    transfer = source.model_copy(deep=True)

    # Keep the target's authoritative survey coordinates/code/category while moving only
    # the derived interpretation and its evidence.
    target.status = transfer.status
    target.dip_status = transfer.dip_status
    target.qa_needs_review = transfer.qa_needs_review
    target.confidence = transfer.confidence
    target.review_state = ReviewState.EDITED
    target.pipes = deepcopy(transfer.pipes)
    target.evidence_records = deepcopy(transfer.evidence_records)
    target.notes = transfer.notes
    target.manually_overridden = True
    target.smart_confidence = transfer.smart_confidence
    target.confidence_factors = list(transfer.confidence_factors)
    target.qc_flags = list(transfer.qc_flags)
    target.point_id_reassigned_from = source_point_id
    target.point_id_reassigned_to = None
    target.point_id_reassignment_note = (reason or f"Reviewer reassigned field-book evidence from Point {source_point_id} to Point {target_point_id}.").strip()
    for ev in target.evidence_records:
        # Preserve point_id_raw/OCR text as the immutable observation while changing the
        # reviewed association used by downstream survey logic.
        ev.matched_point_id = target_point_id
        if "REVIEWER_POINTID_REASSIGNMENT" not in ev.validation_flags:
            ev.validation_flags.append("REVIEWER_POINTID_REASSIGNMENT")
        if "Reviewer" not in ev.evidence_sources:
            ev.evidence_sources.append("Reviewer")

    source_reset = _baseline_result_for_survey_point_locked(source_point_id)
    source_reset.review_state = ReviewState.EDITED
    source_reset.manually_overridden = True
    source_reset.point_id_reassigned_to = target_point_id
    source_reset.point_id_reassignment_note = f"Field-book evidence was reassigned by reviewer to Point {target_point_id}. The original automated assignment is retained in audit history."
    source_reset.notes = source_reset.point_id_reassignment_note
    for i, item in enumerate(runtime.storage.state.results):
        if item.point_id == source_point_id:
            runtime.storage.state.results[i] = source_reset
            break
    return target, related_before


@app.put("/api/results/{point_id}")
def api_edit_result(point_id: str, payload: ResultEditIn) -> dict:
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        result = next((r for r in runtime.storage.state.results if r.point_id == point_id), None)
        if result is None:
            raise HTTPException(404, "Result not found.")
        requested_point_id = (payload.point_id or point_id).strip()
        if not requested_point_id:
            raise HTTPException(400, "Survey PointID is required.")
        if any(p.dip is not None for p in payload.pipes) and payload.dip_status == DipStatus.NOT_FOUND:
            raise HTTPException(400, "Dip detail cannot be NOT FOUND when a measured pipe dip is entered. Choose YES or REVIEW.")

        related_before: dict[str, dict] = {}
        if requested_point_id != point_id:
            result, related_before = _reassign_result_locked(point_id, requested_point_id, payload.reassignment_reason)
        before = result.model_dump(mode="json") if not related_before else related_before[requested_point_id]

        result.status = payload.status
        result.dip_status = payload.dip_status
        result.qa_needs_review = payload.dip_status == DipStatus.REVIEW
        result.review_state = payload.review_state
        if payload.confidence is not None:
            result.confidence = payload.confidence
        result.notes = payload.notes
        result.pipes = payload.pipes
        result.manually_overridden = True
        _refresh_intelligence_locked()
        after = result.model_dump(mode="json")

        if related_before:
            related_after = {
                pid: next(r for r in runtime.storage.state.results if r.point_id == pid).model_dump(mode="json")
                for pid in related_before
            }
            _record_history_locked(
                "Reassign PointID", requested_point_id, before, after,
                f"Reviewer reassigned field-book evidence from Point {point_id} to Point {requested_point_id}.",
                related_before=related_before, related_after=related_after,
            )
        else:
            _record_history_locked("Edit result", point_id, before, after, "Manual result/pipe edit")
        runtime.storage.save()
        return result.model_dump(mode="json")


@app.post("/api/results/{point_id}/accept")
def api_accept_result(point_id: str) -> dict:
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        result = next((r for r in runtime.storage.state.results if r.point_id == point_id), None)
        if result is None:
            raise HTTPException(404, "Result not found.")
        before = result.model_dump(mode="json")
        result.review_state = ReviewState.ACCEPTED
        _capture_verified_example_locked(result)
        _refresh_intelligence_locked()
        after = result.model_dump(mode="json")
        _record_history_locked("Accept result", point_id, before, after, "Verified by operator")
        runtime.storage.save()
        return result.model_dump(mode="json")


@app.get("/api/unmatched")
def api_unmatched() -> list[dict]:
    with runtime.lock:
        if runtime.job.running and runtime.live_active:
            return [u.model_dump(mode="json") for u in runtime.live_unmatched]
    with runtime.storage.lock:
        return [u.model_dump(mode="json") for u in runtime.storage.state.unmatched]


@app.get("/api/ocr/candidates")
def api_ocr_candidates(point_id: Optional[str] = None) -> list[dict]:
    with runtime.lock:
        if runtime.job.running and runtime.live_active:
            items = runtime.live_candidates
            if point_id:
                items = [c for c in items if c.point_id == point_id]
            return [c.model_dump(mode="json") for c in items]
    with runtime.storage.lock:
        items = runtime.storage.state.ocr_candidates
        if point_id:
            items = [c for c in items if c.point_id == point_id]
        return [c.model_dump(mode="json") for c in items]













































@app.get("/api/search")
def api_search(q: str) -> list[dict]:
    with runtime.storage.lock:
        return search_project(runtime.storage.state, q)


@app.get("/api/history")
def api_history() -> dict:
    with runtime.storage.lock:
        return {
            "history": [h.model_dump(mode="json") for h in reversed(runtime.storage.state.history[-100:])],
            "can_undo": bool(runtime.storage.state.history),
            "can_redo": bool(runtime.storage.state.redo_stack),
        }


def _apply_history_snapshot_locked(point_id: str | None, snapshot: dict | None) -> None:
    if not point_id or not snapshot:
        return
    restored = ResultRecord.model_validate(snapshot)
    for i, r in enumerate(runtime.storage.state.results):
        if r.point_id == point_id:
            runtime.storage.state.results[i] = restored
            return
    runtime.storage.state.results.append(restored)


def _apply_history_event_locked(event: HistoryEvent, *, before: bool) -> None:
    related = event.related_before if before else event.related_after
    if related:
        for pid, snapshot in related.items():
            _apply_history_snapshot_locked(pid, snapshot)
        return
    _apply_history_snapshot_locked(event.point_id, event.before if before else event.after)


@app.post("/api/undo")
def api_undo() -> dict:
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        if not runtime.storage.state.history:
            raise HTTPException(409, "Nothing to undo.")
        event = runtime.storage.state.history.pop()
        _apply_history_event_locked(event, before=True)
        runtime.storage.state.redo_stack.append(event)
        _refresh_intelligence_locked()
        runtime.storage.save()
        return {"ok": True, "event": event.model_dump(mode="json"), **_summary()}


@app.post("/api/redo")
def api_redo() -> dict:
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        if not runtime.storage.state.redo_stack:
            raise HTTPException(409, "Nothing to redo.")
        event = runtime.storage.state.redo_stack.pop()
        _apply_history_event_locked(event, before=False)
        runtime.storage.state.history.append(event)
        _refresh_intelligence_locked()
        runtime.storage.save()
        return {"ok": True, "event": event.model_dump(mode="json"), **_summary()}


@app.post("/api/project/name")
def api_project_name(payload: ProjectNameIn) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Project name is required.")
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        runtime.storage.state.project_name = name[:120]
        runtime.storage.save()
    return _summary()


def _selected_profile_or_none() -> CodeProfile | None:
    with runtime.storage.lock:
        name = runtime.storage.state.selected_profile
    if not name:
        return None
    try:
        return get_profile(runtime.storage.profile_dir, name)
    except Exception:
        return None


@app.get("/api/projects")
def api_projects() -> list[dict]:
    items = []
    for p in sorted(runtime.storage.project_dir.glob("*.fbs"), key=lambda x: x.stat().st_mtime, reverse=True):
        items.append({
            "name": p.stem, "filename": p.name, "path": str(p),
            "modified_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
            "size": p.stat().st_size,
        })
    return items[:30]


@app.post("/api/project/save")
def api_project_save() -> dict:
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        runtime.storage.save()
        state_copy = deepcopy(runtime.storage.state)
    path = create_project_bundle(state_copy, runtime.storage.page_dir, runtime.storage.project_dir, _selected_profile_or_none())
    return {"ok": True, "filename": path.name, "path": str(path), "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")}


@app.post("/api/project/save-as")
def api_project_save_as(payload: ProjectSaveAsIn) -> dict:
    target = Path(str(payload.path or "")).expanduser()
    if not str(target).strip():
        raise HTTPException(400, "Choose where to save the FieldBook Sync project.")
    if target.suffix.lower() != ".fbs":
        target = target.with_suffix(".fbs")
    try:
        target = target.resolve()
    except Exception as exc:
        raise HTTPException(400, f"Save path is invalid: {exc}") from exc
    if target.exists() and target.is_dir():
        raise HTTPException(400, "Choose a file name, not a folder.")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise HTTPException(400, f"Could not create the destination folder: {exc}") from exc
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        runtime.storage.save()
        state_copy = deepcopy(runtime.storage.state)
        profile = _selected_profile_or_none()
    temp_target = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        with tempfile.TemporaryDirectory(dir=str(runtime.storage.export_dir)) as tmp_dir:
            bundle = create_project_bundle(state_copy, runtime.storage.page_dir, Path(tmp_dir), profile)
            shutil.copy2(bundle, temp_target)
        if not zipfile.is_zipfile(temp_target):
            raise RuntimeError("Prepared project bundle failed ZIP validation.")
        os.replace(temp_target, target)
    except Exception as exc:
        temp_target.unlink(missing_ok=True)
        try:
            record_diagnostic_error(
                SurveySyncConfigStore().root,
                component="project_save_as",
                code="FBS-SAVEAS-001",
                message=str(exc),
                recoverable=True,
                context={"target": str(target)},
            )
        except Exception:
            logging.getLogger(__name__).warning("Recovery fallback in app; operation did not complete.", exc_info=True)
        raise HTTPException(500, f"Could not save the project file: {exc}") from exc
    return {
        "ok": True,
        "filename": target.name,
        "path": str(target),
        "modified_at": datetime.fromtimestamp(target.stat().st_mtime).isoformat(timespec="seconds"),
        "atomic": True,
    }


@app.get("/api/project/download")
def api_project_download() -> FileResponse:
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        runtime.storage.save()
        state_copy = deepcopy(runtime.storage.state)
    path = create_project_bundle(state_copy, runtime.storage.page_dir, runtime.storage.export_dir, _selected_profile_or_none())
    return FileResponse(path, media_type="application/octet-stream", filename=path.name, headers={"Cache-Control": "no-store"})


def _stage_project_bundle(bundle: Path) -> tuple[Path, AppState, CodeProfile | None]:
    """Expand/validate a project bundle without holding application state locks."""
    stage_root = runtime.storage.root / f"project_stage_{uuid4().hex}"
    pages = stage_root / "pages"
    examples = stage_root / "examples"
    pages.mkdir(parents=True, exist_ok=False)
    examples.mkdir(parents=True, exist_ok=True)
    try:
        state, profile = load_project_bundle(bundle, pages, examples)
        return stage_root, state, profile
    except Exception:
        shutil.rmtree(stage_root, ignore_errors=True)
        raise


def _commit_staged_project(stage_root: Path, state: AppState, profile: CodeProfile | None, expected_revision: int | None = None) -> None:
    """Commit an already validated project with a short write-lock window."""
    stage_pages = stage_root / "pages"
    stage_examples = stage_root / "examples"
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        if expected_revision is not None and runtime.project_revision != expected_revision:
            raise HTTPException(409, "Project data changed while the project file was being prepared. Retry Open Project.")
        existing_batch = runtime.storage.state.batch_jobs
        if runtime.storage.page_dir.exists():
            shutil.rmtree(runtime.storage.page_dir)
        stage_pages.replace(runtime.storage.page_dir)
        if runtime.storage.examples_dir.exists():
            shutil.rmtree(runtime.storage.examples_dir)
        stage_examples.replace(runtime.storage.examples_dir)
        runtime.storage.enhanced_dir = runtime.storage.page_dir / "enhanced"
        runtime.storage.enhanced_dir.mkdir(parents=True, exist_ok=True)
        for page in state.fieldbook_pages:
            page.image_path = str(runtime.storage.page_dir / Path(page.image_path).name)
            if page.enhanced_image_path:
                page.enhanced_image_path = str(runtime.storage.page_dir / Path(page.enhanced_image_path).name)
        for ex in state.verified_examples:
            if ex.crop_path:
                ex.crop_path = str(runtime.storage.examples_dir / Path(ex.crop_path).name)
        state.batch_jobs = existing_batch
        runtime.storage.state = state
        if profile:
            try:
                save_profile(runtime.storage.profile_dir, profile)
            except Exception:
                logger.warning("Embedded project profile could not be saved; project state was still loaded", exc_info=True)
        _bump_project_revision_locked()
        runtime.storage.save()


@app.post("/api/project/import")
async def api_project_import(file: UploadFile = File(...)) -> dict:
    _ensure_analysis_idle()
    if not (file.filename or "").lower().endswith(".fbs"):
        raise HTTPException(400, "Choose a FieldBook Sync .fbs project file.")
    with runtime.lock:
        start_revision = runtime.project_revision
    temp = runtime.storage.root / f"project_upload_{uuid4().hex}.fbs"
    await _stream_upload_to_path(file, temp)
    stage_root = None
    try:
        try:
            stage_root, state, profile = _stage_project_bundle(temp)
        except Exception as exc:
            raise HTTPException(400, f"Could not open project: {exc}") from exc
        _commit_staged_project(stage_root, state, profile, expected_revision=start_revision)
    finally:
        temp.unlink(missing_ok=True)
        if stage_root:
            shutil.rmtree(stage_root, ignore_errors=True)
    return {"ok": True, **_summary()}


def load_project_path_into_runtime(path: Path) -> dict:
    """Load a trusted local .fbs path into the runtime.

    Used by the desktop shell for Windows .fbs file association and by internal project-open
    workflows. The bundle parser still validates ZIP paths and pydantic project structure.
    """
    path = Path(path).expanduser().resolve()
    if not path.exists() or path.suffix.lower() != ".fbs":
        raise ValueError("Choose an existing FieldBook Sync .fbs project file.")
    with runtime.lock:
        _assert_analysis_idle_locked()
        start_revision = runtime.project_revision
    stage_root = None
    try:
        stage_root, state, profile = _stage_project_bundle(path)
        _commit_staged_project(stage_root, state, profile, expected_revision=start_revision)
    finally:
        if stage_root:
            shutil.rmtree(stage_root, ignore_errors=True)
    return _summary()


@app.post("/api/project/load/{filename}")
def api_project_load(filename: str) -> dict:
    safe = Path(filename).name
    path = runtime.storage.project_dir / safe
    if not path.exists() or path.suffix.lower() != ".fbs":
        raise HTTPException(404, "Saved project not found.")
    try:
        summary = load_project_path_into_runtime(path)
    except Exception as exc:
        raise HTTPException(400, f"Could not open project: {exc}") from exc
    return {"ok": True, **summary}


@app.post("/api/recovery/restore")
def api_recovery_restore() -> dict:
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        if not runtime.storage.recovery_path.exists():
            raise HTTPException(404, "No recovery snapshot is available.")
        try:
            recovered = runtime.storage.state.__class__.model_validate_json(runtime.storage.recovery_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(400, f"Recovery snapshot could not be read: {exc}") from exc
        # Page images are retained in the local workspace and their paths remain valid.
        recovered.batch_jobs = runtime.storage.state.batch_jobs
        runtime.storage.state = recovered
        _bump_project_revision_locked()
        runtime.storage.save()
    return {"ok": True, **_summary()}


@app.post("/api/results/{point_id}/second-opinion")
def api_second_opinion(point_id: str) -> dict:
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        if not runtime.gemini_api_key:
            raise HTTPException(400, "Add a Gemini API key in Analysis Engine before requesting a cloud second opinion.")
        result = next((r for r in runtime.storage.state.results if r.point_id == point_id), None)
        if not result:
            raise HTTPException(404, "Result not found.")
        page_ids = [e.page_id for e in result.evidence_records]
        page = next((p for p in runtime.storage.state.fieldbook_pages if p.page_id in page_ids), None)
        if page is None:
            # Fall back to OCR index.
            cand = next((c for c in runtime.storage.state.ocr_candidates if c.point_id == point_id), None)
            page = next((p for p in runtime.storage.state.fieldbook_pages if cand and p.page_id == cand.page_id), None)
        if page is None:
            raise HTTPException(400, "No field-book page is linked to this point.")
        key = runtime.gemini_api_key
        model = runtime.gemini_model
        before = result.model_dump(mode="json")
    try:
        evidence, unmatched, usage = read_pages_gemini(pages=[page], target_point_ids=[point_id], api_key=key, model=model, profile_context=_field_note_profile_context())
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    with runtime.lock, runtime.storage.lock:
        result = next((r for r in runtime.storage.state.results if r.point_id == point_id), None)
        if result is None:
            raise HTTPException(409, "Result changed while the second opinion was running.")
        _record_usage_locked("gemini", usage)
        if evidence:
            gem = evidence[0]
            existing_sig = (result.status.value, [(p.dip, p.diameter_in, p.material, p.azimuth_deg) for p in result.pipes])
            gem_sig = (gem.dipped.value, [(p.dip, p.diameter_in, p.material, p.azimuth_deg) for p in gem.pipes])
            agree = existing_sig == gem_sig or (result.status == gem.dipped and (not result.pipes or not gem.pipes))
            gem.primary_engine = f"Gemini second opinion ({model})"
            gem.model_agreement = agree
            result.evidence_records.append(gem)
            for ev in result.evidence_records:
                if ev is not gem:
                    ev.secondary_engine = f"Gemini ({model})"
                    ev.model_agreement = agree
            if not agree:
                result.status = DipStatus.REVIEW
                result.notes = (result.notes + " Gemini second opinion disagreed with the existing interpretation; review required.").strip()
        else:
            agree = False
            result.status = DipStatus.REVIEW
            result.notes = (result.notes + " Gemini second opinion could not confirm the existing interpretation.").strip()
        _refresh_intelligence_locked()
        after = result.model_dump(mode="json")
        _record_history_locked("Gemini second opinion", point_id, before, after, f"Agreement: {agree}")
        runtime.storage.save()
        return {"ok": True, "agreement": agree, "result": result.model_dump(mode="json"), "unmatched": [u.model_dump(mode="json") for u in unmatched]}











@app.get("/api/batch")
def api_batch() -> list[dict]:
    with runtime.storage.lock:
        return [j.model_dump(mode="json") for j in runtime.storage.state.batch_jobs]


@app.post("/api/batch/add-current")
def api_batch_add_current(payload: BatchAddIn) -> dict:
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        if not runtime.storage.state.survey_points or not runtime.storage.state.fieldbook_pages:
            raise HTTPException(400, "Load a complete project before adding it to the batch queue.")
        job_id = uuid4().hex
        job_dir = runtime.storage.batch_dir / job_id
        state_copy = deepcopy(runtime.storage.state)
        state_copy.batch_jobs = []
        name = (payload.name or state_copy.project_name or f"Batch {job_id[:8]}").strip()
    input_bundle = create_project_bundle(state_copy, runtime.storage.page_dir, job_dir, _selected_profile_or_none())
    with runtime.lock, runtime.storage.lock:
        job = BatchJob(job_id=job_id, name=name, profile_name=state_copy.selected_profile, provider=runtime.provider, project_file=str(input_bundle))
        runtime.storage.state.batch_jobs.append(job)
        runtime.storage.save()
        return job.model_dump(mode="json")


@app.post("/api/batch/import-projects")
async def api_batch_import_projects(files: List[UploadFile] = File(...)) -> dict:
    _ensure_analysis_idle()
    added = []
    for upload in files:
        if not (upload.filename or "").lower().endswith(".fbs"):
            continue
        job_id = uuid4().hex
        job_dir = runtime.storage.batch_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / "input.fbs"
        await _stream_upload_to_path(upload, path)
        job = BatchJob(job_id=job_id, name=Path(upload.filename or "Project").stem, provider=runtime.provider, project_file=str(path))
        added.append(job)
    with runtime.lock, runtime.storage.lock:
        runtime.storage.state.batch_jobs.extend(added)
        runtime.storage.save()
    return {"ok": True, "added": [j.model_dump(mode="json") for j in added]}


@app.post("/api/batch/import-raw")
async def api_batch_import_raw(
    survey_files: List[UploadFile] = File(...),
    fieldbook_files: List[UploadFile] = File(...),
    profile_name: str = Form(""),
) -> dict:
    """Pair raw survey files with raw field books and create self-contained queued projects.

    Filename pairing is deliberately conservative. Ambiguous/unmatched files are reported and
    never silently assigned to a job. Renaming files to share a job/order identifier is the
    recommended way to resolve an ambiguous set.
    """
    _ensure_analysis_idle()
    selected = (profile_name or "").strip()
    if not selected:
        with runtime.storage.lock:
            selected = runtime.storage.state.selected_profile or ""
    if not selected:
        raise HTTPException(400, "Select a client code profile before queueing raw jobs.")
    try:
        profile = get_profile(runtime.storage.profile_dir, selected)
    except Exception as exc:
        raise HTTPException(400, f"Profile '{selected}' was not found.") from exc

    request_upload_dir = runtime.storage.root / f"batch_raw_upload_{uuid4().hex}"
    request_upload_dir.mkdir(parents=True, exist_ok=False)
    survey_payloads: list[tuple[str, Path]] = []
    fieldbook_payloads: list[tuple[str, Path]] = []
    try:
        for i, u in enumerate(survey_files):
            name = u.filename or f"survey_{i+1}.csv"
            path = request_upload_dir / f"survey_{i:04d}_{_safe_upload_filename(name, 'survey.csv')}"
            await _stream_upload_to_path(u, path)
            survey_payloads.append((name, path))
        for i, u in enumerate(fieldbook_files):
            name = u.filename or f"fieldbook_{i+1}.pdf"
            path = request_upload_dir / f"fieldbook_{i:04d}_{_safe_upload_filename(name, 'fieldbook.pdf')}"
            await _stream_upload_to_path(u, path)
            fieldbook_payloads.append((name, path))
    except Exception:
        shutil.rmtree(request_upload_dir, ignore_errors=True)
        raise
    pairing = pair_batch_files([n for n, _ in survey_payloads], [n for n, _ in fieldbook_payloads])
    if not pairing.pairs:
        shutil.rmtree(request_upload_dir, ignore_errors=True)
        raise HTTPException(400, {
            "message": "No unambiguous survey/field-book pairs could be identified from the filenames.",
            "unmatched_surveys": list(pairing.unmatched_surveys),
            "unmatched_fieldbooks": list(pairing.unmatched_fieldbooks),
            "ambiguous_surveys": list(pairing.ambiguous_surveys),
        })

    from collections import defaultdict, deque
    survey_by_name = defaultdict(deque)
    fieldbook_by_name = defaultdict(deque)
    for name, path in survey_payloads:
        survey_by_name[name].append(path)
    for name, path in fieldbook_payloads:
        fieldbook_by_name[name].append(path)

    added: list[BatchJob] = []
    created_job_dirs: list[Path] = []
    try:
        for pair in pairing.pairs:
            job_id = uuid4().hex
            job_dir = runtime.storage.batch_dir / job_id
            created_job_dirs.append(job_dir)
            staging = job_dir / "raw_staging"
            pages_dir = staging / "pages"
            pages_dir.mkdir(parents=True, exist_ok=True)
            try:
                groups = []
                issues = []
                for name in pair.survey_files:
                    if not survey_by_name[name]:
                        continue
                    points, parsed_issues = parse_survey_file(survey_by_name[name].popleft(), name, profile)
                    groups.append(points)
                    issues.extend(parsed_issues)
                merged, duplicate_issues = merge_survey_points(groups)
                issues.extend(duplicate_issues)
                if not merged:
                    raise HTTPException(400, f"Paired job '{pair.key}' contains no survey structures matching profile '{profile.name}'.")

                pages: list[FieldBookPage] = []
                for name in pair.fieldbook_files:
                    if not fieldbook_by_name[name]:
                        continue
                    source_path = fieldbook_by_name[name].popleft()
                    try:
                        pages.extend(ingest_fieldbook_path(source_path, name, pages_dir))
                    except ValueError as exc:
                        raise HTTPException(400, f"Could not import field book '{name}': {exc}") from exc
                if not pages:
                    raise HTTPException(400, f"Paired job '{pair.key}' contains no readable field-book pages.")

                display_name = " ".join(part.capitalize() if part.isalpha() else part for part in pair.key.split())[:120] or f"Raw Job {job_id[:8]}"
                batch_state = AppState(
                    project_name=display_name,
                    selected_profile=profile.name,
                    survey_points=merged,
                    survey_issues=issues,
                    fieldbook_pages=pages,
                )
                bundle = create_project_bundle(batch_state, pages_dir, job_dir, profile)
                job = BatchJob(
                    job_id=job_id,
                    name=display_name,
                    profile_name=profile.name,
                    provider=runtime.provider,
                    project_file=str(bundle),
                    source_type="raw",
                    source_summary=f"{len(pair.survey_files)} survey file(s) + {len(pair.fieldbook_files)} field-book file(s) · {pair.method} ({pair.score:.0%})",
                    message="Queued from raw files",
                )
                added.append(job)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
    except Exception:
        # Queueing raw files is transactional. If any paired job fails validation/import,
        # remove every bundle created by this request so no orphaned or partially queued
        # projects are left behind. Nothing is appended to AppState until all pairs succeed.
        for created in created_job_dirs:
            shutil.rmtree(created, ignore_errors=True)
        shutil.rmtree(request_upload_dir, ignore_errors=True)
        raise

    shutil.rmtree(request_upload_dir, ignore_errors=True)
    with runtime.lock, runtime.storage.lock:
        runtime.storage.state.batch_jobs.extend(added)
        runtime.storage.save()
    return {
        "ok": True,
        "added": [j.model_dump(mode="json") for j in added],
        "unmatched_surveys": list(pairing.unmatched_surveys),
        "unmatched_fieldbooks": list(pairing.unmatched_fieldbooks),
        "ambiguous_surveys": list(pairing.ambiguous_surveys),
    }


@app.post("/api/batch/start")
def api_batch_start() -> dict:
    with runtime.lock:
        if runtime.job.running:
            raise HTTPException(409, "Finish or cancel the current project analysis first.")
        if runtime.batch_thread and runtime.batch_thread.is_alive():
            return {"ok": True, "message": "Batch queue is already running."}
        thread = threading.Thread(target=_batch_worker, daemon=True, name="FieldBookSyncBatch")
        runtime.batch_thread = thread
        thread.start()
    return {"ok": True, "message": "Batch queue started."}


@app.post("/api/batch/{job_id}/load")
def api_batch_load(job_id: str) -> dict:
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        job = next((j for j in runtime.storage.state.batch_jobs if j.job_id == job_id), None)
        if not job or job.status != "COMPLETE" or not job.project_file:
            raise HTTPException(400, "Batch job is not complete.")
        path = Path(job.project_file)
        start_revision = runtime.project_revision
    stage_root = None
    try:
        try:
            stage_root, state, profile = _stage_project_bundle(path)
        except Exception as exc:
            raise HTTPException(400, f"Could not open batch project: {exc}") from exc
        _commit_staged_project(stage_root, state, profile, expected_revision=start_revision)
    finally:
        if stage_root:
            shutil.rmtree(stage_root, ignore_errors=True)
    return {"ok": True, **_summary()}


@app.post("/api/reset")
def api_reset() -> dict:
    with runtime.lock:
        _assert_analysis_idle_locked()
        runtime.storage.reset_project()
        _bump_project_revision_locked()
    return _summary()



@app.get("/api/export")
def api_export() -> FileResponse:
    # Snapshot under lock, then perform ZIP/GIS generation outside it so UI polling stays responsive.
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        if not runtime.storage.state.results:
            raise HTTPException(400, "There are no results to export.")
        state_copy = deepcopy(runtime.storage.state)
    path = create_export_zip(state_copy, runtime.storage.export_dir)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/export/{fmt}")
def api_direct_export(fmt: str) -> StreamingResponse:
    """Download a lightweight native GIS/CAD format without building the whole QA ZIP."""
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        if not runtime.storage.state.results:
            raise HTTPException(400, "There are no results to export.")
        state_copy = deepcopy(runtime.storage.state)
    try:
        filename, media_type, text = direct_export_text(state_copy, fmt)
    except ValueError as exc:
        raise HTTPException(404, "Supported direct exports are GeoJSON, KML, and DXF.") from exc
    headers = {"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"}
    return StreamingResponse(iter([text.encode("utf-8")]), media_type=media_type, headers=headers)


@app.get("/api/arcgis/status")
def api_arcgis_status() -> dict:
    """Report ArcGIS Pro and ArcGIS Desktop / ArcMap 10.x integration availability."""
    return find_arcgis_products()


@app.post("/api/arcgis/maps")
def api_arcgis_maps(payload: ArcGISMapsIn) -> dict:
    try:
        path = payload.resolved_path()
        if not path:
            raise ValueError("Choose an ArcGIS Pro .aprx project or ArcMap .mxd document.")
        return list_project_maps(APP_ROOT, path)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/arcgis/export")
def api_arcgis_export(payload: ArcGISExportIn) -> dict:
    """Export Shapefiles and optionally add them to ArcGIS Pro (.aprx) or ArcMap 10.x (.mxd)."""
    with runtime.lock, runtime.storage.lock:
        _assert_analysis_idle_locked()
        if not runtime.storage.state.results:
            raise HTTPException(400, "There are no results to export.")
        state_copy = deepcopy(runtime.storage.state)
    try:
        return export_to_arcgis(
            state_copy,
            APP_ROOT,
            payload.output_folder,
            project_path=payload.resolved_project_path(),
            map_name=payload.map_name or None,
            include_network=payload.include_network,
            assign_map_crs=payload.assign_map_crs,
            replace_existing=payload.replace_existing,
            create_project_subfolder=payload.create_project_subfolder,
            backup_project=payload.backup_project,
            backup_aprx=payload.backup_aprx,
            open_project_after=payload.open_project_after,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        logger.exception("ArcGIS/Shapefile export failed")
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/diagnostics/log")
def api_diagnostics_log() -> FileResponse:
    path = runtime.storage.root / "logs" / "fieldbook_sync.log"
    if not path.exists():
        raise HTTPException(404, "No diagnostic log has been written yet.")
    return FileResponse(path, media_type="text/plain", filename="fieldbook_sync.log", headers={"Cache-Control": "no-store"})


def _choose_port(host: str, preferred: int) -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, preferred))
        return preferred
    except OSError:
        probe.close()
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind((host, 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def run_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn

    actual_port = _choose_port(host, port)
    runtime.shutdown_event.clear()
    config = uvicorn.Config(app, host=host, port=actual_port, log_level="info")
    server = uvicorn.Server(config)

    def _watch_shutdown() -> None:
        runtime.shutdown_event.wait()
        server.should_exit = True

    threading.Thread(target=_watch_shutdown, name="FBS-server-shutdown", daemon=True).start()
    if open_browser:
        opener = threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{actual_port}"))
        opener.daemon = True
        opener.start()
    try:
        server.run()
    finally:
        request_application_shutdown("Local FieldBook Sync server stopped.")
        finalize_application_shutdown()


# SurveySync v9 platform shell and shared-module APIs.

from .map_routes import router as map_routes_router
from .map_routes import (
    _aligned_project_xy_locked as _aligned_project_xy_locked,
    _inverse_aligned_project_xy_locked as _inverse_aligned_project_xy_locked,
    _manual_network_edges_locked as _manual_network_edges_locked,
    _project_xy_to_lonlat_locked as _project_xy_to_lonlat_locked,
    _structure_map_record as _structure_map_record,
    api_map_alignment as api_map_alignment,
    api_map_alignment_solve as api_map_alignment_solve,
    api_map_bookmark_add as api_map_bookmark_add,
    api_map_bookmark_delete as api_map_bookmark_delete,
    api_map_crs as api_map_crs,
    api_map_crs_import as api_map_crs_import,
    api_map_crs_search as api_map_crs_search,
    api_map_import as api_map_import,
    api_map_layer_delete as api_map_layer_delete,
    api_map_layer_order as api_map_layer_order,
    api_map_layer_settings as api_map_layer_settings,
    api_map_state as api_map_state,
    api_map_transform as api_map_transform,
    api_network as api_network,
    api_network_manual_add as api_network_manual_add,
    api_network_manual_delete as api_network_manual_delete,
)
app.include_router(map_routes_router)


from .profile_routes import router as profile_routes_router
from .profile_routes import (
    api_delete_field_note_profile as api_delete_field_note_profile,
    api_delete_field_note_training_example as api_delete_field_note_training_example,
    api_duplicate_field_note_profile as api_duplicate_field_note_profile,
    api_export_field_note_profile as api_export_field_note_profile,
    api_field_note_profiles as api_field_note_profiles,
    api_field_note_training_example_image as api_field_note_training_example_image,
    api_field_note_training_examples as api_field_note_training_examples,
    api_fieldbook_profile_assignment as api_fieldbook_profile_assignment,
    api_fieldbook_profile_assignments as api_fieldbook_profile_assignments,
    api_fieldbook_training_preview as api_fieldbook_training_preview,
    api_import_field_note_profile as api_import_field_note_profile,
    api_save_field_note_profile as api_save_field_note_profile,
    api_save_field_note_training_example as api_save_field_note_training_example,
    api_select_field_note_profile as api_select_field_note_profile,
    api_teach_result_to_profile as api_teach_result_to_profile,
)
app.include_router(profile_routes_router)


from .vision_pipeline import (
    _direct_vision_analysis as _direct_vision_analysis,
    _hybrid_local_analysis as _hybrid_local_analysis,
    _windows_local_analysis as _windows_local_analysis,
    _windows_ocr_candidates_from_payload as _windows_ocr_candidates_from_payload,
)


from .live_analysis import (
    _begin_live_analysis_locked as _begin_live_analysis_locked,
    _dedupe_unmatched as _dedupe_unmatched,
    _end_live_analysis_locked as _end_live_analysis_locked,
    _live_candidate_key as _live_candidate_key,
    _live_pending_evidence as _live_pending_evidence,
    _live_point_state_locked as _live_point_state_locked,
    _live_result_dict_locked as _live_result_dict_locked,
    _publish_live_candidates as _publish_live_candidates,
    _publish_live_interpretation as _publish_live_interpretation,
    _rebuild_live_analysis_locked as _rebuild_live_analysis_locked,
    _record_usage_locked as _record_usage_locked,
    _run_live_network_rebuild as _run_live_network_rebuild,
    _schedule_live_network_rebuild_locked as _schedule_live_network_rebuild_locked,
    _sync_live_job_counts_locked as _sync_live_job_counts_locked,
)


from .batch_workers import (
    _batch_analyze_state as _batch_analyze_state,
    _batch_hybrid_local as _batch_hybrid_local,
    _batch_windows_local as _batch_windows_local,
    _batch_worker as _batch_worker,
    _set_batch_progress as _set_batch_progress,
)

from surveysync.router import router as surveysync_router
app.include_router(surveysync_router)

if __name__ == "__main__":
    run_server()
