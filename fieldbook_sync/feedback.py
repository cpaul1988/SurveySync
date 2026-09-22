from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests


MAX_ATTACHMENT_COUNT = 5
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_REMOTE_FILE_BYTES = 10 * 1024 * 1024
TRACKER_POST_TIMEOUT = 30

_REPORT_LOCK = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_name(value: str, fallback: str = "attachment") -> str:
    name = Path(str(value or "")).name.strip() or fallback
    name = re.sub(r"[^A-Za-z0-9._()\- ]+", "_", name).strip(" .")
    return (name or fallback)[:180]


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    temp.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(line)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass


def feedback_root(storage_root: str | Path) -> Path:
    root = Path(storage_root) / "feedback"
    root.mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(exist_ok=True)
    return root


def new_report_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    token = os.urandom(3).hex().upper()
    return f"FBL-{stamp}-{token}"


def save_uploaded_attachments(report_dir: Path, uploads: Iterable[Any]) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    total = 0
    attach_dir = report_dir / "attachments"
    for index, upload in enumerate(list(uploads or [])):
        if index >= MAX_ATTACHMENT_COUNT:
            raise ValueError(f"A feedback report can include at most {MAX_ATTACHMENT_COUNT} attachments.")
        original = _safe_name(getattr(upload, "filename", "") or f"attachment_{index + 1}")
        target = attach_dir / original
        attach_dir.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = attach_dir / f"{target.stem}_{index + 1}{target.suffix}"
        size = 0
        with target.open("wb") as out:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                total += len(chunk)
                if total > MAX_ATTACHMENT_BYTES:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise ValueError("Feedback attachments are limited to 25 MB total.")
                out.write(chunk)
        saved.append({
            "name": target.name,
            "size_bytes": size,
            "content_type": str(getattr(upload, "content_type", "") or "application/octet-stream"),
            "relative_path": str(target.relative_to(report_dir)).replace("\\", "/"),
        })
    return saved


def create_report(
    *,
    storage_root: str | Path,
    report: dict[str, Any],
    attachments: Iterable[Any] = (),
    diagnostic_bundle: str | Path | None = None,
) -> dict[str, Any]:
    """Persist one feedback report locally before any network submission occurs."""
    root = feedback_root(storage_root)
    report_id = str(report.get("report_id") or new_report_id())
    report_dir = root / "reports" / report_id
    report_dir.mkdir(parents=True, exist_ok=True)

    payload = dict(report)
    payload["report_id"] = report_id
    payload.setdefault("created_utc", _utc_now())
    payload.setdefault("sync", {"status": "local_only"})

    payload["attachments"] = save_uploaded_attachments(report_dir, attachments)

    if diagnostic_bundle:
        src = Path(diagnostic_bundle)
        if src.exists() and src.is_file():
            dst = report_dir / _safe_name(src.name, "diagnostics.zip")
            shutil.copy2(src, dst)
            payload["diagnostic_bundle"] = {
                "name": dst.name,
                "size_bytes": dst.stat().st_size,
                "relative_path": dst.name,
            }

    with _REPORT_LOCK:
        _json_dump(report_dir / "report.json", payload)
        _append_jsonl(root / "feedback_log.jsonl", payload)
    return payload


def update_report_sync(storage_root: str | Path, report_id: str, sync: dict[str, Any]) -> dict[str, Any]:
    root = feedback_root(storage_root)
    path = root / "reports" / report_id / "report.json"
    if not path.exists():
        raise FileNotFoundError(report_id)
    with _REPORT_LOCK:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["sync"] = dict(sync)
        _json_dump(path, payload)
        _append_jsonl(root / "feedback_log.jsonl", {
            "event": "sync_update",
            "report_id": report_id,
            "created_utc": _utc_now(),
            "sync": dict(sync),
        })
    return payload


def list_reports(storage_root: str | Path, limit: int = 50) -> list[dict[str, Any]]:
    root = feedback_root(storage_root) / "reports"
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/report.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(item, dict):
                items.append(item)
        except Exception:
            continue
        if len(items) >= max(1, min(int(limit), 250)):
            break
    return items


def report_log_path(storage_root: str | Path) -> Path:
    return feedback_root(storage_root) / "feedback_log.jsonl"


def valid_tracker_endpoint(value: str) -> bool:
    """Accept only deployed Google Apps Script web-app endpoints."""
    try:
        parsed = urlparse(str(value or "").strip())
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme.lower() == "https"
        and host == "script.google.com"
        and parsed.path.startswith("/macros/s/")
        and parsed.path.rstrip("/").endswith("/exec")
    )


def _remote_values(report: dict[str, Any]) -> dict[str, str]:
    context = report.get("context") or {}
    return {
        "local_report_id": str(report.get("report_id") or ""),
        "submitted": str(report.get("created_utc") or _utc_now()),
        "requester": str(report.get("reporter_name") or ""),
        "type": str(report.get("report_type") or ""),
        "title": str(report.get("title") or ""),
        "description": str(report.get("description") or ""),
        "version": str(report.get("app_version") or ""),
        "priority": str(report.get("importance") or "Normal"),
        "severity": str(report.get("severity") or "Not applicable"),
        "steps": str(report.get("steps") or ""),
        "expected": str(report.get("expected") or ""),
        "actual": str(report.get("actual") or ""),
        "submitter_notes": str(report.get("additional") or ""),
        "project_name": str(context.get("project_name") or ""),
        "job_state": str(context.get("job_state") or ""),
        "provider": str(context.get("provider") or ""),
    }


def _read_remote_files(report: dict[str, Any], report_dir: Path) -> tuple[list[dict[str, str | int]], list[str]]:
    """Encode explicitly selected support files for the tracker endpoint.

    Local logging allows 25 MB. The direct tracker transport intentionally caps the
    aggregate remote upload at 10 MB to stay comfortably below Apps Script request
    and execution limits. Files over the cap remain safe in the local report folder.
    """
    candidates: list[tuple[str, Path, str]] = []
    for item in report.get("attachments") or []:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("relative_path") or "")
        if not rel:
            continue
        candidates.append((str(item.get("name") or Path(rel).name), report_dir / rel, str(item.get("content_type") or "")))
    diag = report.get("diagnostic_bundle") or {}
    if isinstance(diag, dict) and diag.get("relative_path"):
        rel = str(diag["relative_path"])
        candidates.append((str(diag.get("name") or Path(rel).name), report_dir / rel, "application/zip"))

    encoded: list[dict[str, str | int]] = []
    skipped: list[str] = []
    total = 0
    report_root = report_dir.resolve()
    for name, path, content_type in candidates:
        try:
            resolved = path.resolve()
            if report_root not in resolved.parents and resolved != report_root:
                skipped.append(f"{name} (unsafe path)")
                continue
            if not resolved.is_file():
                skipped.append(f"{name} (missing)")
                continue
            size = resolved.stat().st_size
            if total + size > MAX_REMOTE_FILE_BYTES:
                skipped.append(f"{name} (remote 10 MB cap)")
                continue
            total += size
            encoded.append({
                "name": _safe_name(name),
                "content_type": content_type or mimetypes.guess_type(name)[0] or "application/octet-stream",
                "size_bytes": size,
                "data_base64": base64.b64encode(resolved.read_bytes()).decode("ascii"),
            })
        except Exception as exc:
            skipped.append(f"{name} ({type(exc).__name__})")
    return encoded, skipped


def submit_to_tracker_endpoint(endpoint_url: str, report: dict[str, Any], report_dir: str | Path) -> dict[str, Any]:
    """Submit a locally persisted report directly to the shared Intake tracker."""
    endpoint = str(endpoint_url or "").strip()
    if not valid_tracker_endpoint(endpoint):
        raise ValueError("The shared tracker endpoint must be a deployed HTTPS Google Apps Script /exec URL.")

    files, skipped_files = _read_remote_files(report, Path(report_dir))
    # Feedback intentionally uses the original FieldBook Sync envelope.  The shared
    # Intake Web App has been deployed in more than one generation; older deployments
    # reject the newer SurveySync routing fields before they ever inspect the report.
    # Current SurveySync tracker code accepts this legacy identifier too, so this is the
    # one envelope that is compatible with both old and new /exec deployments.
    payload = {
        "schema_version": 1,
        "application": "FieldBook Sync",
        "report": _remote_values(report),
        "files": files,
        "skipped_files": skipped_files,
    }
    headers = {
        "User-Agent": f"FieldBookSync/{report.get('app_version') or 'desktop'}",
        "Content-Type": "application/json",
    }
    response = requests.post(endpoint, json=payload, headers=headers, timeout=TRACKER_POST_TIMEOUT, allow_redirects=True)
    metadata_only_retry = False
    # Google Apps Script can return HTTP 5xx when Drive attachment handling or request-size
    # work fails even though the tracker itself is healthy. Never lose the report for that.
    # If support files were included, retry the same report once without file bytes. The
    # original attachments remain in the local append-only report folder for manual review.
    deferred_note = "Remote support-file upload deferred after tracker error; files remain in the local feedback log."
    if response.status_code in {413, 429, 500, 502, 503, 504} and files:
        metadata_only_retry = True
        reduced_payload = dict(payload)
        reduced_payload["files"] = []
        reduced_payload["skipped_files"] = [*skipped_files, deferred_note]
        response = requests.post(endpoint, json=reduced_payload, headers=headers, timeout=TRACKER_POST_TIMEOUT, allow_redirects=True)
    if response.status_code >= 400:
        body = (response.text or "").strip().replace("\r", " ").replace("\n", " ")[:500]
        detail = f"HTTP {response.status_code} from the shared Intake tracker"
        if body:
            detail += f": {body}"
        raise RuntimeError(detail)
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError("The shared tracker endpoint returned an invalid response.") from exc
    if not isinstance(data, dict) or not data.get("ok"):
        message = data.get("error") if isinstance(data, dict) else ""
        raise RuntimeError(str(message or "The shared tracker did not accept the report."))
    intake_id = str(data.get("intake_id") or "").strip()
    if not re.fullmatch(r"FBR-\d{4,}", intake_id):
        raise RuntimeError("The tracker accepted the report but did not return a valid FBR intake ID.")
    return {
        "status": "synced",
        "synced_utc": _utc_now(),
        "provider": "google_apps_script",
        "intake_id": intake_id,
        "tracker_row": data.get("row"),
        "attachment_folder_url": str(data.get("attachment_folder_url") or ""),
        "skipped_files": [*skipped_files, deferred_note] if metadata_only_retry else skipped_files,
        "http_status": response.status_code,
        "metadata_only_retry": metadata_only_retry,
        "remote_files_uploaded": bool(files) and not metadata_only_retry,
    }
