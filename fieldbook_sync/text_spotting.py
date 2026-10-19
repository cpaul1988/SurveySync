"""Validate local PaddleOCR-VL 1.6 spotting and retain its spatial evidence.

The public PaddleOCRVL API uses ``prompt_label='spotting'`` with layout detection
disabled. PaddleX exposes ``spotting_res.rec_texts`` and ``rec_polys`` (four points
per text, in input-image pixels). Its internal 2x enlargement is already undone;
these are *not* normalized 0--1000 coordinates. Source contracts reviewed at:

https://github.com/PaddlePaddle/PaddleOCR/blob/dab3fe35379033fdcb2d0e9572fac0b36c9a9ebf/paddleocr/_pipelines/paddleocr_vl.py
https://github.com/PaddlePaddle/PaddleX/blob/ffb64904d23708863ff5b8da312a5cbd52a7f462/paddlex/inference/pipelines/paddleocr_vl/uilts.py
https://github.com/PaddlePaddle/PaddleX/blob/ffb64904d23708863ff5b8da312a5cbd52a7f462/paddlex/inference/models/doc_vlm/predictor.py

No Paddle import, model download, survey-text interpretation, or confidence
estimate belongs in this adapter. Located text remains OCR evidence for review.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODEL_NAME = "PaddleOCR-VL-1.6-0.9B"
SOURCE = "paddleocr-vl-1.6-spotting"
SPOTTING_SCHEMA = "fbs-paddle-spotting-v1"


class SpottingError(RuntimeError):
    """Spotting cannot safely produce spatial evidence for this request."""


class SpottingCapabilityError(SpottingError):
    """The selected local assets or installed API cannot provide spotting."""


@dataclass(frozen=True)
class LocalSpottingModel:
    directory: Path
    asset_sha256: str


def _local_path(value: str | Path) -> Path:
    text = str(value).strip()
    if not text or "://" in text or text.startswith(("//", "\\\\")):
        raise SpottingCapabilityError("Select an existing local PaddleOCR-VL 1.6 model directory.")
    try:
        path = Path(text).resolve()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SpottingCapabilityError(
            f"Cannot resolve the local spotting directory: {exc}"
        ) from exc
    if str(path).startswith(("//", "\\\\")):
        raise SpottingCapabilityError(
            "Spotting requires local files; network shares are unsupported."
        )
    return path


def validate_spotting_model_dir(value: str | Path) -> LocalSpottingModel:
    """Check an existing native Paddle export and hash all inference asset contents.

    This verifies local identity/completeness, not publisher authenticity. It does
    not search the home directory or download missing files. The digest changes
    with weights, tokenizer, processor, or model configuration, so it can key an
    OCR cache. A caller should run it when selecting assets/starting a job, not on
    every UI refresh. Only the native single-file weight formats PaddleX resolves
    are accepted; unsupported exports require an explicit environment repair.
    """
    directory = _local_path(value)
    required = [
        "inference.yml",
        "config.json",
        "preprocessor_config.json",
        "tokenizer_config.json",
        "tokenizer.model",
        "chat_template.jinja",
    ]
    weights = [
        name
        for name in ("model.safetensors", "model_state.pdparams", "inference.pdparams")
        if (directory / name).is_file()
    ]
    if not directory.is_dir() or not weights:
        raise SpottingCapabilityError(
            "The spotting directory must contain an existing native PaddleOCR-VL 1.6 export "
            "and model.safetensors, model_state.pdparams, or inference.pdparams. "
            "No assets were downloaded."
        )
    optional = [
        name
        for name in (
            "special_tokens_map.json",
            "added_tokens.json",
            "generation_config.json",
            "tokenizer.json",
        )
        if (directory / name).exists()
    ]
    names = sorted(required + weights + optional)
    try:
        for name in names:
            path = _local_path(directory / name)
            if not path.is_file() or path.stat().st_size == 0:
                raise SpottingCapabilityError(f"Missing or empty local spotting asset: {name}.")
        # PyYAML is already a SurveySync and PaddleX dependency; no model import.
        import yaml

        try:
            config = yaml.safe_load((directory / "inference.yml").read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise SpottingCapabilityError("Malformed local spotting inference.yml.") from exc
        global_config = config.get("Global") if isinstance(config, dict) else None
        if not isinstance(global_config, dict) or global_config.get("model_name") != MODEL_NAME:
            raise SpottingCapabilityError(
                f"inference.yml must identify Global.model_name as {MODEL_NAME}."
            )
        for name in names:
            if name.endswith(".json"):
                value = json.loads((directory / name).read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise SpottingCapabilityError(
                        f"Local spotting asset {name} must be a JSON object."
                    )
        digest = hashlib.sha256()
        for name in names:
            file_digest = hashlib.sha256()
            with (directory / name).open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    file_digest.update(chunk)
            digest.update(name.encode("utf-8") + b"\0" + file_digest.digest())
        return LocalSpottingModel(directory=directory, asset_sha256=digest.hexdigest())
    except SpottingError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, ImportError) as exc:
        raise SpottingCapabilityError(f"Cannot validate local spotting assets: {exc}") from exc


def require_spotting_api(pipeline_type: type) -> None:
    """Do not infer support from a permissive **kwargs signature or version label."""
    needed_init = {
        "pipeline_version",
        "vl_rec_model_name",
        "vl_rec_model_dir",
        "vl_rec_backend",
        "use_layout_detection",
        "use_doc_orientation_classify",
        "use_doc_unwarping",
        "use_queues",
    }
    needed_predict = {
        "prompt_label",
        "use_layout_detection",
        "use_doc_orientation_classify",
        "use_doc_unwarping",
        "use_queues",
    }
    try:
        init = inspect.signature(pipeline_type.__init__).parameters
        predict = inspect.signature(pipeline_type.predict).parameters
    except (AttributeError, ValueError, TypeError) as exc:
        raise SpottingCapabilityError(
            "The installed PaddleOCR API cannot be checked for spotting."
        ) from exc
    if not needed_init.issubset(init) or not needed_predict.issubset(predict):
        raise SpottingCapabilityError(
            "The installed PaddleOCR API lacks explicit local-model/spotting controls. "
            "Repair the local OCR environment; block OCR was not substituted."
        )


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpottingError(f"{name} must be a finite number.")
    try:
        number = float(value)
    except OverflowError as exc:
        raise SpottingError(f"{name} must be a finite number.") from exc
    if not math.isfinite(number):
        raise SpottingError(f"{name} must be a finite number.")
    return number


def _size(value: Any, name: str) -> int:
    number = _number(value, name)
    if number <= 0 or not number.is_integer():
        raise SpottingError(f"{name} must be a positive integer.")
    return int(number)


@dataclass(frozen=True)
class ViewTransform:
    """A page crop, then a clockwise quarter-turn, then optional image resizing.

    Dimensions and the crop describe the original rendered page, after its EXIF
    orientation has been applied. Arbitrary deskew/unwarping is unsupported: the
    caller must not label a non-affine image as this transform.
    """

    page_width: int
    page_height: int
    crop_bbox: tuple[float, float, float, float] | None = None
    rotation_cw: int = 0

    def geometry(self) -> tuple[int, int, tuple[float, float, float, float]]:
        width = _size(self.page_width, "page_width")
        height = _size(self.page_height, "page_height")
        if isinstance(self.rotation_cw, bool) or self.rotation_cw not in (0, 90, 180, 270):
            raise SpottingError("Only clockwise rotations 0, 90, 180, and 270 are supported.")
        crop = self.crop_bbox if self.crop_bbox is not None else (0, 0, width, height)
        if not isinstance(crop, (list, tuple)) or len(crop) != 4:
            raise SpottingError("crop_bbox must contain four original-page coordinates.")
        x0, y0, x1, y1 = (_number(v, "crop_bbox") for v in crop)
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise SpottingError("crop_bbox must have positive area within the original page.")
        return width, height, (x0, y0, x1, y1)


def map_polygon_to_page(
    polygon: Any, *, image_width: int, image_height: int, transform: ViewTransform
) -> list[list[float]]:
    """Map an upstream four-point input-pixel polygon back to the original page."""
    width, height = _size(image_width, "image_width"), _size(image_height, "image_height")
    _, _, (x0, y0, x1, y1) = transform.geometry()
    crop_w, crop_h = x1 - x0, y1 - y0
    rotated_w, rotated_h = (
        (crop_h, crop_w) if transform.rotation_cw in (90, 270) else (crop_w, crop_h)
    )
    if not isinstance(polygon, (list, tuple)) or len(polygon) != 4:
        raise SpottingError("Each spotted text needs exactly four polygon points.")
    points = []
    for point in polygon:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise SpottingError("Each polygon point must contain x and y.")
        px, py = (_number(v, "polygon coordinate") for v in point)
        if not (0 <= px <= width and 0 <= py <= height):
            raise SpottingError(
                "Spotting polygon lies outside its input image; coordinates were not clamped."
            )
        u, v = px / width * rotated_w, py / height * rotated_h
        if transform.rotation_cw == 90:
            x, y = v, crop_h - u
        elif transform.rotation_cw == 180:
            x, y = crop_w - u, crop_h - v
        elif transform.rotation_cw == 270:
            x, y = crop_w - v, u
        else:
            x, y = u, v
        points.append([x0 + x, y0 + y])
    # Reject degenerate, crossed, or concave quads rather than manufacture a box.
    crosses = []
    for i in range(4):
        a, b, c = points[i], points[(i + 1) % 4], points[(i + 2) % 4]
        crosses.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    if not (all(c > 0 for c in crosses) or all(c < 0 for c in crosses)):
        raise SpottingError("Spotting polygon must be a nondegenerate convex quadrilateral.")
    return points


def normalize_spotting_result(
    payload: Any,
    *,
    image_path: str | Path,
    image_sha256: str,
    transform: ViewTransform | None = None,
    asset_sha256: str = "",
    expected_image_size: tuple[int, int] | None = None,
) -> dict:
    """Adapt the actual PaddleX JSON contract to one evidence block per text.

    Generated blocks use original-page pixels, retain input polygons and image
    provenance, and have no invented confidence. ``spotting_res`` is retained in
    its native input-image coordinate space, explicitly labelled in metadata.
    Missing spotting is a capability failure; malformed data fails the page.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("res"), dict):
        raise SpottingError("Paddle spotting result must be a JSON object with a res object.")
    if not isinstance(image_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", image_sha256):
        raise SpottingError("Spotting evidence requires the SHA-256 of the actual input image.")
    if asset_sha256 and (
        not isinstance(asset_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", asset_sha256)
    ):
        raise SpottingError("Invalid local spotting asset SHA-256.")
    res = payload["res"]
    spotting = res.get("spotting_res")
    if not isinstance(spotting, dict):
        raise SpottingCapabilityError(
            "Paddle did not return spotting_res; this local environment cannot supply "
            "localized spotting evidence. Block OCR was not substituted."
        )
    settings = res.get("model_settings")
    if (
        not isinstance(settings, dict)
        or settings.get("use_layout_detection") is not False
        or settings.get("use_doc_preprocessor") is not False
    ):
        raise SpottingError(
            "Spotting must disable layout detection, orientation changes, and unwarping."
        )
    width, height = _size(res.get("width"), "width"), _size(res.get("height"), "height")
    if expected_image_size is not None and (width, height) != tuple(expected_image_size):
        raise SpottingError("Spotting result dimensions do not match the actual input image.")
    source_path = str(Path(image_path).resolve())
    returned_path = res.get("input_path")
    if returned_path is not None and not isinstance(returned_path, str):
        raise SpottingError("Spotting input_path must be a local image path.")
    if returned_path and str(Path(returned_path).resolve()) != source_path:
        raise SpottingError("Spotting result belongs to a different input image.")
    view = transform or ViewTransform(width, height)
    page_w, page_h, crop = view.geometry()
    texts, polygons = spotting.get("rec_texts"), spotting.get("rec_polys")
    if (
        not isinstance(texts, (list, tuple))
        or not isinstance(polygons, (list, tuple))
        or len(texts) != len(polygons)
    ):
        raise SpottingError(
            "spotting_res must contain equally sized rec_texts and rec_polys arrays."
        )
    if len(texts) > 10000:
        raise SpottingError("Spotting response contains too many regions for one image.")
    provenance = {
        "schema": SPOTTING_SCHEMA,
        "source": SOURCE,
        "image_path": source_path,
        "image_sha256": image_sha256,
        "model_asset_sha256": asset_sha256,
        "input_image_size": [width, height],
        "page_size": [page_w, page_h],
        "crop_bbox": list(crop),
        "rotation_cw": view.rotation_cw,
        "coordinate_space": "original_page_pixels",
    }
    blocks = []
    for index, (text, polygon) in enumerate(zip(texts, polygons)):
        if not isinstance(text, str) or not text.strip() or len(text) > 100000:
            raise SpottingError("Each spotted region must have nonempty bounded text.")
        page_polygon = map_polygon_to_page(
            polygon, image_width=width, image_height=height, transform=view
        )
        xs, ys = [p[0] for p in page_polygon], [p[1] for p in page_polygon]
        blocks.append(
            {
                "block_id": index,
                "block_label": "text",
                "block_content": text,
                "block_bbox": [min(xs), min(ys), max(xs), max(ys)],
                "block_polygon": page_polygon,
                "source": SOURCE,
                "confidence": None,
                "provenance": {**provenance, "input_polygon": [list(p) for p in polygon]},
            }
        )
    return {
        "res": {
            **res,
            "width": page_w,
            "height": page_h,
            "parsing_res_list": blocks,
            "ocr_mode": "spotting",
            "spotting_metadata": {**provenance, "native_coordinate_space": "input_image_pixels"},
        }
    }
