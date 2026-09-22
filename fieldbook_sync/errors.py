from __future__ import annotations

import errno
import re
import traceback
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    component: str
    severity: str
    recoverable: bool
    user_message: str
    detail: str


def classify_exception(exc: BaseException, component: str = "analysis") -> ErrorInfo:
    text = str(exc or "").strip()
    low = text.lower()
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-12000:]

    if "python314.dll" in low or "conflicts with this version of python" in low:
        return ErrorInfo(
            "OCR-ENV-001", "paddle", "ERROR", False,
            "PaddleOCR is using an incompatible Python environment. Repair PaddleOCR with Python 3.11-3.13.", detail,
        )
    if component == "qwen" or "ollama" in low or "qwen" in low:
        if "not installed" in low or ("model" in low and "not found" in low):
            return ErrorInfo(
                "QWN-MODEL-001", "qwen", "ERROR", True,
                text or "The selected Ollama model is not installed.", detail,
            )
        if "out of memory" in low or ("memory" in low and any(x in low for x in ("ollama", "qwen", "model"))):
            return ErrorInfo(
                "QWN-OOM-001", "qwen", "ERROR", True,
                text or "Ollama ran out of memory while loading or running the selected model.", detail,
            )
        if "timed out" in low or "timeout" in low:
            return ErrorInfo(
                "QWN-TIMEOUT-001", "qwen", "WARNING", True,
                text or "Local Qwen inference timed out. Completed OCR checkpoints were preserved.", detail,
            )
        if "unavailable" in low or "connection" in low or "service" in low and "ollama" in low:
            return ErrorInfo(
                "QWN-SVC-001", "qwen", "WARNING", True,
                text or "The local Ollama service is unavailable or the connection was interrupted.", detail,
            )
        if "warm-up" in low or "loading" in low:
            return ErrorInfo(
                "QWN-LOAD-001", "qwen", "WARNING", True,
                text or "The selected Ollama model did not finish loading.", detail,
            )
        if "parse" in low or "invalid json" in low or "structured json" in low:
            return ErrorInfo(
                "QWN-PARSE-001", "qwen", "WARNING", True,
                text or "Qwen returned an invalid structured response; the request can be retried.", detail,
            )
        if "http " in low:
            return ErrorInfo(
                "QWN-HTTP-001", "qwen", "ERROR", True,
                text or "Ollama returned an HTTP error.", detail,
            )
    if "out of memory" in low or "cuda error" in low and "memory" in low:
        return ErrorInfo(
            "AI-MEM-001", component, "ERROR", True,
            "The AI worker ran out of memory. FieldBook Sync can retry with a safer performance plan.", detail,
        )
    if "timed out" in low or "timeout" in low:
        return ErrorInfo(
            "AI-TIMEOUT-001", component, "WARNING", True,
            "The analysis worker stopped making progress and timed out. The affected work can be retried from its checkpoint.", detail,
        )
    if "connection" in low and any(x in low for x in ("refused", "reset", "aborted", "failed")):
        return ErrorInfo(
            "AI-CONN-001", component, "WARNING", True,
            "The local AI service connection was interrupted. FieldBook Sync can retry without discarding completed work.", detail,
        )
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in {errno.ENOSPC, 28}:
        return ErrorInfo(
            "SYS-DISK-001", "storage", "ERROR", True,
            "The drive is out of free space. Free disk space, then resume the job.", detail,
        )
    if isinstance(exc, PermissionError) or "permission denied" in low or "access is denied" in low:
        return ErrorInfo(
            "SYS-PERM-001", "storage", "ERROR", True,
            "Windows denied access to a required file or folder. Close programs using the files and check folder permissions.", detail,
        )
    if "paddleocr" in low or "paddle" in low:
        return ErrorInfo(
            "OCR-001", "paddle", "ERROR", True,
            text or "PaddleOCR failed. The job can resume from completed OCR checkpoints.", detail,
        )
    if "ollama" in low or "qwen" in low:
        return ErrorInfo(
            "QWN-001", "qwen", "ERROR", True,
            text or "Qwen/Ollama failed. Completed OCR work remains available for retry.", detail,
        )
    return ErrorInfo(
        "ANL-001", component, "ERROR", False,
        text or "Analysis failed unexpectedly.", detail,
    )


def error_payload(info: ErrorInfo, reference: str | None = None) -> dict[str, Any]:
    return {
        "code": info.code,
        "component": info.component,
        "severity": info.severity,
        "recoverable": info.recoverable,
        "message": info.user_message,
        "reference": reference,
    }
