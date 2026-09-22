from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


def _safe_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def build_diagnostic_bundle(
    *,
    output_dir: str | Path,
    app_version: str,
    storage_root: str | Path,
    hardware: dict[str, Any],
    settings: dict[str, Any],
    job_store: Any,
    current_job_id: str | None = None,
) -> Path:
    """Create a privacy-first diagnostic ZIP. Field-book/survey imagery is excluded."""
    root = Path(storage_root)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = out_dir / f"FieldBookSync_Diagnostics_{stamp}"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    _safe_json(work / "system.json", {
        "app_version": app_version,
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "hardware": hardware,
    })
    scrubbed_settings = dict(settings or {})
    for key in list(scrubbed_settings):
        if "key" in key.lower() or "token" in key.lower() or "secret" in key.lower():
            scrubbed_settings[key] = "<redacted>"
    _safe_json(work / "settings_redacted.json", scrubbed_settings)
    _safe_json(work / "jobs.json", job_store.list_jobs(limit=50))
    _safe_json(work / "errors.json", job_store.list_errors(current_job_id, limit=250) if current_job_id else job_store.list_errors(limit=250))
    if current_job_id:
        _safe_json(work / "current_job.json", job_store.get_job(current_job_id) or {})

    logs_src = root / "logs"
    logs_dst = work / "logs"
    logs_dst.mkdir(exist_ok=True)
    if logs_src.exists():
        for src in sorted(logs_src.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]:
            try:
                shutil.copy2(src, logs_dst / src.name)
            except OSError:
                pass

    for name in ("PaddleOCR_Install.log", "PaddleOCR_Install_Diagnostic.log"):
        for candidate in (root / name, Path.cwd() / name):
            if candidate.exists():
                try:
                    shutil.copy2(candidate, work / candidate.name)
                except OSError:
                    pass
                break

    (work / "PRIVACY.txt").write_text(
        "This bundle intentionally excludes field-book page images, survey uploads, OCR crops, API keys, and project exports.\n",
        encoding="utf-8",
    )
    zip_path = out_dir / f"FieldBookSync_Diagnostics_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in work.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(work))
    shutil.rmtree(work, ignore_errors=True)
    return zip_path
