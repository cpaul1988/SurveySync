"""Bounded, conservative spatial proposals measured from original page pixels.

This pilot recognizes closed, circle-like structures and intact ink leaders. It
does not read handwriting, repair missing strokes, interpret pipe values, or
accept evidence. A ``supported`` association is a proposal for review only.

All public coordinates are in the original page's 0--1000 coordinate space.
``structure_hints`` are never used as boundaries and cannot establish a path.
The implementation is original; see docs/development/fieldbook_spatial_core.md.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import hashlib
import math
import time
from typing import Callable, Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw


class SpatialCancelled(RuntimeError):
    """The caller cancelled pixel analysis; no partial support is returned."""


class _LimitReached(RuntimeError):
    pass


@dataclass(frozen=True)
class SpatialLimits:
    max_original_pixels: int = 24_000_000
    max_work_pixels: int = 600_000
    max_work_side: int = 1000
    max_seconds: float = 5.0
    max_text_regions: int = 256
    max_point_anchors: int = 128
    max_structure_hints: int = 128
    max_components: int = 4096
    max_runs: int = 80_000
    max_structures: int = 64
    max_paths: int = 128
    max_skeleton_pixels: int = 24_000
    max_thinning_iterations: int = 48
    max_path_points: int = 512
    max_endpoints_per_path: int = 64
    max_validation_pixels: int = 4_000_000
    ink_threshold: int = 170
    text_gap: float = 8.0  # normalized page units; used at path endpoints only
    min_path_length: float = 20.0  # normalized by the longer image dimension


class _Budget:
    def __init__(self, limits: SpatialLimits, cancelled: Callable[[], bool] | None):
        self.limits = limits
        self.cancelled = cancelled
        self.started = time.monotonic()
        self.validation_pixels = 0

    def check(self):
        if self.cancelled and self.cancelled():
            raise SpatialCancelled("Spatial association cancelled")
        if time.monotonic() - self.started > self.limits.max_seconds:
            raise _LimitReached("time_budget")


def _validate_limits(limits: SpatialLimits):
    for key, value in asdict(limits).items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a positive finite number")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be a positive finite number")
    if limits.ink_threshold > 254 or limits.max_path_points < 2:
        raise ValueError("ink_threshold must be <= 254 and max_path_points >= 2")
    if limits.max_work_side < 2 or limits.max_work_pixels < 4:
        raise ValueError("Working-image bounds must permit an image of at least 2x2 pixels")
    for key in asdict(limits):
        if key not in {"max_seconds", "text_gap", "min_path_length"}:
            if not isinstance(getattr(limits, key), int):
                raise ValueError(f"{key} must be an integer")


def _records(values: Sequence[Mapping], kind: str) -> list[dict]:
    result, seen = [], set()
    for value in values:
        if not isinstance(value, Mapping):
            raise ValueError(f"{kind} records must be mappings")
        ident = value.get("id")
        if not isinstance(ident, str) or not ident.strip() or ident in seen:
            raise ValueError(f"{kind} IDs must be nonempty and unique")
        seen.add(ident)
        box = value.get("bbox")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise ValueError(f"{kind} {ident}: bbox must contain four coordinates")
        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or not 0 <= v <= 1000
            for v in box
        ):
            raise ValueError(f"{kind} {ident}: coordinates must be finite and within 0--1000")
        x1, y1, x2, y2 = map(float, box)
        if x1 >= x2 or y1 >= y2:
            raise ValueError(f"{kind} {ident}: bbox must have positive ordered dimensions")
        record = dict(value)
        record["bbox"] = [x1, y1, x2, y2]
        result.append(record)
    return result


def _local_box(box: list[float], *, anchor: bool = False) -> bool:
    width, height = box[2] - box[0], box[3] - box[1]
    return (
        width * height <= (15_000 if anchor else 60_000)
        and width <= (250 if anchor else 650)
        and height <= (150 if anchor else 300)
    )


def _pixel_box(box, width, height, pad=0):
    return (
        max(0, math.floor(box[0] * width / 1000) - pad),
        max(0, math.floor(box[1] * height / 1000) - pad),
        min(width, math.ceil(box[2] * width / 1000) + pad),
        min(height, math.ceil(box[3] * height / 1000) + pad),
    )


def _norm_point(x, y, width, height):
    return [
        round(max(0, min(1000, x * 1000 / width)), 3),
        round(max(0, min(1000, y * 1000 / height)), 3),
    ]


def _norm_box(box, width, height):
    return _norm_point(box[0], box[1], width, height) + _norm_point(box[2], box[3], width, height)


def _dilate(mask, count=1):
    out = mask.copy()
    for _ in range(count):
        padded = np.pad(out, 1)
        out = np.logical_or.reduce(
            [
                padded[dy : dy + out.shape[0], dx : dx + out.shape[1]]
                for dy in range(3)
                for dx in range(3)
            ]
        )
    return out


def _components(mask: np.ndarray, budget: _Budget):
    """Eight-connected run-length components; bounded runs avoid pixel queues."""
    height, width = mask.shape
    parent = [0]
    runs = []
    previous = []

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for y in range(height):
        if y % 16 == 0:
            budget.check()
        changes = np.flatnonzero(np.diff(np.pad(mask[y].astype(np.int8), (1, 1))))
        current, prior_pos = [], 0
        for left, right in zip(changes[::2].tolist(), changes[1::2].tolist()):
            if len(runs) >= budget.limits.max_runs:
                raise _LimitReached("component_run_budget")
            label = len(parent)
            parent.append(label)
            while prior_pos < len(previous) and previous[prior_pos][1] < left:
                prior_pos += 1
            j = prior_pos
            while j < len(previous) and previous[j][0] <= right:
                old = root(previous[j][2])
                new = root(label)
                if old != new:
                    parent[new] = old
                j += 1
            current.append((left, right, label))
            runs.append((y, left, right, label))
        previous = current
    labels = np.zeros((height, width), dtype=np.int32)
    parts = {}
    for index, (y, left, right, label) in enumerate(runs):
        if index % 512 == 0:
            budget.check()
        key = root(label)
        if key not in parts:
            if len(parts) >= budget.limits.max_components:
                raise _LimitReached("component_count_budget")
            parts[key] = {"label": key, "bbox": [left, y, right, y + 1], "area": 0}
        item = parts[key]
        item["area"] += right - left
        box = item["bbox"]
        box[0], box[1] = min(box[0], left), min(box[1], y)
        box[2], box[3] = max(box[2], right), max(box[3], y + 1)
        labels[y, left:right] = key
    return labels, list(parts.values())


def _thin(mask, budget):
    """Zhang--Suen thinning with explicit iteration and cancellation bounds."""
    out = np.pad(mask, 1)
    for _ in range(budget.limits.max_thinning_iterations):
        budget.check()
        changed = False
        for phase in (0, 1):
            p = [
                out[:-2, 1:-1],
                out[:-2, 2:],
                out[1:-1, 2:],
                out[2:, 2:],
                out[2:, 1:-1],
                out[2:, :-2],
                out[1:-1, :-2],
                out[:-2, :-2],
            ]
            count = sum(v.astype(np.uint8) for v in p)
            transitions = sum((~p[i] & p[(i + 1) % 8]).astype(np.uint8) for i in range(8))
            remove = out[1:-1, 1:-1] & (count >= 2) & (count <= 6) & (transitions == 1)
            if phase == 0:
                remove &= ~(p[0] & p[2] & p[4]) & ~(p[2] & p[4] & p[6])
            else:
                remove &= ~(p[0] & p[2] & p[6]) & ~(p[0] & p[4] & p[6])
            if remove.any():
                out[1:-1, 1:-1][remove] = False
                changed = True
        if not changed:
            return out[1:-1, 1:-1]
    raise _LimitReached("thinning_iteration_budget")


def _skeleton_graph(mask, budget):
    skeleton = _thin(mask, budget)
    if int(skeleton.sum()) > budget.limits.max_skeleton_pixels:
        raise _LimitReached("skeleton_pixel_budget")
    padded = np.pad(skeleton, 1)
    p = [
        padded[:-2, 1:-1],
        padded[:-2, 2:],
        padded[1:-1, 2:],
        padded[2:, 2:],
        padded[2:, 1:-1],
        padded[2:, :-2],
        padded[1:-1, :-2],
        padded[:-2, :-2],
    ]
    counts = sum(v.astype(np.uint8) for v in p)
    transitions = sum((~p[i] & p[(i + 1) % 8]).astype(np.uint8) for i in range(8))
    ends = [(int(x), int(y)) for y, x in np.argwhere(skeleton & (counts == 1))]
    if len(ends) > budget.limits.max_endpoints_per_path:
        raise _LimitReached("path_endpoint_budget")
    branched = bool((skeleton & (transitions >= 3)).any()) or len(ends) != 2
    points = []
    if len(ends) == 2 and not branched:
        start, goal = ends
        queue = deque([start])
        visited = {start: None}
        while queue:
            if len(visited) % 128 == 0:
                budget.check()
            x, y = queue.popleft()
            if (x, y) == goal:
                break
            for dy, dx in ((-1, 0), (0, -1), (0, 1), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1)):
                xx, yy = x + dx, y + dy
                point = (xx, yy)
                if (
                    0 <= yy < mask.shape[0]
                    and 0 <= xx < mask.shape[1]
                    and skeleton[yy, xx]
                    and point not in visited
                ):
                    visited[point] = (x, y)
                    queue.append(point)
        if goal in visited:
            point = goal
            while point is not None:
                points.append(point)
                point = visited[point]
            points.reverse()
            # Keep every change of direction. Do not draw sampled shortcuts over
            # unobserved pixels when transporting a curved/stepped ink path.
            compact = points[:1]
            for i in range(1, len(points) - 1):
                before = (points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
                after = (points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
                if before != after:
                    compact.append(points[i])
            compact.extend(points[-1:])
            if len(compact) > budget.limits.max_path_points:
                raise _LimitReached("path_point_budget")
            points = compact
    # Branched components have endpoints but deliberately no invented single polyline.
    return points, ends, branched, int(skeleton.sum())


def _point_box_distance(point, box):
    return math.hypot(
        max(box[0] - point[0], 0, point[0] - box[2]), max(box[1] - point[1], 0, point[1] - box[3])
    )


def _source_hash(rgb, budget):
    digest = hashlib.sha256(f"RGB:{rgb.width}x{rgb.height}:".encode("ascii"))
    for top in range(0, rgb.height, 128):
        budget.check()
        digest.update(rgb.crop((0, top, rgb.width, min(top + 128, rgb.height))).tobytes())
    return digest.hexdigest()


def _endpoint_reaches_boundary(point, structure, ink):
    """Verify a short local original-ink connection; no dilation bridges gaps."""
    x, y = point
    rx1, ry1, rx2, ry2 = structure["roi"]
    if not rx1 - 8 <= x < rx2 + 8 or not ry1 - 8 <= y < ry2 + 8:
        return False
    queue, seen = deque([(x, y)]), {(x, y)}
    while queue:
        xx, yy = queue.popleft()
        if rx1 <= xx < rx2 and ry1 <= yy < ry2 and structure["border"][yy - ry1, xx - rx1]:
            return True
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nx, ny = xx + dx, yy + dy
                if (
                    (nx, ny) not in seen
                    and abs(nx - x) <= 8
                    and abs(ny - y) <= 8
                    and 0 <= nx < ink.shape[1]
                    and 0 <= ny < ink.shape[0]
                    and ink[ny, nx]
                ):
                    seen.add((nx, ny))
                    queue.append((nx, ny))
    return False


def _verify_source_resolution(rgb, path, structure, texts, anchors, budget, work_scale):
    """Check that resizing did not close a loop or bridge a leader's white gap.

    Only a bounded native-resolution ROI is inspected. Every ink component in a
    narrow corridor around the measured path must be the circle's component;
    disconnected fragments and competing nearby ink cause abstention.
    """
    boxes = [path["bbox"], structure["bbox"]]
    box = [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]
    radius = max(2, math.ceil(2 / work_scale))
    left, top, right, bottom = _pixel_box(box, rgb.width, rgb.height, pad=radius + 3)
    pixels = (right - left) * (bottom - top)
    budget.validation_pixels += pixels
    if budget.validation_pixels > budget.limits.max_validation_pixels:
        raise _LimitReached("source_validation_pixel_budget")
    budget.check()
    ink = (
        np.asarray(rgb.crop((left, top, right, bottom)).convert("L")) <= budget.limits.ink_threshold
    )
    for record in texts + anchors:
        if record["local"]:
            x1, y1, x2, y2 = _pixel_box(record["bbox"], rgb.width, rgb.height, pad=1)
            x1, x2 = max(0, x1 - left), min(right - left, x2 - left)
            y1, y2 = max(0, y1 - top), min(bottom - top, y2 - top)
            if x1 < x2 and y1 < y2:
                ink[y1:y2, x1:x2] = False
    white, holes = _components(~ink, budget)
    anchor = next(a for a in anchors if a["id"] in structure["anchor_ids"])
    cx = int((anchor["bbox"][0] + anchor["bbox"][2]) * rgb.width / 2000) - left
    cy = int((anchor["bbox"][1] + anchor["bbox"][3]) * rgb.height / 2000) - top
    if not 0 <= cx < ink.shape[1] or not 0 <= cy < ink.shape[0]:
        return False
    hole = next((h for h in holes if h["label"] == white[cy, cx]), None)
    if (
        hole is None
        or hole["bbox"][0] == 0
        or hole["bbox"][1] == 0
        or hole["bbox"][2] == ink.shape[1]
        or hole["bbox"][3] == ink.shape[0]
    ):
        return False
    inside = white == hole["label"]
    source_ids = set()
    for item in anchors:
        if not item["trusted"]:
            continue
        x1, y1, x2, y2 = _pixel_box(item["bbox"], rgb.width, rgb.height)
        if (
            left <= x1 < x2 <= right
            and top <= y1 < y2 <= bottom
            and np.all(inside[y1 - top : y2 - top, x1 - left : x2 - left])
        ):
            source_ids.add(item["point_id"])
    if source_ids != {structure["point_id"]}:
        return False
    labels, _ = _components(ink, budget)
    border = _dilate(inside) & ~inside
    target_labels = set(np.unique(labels[border]).tolist()) - {0}
    if len(target_labels) != 1:
        return False
    corridor = Image.new("1", (right - left, bottom - top))
    points = [
        (round(p[0] * rgb.width / 1000) - left, round(p[1] * rgb.height / 1000) - top)
        for p in path["points"]
    ]
    ImageDraw.Draw(corridor).line(points, fill=1, width=radius * 2 + 1)
    seen_labels = set(np.unique(labels[np.asarray(corridor, dtype=bool)]).tolist()) - {0}
    return seen_labels == target_labels


def associate_page_geometry(
    original_image: Image.Image,
    *,
    page_id: str,
    text_regions: Sequence[Mapping],
    point_anchors: Sequence[Mapping],
    structure_hints: Sequence[Mapping] = (),
    limits: SpatialLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Return JSON-safe measured geometry and conservative review proposals.

    Text records: ``{id, text, bbox, source}``. Anchor records additionally have
    ``point_id, raw_text, exact_match, independent``; raw_text must be the exact
    independently read ID token, preserving leading zeros. Duplicate readings
    inside one loop are permitted, but repeated IDs in separate loops abstain.

    The caller must supply a full original page and geometries already mapped to
    that page. A context crop or VLM leader box is not a valid pixel source. The
    routine neither accepts supplied polylines nor treats hints as boundaries.
    Invalid coordinates raise ValueError; cancellation raises SpatialCancelled.
    Budget exhaustion returns status='partial' and no supported associations.
    """
    limits = limits or SpatialLimits()
    _validate_limits(limits)
    budget = _Budget(limits, cancelled)
    if not isinstance(original_image, Image.Image) or min(original_image.size) < 2:
        raise ValueError("original_image must be a full PIL page image at least 2x2 pixels")
    if not isinstance(page_id, str) or not page_id.strip():
        raise ValueError("page_id must be nonempty")
    result = {
        "schema_version": 1,
        "status": "complete",
        "review_only": True,
        "source": {
            "page_id": page_id,
            "width": original_image.width,
            "height": original_image.height,
            "pixel_sha256": None,
            "coordinate_space": "original_normalized_0_1000",
        },
        "structures": [],
        "paths": [],
        "associations": [],
        "flags": [],
        "ignored_inputs": [],
        "limits": asdict(limits),
        "truncated": False,
    }
    try:
        budget.check()
        for values, maximum in (
            (text_regions, limits.max_text_regions),
            (point_anchors, limits.max_point_anchors),
            (structure_hints, limits.max_structure_hints),
        ):
            if len(values) > maximum:
                raise _LimitReached("input_record_budget")
        if original_image.width * original_image.height > limits.max_original_pixels:
            raise _LimitReached("original_pixel_budget")
        texts = _records(text_regions, "text")
        anchors = _records(point_anchors, "anchor")
        hints = _records(structure_hints, "hint")
        for text in texts:
            if not isinstance(text.get("text"), str):
                raise ValueError("text records require a string text")
            result["associations"].append(
                {
                    "text_id": text["id"],
                    "point_id": None,
                    "structure_id": None,
                    "path_ids": [],
                    "status": "unresolved",
                    "candidates": [],
                    "reasons": ["no_measured_path"],
                }
            )
        rgb = original_image.convert("RGB")
        result["source"]["pixel_sha256"] = _source_hash(rgb, budget)
        scale = min(
            1.0,
            limits.max_work_side / max(rgb.size),
            math.sqrt(limits.max_work_pixels / (rgb.width * rgb.height)),
        )
        width, height = max(2, int(rgb.width * scale)), max(2, int(rgb.height * scale))
        work = rgb.convert("L").resize((width, height), Image.Resampling.LANCZOS)
        result["analysis"] = {
            "width": width,
            "height": height,
            "ink_threshold": limits.ink_threshold,
            "boundary_method": "closed_original_ink_loop",
            "path_method": "unrepaired_original_ink_skeleton",
        }
        ink = np.asarray(work) <= limits.ink_threshold
        usable_texts = []
        for record, anchor in [(x, False) for x in texts] + [(x, True) for x in anchors]:
            local = _local_box(record["bbox"], anchor=anchor)
            record["local"] = local
            if local:
                x1, y1, x2, y2 = _pixel_box(record["bbox"], width, height, pad=1)
                ink[y1:y2, x1:x2] = False
                if not anchor:
                    usable_texts.append(record)
            else:
                result["ignored_inputs"].append(
                    {"id": record["id"], "reason": "nonlocal_context_box"}
                )
        for anchor in anchors:
            point_id, raw = anchor.get("point_id"), anchor.get("raw_text")
            anchor["trusted"] = bool(
                anchor["local"]
                and isinstance(point_id, str)
                and point_id.strip()
                and isinstance(raw, str)
                and raw.strip() == point_id
                and anchor.get("exact_match") is True
                and anchor.get("independent") is True
                and isinstance(anchor.get("source"), str)
                and anchor["source"]
            )
        raw_labels, _ = _components(ink, budget)
        holes, regions = _components(~ink, budget)
        erased = np.zeros_like(ink)
        measured = []
        for region in regions:
            budget.check()
            x1, y1, x2, y2 = region["bbox"]
            rw, rh = x2 - x1, y2 - y1
            if x1 == 0 or y1 == 0 or x2 == width or y2 == height:
                continue
            if min(rw, rh) < 12 or max(rw / width, rh / height) > 0.35:
                continue
            fill = region["area"] / (rw * rh)
            if not 0.60 <= rw / rh <= 1.67 or not 0.62 <= fill <= 0.91:
                continue
            if len(measured) >= limits.max_structures:
                raise _LimitReached("structure_count_budget")
            # A local halo removes the measured boundary, not a rectangular VLM crop.
            halo = 6
            rx1, ry1, rx2, ry2 = (
                max(0, x1 - halo),
                max(0, y1 - halo),
                min(width, x2 + halo),
                min(height, y2 + halo),
            )
            inside = holes[ry1:ry2, rx1:rx2] == region["label"]
            border = _dilate(inside) & ~inside
            circle_ink_labels = set(np.unique(raw_labels[ry1:ry2, rx1:rx2][border]).tolist()) - {0}
            if not circle_ink_labels:
                continue
            body = _dilate(inside, 5)
            erased[ry1:ry2, rx1:rx2] |= body
            enclosed = []
            all_enclosed = []
            for anchor in anchors:
                ax1, ay1, ax2, ay2 = _pixel_box(anchor["bbox"], width, height)
                if ax2 > ax1 and ay2 > ay1 and np.all(holes[ay1:ay2, ax1:ax2] == region["label"]):
                    all_enclosed.append(anchor["id"])
                    if anchor["trusted"]:
                        enclosed.append(anchor)
            unique_ids = sorted({a["point_id"] for a in enclosed})
            ident = f"structure-{len(measured) + 1}"
            item = {
                "id": ident,
                "kind": "circle_like_closed_loop",
                "bbox": _norm_box((x1 - 1, y1 - 1, x2 + 1, y2 + 1), width, height),
                "evidence": "original_pixels",
                "point_id": unique_ids[0] if len(unique_ids) == 1 else None,
                "anchor_ids": [a["id"] for a in enclosed],
                "enclosed_anchor_ids": all_enclosed,
                "candidate_point_ids": unique_ids,
                "status": "supported"
                if len(unique_ids) == 1
                else "ambiguous"
                if unique_ids
                else "unresolved",
                "reasons": []
                if len(unique_ids) == 1
                else [
                    "multiple_exact_point_ids" if unique_ids else "no_independent_exact_point_id"
                ],
                "metrics": {"interior_fill": round(fill, 4), "interior_pixels": region["area"]},
                "hint_ids": [
                    h["id"]
                    for h in hints
                    if _local_box(h["bbox"])
                    and h["bbox"][0] <= (x1 + x2) * 500 / width <= h["bbox"][2]
                    and h["bbox"][1] <= (y1 + y2) * 500 / height <= h["bbox"][3]
                ],
                "original_resolution_verified": scale == 1.0,
            }
            result["structures"].append(item)
            measured.append(
                {
                    "item": item,
                    "roi": (rx1, ry1, rx2, ry2),
                    "body": body,
                    "raw_labels": circle_ink_labels,
                    "border": border & ink[ry1:ry2, rx1:rx2],
                }
            )
        for item in result["structures"]:
            if (
                item["point_id"]
                and sum(other["point_id"] == item["point_id"] for other in result["structures"]) > 1
            ):
                item["status"] = "ambiguous"
                item["reasons"].append("point_id_repeated_in_separate_structures")
        labels, parts = _components(ink & ~erased, budget)
        structure_contacts = {}
        for structure in measured:
            x1, y1, x2, y2 = structure["roi"]
            frontier = _dilate(structure["body"]) & ~structure["body"]
            local_path_labels = labels[y1:y2, x1:x2]
            for label in set(np.unique(local_path_labels[frontier]).tolist()) - {0}:
                positions = (local_path_labels == label) & frontier
                # Require an original connected-ink component shared with the boundary.
                shared = set(np.unique(raw_labels[y1:y2, x1:x2][positions]).tolist())
                if shared & structure["raw_labels"]:
                    structure_contacts.setdefault(label, []).append(structure["item"]["id"])
        for part in parts:
            budget.check()
            if part["label"] not in structure_contacts:
                continue
            x1, y1, x2, y2 = part["bbox"]
            if math.hypot(x2 - x1, y2 - y1) * 1000 / max(width, height) < limits.min_path_length:
                continue
            if len(result["paths"]) >= limits.max_paths:
                raise _LimitReached("path_count_budget")
            crop = labels[y1:y2, x1:x2] == part["label"]
            points, ends, branched, count = _skeleton_graph(crop, budget)
            ends = [(x + x1, y + y1) for x, y in ends]
            text_contacts = []
            endpoint_contacts = {}
            for text in usable_texts:
                box = _pixel_box(text["bbox"], width, height)
                near = [
                    i
                    for i, point in enumerate(ends)
                    if _point_box_distance(point, box) * 1000 / max(width, height)
                    <= limits.text_gap
                ]
                if near:
                    text_contacts.append(text["id"])
                    endpoint_contacts[text["id"]] = near
            structure_endpoints = {}
            for structure in measured:
                if structure["item"]["id"] not in structure_contacts[part["label"]]:
                    continue
                near = [
                    i
                    for i, point in enumerate(ends)
                    if _endpoint_reaches_boundary(point, structure, ink)
                ]
                if near:
                    structure_endpoints[structure["item"]["id"]] = near
            if points:
                points = [_norm_point(x + x1, y + y1, width, height) for x, y in points]
            path = {
                "id": f"path-{len(result['paths']) + 1}",
                "points": points,
                "endpoints": [_norm_point(x, y, width, height) for x, y in ends],
                "bbox": _norm_box((x1, y1, x2, y2), width, height),
                "pixel_count": part["area"],
                "skeleton_pixel_count": count,
                "branched": branched,
                "structure_ids": structure_contacts[part["label"]],
                "text_ids": text_contacts,
                "text_endpoint_indices": endpoint_contacts,
                "structure_endpoint_indices": structure_endpoints,
                "original_resolution_verified": scale == 1.0,
                "evidence": "original_pixels",
            }
            result["paths"].append(path)
        structures = {s["id"]: s for s in result["structures"]}
        for association in result["associations"]:
            paths = [p for p in result["paths"] if association["text_id"] in p["text_ids"]]
            association["path_ids"] = [p["id"] for p in paths]
            if not paths:
                if any(i["id"] == association["text_id"] for i in result["ignored_inputs"]):
                    association["reasons"] = ["nonlocal_context_box"]
                continue
            targets = sorted({sid for p in paths for sid in p["structure_ids"]})
            association["candidates"] = [
                {
                    "structure_id": sid,
                    "point_id": structures[sid]["point_id"],
                    "path_ids": [p["id"] for p in paths if sid in p["structure_ids"]],
                }
                for sid in targets
            ]
            reasons = []
            if len(paths) != 1:
                reasons.append("multiple_measured_paths")
            if any(p["branched"] for p in paths):
                reasons.append("crossing_or_branched_ink")
            if any(len(p["text_ids"]) != 1 for p in paths):
                reasons.append("competing_text_regions")
            if len(targets) != 1:
                reasons.append("multiple_structure_targets")
            if any(structures[sid]["status"] != "supported" for sid in targets):
                reasons.append("no_unique_independent_point_id")
            if len(paths) == 1 and len(targets) == 1:
                path = paths[0]
                text_ends = path["text_endpoint_indices"].get(association["text_id"], [])
                structure_ends = path["structure_endpoint_indices"].get(targets[0], [])
                if len(text_ends) != 1 or len(structure_ends) != 1 or text_ends == structure_ends:
                    reasons.append("no_opposite_terminal_evidence")
            if not reasons and scale < 1.0:
                paths[0]["original_resolution_verified"] = _verify_source_resolution(
                    rgb, paths[0], structures[targets[0]], texts, anchors, budget, scale
                )
                if not paths[0]["original_resolution_verified"]:
                    reasons.append("source_resolution_geometry_not_verified")
                else:
                    structures[targets[0]]["original_resolution_verified"] = True
            association["reasons"] = reasons or ["intact_original_ink_path_to_unique_exact_id"]
            association["status"] = "ambiguous" if reasons else "supported"
            if not reasons:
                association["structure_id"] = targets[0]
                association["point_id"] = structures[targets[0]]["point_id"]
        budget.check()
    except _LimitReached as exc:
        result["status"] = "partial"
        result["truncated"] = True
        result["flags"].append(str(exc))
        for association in result["associations"]:
            association.update(
                status="unresolved",
                point_id=None,
                structure_id=None,
                reasons=["incomplete_topology", str(exc)],
            )
        for structure in result["structures"]:
            structure["status"] = "unresolved"
            structure["reasons"].append("incomplete_topology")
    return result
