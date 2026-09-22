from __future__ import annotations

"""Shared local-AI runtime for SurveySync.

The module is intentionally dependency-optional.  SurveySync can run without any of
Microsoft's local AI components; Automatic mode simply falls through to the existing
local FieldBook engine.  On Windows, optional packages installed by Setup expose:

* Windows AI TextRecognizer (OCR) through PyWinRT / Windows App SDK.
* Microsoft Foundry Local for hardware-aware, on-device multimodal inference.

No cloud endpoint is used by this module.
"""

import asyncio
import base64
import io
import json
import logging
import os
import platform

logger = logging.getLogger(__name__)
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import requests
from PIL import Image, ImageOps


WINDOWS_AI_PACKAGE_HINT = (
    "Windows AI Python bindings are not installed. Re-run SurveySync Setup 9.1.0 or later."
)
FOUNDRY_PACKAGE_HINT = (
    "Microsoft Foundry Local support is not installed. Re-run SurveySync Setup 9.1.0 or later."
)
DEFAULT_FOUNDRY_VISION_MODEL = "qwen3.5-vision"


@dataclass(frozen=True)
class ComponentStatus:
    id: str
    name: str
    installed: bool = False
    supported: bool = False
    ready: bool = False
    needs_download: bool = False
    local_only: bool = True
    detail: str = ""
    state: str = "unavailable"
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AutoPlan:
    requested: str
    effective_provider: str
    ocr_provider: str
    vision_provider: str
    label: str
    reason: str
    local_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_status_lock = threading.RLock()
_status_cache: tuple[float, dict[str, Any]] | None = None
_foundry_lock = threading.RLock()
_foundry_manager: Any = None
_foundry_model: Any = None
_foundry_service_started = False


def _is_windows() -> bool:
    return os.name == "nt" or platform.system().lower() == "windows"


def _enum_text(value: Any) -> str:
    if value is None:
        return "unknown"
    name = getattr(value, "name", None)
    if name:
        return str(name)
    text = str(value)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _ready_state_flags(state: Any) -> tuple[bool, bool, bool, str]:
    """Map AIFeatureReadyState without importing the enum at module import time."""
    raw = _enum_text(state).replace("_", "").replace(" ", "").lower()
    try:
        number = int(state)
    except Exception:
        number = None
    if raw == "ready" or number == 0:
        return True, True, False, "ready"
    if raw == "notready" or number == 1:
        return True, False, True, "not_ready"
    if raw in {"notsupportedoncurrentsystem", "notcompatiblewithsystemhardware"} or number in {2, 5}:
        return False, False, False, "unsupported"
    if raw == "disabledbyuser" or number == 3:
        return True, False, False, "disabled"
    if raw == "capabilitymissing" or number == 4:
        return False, False, False, "capability_missing"
    if raw == "osupdateneeded" or number == 6:
        return False, False, False, "os_update_needed"
    return False, False, False, raw or "unknown"


@contextmanager
def _windows_app_runtime(*, show_install_ui: bool = False):
    from winui3.microsoft.windows.applicationmodel.dynamicdependency import bootstrap

    options = bootstrap.InitializeOptions.NONE
    if show_install_ui:
        options = bootstrap.InitializeOptions.ON_NO_MATCH_SHOW_UI
    with bootstrap.initialize(options=options):
        yield


def _probe_windows_ocr() -> ComponentStatus:
    if not _is_windows():
        return ComponentStatus("windows_ocr", "Windows AI OCR", detail="Windows only.")
    try:
        from winui3.microsoft.windows.ai.imaging import TextRecognizer
    except Exception as exc:
        return ComponentStatus(
            "windows_ocr", "Windows AI OCR", installed=False, detail=f"{WINDOWS_AI_PACKAGE_HINT} ({exc})"
        )
    try:
        with _windows_app_runtime(show_install_ui=False):
            state = TextRecognizer.get_ready_state()
            supported, ready, needs_download, state_text = _ready_state_flags(state)
            detail = {
                "ready": "Windows AI Text Recognition is installed and ready.",
                "not_ready": "Supported by this PC; Windows needs to download/prepare the OCR model.",
                "disabled": "Windows AI OCR is disabled by the user.",
                "capability_missing": "Windows reports that this app is missing the system AI capability.",
                "os_update_needed": "A newer Windows release is required for this OCR component.",
                "unsupported": "Windows AI OCR is not supported on this hardware/OS.",
            }.get(state_text, f"Windows AI OCR state: {state_text}.")
            return ComponentStatus(
                "windows_ocr", "Windows AI OCR", installed=True, supported=supported,
                ready=ready, needs_download=needs_download, detail=detail, state=state_text,
            )
    except Exception as exc:
        return ComponentStatus(
            "windows_ocr", "Windows AI OCR", installed=True, detail=f"Windows App Runtime unavailable: {exc}",
            state="runtime_unavailable",
        )


def _probe_windows_language() -> ComponentStatus:
    if not _is_windows():
        return ComponentStatus("windows_language", "Windows on-device language model", detail="Windows only.")
    try:
        from winui3.microsoft.windows.ai.text import LanguageModel
    except Exception as exc:
        return ComponentStatus(
            "windows_language", "Windows on-device language model", installed=False,
            detail=f"{WINDOWS_AI_PACKAGE_HINT} ({exc})",
        )
    try:
        with _windows_app_runtime(show_install_ui=False):
            state = LanguageModel.get_ready_state()
            supported, ready, needs_download, state_text = _ready_state_flags(state)
            detail = {
                "ready": "Windows on-device language model is ready.",
                "not_ready": "Supported by this PC; Windows needs to download/prepare the model.",
                "disabled": "The Windows on-device language model is disabled by the user.",
                "capability_missing": "Windows reports that this app is missing the system AI capability.",
                "os_update_needed": "A newer Windows release is required for this model.",
                "unsupported": "Windows on-device language model is not supported on this hardware/OS.",
            }.get(state_text, f"Windows language-model state: {state_text}.")
            return ComponentStatus(
                "windows_language", "Windows on-device language model", installed=True,
                supported=supported, ready=ready, needs_download=needs_download,
                detail=detail, state=state_text,
            )
    except Exception as exc:
        return ComponentStatus(
            "windows_language", "Windows on-device language model", installed=True,
            detail=f"Windows App Runtime unavailable: {exc}", state="runtime_unavailable",
        )


def _get_foundry_manager() -> Any:
    global _foundry_manager
    with _foundry_lock:
        if _foundry_manager is not None:
            return _foundry_manager
        from foundry_local_sdk import Configuration, FoundryLocalManager

        config = Configuration(app_name="SurveySync")
        # SDK 1.1/1.2 exposes initialize + instance. Keep a compatibility fallback
        # for builds that use create() instead.
        if hasattr(FoundryLocalManager, "initialize"):
            FoundryLocalManager.initialize(config)
            manager = getattr(FoundryLocalManager, "instance", None)
            if callable(manager):
                manager = manager()
            if manager is None:
                manager = getattr(FoundryLocalManager, "Instance", None)
                manager = manager() if callable(manager) else manager
        elif hasattr(FoundryLocalManager, "create"):
            manager = FoundryLocalManager.create({"app_name": "SurveySync"})
        else:
            raise RuntimeError("Unsupported Foundry Local SDK manager API.")
        if manager is None:
            raise RuntimeError("Foundry Local SDK did not return a manager instance.")
        _foundry_manager = manager
        return manager


def _foundry_get_model(manager: Any, alias: str = DEFAULT_FOUNDRY_VISION_MODEL) -> Any:
    catalog = getattr(manager, "catalog", None)
    if callable(catalog):
        catalog = catalog()
    if catalog is None:
        raise RuntimeError("Foundry Local catalog is unavailable.")
    getter = getattr(catalog, "get_model", None) or getattr(catalog, "GetModel", None)
    if getter is None:
        getter = getattr(catalog, "get_model_async", None) or getattr(catalog, "GetModelAsync", None)
    if getter is None:
        raise RuntimeError("Foundry Local catalog does not expose get_model().")
    model = getter(alias)
    if asyncio.iscoroutine(model):
        model = asyncio.run(model)
    return model


def _model_cached(model: Any) -> bool:
    for name in ("is_cached", "IsCached", "cached"):
        value = getattr(model, name, None)
        if callable(value):
            value = value()
        if value is not None:
            return bool(value)
    # Unknown SDK shape: do not claim the model is cached.
    return False


def _probe_foundry_local(alias: str = DEFAULT_FOUNDRY_VISION_MODEL) -> ComponentStatus:
    if not _is_windows():
        return ComponentStatus("foundry_local", "Microsoft Foundry Local", detail="Windows only.", model=alias)
    try:
        import foundry_local_sdk  # noqa: F401
    except Exception as exc:
        return ComponentStatus(
            "foundry_local", "Microsoft Foundry Local", installed=False,
            detail=f"{FOUNDRY_PACKAGE_HINT} ({exc})", model=alias,
        )
    try:
        manager = _get_foundry_manager()
        model = _foundry_get_model(manager, alias)
        cached = _model_cached(model)
        return ComponentStatus(
            "foundry_local", "Microsoft Foundry Local", installed=True, supported=True,
            ready=cached, needs_download=not cached,
            detail=(
                f"{alias} is cached and ready for local vision." if cached else
                f"Foundry Local is available; {alias} needs a one-time local model download."
            ),
            state="ready" if cached else "model_download_required", model=alias,
        )
    except Exception as exc:
        return ComponentStatus(
            "foundry_local", "Microsoft Foundry Local", installed=True,
            detail=f"Foundry Local could not initialize: {exc}", state="runtime_unavailable", model=alias,
        )


def get_local_ai_status(*, force: bool = False) -> dict[str, Any]:
    """Return local-only AI capabilities. Expensive probes are cached briefly."""
    global _status_cache
    now = time.monotonic()
    with _status_lock:
        if not force and _status_cache and now - _status_cache[0] < 20:
            return json.loads(json.dumps(_status_cache[1]))
        windows_ocr = _probe_windows_ocr()
        windows_language = _probe_windows_language()
        foundry = _probe_foundry_local()
        payload = {
            "windows": _is_windows(),
            "windows_ocr": windows_ocr.to_dict(),
            "windows_language": windows_language.to_dict(),
            "foundry_local": foundry.to_dict(),
            "privacy": "local_only",
            "cost": "free_local",
        }
        _status_cache = (now, payload)
        return json.loads(json.dumps(payload))


def resolve_automatic_plan(
    status: dict[str, Any], *,
    hybrid_ready: bool,
    paddle_ready: bool,
    ollama_ready: bool,
) -> AutoPlan:
    """Select the safest local pipeline without triggering downloads.

    Priority is component-aware rather than branding-aware: use Windows OCR whenever it
    is already ready, Foundry Local vision whenever its model is already cached, then the
    proven SurveySync local stack.  Nothing is downloaded silently.
    """
    wo = status.get("windows_ocr") or {}
    fl = status.get("foundry_local") or {}
    windows_ocr_ready = bool(wo.get("ready"))
    foundry_ready = bool(fl.get("ready"))

    # Accuracy/speed default for survey field books:
    # PaddleOCR-VL 1.6 is specialized for document parsing and locating the exact
    # handwritten/printed PointID evidence that SurveySync needs.  Qwen3-VL then
    # sees only small, targeted crops instead of whole books.  This keeps the heavy
    # vision reasoning workload small while preserving the independent OCR gate.
    # Windows AI / Foundry remain valuable fallbacks on PCs where the SurveySync
    # local stack is not ready, but Automatic does not prefer a general-purpose
    # Windows model over the document-specialized pipeline merely because it exists.
    if hybrid_ready:
        if windows_ocr_ready:
            return AutoPlan(
                "auto", "hybrid", "windows_ai+paddle_vl_1_6", "qwen3_vl",
                "Evidence-First Local — Windows AI + PaddleOCR-VL + Qwen3-VL",
                "Windows AI performs a fast exact-PointID/page-type pass. PaddleOCR-VL handles unresolved or risky evidence, and a hardware-sized Qwen3-VL model interprets only localized crops. Deterministic scoring decides whether details can be accepted or need review.",
            )
        return AutoPlan(
            "auto", "hybrid", "paddle_vl_1_6", "qwen3_vl",
            "Evidence-First Local — PaddleOCR-VL + Qwen3-VL",
            "PaddleOCR-VL locates exact survey evidence and classifies page context, then a hardware-sized Qwen3-VL model interprets only localized crops. Deterministic scoring decides whether details can be accepted or need review.",
        )
    if foundry_ready and windows_ocr_ready:
        return AutoPlan(
            "auto", "microsoft_auto", "windows_ai", "foundry_local",
            "Windows AI OCR + Foundry Local Vision",
            "The preferred SurveySync document pipeline is not ready, so Automatic selected the fully local Windows AI/Foundry fallback.",
        )
    if windows_ocr_ready and ollama_ready:
        return AutoPlan(
            "auto", "windows_ocr_ollama", "windows_ai", "qwen3_vl",
            "Windows AI OCR + Qwen3-VL",
            "PaddleOCR-VL is not ready; Windows AI OCR supplies the exact-text gate and Qwen3-VL interprets the localized evidence.",
        )
    if windows_ocr_ready:
        return AutoPlan(
            "auto", "windows_ocr", "windows_ai", "manual",
            "Windows AI OCR + Manual Review",
            "Windows OCR is ready, but no local vision model is ready; semantic decisions stay manual.",
        )
    if paddle_ready:
        return AutoPlan(
            "auto", "paddle", "paddle", "manual", "Paddle OCR + Manual Review",
            "Only the local OCR engine is ready; semantic decisions stay manual.",
        )
    return AutoPlan(
        "auto", "manual", "manual", "manual", "Manual Review",
        "No local AI engine is ready. SurveySync will not silently use a paid/cloud provider.",
    )


async def _ensure_windows_feature(feature: str) -> dict[str, Any]:
    if feature not in {"ocr", "language"}:
        raise ValueError("feature must be 'ocr' or 'language'")
    if not _is_windows():
        raise RuntimeError("Windows AI can only be enabled on Windows.")
    with _windows_app_runtime(show_install_ui=True):
        if feature == "ocr":
            from winui3.microsoft.windows.ai.imaging import TextRecognizer as Feature
        else:
            from winui3.microsoft.windows.ai.text import LanguageModel as Feature
        state = Feature.get_ready_state()
        _, ready, needs_download, state_text = _ready_state_flags(state)
        if ready:
            return {"feature": feature, "ready": True, "state": state_text, "message": "Already ready."}
        if not needs_download:
            raise RuntimeError(f"Windows reports {feature} state '{state_text}', so SurveySync cannot download it automatically.")
        result = await Feature.ensure_ready_async()
        status = _enum_text(getattr(result, "status", None))
        state_after = Feature.get_ready_state()
        _, ready_after, _, state_text_after = _ready_state_flags(state_after)
        if not ready_after:
            error = getattr(result, "extended_error", None)
            raise RuntimeError(f"Windows could not prepare {feature} ({status}): {error or state_text_after}")
        return {"feature": feature, "ready": True, "state": state_text_after, "message": "Windows AI component is ready."}


def ensure_windows_feature(feature: str) -> dict[str, Any]:
    result = asyncio.run(_ensure_windows_feature(feature))
    get_local_ai_status(force=True)
    return result


async def _windows_ocr_async(image_path: str | Path, *, ensure_ready: bool = False) -> dict[str, Any]:
    path = str(Path(image_path).expanduser().resolve())
    with _windows_app_runtime(show_install_ui=False):
        from winui3.microsoft.windows.ai.imaging import TextRecognizer
        from winui3.microsoft.graphics.imaging import ImageBuffer
        from winrt.windows.storage import StorageFile, FileAccessMode
        from winrt.windows.graphics.imaging import BitmapDecoder

        state = TextRecognizer.get_ready_state()
        _, ready, needs_download, state_text = _ready_state_flags(state)
        if not ready:
            if ensure_ready and needs_download:
                await TextRecognizer.ensure_ready_async()
            else:
                raise RuntimeError(f"Windows AI OCR is not ready ({state_text}).")
        recognizer = await TextRecognizer.create_async()
        file = await StorageFile.get_file_from_path_async(path)
        stream = await file.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        image_buffer = ImageBuffer.create_for_software_bitmap(bitmap)
        try:
            recognized = recognizer.recognize_text_from_image(image_buffer)
            lines_out: list[dict[str, Any]] = []
            for line in list(getattr(recognized, "lines", []) or []):
                words = list(getattr(line, "words", []) or [])
                confidences = [float(getattr(w, "match_confidence", 0.0) or 0.0) for w in words]
                bbox = getattr(line, "bounding_box", None)
                points = []
                if bbox is not None:
                    for name in ("top_left", "top_right", "bottom_right", "bottom_left"):
                        pt = getattr(bbox, name, None)
                        if pt is not None:
                            points.append([float(getattr(pt, "x", 0.0)), float(getattr(pt, "y", 0.0))])
                lines_out.append({
                    "text": str(getattr(line, "text", "") or ""),
                    "confidence": sum(confidences) / len(confidences) if confidences else 0.0,
                    "polygon": points,
                })
            return {
                "engine": "Windows AI TextRecognizer",
                "width": int(getattr(image_buffer, "pixel_width", 0) or 0),
                "height": int(getattr(image_buffer, "pixel_height", 0) or 0),
                "lines": lines_out,
                "text": "\n".join(x["text"] for x in lines_out if x["text"]),
            }
        finally:
            for obj in (image_buffer, bitmap, stream, recognizer):
                try:
                    close = getattr(obj, "close", None) or getattr(obj, "dispose", None)
                    if close:
                        close()
                except Exception:
                    logger.debug("Optional local-AI resource cleanup failed.", exc_info=True)


def windows_ocr(image_path: str | Path, *, ensure_ready: bool = False) -> dict[str, Any]:
    return asyncio.run(_windows_ocr_async(image_path, ensure_ready=ensure_ready))


def _call_maybe_async(obj: Any, method_names: Iterable[str], *args: Any) -> Any:
    method = None
    for name in method_names:
        method = getattr(obj, name, None)
        if method is not None:
            break
    if method is None:
        raise RuntimeError(f"Object {type(obj).__name__} does not expose any of {tuple(method_names)}")
    result = method(*args)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return result


def enable_foundry_model(alias: str = DEFAULT_FOUNDRY_VISION_MODEL) -> dict[str, Any]:
    """User-initiated model download. Never called by automatic probing."""
    global _foundry_model
    manager = _get_foundry_manager()
    # Hardware execution providers can require their own local package. This function is
    # only called after explicit user consent, so it is the correct place to prepare them.
    prepare_eps = getattr(manager, "download_and_register_eps", None) or getattr(manager, "DownloadAndRegisterEps", None)
    if prepare_eps is not None:
        try:
            ep_result = prepare_eps()
            if asyncio.iscoroutine(ep_result):
                asyncio.run(ep_result)
        except Exception:
            # CPU execution remains a valid fallback when an accelerator package fails.
            logger.warning("Local-AI accelerator initialization failed; continuing with CPU fallback.", exc_info=True)
    model = _foundry_get_model(manager, alias)
    if not _model_cached(model):
        _call_maybe_async(model, ("download", "Download", "download_async", "DownloadAsync"))
    _call_maybe_async(model, ("load", "Load", "load_async", "LoadAsync"))
    with _foundry_lock:
        _foundry_model = model
    get_local_ai_status(force=True)
    return {"ready": True, "model": alias, "message": f"{alias} is downloaded and loaded locally."}


def _foundry_service_url(manager: Any) -> str:
    global _foundry_service_started
    with _foundry_lock:
        if not _foundry_service_started:
            starter = getattr(manager, "start_web_service", None) or getattr(manager, "StartWebService", None)
            if starter is None:
                raise RuntimeError("Foundry Local SDK does not expose start_web_service().")
            result = starter()
            if asyncio.iscoroutine(result):
                asyncio.run(result)
            _foundry_service_started = True
        urls = getattr(manager, "urls", None) or getattr(manager, "Urls", None)
        if callable(urls):
            urls = urls()
        if not urls:
            raise RuntimeError("Foundry Local did not report a local service URL.")
        return str(list(urls)[0]).rstrip("/")


def _prepare_image_b64(path: str | Path, max_dim: int = 2200) -> str:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if max(image.size) > max_dim:
            scale = max_dim / max(image.size)
            image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=88, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")


def foundry_vision_json(
    image_paths: Iterable[str | Path],
    *,
    prompt: str,
    model_alias: str = DEFAULT_FOUNDRY_VISION_MODEL,
    timeout_seconds: int = 360,
) -> dict[str, Any]:
    """Run local multimodal inference through Foundry Local's Responses API.

    This function never downloads the model. The caller must obtain user consent and
    call enable_foundry_model() first if the model is not cached.
    """
    global _foundry_model
    manager = _get_foundry_manager()
    model = _foundry_get_model(manager, model_alias)
    if not _model_cached(model):
        raise RuntimeError(f"Foundry Local model '{model_alias}' is not downloaded. Enable Microsoft Local AI first.")
    try:
        _call_maybe_async(model, ("load", "Load", "load_async", "LoadAsync"))
    except Exception:
        # Some SDK builds report an already-loaded model as an error; the service call is authoritative.
        logger.debug("Foundry model load call reported an error; continuing to the authoritative service request.", exc_info=True)
    _foundry_model = model
    service = _foundry_service_url(manager)
    model_id = str(getattr(model, "id", None) or getattr(model, "Id", None) or model_alias)
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for image_path in image_paths:
        content.append({
            "type": "input_image",
            "image_url": "data:image/jpeg;base64," + _prepare_image_b64(image_path),
        })
    body = {
        "model": model_id,
        "input": [{"type": "message", "role": "user", "content": content}],
        "temperature": 0,
    }
    response = requests.post(f"{service}/v1/responses", json=body, timeout=timeout_seconds)
    if response.status_code >= 400:
        raise RuntimeError(f"Foundry Local returned HTTP {response.status_code}: {response.text[:800]}")
    payload = response.json()
    text = payload.get("output_text")
    if not isinstance(text, str):
        chunks: list[str] = []
        for item in payload.get("output", []) or []:
            for part in item.get("content", []) or []:
                if isinstance(part.get("text"), str):
                    chunks.append(part["text"])
        text = "\n".join(chunks)
    if not text:
        raise RuntimeError("Foundry Local returned no text output.")
    text = text.strip()
    # Models occasionally wrap JSON in fenced code blocks even when instructed not to.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("Foundry Local response was not valid JSON.")
        data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise RuntimeError("Foundry Local response JSON must be an object.")
    return {"data": data, "raw": payload, "model": model_id}
