"""Isolated PaddleOCR-VL 1.6 bridge used by SurveySync FieldBookSync.

The bridge runs inside SurveySync's isolated ``.paddleenv`` interpreter, keeps one
Paddle pipeline loaded, streams page-level events back to the main application,
retries individual page failures, and can use compatible GPU/HPI acceleration.
It is a required runtime asset for the evidence-first FieldBook analysis pipeline.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

PREFIX = "FBS_EVENT|"


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


_configure_utf8_stdio()


def emit(event: dict) -> None:
    # ASCII-safe transport prevents Windows ANSI consoles from failing on OCR text.
    print(PREFIX + json.dumps(event, ensure_ascii=True, default=str), flush=True)


def _parse_args(argv: list[str]) -> tuple[list[str], int, bool, bool, int]:
    paths: list[str] = []
    prefetch_pages = 2
    enable_hpi = False
    prefer_gpu = False
    page_retries = 2
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--manifest" and i + 1 < len(argv):
            manifest = Path(argv[i + 1])
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("Paddle manifest must contain a JSON list of image paths.")
            paths.extend(str(Path(x).resolve()) for x in data)
            i += 2
            continue
        if arg == "--prefetch-pages" and i + 1 < len(argv):
            prefetch_pages = max(1, min(16, int(argv[i + 1])))
            i += 2
            continue
        if arg == "--enable-hpi":
            enable_hpi = True
            i += 1
            continue
        if arg == "--prefer-gpu":
            prefer_gpu = True
            i += 1
            continue
        if arg == "--page-retries" and i + 1 < len(argv):
            page_retries = max(0, min(5, int(argv[i + 1])))
            i += 2
            continue
        paths.append(str(Path(arg).resolve()))
        i += 1
    return paths, prefetch_pages, enable_hpi, prefer_gpu, page_retries


def _warm_file(path: str) -> bytes:
    # Retaining the bytes in the Future keeps a bounded working set in RAM while
    # also warming Windows' filesystem cache. Paddle can then open the same path
    # without a second cold-disk read. The bytes are released after that page.
    return Path(path).read_bytes()


def _choose_device(prefer_gpu: bool) -> tuple[str, bool, str]:
    try:
        import paddle
        compiled = bool(getattr(paddle.device, "is_compiled_with_cuda", lambda: False)())
        count = int(paddle.device.cuda.device_count()) if compiled else 0
        if prefer_gpu and compiled and count > 0:
            return "gpu:0", True, str(getattr(paddle, "__version__", ""))
        return "cpu", False, str(getattr(paddle, "__version__", ""))
    except Exception:
        return "cpu", False, ""


def _create_pipeline(enable_hpi: bool, device: str):
    from paddleocr import PaddleOCRVL

    common = dict(
        pipeline_version="v1.6",
        use_doc_orientation_classify=True,
        use_doc_unwarping=True,
        use_layout_detection=True,
        device=device,
    )
    if enable_hpi:
        try:
            return PaddleOCRVL(enable_hpi=True, **common), True
        except Exception as exc:
            # HPI is an optional accelerator and can require extra runtime pieces on
            # some PaddleOCR releases.  Falling back to the normal engine preserves
            # accuracy and keeps the application usable.
            emit({"event": "warning", "message": f"HPI unavailable; using standard inference: {type(exc).__name__}: {exc}"})
    try:
        return PaddleOCRVL(**common), False
    except TypeError:
        # Compatibility with older PaddleOCR builds whose constructor did not yet
        # expose the device keyword.  Those builds choose GPU automatically when the
        # installed PaddlePaddle runtime supports it.
        common.pop("device", None)
        return PaddleOCRVL(**common), False


def main() -> int:
    try:
        paths, prefetch_pages, enable_hpi, prefer_gpu, page_retries = _parse_args(sys.argv)
    except Exception as exc:
        emit({"event": "fatal", "error": f"{type(exc).__name__}: {exc}"})
        return 2
    if not paths:
        emit({"event": "fatal", "error": "one or more image paths required"})
        return 2

    try:
        emit({"event": "initializing", "total": len(paths)})
        device, cuda_available, paddle_version = _choose_device(prefer_gpu)
        try:
            pipeline, hpi_active = _create_pipeline(enable_hpi, device)
        except Exception as exc:
            if device.startswith("gpu"):
                emit({
                    "event": "warning",
                    "message": f"GPU Paddle initialization failed; retrying on CPU: {type(exc).__name__}: {exc}",
                })
                device = "cpu"
                cuda_available = False
                pipeline, hpi_active = _create_pipeline(enable_hpi, device)
            else:
                raise
        emit({
            "event": "ready",
            "total": len(paths),
            "prefetch_pages": prefetch_pages,
            "device": device,
            "cuda_available": cuda_available,
            "paddle_version": paddle_version,
            "hpi": hpi_active,
        })

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="FBS-prefetch") as pool:
            warm: dict[int, Future[bytes]] = {}

            def fill_window(current: int) -> None:
                stop = min(len(paths), current + prefetch_pages)
                for idx in range(current, stop):
                    if idx not in warm:
                        warm[idx] = pool.submit(_warm_file, paths[idx])

            fill_window(0)
            for zero_index, path in enumerate(paths):
                index = zero_index + 1
                fill_window(zero_index)
                current_bytes = None
                future = warm.pop(zero_index, None)
                if future is not None:
                    try:
                        current_bytes = future.result()
                    except Exception:
                        current_bytes = None
                fill_window(zero_index + 1)

                emit({"event": "page_start", "index": index, "total": len(paths), "path": path})
                page_ok = False
                last_error = ""
                for attempt in range(1, page_retries + 2):
                    try:
                        results = list(pipeline.predict(path))
                        _ = current_bytes
                        if len(results) != 1:
                            raise RuntimeError(
                                f"PaddleOCR-VL returned {len(results)} result(s) for page {index}; expected exactly 1."
                            )
                        emit({
                            "event": "page_done",
                            "index": index,
                            "total": len(paths),
                            "attempt": attempt,
                            "result": results[0].json,
                        })
                        page_ok = True
                        break
                    except Exception as exc:
                        last_error = f"{type(exc).__name__}: {exc}"
                        low_error = last_error.lower()
                        if (
                            device.startswith("gpu")
                            and attempt <= page_retries
                            and ("out of memory" in low_error or "cuda" in low_error or "cudnn" in low_error)
                        ):
                            emit({
                                "event": "warning",
                                "message": f"GPU inference failed on page {index}; switching Paddle to CPU for recovery: {last_error}",
                            })
                            device = "cpu"
                            cuda_available = False
                            pipeline, hpi_active = _create_pipeline(enable_hpi, device)
                        if attempt <= page_retries:
                            emit({
                                "event": "page_retry", "index": index, "total": len(paths),
                                "attempt": attempt, "next_attempt": attempt + 1, "error": last_error,
                            })
                        else:
                            emit({
                                "event": "page_failed", "index": index, "total": len(paths),
                                "attempts": attempt, "error": last_error,
                            })
                if not page_ok:
                    # Page-level isolation: a single corrupt/difficult page does not kill
                    # a 181-page job. The parent records it for review and Hybrid's
                    # full-page Qwen fallback can still attempt to recover missing IDs.
                    continue

        emit({"event": "complete", "total": len(paths)})
        return 0
    except Exception as exc:
        emit({"event": "fatal", "error": f"{type(exc).__name__}: {exc}"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
