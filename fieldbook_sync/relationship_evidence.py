"""Connect original-page OCR observations to conservative local geometry proposals."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageOps

from .image_processing import normalized_bbox_to_pixels
from .measurement_comparison import (
    compare_measurement_records,
    observation_from_text,
    observation_matches_pipe,
)
from .models import FieldBookPage, OcrCandidate, PageEvidence


def valid_bbox(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if any(
        isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
        for x in value
    ):
        return None
    if not (0 <= value[0] < value[2] <= 1000 and 0 <= value[1] < value[3] <= 1000):
        return None
    return [round(x) for x in value]


def _region(
    text: str, bbox: Any, *, view: str, engine: str, provenance: dict | None = None
) -> dict | None:
    bbox = valid_bbox(bbox)
    text = str(text or "").strip()[:12000]
    if not bbox or not text:
        return None
    token = hashlib.sha256((text + "|" + str(bbox)).encode("utf-8")).hexdigest()[:20]
    return {
        "id": f"text-{token}",
        "text": text,
        "bbox": bbox,
        "source": "ocr",
        "engine": engine,
        "source_view": view,
        "provenance": provenance or {},
    }


def paddle_text_regions(page: FieldBookPage, payload: dict) -> list[dict]:
    from .ocr_local import _extract_blocks, _normalize_bbox_pixels

    with Image.open(page.image_path) as source:
        image = ImageOps.exif_transpose(source)
        width, height = image.size
    regions = []
    for view in payload.get("views", [payload]):
        meta = view.get("surveysync_view", {}) if isinstance(view, dict) else {}
        role = str(meta.get("role", "unknown"))
        for block in _extract_blocks(view)[:513]:
            value = _region(
                block.get("block_content", ""),
                _normalize_bbox_pixels(block.get("block_bbox"), width, height),
                view=role,
                engine=block.get("source", "paddleocr-vl-1.6-blocks"),
                provenance={"view": meta, "spotting": block.get("provenance", {})},
            )
            if value:
                regions.append(value)
    return merge_text_regions(regions)


def windows_text_regions(payload: dict, *, view: str = "original") -> list[dict]:
    from .ocr_local import _normalize_bbox_pixels

    width, height = int(payload.get("width") or 0), int(payload.get("height") or 0)
    regions = []
    for line in (payload.get("lines") or [])[:513]:
        if not isinstance(line, dict):
            continue
        value = _region(
            line.get("text", ""),
            _normalize_bbox_pixels(line.get("polygon"), width, height),
            view=view,
            engine="windows-ai-ocr",
        )
        if value:
            regions.append(value)
    return merge_text_regions(regions)


def merge_text_regions(regions: list[dict]) -> list[dict]:
    """Deduplicate identical observations, keeping original and derivative provenance."""
    merged: dict[str, dict] = {}
    for region in regions:
        key = region["id"]
        if key not in merged:
            merged[key] = deepcopy(region)
            merged[key]["observations"] = []
        observation = {
            "engine": region.get("engine"),
            "source_view": region.get("source_view"),
            "provenance": region.get("provenance", {}),
        }
        if observation not in merged[key]["observations"]:
            merged[key]["observations"].append(observation)
    return list(merged.values())


def independent_anchors(candidates: list[OcrCandidate]) -> list[dict]:
    anchors = []
    seen = set()
    for candidate in candidates:
        bbox = valid_bbox(candidate.bbox)
        raw = candidate.recognized_point_id
        if not raw:
            tokens = re.findall(r"[A-Za-z0-9._-]+", candidate.raw_text or "")
            raw = next((token for token in tokens if token == candidate.point_id), "")
        if not candidate.exact_match or raw != candidate.point_id or not bbox:
            continue
        # A paragraph-sized ID box is only routing context, not a localized ID anchor.
        if bbox[2] - bbox[0] > 250 or bbox[3] - bbox[1] > 150:
            continue
        key = (candidate.point_id, tuple(bbox))
        if key in seen:
            continue
        seen.add(key)
        anchors.append(
            {
                "id": f"anchor-{len(anchors) + 1}",
                "point_id": candidate.point_id,
                "raw_text": raw,
                "bbox": bbox,
                "exact_match": True,
                "independent": True,
                "source": candidate.engine,
                "source_view": candidate.source_view,
            }
        )
    return anchors


def analyze_page_relationships(
    page: FieldBookPage,
    regions: list[dict],
    candidates: list[OcrCandidate],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    from .spatial_association import associate_page_geometry
    from .ocr_local import _sha256_file

    started = time.monotonic()
    anchors = independent_anchors(candidates)
    with Image.open(page.image_path) as source:
        # The core checks the source pixel budget before decoding/converting RGB.
        original = (
            ImageOps.exif_transpose(source)
            if source.width * source.height <= 24_000_000
            else source
        )
        graph = associate_page_geometry(
            original,
            page_id=page.page_id,
            text_regions=regions,
            point_anchors=anchors,
            cancelled=cancelled,
        )
    graph["text_regions"] = deepcopy(regions[:512])
    graph["source"]["image_sha256"] = _sha256_file(page.image_path)
    graph["point_anchors"] = anchors[:512]
    graph["elapsed_seconds"] = round(time.monotonic() - started, 6)
    return graph


def apply_relationship_evidence(evidence: PageEvidence, graph: dict | None) -> None:
    """Attach a fresh local graph, then make unique, complete pipe-record proposals.

    Matching fields here only chooses a proposal to show the reviewer. It never proves
    a connection or permits auto-acceptance. The independently measured graph is kept
    intact so a reviewer can detect swapped model values or competing interpretations.
    """
    # One immutable graph is shared across entries during a run; the final project
    # stores it once by page/digest and each entry retains a reference key.
    evidence.spatial_evidence = graph or {}
    evidence.relationship_status = "unverified"
    for pipe in evidence.pipes:
        pipe.source_page_id = evidence.page_id
        pipe.association_status = "unverified"
        pipe.association_text_ids = []
        pipe.association_path_ids = []
        pipe.association_flags = ["PIPE_BINDING_REVIEW_REQUIRED"]
    if not graph or not evidence.pipes:
        return
    if (
        graph.get("status") != "complete"
        or graph.get("truncated") is not False
        or graph.get("source", {}).get("page_id") != evidence.page_id
    ):
        for pipe in evidence.pipes:
            pipe.association_flags.append("INCOMPLETE_OR_STALE_SPATIAL_EVIDENCE")
        return
    regions = {region["id"]: region for region in graph.get("text_regions", [])}
    paths = {path["id"]: path for path in graph.get("paths", [])}
    options: list[list[dict]] = []
    for pipe in evidence.pipes:
        matches = []
        for association in graph.get("associations", []):
            region = regions.get(association.get("text_id"), {})
            observation = observation_from_text(region.get("text", ""))
            if observation and observation_matches_pipe(observation, pipe, complete=True):
                matches.append(association)
        options.append(matches)
    uses: dict[str, int] = {}
    for matches in options:
        for association in matches:
            text_id = association.get("text_id", "")
            uses[text_id] = uses.get(text_id, 0) + 1
    for pipe, matches in zip(evidence.pipes, options):
        if not matches:
            pipe.association_flags.append("NO_COMPLETE_LOCAL_TEXT_RECORD")
            continue
        pipe.association_text_ids = list(dict.fromkeys(a["text_id"] for a in matches))
        pipe.association_path_ids = list(
            dict.fromkeys(path for a in matches for path in a.get("path_ids", []))
        )
        if len(matches) != 1 or uses.get(matches[0].get("text_id", ""), 0) != 1:
            pipe.association_status = "ambiguous"
            pipe.association_flags.append("COMPETING_TEXT_RECORDS")
        elif matches[0].get("status") != "supported":
            pipe.association_status = (
                "ambiguous" if matches[0].get("status") == "ambiguous" else "unverified"
            )
            pipe.association_flags.extend(matches[0].get("reasons", []))
        elif not matches[0].get("path_ids") or not all(
            paths.get(path_id, {}).get("evidence") == "original_pixels"
            and paths.get(path_id, {}).get("original_resolution_verified") is True
            for path_id in matches[0]["path_ids"]
        ):
            pipe.association_flags.append("NO_VERIFIED_ORIGINAL_INK_PATH")
        elif matches[0].get("point_id") != evidence.matched_point_id:
            pipe.association_status = "conflict"
            pipe.association_flags.append("TEXT_PATH_REACHES_ANOTHER_POINTID")
        else:
            claimed_box = valid_bbox(pipe.leader_bbox)
            if claimed_box:

                def inside_fraction(path: dict) -> float:
                    points = path.get("points", [])
                    if not points:
                        return 0.0
                    left, top, right, bottom = claimed_box
                    return sum(
                        left - 6 <= x <= right + 6 and top - 6 <= y <= bottom + 6 for x, y in points
                    ) / len(points)

                matched_paths = [paths[path_id] for path_id in matches[0]["path_ids"]]
                if any(inside_fraction(path) < 0.65 for path in matched_paths):
                    pipe.association_status = "conflict"
                    pipe.association_flags.append("TEXT_RECORD_AND_MODEL_LEADER_REGION_DISAGREE")
                    continue
                competing = [
                    path
                    for path_id, path in paths.items()
                    if path_id not in matches[0]["path_ids"] and inside_fraction(path) >= 0.65
                ]
                if competing:
                    pipe.association_status = "ambiguous"
                    pipe.association_flags.append("MODEL_LEADER_REGION_COVERS_MULTIPLE_PATHS")
                    continue
            pipe.association_status = "supported"
    states = {pipe.association_status for pipe in evidence.pipes}
    evidence.relationship_status = (
        "conflict"
        if "conflict" in states
        else "ambiguous"
        if "ambiguous" in states
        else "supported"
        if states == {"supported"}
        else "unverified"
    )


def apply_text_comparison(text: str, evidence: PageEvidence) -> str:
    comparison = compare_measurement_records(text, evidence)
    evidence.numerical_agreement = comparison.numerical_agreement
    evidence.pipe_record_agreement = comparison.pipe_record_agreement
    evidence.model_agreement = comparison.agreement
    return comparison.summary


def comparison_text_for_point(candidate: OcrCandidate, graph: dict | None) -> str:
    if (
        not graph
        or graph.get("status") != "complete"
        or graph.get("truncated") is not False
        or graph.get("source", {}).get("page_id") != candidate.page_id
    ):
        return candidate.raw_text
    regions = {region["id"]: region for region in graph.get("text_regions", [])}
    paths = {path["id"]: path for path in graph.get("paths", [])}
    texts = []
    for association in graph.get("associations", []):
        if (
            association.get("status") == "supported"
            and association.get("point_id") == candidate.point_id
        ):
            if not association.get("path_ids") or not all(
                paths.get(path_id, {}).get("evidence") == "original_pixels"
                and paths.get(path_id, {}).get("original_resolution_verified") is True
                for path_id in association["path_ids"]
            ):
                continue
            text = regions.get(association.get("text_id"), {}).get("text", "")
            if text and text not in texts:
                texts.append(text)
    return "\n".join(texts) if texts else candidate.raw_text


def map_crop_evidence_to_original(
    evidence: PageEvidence, original_path: str | Path, crop_bbox: list[int] | None, *, cropped: bool
) -> None:
    """Map model crop boxes back through the actual padded pixel crop, exactly once.

    This retains model observations as such; these boxes are not measured line evidence.
    The original crop is not rotated. Paddle's explicit rotated-view mapping lives in
    text_spotting.ViewTransform and is applied before its observations reach this layer.
    """
    if not cropped or not crop_bbox:
        return
    with Image.open(original_path) as source:
        image = ImageOps.exif_transpose(source)
        width, height = image.size
    rect = normalized_bbox_to_pixels(crop_bbox, width, height, padding=0.08)
    if not rect:
        return
    left, top, right, bottom = rect

    def remap(box: Any) -> list[int] | None:
        box = valid_bbox(box)
        if not box:
            return None
        return [
            round((left + box[0] / 1000 * (right - left)) / width * 1000),
            round((top + box[1] / 1000 * (bottom - top)) / height * 1000),
            round((left + box[2] / 1000 * (right - left)) / width * 1000),
            round((top + box[3] / 1000 * (bottom - top)) / height * 1000),
        ]

    evidence.bbox = remap(evidence.bbox)
    evidence.structure_bbox = remap(evidence.structure_bbox)
    for pipe in evidence.pipes:
        pipe.leader_bbox = remap(pipe.leader_bbox)


def store_page_graphs(
    evidences: list[PageEvidence], *, max_graph_bytes: int = 2_000_000
) -> dict[str, dict]:
    """Store each complete page graph once, preserving all ambiguous alternatives.

    Oversized graphs abstain explicitly rather than dropping competing paths. The
    project and benchmark export retain the canonical graph; evidence records retain
    their pipe-specific IDs and a reference key.
    """
    graphs: dict[str, dict] = {}
    seen: dict[int, str] = {}
    for evidence in evidences:
        graph = evidence.spatial_evidence
        if not graph:
            continue
        identity = id(graph)
        key = seen.get(identity)
        if key is None:
            encoded = json.dumps(graph, ensure_ascii=False, sort_keys=True, allow_nan=False).encode(
                "utf-8"
            )
            if len(encoded) > max_graph_bytes:
                graph = {
                    "schema_version": 1,
                    "status": "partial",
                    "truncated": True,
                    "review_only": True,
                    "source": deepcopy(graph.get("source", {})),
                    "flags": ["serialized_graph_budget"],
                    "structures": [],
                    "paths": [],
                    "associations": [],
                    "text_regions": [],
                    "point_anchors": [],
                }
                encoded = json.dumps(graph, sort_keys=True).encode("utf-8")
            key = evidence.page_id + ":" + hashlib.sha256(encoded).hexdigest()
            graphs[key] = graph
            seen[identity] = key
        if graphs[key].get("status") != "complete":
            apply_relationship_evidence(evidence, graphs[key])
        evidence.spatial_evidence_key = key
        evidence.spatial_evidence = {}
    return graphs
