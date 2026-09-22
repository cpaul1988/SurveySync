from __future__ import annotations

import json
import os
import platform
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def diagnostics_root(config_root: str | Path) -> Path:
    root = Path(config_root) / "diagnostics"
    root.mkdir(parents=True, exist_ok=True)
    return root


def error_log_path(config_root: str | Path) -> Path:
    return diagnostics_root(config_root) / "error_log.jsonl"


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


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if any(token in str(key).lower() for token in ("key", "token", "secret", "password")):
                cleaned[key] = "<redacted>"
            else:
                cleaned[key] = _scrub(item)
        return cleaned
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def record_error(
    config_root: str | Path,
    *,
    component: str,
    code: str,
    message: str,
    detail: str = "",
    severity: str = "ERROR",
    recoverable: bool = True,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "error_id": f"SSE-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6].upper()}",
        "created_utc": utc_now(),
        "component": str(component or "application")[:80],
        "code": str(code or "APP-001")[:80],
        "severity": str(severity or "ERROR")[:40],
        "recoverable": bool(recoverable),
        "message": str(message or "Unexpected SurveySync error")[:2000],
        "detail": str(detail or "")[-12000:],
        "context": _scrub(context or {}),
        "sync": {"status": "local_only"},
    }
    _append_jsonl(error_log_path(config_root), event)
    return event


def list_errors(config_root: str | Path, limit: int = 100) -> list[dict[str, Any]]:
    path = error_log_path(config_root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except (ValueError, TypeError):
            continue
    return rows[-max(1, min(int(limit), 500)):][::-1]


def valid_apps_script_endpoint(value: str) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme.lower() == "https"
        and host == "script.google.com"
        and parsed.path.startswith("/macros/s/")
        and parsed.path.rstrip("/").endswith("/exec")
    )


def submit_error_log(endpoint_url: str, errors: list[dict[str, Any]], *, app_version: str) -> dict[str, Any]:
    endpoint = str(endpoint_url or "").strip()
    if not valid_apps_script_endpoint(endpoint):
        raise ValueError("Error-log sync requires a deployed HTTPS Google Apps Script /exec URL.")
    payload = {
        "schema_version": 1,
        "route": "error_log",
        "target_sheet": "Error Log",
        "application": "SurveySync",
        "app_version": app_version,
        "submitted_utc": utc_now(),
        "errors": [_scrub(item) for item in errors[:100]],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"SurveySync/{app_version}",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(512 * 1024)
            status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        text = exc.read(2048).decode("utf-8", "replace").strip()
        raise RuntimeError(f"HTTP {exc.code} from Error Log tracker: {text[:500]}") from exc
    data: dict[str, Any] = {}
    if body:
        try:
            parsed = json.loads(body.decode("utf-8-sig"))
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}
    if status >= 400 or (data and data.get("ok") is False):
        raise RuntimeError(str(data.get("error") or f"HTTP {status} from Error Log tracker"))
    return {
        "status": "synced",
        "provider": "google_apps_script",
        "route": "error_log",
        "synced_utc": utc_now(),
        "http_status": status,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "tracker_row": data.get("row"),
        "remote_id": data.get("error_log_id") or data.get("intake_id") or "",
    }


def build_diagnostic_bundle(
    *,
    config_root: str | Path,
    output_dir: str | Path,
    app_version: str,
    config: dict[str, Any],
    project_summary: dict[str, Any] | None = None,
) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = out_dir / f"SurveySync_Diagnostics_{stamp}.zip"
    root = Path(config_root)
    files: dict[str, bytes] = {
        "system.json": json.dumps({
            "app_version": app_version,
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        }, indent=2, ensure_ascii=False).encode("utf-8"),
        "config_redacted.json": json.dumps(_scrub(config), indent=2, ensure_ascii=False).encode("utf-8"),
        "project_summary.json": json.dumps(_scrub(project_summary or {}), indent=2, ensure_ascii=False).encode("utf-8"),
        "PRIVACY.txt": (
            "This bundle is designed for support triage. It includes logs, error metadata, "
            "redacted settings, and project summary only. It does not intentionally include "
            "survey source files, field-book images, OCR crops, exports, API keys, tokens, or passwords.\n"
        ).encode("utf-8"),
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        for rel in (
            Path("diagnostics") / "error_log.jsonl",
            Path("feedback") / "feedback_log.jsonl",
        ):
            src = root / rel
            if src.exists() and src.is_file():
                zf.write(src, str(rel).replace("\\", "/"))
        logs_root = root / "logs"
        if logs_root.exists():
            for src in sorted(logs_root.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:12]:
                if src.is_file() and re.fullmatch(r"[A-Za-z0-9_. -]+\.log", src.name):
                    zf.write(src, f"logs/{src.name}")
    return zip_path
