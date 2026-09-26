from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fieldbook_sync.feedback import (
    create_report,
    list_reports,
    submit_to_tracker_endpoint,
    update_report_sync,
)

from . import __version__
from .audit import utc_now
from .diagnostics import list_errors as list_diagnostic_errors
from .diagnostics import submit_error_log
from .session_recovery import (
    dismiss_recovery_notice,
    heartbeat,
    recovery_summary,
    restore_latest_recovery,
)

router = APIRouter(prefix="/api/v9/support", tags=["Support Center"])
_STATE_LOCK = threading.RLock()
_AUTO_LOCK = threading.Lock()
_AUTO_RUNNING = False
AUTO_RETRY_SECONDS = 15 * 60


class ErrorSyncIn(BaseModel):
    error_ids: list[str] = Field(default_factory=list, max_length=100)


class FeedbackRefreshIn(BaseModel):
    local_report_ids: list[str] = Field(default_factory=list, max_length=100)


class ErrorReportIn(BaseModel):
    error_id: str = Field(min_length=6, max_length=100)


class RecoveryRestoreIn(BaseModel):
    confirmed: bool = False


def _context():
    from . import router as context

    return context


def _state_path() -> Path:
    root = _context().config_store.root / "support"
    root.mkdir(parents=True, exist_ok=True)
    return root / "support_state.json"


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {"errors": {}, "feedback": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"errors": {}, "feedback": {}}
    if not isinstance(data, dict):
        return {"errors": {}, "feedback": {}}
    data.setdefault("errors", {})
    data.setdefault("feedback", {})
    return data


def _save_state(data: dict[str, Any]) -> None:
    path = _state_path()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _mark_error(error_id: str, **values: Any) -> None:
    with _STATE_LOCK:
        state = _load_state()
        item = dict(state["errors"].get(error_id) or {})
        item.update(values)
        item["updated_utc"] = utc_now()
        state["errors"][error_id] = item
        _save_state(state)


def _merged_errors(limit: int = 100) -> list[dict[str, Any]]:
    context = _context()
    state = _load_state()
    output: list[dict[str, Any]] = []
    for item in list_diagnostic_errors(context.config_store.root, limit=limit):
        row = dict(item)
        error_id = str(row.get("error_id") or "")
        sync = dict(row.get("sync") or {})
        sync.update(state["errors"].get(error_id) or {})
        sync.setdefault("status", "local_only")
        row["sync"] = sync
        output.append(row)
    return output


def _pending_errors(limit: int = 100) -> list[dict[str, Any]]:
    return [
        item
        for item in _merged_errors(limit=limit)
        if str((item.get("sync") or {}).get("status") or "local_only") not in {"synced", "resolved"}
    ]


def _sync_errors(errors: list[dict[str, Any]]) -> dict[str, Any]:
    context = _context()
    cfg = context.config_store.load()
    endpoint = str(cfg.feedback_endpoint or "").strip()
    if not endpoint:
        raise ValueError("Feedback/Error Log endpoint is not configured.")
    if not errors:
        return {"status": "nothing_to_sync", "count": 0}
    error_ids = [str(item.get("error_id") or "") for item in errors if item.get("error_id")]
    for error_id in error_ids:
        _mark_error(error_id, status="syncing")
    try:
        result = submit_error_log(endpoint, errors, app_version=__version__)
    except (ValueError, RuntimeError, OSError, urllib.error.URLError) as exc:
        for error_id in error_ids:
            _mark_error(error_id, status="pending", last_error=str(exc))
        raise RuntimeError(str(exc)) from exc
    for error_id in error_ids:
        _mark_error(
            error_id,
            status="synced",
            synced_utc=str(result.get("synced_utc") or utc_now()),
            remote_id=str(result.get("remote_id") or ""),
            tracker_row=result.get("tracker_row"),
            last_error="",
        )
    with _STATE_LOCK:
        state = _load_state()
        state["last_error_sync_success_utc"] = utc_now()
        _save_state(state)
    return {"count": len(error_ids), **result}


def _parse_utc(value: str) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def schedule_auto_sync() -> dict[str, Any]:
    global _AUTO_RUNNING
    context = _context()
    cfg = context.config_store.load()
    if not str(cfg.feedback_endpoint or "").strip():
        return {"scheduled": False, "reason": "endpoint_not_configured"}
    pending = _pending_errors(limit=100)
    if not pending:
        return {"scheduled": False, "reason": "nothing_pending"}
    state = _load_state()
    last_attempt = _parse_utc(str(state.get("last_error_sync_attempt_utc") or ""))
    now = datetime.now(timezone.utc).timestamp()
    if last_attempt and now - last_attempt < AUTO_RETRY_SECONDS:
        return {"scheduled": False, "reason": "backoff", "pending": len(pending)}
    if not _AUTO_LOCK.acquire(blocking=False):
        return {"scheduled": False, "reason": "already_running", "pending": len(pending)}
    _AUTO_RUNNING = True
    with _STATE_LOCK:
        state = _load_state()
        state["last_error_sync_attempt_utc"] = utc_now()
        _save_state(state)

    def worker() -> None:
        global _AUTO_RUNNING
        try:
            _sync_errors(pending)
        except (ValueError, RuntimeError, OSError, urllib.error.URLError):
            pass
        finally:
            _AUTO_RUNNING = False
            _AUTO_LOCK.release()

    threading.Thread(target=worker, name="SurveySyncSupportSync", daemon=True).start()
    return {"scheduled": True, "pending": len(pending)}


def _feedback_rows(limit: int = 100) -> list[dict[str, Any]]:
    context = _context()
    state = _load_state()
    field_app = context._fieldbook_app_module()
    feedback_storage = field_app.runtime.storage.root
    rows: list[dict[str, Any]] = []
    for report in list_reports(feedback_storage, limit=limit):
        report_id = str(report.get("report_id") or "")
        sync = dict(report.get("sync") or {})
        remote = dict(state["feedback"].get(report_id) or {})
        rows.append(
            {
                "report_id": report_id,
                "created_utc": str(report.get("created_utc") or ""),
                "report_type": str(report.get("report_type") or ""),
                "title": str(report.get("title") or ""),
                "app_version": str(report.get("app_version") or ""),
                "local_sync": sync,
                "intake_id": str(sync.get("intake_id") or ""),
                "tracker_status": str(remote.get("status") or ""),
                "released_in": str(remote.get("released_in") or ""),
                "tracker_updated_utc": str(remote.get("updated_utc") or ""),
            }
        )
    return rows


def _tracker_feedback_status(endpoint: str, local_report_ids: list[str]) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "application": "SurveySync",
        "route": "feedback_status",
        "local_report_ids": local_report_ids[:100],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"SurveySync/{__version__}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(512 * 1024)
            status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        body = exc.read(2048).decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code} from feedback tracker: {body[:400]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Feedback tracker is unavailable: {exc.reason}") from exc
    if status >= 400:
        raise RuntimeError(f"HTTP {status} from feedback tracker")
    try:
        data = json.loads(body.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Feedback tracker returned an invalid response.") from exc
    if not isinstance(data, dict) or data.get("ok") is False:
        raise RuntimeError(
            str(data.get("error") if isinstance(data, dict) else "Tracker rejected status request.")
        )
    return data


@router.get("/summary")
def support_summary() -> dict[str, Any]:
    context = _context()
    heartbeat(context.config_store.root)
    auto = schedule_auto_sync()
    errors = _merged_errors(limit=100)
    counts = {"local_only": 0, "pending": 0, "syncing": 0, "synced": 0, "resolved": 0}
    for item in errors:
        status = str((item.get("sync") or {}).get("status") or "local_only")
        counts[status] = counts.get(status, 0) + 1
    return {
        "version": __version__,
        "error_counts": counts,
        "errors": errors,
        "feedback": _feedback_rows(limit=100),
        "recovery": recovery_summary(context.config_store.root, context.current_project),
        "auto_sync": auto,
    }


@router.post("/errors/sync")
def sync_selected_errors(payload: ErrorSyncIn) -> dict[str, Any]:
    wanted = {value for value in payload.error_ids if value}
    errors = [
        item
        for item in _merged_errors(limit=500)
        if not wanted or str(item.get("error_id") or "") in wanted
    ]
    if wanted and len(errors) != len(wanted):
        missing = sorted(wanted - {str(item.get("error_id") or "") for item in errors})
        raise HTTPException(404, f"Error IDs were not found: {', '.join(missing[:8])}")
    try:
        result = _sync_errors(errors[:100])
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, **result}


@router.post("/errors/report")
def report_error(payload: ErrorReportIn) -> dict[str, Any]:
    context = _context()
    error = next(
        (item for item in _merged_errors(limit=500) if item.get("error_id") == payload.error_id),
        None,
    )
    if error is None:
        raise HTTPException(404, "SurveySync error was not found.")
    field_app = context._fieldbook_app_module()
    storage_root = field_app.runtime.storage.root
    cfg = context.config_store.load()
    report = create_report(
        storage_root=storage_root,
        report={
            "report_type": "Bug",
            "reporter_name": "",
            "title": f"{error.get('code')}: {str(error.get('message') or 'SurveySync error')[:120]}",
            "description": (
                f"Reported from SurveySync Support Center. Error ID: {error.get('error_id')}. "
                f"Component: {error.get('component')}. Message: {error.get('message')}"
            ),
            "app_version": __version__,
            "importance": "High"
            if str(error.get("severity") or "").upper() in {"ERROR", "CRITICAL"}
            else "Normal",
            "severity": "Major"
            if str(error.get("severity") or "").upper() in {"ERROR", "CRITICAL"}
            else "Minor",
            "steps": "",
            "expected": "The operation completes without an application error.",
            "actual": str(error.get("detail") or error.get("message") or "")[-12000:],
            "additional": "Created with Report This Error. Survey source files were not attached.",
            "context": {
                "job_state": "",
                "provider": "",
                "support_error_id": str(error.get("error_id") or ""),
            },
        },
    )
    endpoint = str(cfg.feedback_endpoint or "").strip()
    if endpoint:
        try:
            report_dir = storage_root / "feedback" / "reports" / str(report["report_id"])
            sync = submit_to_tracker_endpoint(endpoint, report, report_dir)
            report = update_report_sync(storage_root, str(report["report_id"]), sync)
        except (ValueError, RuntimeError, OSError) as exc:
            update_report_sync(
                storage_root,
                str(report["report_id"]),
                {"status": "pending", "last_error": str(exc), "attempted_utc": utc_now()},
            )
    return {
        "ok": True,
        "report_id": report.get("report_id"),
        "sync": report.get("sync") or {},
        "survey_data_attached": False,
    }


@router.post("/feedback/refresh")
def refresh_feedback_status(payload: FeedbackRefreshIn) -> dict[str, Any]:
    context = _context()
    cfg = context.config_store.load()
    endpoint = str(cfg.feedback_endpoint or "").strip()
    ids = [value for value in payload.local_report_ids if value]
    if not ids:
        ids = [row["report_id"] for row in _feedback_rows(limit=100) if row["report_id"]]
    if not endpoint:
        return {
            "ok": False,
            "available": False,
            "message": "Feedback endpoint is not configured.",
            "feedback": _feedback_rows(limit=100),
        }
    try:
        remote = _tracker_feedback_status(endpoint, ids)
    except RuntimeError as exc:
        return {
            "ok": False,
            "available": False,
            "message": str(exc),
            "feedback": _feedback_rows(limit=100),
        }
    statuses = remote.get("statuses") if isinstance(remote.get("statuses"), list) else []
    with _STATE_LOCK:
        state = _load_state()
        for item in statuses:
            if not isinstance(item, dict):
                continue
            report_id = str(item.get("local_report_id") or "")
            if not report_id:
                continue
            state["feedback"][report_id] = {
                "status": str(item.get("status") or ""),
                "released_in": str(item.get("released_in") or ""),
                "intake_id": str(item.get("intake_id") or ""),
                "updated_utc": utc_now(),
            }
        state["last_feedback_refresh_utc"] = utc_now()
        _save_state(state)
    return {
        "ok": True,
        "available": True,
        "statuses": statuses,
        "feedback": _feedback_rows(limit=100),
    }


@router.post("/recovery/restore-latest")
def restore_latest(payload: RecoveryRestoreIn) -> dict[str, Any]:
    if not payload.confirmed:
        raise HTTPException(400, "Explicit recovery confirmation is required.")
    context = _context()
    if context.current_project is None:
        raise HTTPException(409, "Open the interrupted SurveySync project first.")
    try:
        result = restore_latest_recovery(context.config_store.root, context.current_project)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "restored": result}


@router.post("/recovery/dismiss")
def dismiss_recovery() -> dict[str, Any]:
    context = _context()
    dismiss_recovery_notice(context.config_store.root)
    return {
        "ok": True,
        "recovery": recovery_summary(context.config_store.root, context.current_project),
    }
