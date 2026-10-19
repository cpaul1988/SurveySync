"""Private, reproducible analysis snapshots for the offline FieldBook benchmark."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re
import subprocess

from .models import AppState, FieldBookPage, utc_now_iso


def record_ocr_provenance(observations: dict, page_id: str, payload: dict) -> None:
    """Retain only receipts from the parent's validated worker/cache page callback."""
    for view in payload.get("views", [payload]):
        meta = view.get("surveysync_view", {}) if isinstance(view, dict) else {}
        mode = meta.get("ocr_mode")
        if mode not in {"blocks", "spotting"}:
            continue
        asset_hash = meta.get("model_sha256", "")
        image_hash = meta.get("image_sha256", "")
        if not isinstance(image_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", image_hash):
            continue
        if not isinstance(asset_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", asset_hash):
            asset_hash = ""
        key = (page_id, str(meta.get("role", "unknown")), image_hash, asset_hash, mode)
        observations[key] = {"page_id": page_id, "mode": mode, "model_sha256": asset_hash}


def summarize_ocr_provenance(observations: dict) -> dict:
    return {
        "observed_modes": sorted({entry["mode"] for entry in observations.values()}),
        "observed_model_asset_sha256": sorted(
            {entry["model_sha256"] for entry in observations.values() if entry["model_sha256"]}
        ),
        "observed_page_count": len({entry["page_id"] for entry in observations.values()}),
        "observed_view_count": len(observations),
    }


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analysis_run_metadata(
    *, app_root: Path, pages: list[FieldBookPage], mode: str, model: str, hardware: dict
) -> dict:
    """Capture run provenance at analysis time, not from settings at export time."""
    code = hashlib.sha256()
    source_files = [
        "paddle_bridge.py",
        "fieldbook_sync/ocr_local.py",
        "fieldbook_sync/text_spotting.py",
        "fieldbook_sync/measurement_comparison.py",
        "fieldbook_sync/relationship_evidence.py",
        "fieldbook_sync/spatial_association.py",
        "fieldbook_sync/vision_pipeline.py",
        "fieldbook_sync/batch_workers.py",
        "fieldbook_sync/evidence_pipeline.py",
        "fieldbook_sync/ai_reader.py",
        "fieldbook_sync/image_processing.py",
        "fieldbook_sync/models.py",
        "fieldbook_sync/aggregate.py",
        "fieldbook_sync/app.py",
        "fieldbook_sync/benchmark_export.py",
    ]
    for name in source_files:
        path = app_root / name
        code.update(name.encode("utf-8") + b"\0")
        code.update((_file_hash(path) if path.is_file() else "unavailable").encode("ascii"))
    source_commit, source_dirty = None, None
    if (app_root / ".git").exists():
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=app_root,
                capture_output=True,
                text=True,
                timeout=2,
                check=True,
            ).stdout.strip()
            if len(commit) == 40 and all(char in "0123456789abcdef" for char in commit):
                source_commit = commit
            status = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=normal"],
                cwd=app_root,
                capture_output=True,
                text=True,
                timeout=2,
                check=True,
            )
            source_dirty = bool(status.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    page_hashes: dict[str, str | None] = {}
    unavailable_pages: list[str] = []
    for page in pages:
        try:
            page_hashes[page.page_id] = _file_hash(Path(page.image_path))
        except OSError:
            # Provenance is optional evidence, not a replacement for engine error
            # handling or the stale-project commit guard.
            page_hashes[page.page_id] = None
            unavailable_pages.append(page.page_id)
    info = {
        "schema_version": 1,
        "mode": mode,
        "model": model,
        "generated_at": utc_now_iso(),
        "source_commit": source_commit,
        "implementation_sha256": code.hexdigest(),
        "measurements": {},
        "hardware": {},
        "page_sha256": page_hashes,
    }
    if unavailable_pages:
        info["provenance_warnings"] = [
            "Source image hash unavailable: " + page_id for page_id in unavailable_pages
        ]
    if source_dirty is not None:
        info["source_dirty"] = source_dirty
    if hardware.get("platform"):
        info["hardware"]["os"] = hardware["platform"]
    if hardware.get("logical_cores"):
        info["hardware"]["cpu"] = f"{hardware['logical_cores']} logical cores"
    if hardware.get("nvidia_gpu_name"):
        info["hardware"]["gpu"] = hardware["nvidia_gpu_name"]
    for target, field in (("ram_gib", "total_ram_bytes"), ("vram_gib", "nvidia_vram_bytes")):
        if hardware.get(field):
            info["hardware"][target] = hardware[field] / 1024**3
    return info


def benchmark_payload(state: AppState) -> dict:
    metadata = deepcopy(state.analysis_metadata) or {"schema_version": 1, "mode": "unknown"}
    hashes = metadata.pop("page_sha256", {})
    timed = [record for record in state.results if record.review_elapsed_seconds is not None]
    if timed:
        measurements = metadata.setdefault("measurements", {})
        measurements["correction_seconds"] = sum(record.review_elapsed_seconds for record in timed)
        measurements["reviewed_structures"] = len(timed)
        metadata["review_timing_basis"] = (
            "Review dialog elapsed time, including reading and idle time; only timed records."
        )
    return {
        "benchmark_metadata": metadata,
        "page_sha256": hashes,
        "spatial_graphs": deepcopy(state.spatial_graphs),
        "results": [record.model_dump(mode="json") for record in state.results],
        "ocr_candidates": [candidate.model_dump(mode="json") for candidate in state.ocr_candidates],
    }
