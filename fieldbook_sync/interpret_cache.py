from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .ai_reader import ProviderUsage
from .cache_stats import get_incremental_cache_stats, record_cache_delete, record_cache_write, reset_cache_stats
from .models import PageEvidence, UnmatchedEvidence

# Bump whenever the Qwen crop prompt/schema or cache semantics change.
INTERPRETATION_CACHE_SCHEMA = "fbs-qwen-crop-v3-dip-status"


def _sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def interpretation_cache_key(
    image_path: str | Path,
    *,
    point_id: str,
    model: str,
    schema: str = INTERPRETATION_CACHE_SCHEMA,
) -> str:
    payload = "|".join([
        schema,
        _sha256_file(image_path),
        str(point_id).strip(),
        str(model).strip(),
    ]).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _cache_path(cache_dir: str | Path, key: str) -> Path:
    root = Path(cache_dir)
    return root / key[:2] / f"{key}.json.gz"


def load_interpretation_cache(cache_dir: str | Path, key: str) -> tuple[list[PageEvidence], list[UnmatchedEvidence], ProviderUsage] | None:
    path = _cache_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            wrapper = json.load(fh)
        if wrapper.get("schema") != INTERPRETATION_CACHE_SCHEMA:
            return None
        evidence = [PageEvidence.model_validate(x) for x in (wrapper.get("evidence") or [])]
        unmatched = [UnmatchedEvidence.model_validate(x) for x in (wrapper.get("unmatched") or [])]
        usage_data = wrapper.get("usage") or {}
        usage = ProviderUsage(
            requests=int(usage_data.get("requests") or 0),
            input_tokens=int(usage_data.get("input_tokens") or 0),
            output_tokens=int(usage_data.get("output_tokens") or 0),
            total_tokens=int(usage_data.get("total_tokens") or 0),
        )
        return evidence, unmatched, usage
    except Exception:
        try:
            old_size = path.stat().st_size if path.exists() else 0
            path.unlink(missing_ok=True)
            record_cache_delete(cache_dir, old_size=old_size)
        except OSError:
            pass
        return None


def save_interpretation_cache(
    cache_dir: str | Path,
    key: str,
    evidence: list[PageEvidence],
    unmatched: list[UnmatchedEvidence],
    usage: ProviderUsage | None = None,
) -> None:
    path = _cache_path(cache_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    usage = usage or ProviderUsage()
    payload: dict[str, Any] = {
        "schema": INTERPRETATION_CACHE_SCHEMA,
        "evidence": [x.model_dump(mode="json") for x in evidence],
        "unmatched": [x.model_dump(mode="json") for x in unmatched],
        # Usage is retained for diagnostics only. Cache hits deliberately do not add
        # these token/request counts to the current run because no inference occurred.
        "usage": {
            "requests": usage.requests,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        },
    }
    existed_before = path.exists()
    try:
        old_size = path.stat().st_size if existed_before else 0
    except OSError:
        old_size = 0
    try:
        with gzip.open(temp, "wt", encoding="utf-8", compresslevel=5) as fh:
            json.dump(payload, fh, ensure_ascii=False, default=str)
        os.replace(temp, path)
        record_cache_write(cache_dir, path, existed_before=existed_before, old_size=old_size)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def interpretation_cache_stats(cache_dir: str | Path) -> dict[str, int]:
    return get_incremental_cache_stats(cache_dir)


def clear_interpretation_cache(cache_dir: str | Path) -> None:
    root = Path(cache_dir)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    reset_cache_stats(root)

