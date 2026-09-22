from __future__ import annotations
import logging

import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import queue
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from PIL import Image

from .models import DipStatus, FieldBookPage, OcrCandidate, PageEvidence
from .survey import normalize_point_id
from .performance import build_performance_plan
from .cache_stats import get_incremental_cache_stats, record_cache_delete, record_cache_write, reset_cache_stats




class PaddleCancelled(RuntimeError):
    """Raised when a streamed PaddleOCR job is cancelled by FieldBook Sync."""


@dataclass(frozen=True)
class PaddleStatus:
    installed: bool
    python_path: str | None
    message: str
    verified: bool = False
    device: str = "unknown"
    cuda_available: bool = False
    paddle_version: str = ""


def paddle_python_path(app_root: Path) -> Path:
    if os.name == "nt":
        return app_root / ".paddleenv" / "Scripts" / "python.exe"
    return app_root / ".paddleenv" / "bin" / "python"


def paddle_bridge_path(app_root: Path) -> Path:
    """Return the packaged Paddle worker bridge path.

    Source/installer builds place the bridge beside SurveySync.exe. Frozen fallback
    support is retained for compatibility with historical packaged builds.
    """
    bridge = app_root / "paddle_bridge.py"
    if bridge.exists():
        return bridge
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        frozen = Path(frozen_root) / "paddle_bridge.py"
        if frozen.exists():
            return frozen
    return bridge


_PADDLE_STATUS_CACHE_LOCK = threading.Lock()
_PADDLE_STATUS_CACHE: tuple[str, float, PaddleStatus] | None = None
_PADDLE_STATUS_TTL_SECONDS = 600.0


_PADDLE_SUPPORTED_MIN = (3, 11)
_PADDLE_SUPPORTED_MAX = (3, 13)


def _venv_version_from_cfg(env_root: Path) -> tuple[int, int] | None:
    """Read a Windows/venv Python major.minor without starting the interpreter."""
    cfg = env_root / "pyvenv.cfg"
    if not cfg.exists():
        return None
    try:
        for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("version") and "=" in line:
                value = line.split("=", 1)[1].strip()
                match = re.match(r"(\d+)\.(\d+)", value)
                if match:
                    return int(match.group(1)), int(match.group(2))
    except OSError:
        return None
    return None


def _paddle_subprocess_env(app_root: Path, cpu_threads: int | None = None) -> dict[str, str]:
    """Return a clean environment for the isolated Paddle interpreter.

    A common Windows failure mode is a Python 3.13 Paddle venv inheriting Python 3.14
    PYTHONHOME/PYTHONPATH/PATH entries from the launcher. Native extensions can then
    resolve python314.dll while the child interpreter is Python 3.13, producing:
    "Module use of python314.dll conflicts with this version of Python."  We keep the
    process isolated and remove only the conflicting Python 3.14 hints.
    """
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    # Force a deterministic UTF-8 text channel between the main app and the
    # isolated Paddle worker.  Windows otherwise inherits the active ANSI code
    # page (often cp1252), which cannot represent OCR text such as Chinese,
    # Japanese, accented, or other non-Latin characters.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if cpu_threads:
        # Bound native math-library threading to the hardware-aware plan. This lets
        # Paddle use multiple CPU cores without allowing every dependency to spawn
        # an unbounded thread pool of its own.
        threads = str(max(1, int(cpu_threads)))
        env["OMP_NUM_THREADS"] = threads
        env["MKL_NUM_THREADS"] = threads
        env["OPENBLAS_NUM_THREADS"] = threads
        env["NUMEXPR_NUM_THREADS"] = threads
        env["VECLIB_MAXIMUM_THREADS"] = threads
    expected = _venv_version_from_cfg(app_root / ".paddleenv")
    if os.name == "nt" and expected and expected <= _PADDLE_SUPPORTED_MAX:
        path_parts = []
        for part in env.get("PATH", "").split(os.pathsep):
            low = part.lower().replace("/", "\\")
            if "python314" in low or "python3.14" in low:
                continue
            path_parts.append(part)
        env["PATH"] = os.pathsep.join(path_parts)
    return env


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    """Prevent helper Python processes from flashing a console window on Windows.

    FieldBook Sync is packaged as a windowed app.  Without CREATE_NO_WINDOW, starting
    the isolated Paddle Python interpreter can create a large blank console window even
    when stdout/stderr are captured.
    """
    if os.name != "nt":
        return {}
    kwargs: dict[str, Any] = {}
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        kwargs["creationflags"] = create_no_window
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_cls is not None:
        startupinfo = startupinfo_cls()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs


def paddle_status(
    app_root: Path,
    *,
    verify_import: bool = True,
    force: bool = False,
    timeout: int = 45,
) -> PaddleStatus:
    """Return Paddle environment status without repeatedly paying the import cost.

    ``verify_import=False`` is a fast filesystem-only health check for background UI
    refreshes.  A successful full import check is cached for ten minutes.  The explicit
    Check Installation button uses ``force=True`` so the user can re-test immediately
    after installing or repairing Paddle.
    """
    global _PADDLE_STATUS_CACHE
    py = paddle_python_path(app_root)
    if not py.exists():
        return PaddleStatus(False, None, "PaddleOCR-VL is not installed. Run install_paddleocr_auto.bat.", False)

    env_version = _venv_version_from_cfg(app_root / ".paddleenv")
    if env_version and not (_PADDLE_SUPPORTED_MIN <= env_version <= _PADDLE_SUPPORTED_MAX):
        version_text = f"{env_version[0]}.{env_version[1]}"
        return PaddleStatus(
            False,
            str(py),
            f"PaddleOCR environment uses Python {version_text}, which is not supported by the current PaddlePaddle Windows runtime. "
            "Run Repair_PaddleOCR_Environment.bat to rebuild only the Paddle environment with Python 3.11-3.13.",
            False,
        )

    if not verify_import:
        return PaddleStatus(True, str(py), "PaddleOCR environment found. Click Check installation for a full import test.", False)

    cache_key = str(py.resolve())
    now = time.monotonic()
    if not force:
        with _PADDLE_STATUS_CACHE_LOCK:
            cached = _PADDLE_STATUS_CACHE
            if cached and cached[0] == cache_key and (now - cached[1]) < _PADDLE_STATUS_TTL_SECONDS:
                return cached[2]

    try:
        probe_code = (
            "import json, paddle; from paddleocr import PaddleOCRVL; "
            "cuda=bool(getattr(paddle.device,'is_compiled_with_cuda',lambda:False)()); "
            "count=int(paddle.device.cuda.device_count()) if cuda else 0; "
            "print(json.dumps({'ok':True,'paddle_version':getattr(paddle,'__version__',''),"
            "'cuda':cuda,'device_count':count}))"
        )
        probe = subprocess.run(
            [str(py), "-c", probe_code],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, stdin=subprocess.DEVNULL,
            env=_paddle_subprocess_env(app_root),
            **_hidden_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return PaddleStatus(False, str(py), f"PaddleOCR import check timed out after {timeout} seconds.", False)
    except OSError as exc:
        return PaddleStatus(False, str(py), f"Could not start PaddleOCR Python: {exc}", False)

    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "PaddleOCR import failed").strip()[-500:]
        return PaddleStatus(False, str(py), detail, False)

    info = {}
    try:
        for line in reversed((probe.stdout or "").splitlines()):
            line = line.strip()
            if line.startswith("{"):
                info = json.loads(line)
                break
    except Exception:
        info = {}
    cuda_available = bool(info.get("cuda")) and int(info.get("device_count") or 0) > 0
    device = "gpu" if cuda_available else "cpu"
    paddle_version = str(info.get("paddle_version") or "")
    message = f"PaddleOCR-VL 1.6 environment is ready on {device.upper()}."
    status = PaddleStatus(True, str(py), message, True, device, cuda_available, paddle_version)
    with _PADDLE_STATUS_CACHE_LOCK:
        _PADDLE_STATUS_CACHE = (cache_key, now, status)
    return status


def _normalize_bbox_pixels(box: Any, width: int, height: int) -> list[int] | None:
    if not isinstance(box, (list, tuple)):
        return None
    # rect: [x1,y1,x2,y2]; quad/poly: [[x,y], ...]
    if len(box) == 4 and all(isinstance(x, (int, float)) for x in box):
        x1, y1, x2, y2 = [float(x) for x in box]
    else:
        pts = []
        for p in box:
            if isinstance(p, (list, tuple)) and len(p) >= 2 and all(isinstance(x, (int, float)) for x in p[:2]):
                pts.append((float(p[0]), float(p[1])))
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
    if width <= 0 or height <= 0:
        return None
    vals = [round(x1 / width * 1000), round(y1 / height * 1000), round(x2 / width * 1000), round(y2 / height * 1000)]
    return [max(0, min(1000, int(v))) for v in vals]


def _extract_blocks(payload: Any) -> list[dict]:
    blocks: list[dict] = []
    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if isinstance(obj.get("parsing_res_list"), list):
                for item in obj["parsing_res_list"]:
                    if isinstance(item, dict):
                        blocks.append(item)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(payload)
    # de-duplicate blocks that appear in nested pruned/full result copies.
    unique = []
    seen = set()
    for block in blocks:
        key = (str(block.get("block_content", "")), json.dumps(block.get("block_bbox"), sort_keys=True, default=str))
        if key not in seen:
            seen.add(key)
            unique.append(block)
    return unique


def _parse_bridge_output(proc: subprocess.CompletedProcess[str]) -> dict:
    candidates = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("{")]
    if not candidates:
        detail = (proc.stderr or proc.stdout or "No PaddleOCR result").strip()[-1000:]
        raise RuntimeError(f"PaddleOCR-VL did not return JSON: {detail}")
    try:
        data = json.loads(candidates[-1])
    except Exception as exc:
        raise RuntimeError("Could not parse PaddleOCR-VL bridge output.") from exc
    if not data.get("ok"):
        raise RuntimeError(data.get("error") or "PaddleOCR-VL failed.")
    return data



_OCR_CACHE_SCHEMA = "fbs-paddle-v807-cache-v1"


def _sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _ocr_cache_key(image_path: str | Path) -> str:
    # OCR payloads depend only on the rendered/enhanced page bytes and the bridge
    # schema/pipeline configuration, not on the selected survey profile or PointIDs.
    raw = f"{_OCR_CACHE_SCHEMA}|{_sha256_file(image_path)}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / key[:2] / f"{key}.json.gz"


def _load_cached_payload(cache_dir: Path, key: str) -> dict | None:
    path = _cache_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            wrapper = json.load(fh)
        if wrapper.get("schema") != _OCR_CACHE_SCHEMA or not isinstance(wrapper.get("payload"), dict):
            return None
        return wrapper["payload"]
    except Exception:
        # A partial/corrupt cache entry is never fatal; discard it and re-run OCR.
        try:
            old_size = path.stat().st_size if path.exists() else 0
            path.unlink(missing_ok=True)
            record_cache_delete(cache_dir, old_size=old_size)
        except OSError:
            pass
        return None


def _save_cached_payload(cache_dir: Path, key: str, payload: dict) -> None:
    path = _cache_path(cache_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    existed_before = path.exists()
    try:
        old_size = path.stat().st_size if existed_before else 0
    except OSError:
        old_size = 0
    try:
        with gzip.open(temp, "wt", encoding="utf-8", compresslevel=5) as fh:
            json.dump({"schema": _OCR_CACHE_SCHEMA, "payload": payload}, fh, ensure_ascii=False, default=str)
        os.replace(temp, path)
        record_cache_write(cache_dir, path, existed_before=existed_before, old_size=old_size)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def ocr_cache_stats(cache_dir: str | Path) -> dict[str, int]:
    return get_incremental_cache_stats(cache_dir)


def clear_ocr_cache(cache_dir: str | Path) -> None:
    import shutil
    root = Path(cache_dir)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    reset_cache_stats(root)

def run_paddle_pages(
    pages: Sequence[FieldBookPage],
    app_root: Path,
    timeout: int = 3600,
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
    page_callback: Callable[[int, FieldBookPage, dict, bool], None] | None = None,
    page_error_callback: Callable[[int, FieldBookPage, str, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    cache_dir: str | Path | None = None,
    performance_mode: str = "auto",
) -> list[dict]:
    """Run PaddleOCR-VL once and stream individual page results back to the caller.

    v8.0.7 keeps one Paddle pipeline loaded, streams page results as they complete,
    checkpoints each completed page to a persistent content-addressed cache, and
    resumes after cancellation/crash by processing only uncached pages. A bounded
    RAM prefetch window and hardware-aware native thread limits improve throughput
    without loading multiple multi-gigabyte OCR models.
    """
    if not pages:
        return []
    status = paddle_status(app_root)
    if not status.installed or not status.python_path:
        raise RuntimeError(status.message)
    bridge = paddle_bridge_path(app_root)
    if not bridge.exists():
        raise RuntimeError("SurveySync's PaddleOCR bridge is missing. Repair or reinstall SurveySync.")

    image_paths = [
        p.enhanced_image_path if p.enhanced_image_path and Path(p.enhanced_image_path).exists() else p.image_path
        for p in pages
    ]
    plan = build_performance_plan(performance_mode)
    cache_root = Path(cache_dir) if cache_dir else None
    results: list[dict | None] = [None] * len(pages)
    cache_keys: list[str | None] = [None] * len(pages)
    missing_indices: list[int] = []
    cached_count = 0

    # Cache lookup is intentionally performed before starting the heavyweight Paddle
    # process. A prior crash/cancel therefore resumes from the first uncached page.
    if cache_root and plan.cache_enabled:
        cache_root.mkdir(parents=True, exist_ok=True)
        for original_index, image_path in enumerate(image_paths):
            if cancel_check and cancel_check():
                raise PaddleCancelled("PaddleOCR analysis cancelled.")
            try:
                key = _ocr_cache_key(image_path)
                cache_keys[original_index] = key
                cached = _load_cached_payload(cache_root, key)
            except OSError:
                cached = None
            if cached is not None:
                results[original_index] = cached
                cached_count += 1
                if page_callback:
                    page_callback(original_index + 1, pages[original_index], cached, True)
            else:
                missing_indices.append(original_index)
    else:
        missing_indices = list(range(len(pages)))

    if progress_callback and cached_count:
        progress_callback(cached_count, len(pages), f"PaddleOCR-VL 1.6: restored {cached_count}/{len(pages)} page(s) from OCR cache")
    if not missing_indices:
        if progress_callback:
            progress_callback(len(pages), len(pages), f"PaddleOCR-VL 1.6: all {len(pages)} page(s) restored from OCR cache")
        return [result or {} for result in results]

    missing_paths = [image_paths[i] for i in missing_indices]
    manifest_path: str | None = None
    proc: subprocess.Popen[str] | None = None
    output_tail: list[str] = []
    event_queue: queue.Queue[str | None] = queue.Queue()
    run_started = time.monotonic()

    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="fbs_paddle_", delete=False, encoding="utf-8") as mf:
            json.dump(missing_paths, mf, ensure_ascii=False)
            manifest_path = mf.name

        proc = subprocess.Popen(
            [
                status.python_path, "-u", str(bridge), "--manifest", manifest_path,
                "--prefetch-pages", str(plan.prefetch_pages),
                *( ["--enable-hpi"] if plan.enable_hpi else [] ),
                *( ["--prefer-gpu"] if plan.prefer_gpu else [] ),
                "--page-retries", "2",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            stdin=subprocess.DEVNULL,
            env=_paddle_subprocess_env(app_root, plan.paddle_cpu_threads),
            **_hidden_subprocess_kwargs(),
        )

        def _reader() -> None:
            try:
                assert proc is not None and proc.stdout is not None
                for raw_line in proc.stdout:
                    event_queue.put(raw_line.rstrip("\r\n"))
            finally:
                event_queue.put(None)

        threading.Thread(target=_reader, name="PaddleOCR-stream-reader", daemon=True).start()

        prefix = "FBS_EVENT|"
        completed_new = 0
        failed_new = 0
        retry_events = 0
        last_activity = time.monotonic()
        stream_ended = False

        while not stream_ended:
            if cancel_check and cancel_check():
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                raise PaddleCancelled("PaddleOCR analysis cancelled.")

            try:
                line = event_queue.get(timeout=0.25)
            except queue.Empty:
                if proc.poll() is not None:
                    # Give the reader thread one final chance to enqueue buffered output.
                    try:
                        line = event_queue.get(timeout=0.25)
                    except queue.Empty:
                        break
                else:
                    if timeout and (time.monotonic() - last_activity) > timeout:
                        proc.kill()
                        raise RuntimeError(
                            f"PaddleOCR-VL produced no progress for {timeout} seconds and was stopped."
                        )
                    continue

            if line is None:
                stream_ended = True
                continue
            last_activity = time.monotonic()
            if line:
                output_tail.append(line)
                if len(output_tail) > 60:
                    del output_tail[:-60]
            if not line.startswith(prefix):
                continue

            try:
                event = json.loads(line[len(prefix):])
            except json.JSONDecodeError:
                continue
            kind = event.get("event")
            worker_total = int(event.get("total") or len(missing_indices))
            total = len(pages)

            if kind == "initializing":
                if progress_callback:
                    progress_callback(cached_count, total, f"PaddleOCR-VL 1.6: loading OCR model · {cached_count} cached · {len(missing_indices)} remaining")
            elif kind == "ready":
                if progress_callback:
                    first_original = missing_indices[0] + 1
                    device = str(event.get("device") or status.device or "cpu").upper()
                    hpi = "HPI" if event.get("hpi") else "standard"
                    progress_callback(cached_count, total, f"PaddleOCR-VL 1.6: model ready on {device} ({hpi}) · processing page {first_original}/{total}")
            elif kind == "page_start":
                local_idx = int(event.get("index") or 0)
                if not (1 <= local_idx <= len(missing_indices)):
                    raise RuntimeError(f"PaddleOCR-VL returned an invalid page index: {local_idx}.")
                original_idx = missing_indices[local_idx - 1]
                if progress_callback:
                    progress_callback(cached_count + completed_new, total, f"PaddleOCR-VL 1.6: processing page {original_idx + 1}/{total} · {cached_count} cached")
            elif kind == "page_done":
                local_idx = int(event.get("index") or 0)
                if not (1 <= local_idx <= len(missing_indices)):
                    raise RuntimeError(f"PaddleOCR-VL returned an invalid page index: {local_idx}.")
                original_idx = missing_indices[local_idx - 1]
                payload = event.get("result") or {}
                results[original_idx] = payload
                completed_new += 1
                if cache_root and cache_keys[original_idx]:
                    try:
                        _save_cached_payload(cache_root, cache_keys[original_idx] or "", payload)
                    except OSError:
                        pass
                if page_callback:
                    page_callback(original_idx + 1, pages[original_idx], payload, False)
                if progress_callback:
                    elapsed = max(0.001, time.monotonic() - run_started)
                    sec_per_page = elapsed / max(1, completed_new)
                    remaining = max(0, len(missing_indices) - completed_new)
                    eta = int(round(sec_per_page * remaining))
                    progress_callback(
                        cached_count + completed_new, total,
                        f"PaddleOCR-VL 1.6: indexed page {original_idx + 1}/{total} · {sec_per_page:.1f}s/page · ETA {eta // 60}m {eta % 60:02d}s"
                    )
            elif kind == "page_retry":
                retry_events += 1
                local_idx = int(event.get("index") or 0)
                if 1 <= local_idx <= len(missing_indices) and progress_callback:
                    original_idx = missing_indices[local_idx - 1]
                    progress_callback(
                        cached_count + completed_new + failed_new, total,
                        f"PaddleOCR-VL 1.6: retrying page {original_idx + 1}/{total} · attempt {event.get('next_attempt') or '?'}"
                    )
            elif kind == "page_failed":
                local_idx = int(event.get("index") or 0)
                if not (1 <= local_idx <= len(missing_indices)):
                    raise RuntimeError(f"PaddleOCR-VL returned an invalid failed-page index: {local_idx}.")
                original_idx = missing_indices[local_idx - 1]
                error_text = str(event.get("error") or "PaddleOCR-VL page failed after retries.")
                attempts = int(event.get("attempts") or 1)
                # An empty payload marks this page as handled-but-failed so the remaining
                # pages can continue. It is deliberately not written to OCR cache.
                results[original_idx] = {}
                failed_new += 1
                if page_error_callback:
                    page_error_callback(original_idx + 1, pages[original_idx], error_text, attempts)
                if progress_callback:
                    progress_callback(
                        cached_count + completed_new + failed_new, total,
                        f"PaddleOCR-VL 1.6: page {original_idx + 1}/{total} needs review after {attempts} attempts · continuing"
                    )
            elif kind == "fatal":
                raise RuntimeError(event.get("error") or "PaddleOCR-VL failed.")
            elif kind == "complete":
                # The reader may still have a final line to flush; completion is advisory.
                pass

        rc = proc.wait(timeout=10)
        missing = [i + 1 for i, result in enumerate(results) if result is None]
        if rc != 0:
            detail = "\n".join(output_tail[-20:]).strip()
            raise RuntimeError(f"PaddleOCR-VL exited with code {rc}: {detail[-2000:]}")
        if missing:
            sample = ", ".join(map(str, missing[:10]))
            more = "…" if len(missing) > 10 else ""
            raise RuntimeError(f"PaddleOCR-VL did not return results for page(s): {sample}{more}")
        return [result or {} for result in results]
    finally:
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    logging.getLogger(__name__).warning("Recovery fallback in ocr_local; operation did not complete.", exc_info=True)
        if manifest_path:
            try:
                Path(manifest_path).unlink(missing_ok=True)
            except OSError:
                pass


def run_paddle_page(page: FieldBookPage, app_root: Path, timeout: int = 900) -> dict:
    return {"ok": True, "results": run_paddle_pages([page], app_root, timeout=timeout)}


def _edit_distance_at_most_one(a: str, b: str) -> bool:
    """Return True only for strings with Levenshtein distance exactly/at most one.

    Used only as an *OCR routing hint*.  A near match never becomes final evidence
    unless Qwen visually confirms the exact target PointID; otherwise the normal
    full-page accuracy fallback still runs.
    """
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(ch1 != ch2 for ch1, ch2 in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    # b is exactly one char longer
    i = j = mismatches = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1; j += 1
        else:
            mismatches += 1
            j += 1
            if mismatches > 1:
                return False
    return True


def locate_target_ids(
    page: FieldBookPage,
    payload: dict,
    target_point_ids: Sequence[str],
    *,
    include_near_matches: bool = False,
) -> list[OcrCandidate]:
    targets = {normalize_point_id(x) for x in target_point_ids if normalize_point_id(x)}
    analysis_path = page.enhanced_image_path if page.enhanced_image_path and Path(page.enhanced_image_path).exists() else page.image_path
    with Image.open(analysis_path) as im:
        width, height = im.size
    found: list[OcrCandidate] = []
    for block in _extract_blocks(payload):
        text = str(block.get("block_content") or "")
        if not text:
            continue
        # Field PointIDs are predominantly numeric, but normalization also supports text IDs.
        tokens = re.findall(r"[A-Za-z0-9._-]+", text)
        matches: list[tuple[str, str, bool]] = []
        token_norms: list[tuple[str, str]] = []
        for token in tokens:
            normalized = normalize_point_id(token)
            if not normalized:
                continue
            token_norms.append((token, normalized))
            if normalized in targets:
                matches.append((token, normalized, True))
        if not matches:
            # Fall back to exact substring matching for IDs separated by punctuation OCR omitted.
            for target in targets:
                if target and re.search(rf"(?<![A-Za-z0-9]){re.escape(target)}(?![A-Za-z0-9])", text, flags=re.I):
                    matches.append((target, target, True))

        # Accuracy-first near-match routing.  Long PointIDs that Paddle misses by a
        # single character can still provide an excellent bbox for Qwen.  Only add a
        # routing hint when exactly one target is within edit distance 1; the hint is
        # never considered an exact match and never suppresses the full-page fallback
        # unless Qwen subsequently confirms that target visually.
        if include_near_matches:
            exact_targets = {m[1] for m in matches if m[2]}
            for raw_token, normalized in token_norms:
                if normalized in targets or len(normalized) < 4:
                    continue
                plausible = [
                    target for target in targets
                    if target not in exact_targets and len(target) >= 4 and _edit_distance_at_most_one(normalized, target)
                ]
                if len(plausible) == 1:
                    matches.append((raw_token, plausible[0], False))

        bbox = _normalize_bbox_pixels(block.get("block_bbox"), width, height)
        for raw, point_id, exact in matches:
            found.append(OcrCandidate(
                page_id=page.page_id,
                source_name=page.source_name,
                page_number=page.page_number,
                point_id=point_id,
                raw_text=text[:1200],
                confidence=0.98 if exact else 0.70,
                bbox=bbox,
                engine="PaddleOCR-VL-1.6" if exact else "PaddleOCR-VL-1.6 near-match routing",
                exact_match=exact,
            ))
    # One page/block may expose the same ID multiple times. Keep the first unique bbox/text.
    deduped = []
    seen = set()
    for c in found:
        key = (c.page_id, c.point_id, tuple(c.bbox or []), c.raw_text)
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


_NUM_TOKEN = r"[0-9]{1,3}(?:\.[0-9]+)?"
_NUM = rf"({_NUM_TOKEN})"
_PIPE_MATERIAL = r"RCP|PVC|CMP|HDPE|VCP|DIP"


def _numeric_hits(patterns: Sequence[str], text: str) -> list[float]:
    values: list[float] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            try:
                values.append(float(match.group(1)))
            except (ValueError, IndexError):
                pass
    return values


def _overlaps(span: tuple[int, int], spans: Sequence[tuple[int, int]]) -> bool:
    return any(span[0] < other[1] and other[0] < span[1] for other in spans)


def _dedupe_numbers(values: Sequence[float]) -> list[float]:
    """De-duplicate the same OCR number found by overlapping conservative patterns."""
    out: list[float] = []
    for value in values:
        if not any(abs(value - prior) < 1e-9 for prior in out):
            out.append(value)
    return out


def _comparison_measurements(text: str) -> tuple[list[float], list[float], list[float]]:
    """Extract only measurements that are clear enough for cross-model QA.

    ``DIP`` is ambiguous in survey field books: it can be the *dip/depth* label or the
    material abbreviation for *Ductile Iron Pipe*.  The cross-model checker must never
    turn that lexical ambiguity into a false disagreement.  We therefore classify a
    ``DIP`` token contextually and protect tokens already used as a dip label from the
    pipe-material parser (and vice versa).
    """
    text = text or ""
    dips: list[float] = []
    diameters: list[float] = []
    protected_dip_label_spans: list[tuple[int, int]] = []

    # Value-first field-book notation, e.g. ``4.20 DIP`` or ``4' DEPTH``.
    # Bare integer ``12 DIP`` is deliberately *not* considered a dip measurement because
    # that is common and valid notation for a 12-inch Ductile Iron Pipe.  Decimal values,
    # explicit depth wording, or a depth unit make the measurement interpretation strong.
    suffix_dip = re.compile(
        rf"(?P<value>{_NUM_TOKEN})\s*(?P<unit>ft\.?|feet|foot|['’])?\s*\b(?P<label>dip|depth)\b",
        flags=re.I,
    )
    for match in suffix_dip.finditer(text):
        raw_value = match.group("value")
        label = match.group("label").casefold()
        strong = bool(match.group("unit")) or label == "depth" or "." in raw_value
        if not strong:
            continue
        dips.append(float(raw_value))
        protected_dip_label_spans.append(match.span("label"))

    # Label-first notation, e.g. ``DIP 4.20`` or ``DEPTH: 4.20``.  If the same DIP token
    # was already classified as the suffix label in ``4.20 DIP 15 RCP``, do not reinterpret
    # it as the prefix label for the following 15.  Also avoid treating a DIP token directly
    # preceded by a numeric value as a fresh label; that numeric+DIP pair may be pipe material.
    prefix_dip = re.compile(
        rf"\b(?P<label>dip|depth)\b\s*[:=#-]?\s*(?P<value>{_NUM_TOKEN})",
        flags=re.I,
    )
    for match in prefix_dip.finditer(text):
        label_span = match.span("label")
        if _overlaps(label_span, protected_dip_label_spans):
            continue
        label = match.group("label").casefold()
        if label == "dip":
            before = text[max(0, label_span[0] - 16):label_span[0]]
            # ``12 DIP 4.20`` is materially ambiguous; do not use DIP as a measurement
            # label when a number sits immediately before it.  Returning less evidence is
            # safer than manufacturing a deterministic disagreement.
            if re.search(rf"(?<![0-9.]){_NUM_TOKEN}\s*(?:[\"”]|in(?:ch(?:es)?)?)?\s*$", before, flags=re.I):
                continue
        dips.append(float(match.group("value")))

    # Explicit inch notation is unambiguous regardless of material.
    for match in re.finditer(rf"(?P<value>{_NUM_TOKEN})\s*(?:[\"”]|in(?:ch(?:es)?)?\b)", text, flags=re.I):
        diameters.append(float(match.group("value")))

    # Material-adjacent diameter notation.  For ``DIP`` specifically, skip the match if
    # that DIP token has already been classified as a dip/depth label above.
    material_diameter = re.compile(
        rf"\b(?P<value>{_NUM_TOKEN})\s*(?P<material>{_PIPE_MATERIAL})\b",
        flags=re.I,
    )
    for match in material_diameter.finditer(text):
        if match.group("material").casefold() == "dip" and _overlaps(match.span("material"), protected_dip_label_spans):
            continue
        diameters.append(float(match.group("value")))

    azimuths = _numeric_hits([
        rf"\b(?:az|azi|azimuth)\s*[:=#-]?\s*{_NUM}",
    ], text)
    return _dedupe_numbers(dips), _dedupe_numbers(diameters), _dedupe_numbers(azimuths)

def compare_ocr_to_evidence(text: str, evidence: PageEvidence) -> tuple[bool | None, str]:
    """Compare clearly labeled PaddleOCR text with Qwen structured extraction.

    This is deliberately conservative. If OCR did not expose a labeled dip/diameter/azimuth
    or explicit dipped/not-dipped phrase, it returns None rather than claiming two models
    agreed. Any extracted field that conflicts with Qwen returns False and is routed to REVIEW.
    """
    text = text or ""
    dips, diameters, azimuths = _comparison_measurements(text)
    # Single-letter D is only accepted with an explicit separator (D:4.20 / D=4.20).
    # Keep this legacy shorthand separate from DIP so the material abbreviation cannot
    # bleed into the depth-label parser.
    dips = _dedupe_numbers(dips + _numeric_hits([rf"\bD\s*[:=#]\s*{_NUM}"], text))
    explicit_cna = bool(re.search(r"\b(?:CNA|could\s+not\s+access|cannot\s+access|couldn['’]?t\s+access)\b", text, flags=re.I))
    explicit_cnl = bool(re.search(r"\b(?:CNL|could\s+not\s+locate|cannot\s+locate|couldn['’]?t\s+locate)\b", text, flags=re.I))
    explicit_no = bool(re.search(r"\b(?:not\s+dipped|no\s+dips?|no\s+dip|not\s+opened|N/?D)\b", text, flags=re.I))
    explicit_yes = bool(re.search(r"\b(?:dipped|opened)\b", text, flags=re.I)) and not (explicit_no or explicit_cna or explicit_cnl)

    if not (dips or diameters or azimuths or explicit_no or explicit_yes or explicit_cna or explicit_cnl):
        return None, "PaddleOCR located the PointID but did not expose labeled measurement text for independent comparison."

    q_pipes = evidence.pipes or []
    q_dips = [p.dip for p in q_pipes if p.dip is not None]
    q_diams = [p.diameter_in for p in q_pipes if p.diameter_in is not None]
    q_az = [p.azimuth_deg for p in q_pipes if p.azimuth_deg is not None]

    def every_near(values: Sequence[float], qvalues: Sequence[float], tol: float, circular: bool = False) -> bool:
        if not values:
            return True
        if not qvalues:
            return False
        for value in values:
            if circular:
                if not any(abs((value - q + 180) % 360 - 180) <= tol for q in qvalues):
                    return False
            elif not any(abs(value - q) <= tol for q in qvalues):
                return False
        return True

    checks = [
        every_near(dips, q_dips, 0.08),
        every_near(diameters, q_diams, 0.75),
        every_near(azimuths, q_az, 3.0, circular=True),
    ]
    if explicit_no:
        checks.append(evidence.dipped == DipStatus.NO)
    if explicit_cna:
        checks.append(evidence.dipped == DipStatus.CNA)
    if explicit_cnl:
        checks.append(evidence.dipped == DipStatus.CNL)
    if explicit_yes:
        checks.append(evidence.dipped == DipStatus.YES)
    agree = all(checks)
    summary = []
    if dips: summary.append("dip=" + ",".join(f"{v:g}" for v in dips))
    if diameters: summary.append("diameter=" + ",".join(f"{v:g}" for v in diameters))
    if azimuths: summary.append("azimuth=" + ",".join(f"{v:g}" for v in azimuths))
    if explicit_no: summary.append("explicit NOT DIPPED")
    if explicit_cna: summary.append("CNA (Could Not Access)")
    if explicit_cnl: summary.append("CNL (Could Not Locate)")
    if explicit_yes: summary.append("explicit DIPPED")
    return agree, "PaddleOCR comparison: " + "; ".join(summary)
