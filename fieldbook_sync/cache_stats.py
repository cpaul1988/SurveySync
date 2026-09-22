from __future__ import annotations
import logging

import json
import os
import threading
from pathlib import Path

_STATS_NAME = ".fbs_cache_stats.json"
_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}

def _lock_for(root: Path) -> threading.Lock:
    key = str(root.resolve())
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock

def _stats_path(root: Path) -> Path:
    return root / _STATS_NAME

def _write_stats(root: Path, entries: int, size_bytes: int) -> dict[str, int]:
    root.mkdir(parents=True, exist_ok=True)
    payload = {"entries": max(0, int(entries)), "size_bytes": max(0, int(size_bytes))}
    path = _stats_path(root)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(temp, path)
    return payload

def get_incremental_cache_stats(cache_dir: str | Path) -> dict[str, int]:
    """Return cache stats without walking the tree on normal state refreshes.

    Existing pre-v8.0.10 caches are scanned once to seed the metadata file. New
    writes/deletes update the metadata incrementally.
    """
    root = Path(cache_dir)
    lock = _lock_for(root)
    with lock:
        path = _stats_path(root)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return {"entries": max(0, int(data.get("entries", 0))), "size_bytes": max(0, int(data.get("size_bytes", 0)))}
            except Exception:
                logging.getLogger(__name__).warning("Recovery fallback in cache_stats; operation did not complete.", exc_info=True)
        entries = 0
        size_bytes = 0
        if root.exists():
            for item in root.rglob("*.json.gz"):
                try:
                    entries += 1
                    size_bytes += item.stat().st_size
                except OSError:
                    pass
        return _write_stats(root, entries, size_bytes)

def record_cache_write(cache_dir: str | Path, path: Path, *, existed_before: bool, old_size: int = 0) -> None:
    root = Path(cache_dir)
    lock = _lock_for(root)
    with lock:
        stats_path = _stats_path(root)
        if stats_path.exists():
            try:
                data = json.loads(stats_path.read_text(encoding="utf-8"))
                entries = int(data.get("entries", 0))
                size_bytes = int(data.get("size_bytes", 0))
            except Exception:
                entries = size_bytes = 0
        else:
            # First v8.0.10 write against a legacy cache: reconcile once after the
            # write so overwriting an existing entry cannot skew the count.
            entries = -1
            size_bytes = -1
        try:
            new_size = path.stat().st_size
        except OSError:
            return
        if entries < 0:
            entries = 0
            size_bytes = 0
            for item in root.rglob("*.json.gz"):
                try:
                    entries += 1
                    size_bytes += item.stat().st_size
                except OSError:
                    pass
        else:
            if not existed_before:
                entries += 1
            size_bytes += new_size - (old_size if existed_before else 0)
        _write_stats(root, entries, size_bytes)

def record_cache_delete(cache_dir: str | Path, *, old_size: int = 0) -> None:
    root = Path(cache_dir)
    lock = _lock_for(root)
    with lock:
        path = _stats_path(root)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = max(0, int(data.get("entries", 0)) - 1)
            size_bytes = max(0, int(data.get("size_bytes", 0)) - max(0, int(old_size)))
            _write_stats(root, entries, size_bytes)
        except Exception:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

def reset_cache_stats(cache_dir: str | Path) -> None:
    root = Path(cache_dir)
    lock = _lock_for(root)
    with lock:
        _write_stats(root, 0, 0)
