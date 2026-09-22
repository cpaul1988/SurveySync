"""Conservative, explainable feature-chain change detection for rod-height review."""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import mean, median, pstdev
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .codes import CodeRule, classify, parse_code
from .imports import TopoPoint

Unit = Literal["us_survey_feet", "international_feet", "meters"]
# Convert an international-foot threshold to the explicitly selected coordinate unit.
UNITS_PER_FOOT = {"international_feet": 1.0, "us_survey_feet": 0.999998, "meters": 0.3048}


class DetectionSettings(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    horizontal_units: Unit = "us_survey_feet"
    vertical_units: Unit = "us_survey_feet"
    order: Literal["file", "point_id"] = "file"
    order_confirmed: bool = False
    units_confirmed: bool = False
    classifications_reviewed: bool = False
    min_offset_ft: float = Field(default=0.45, gt=0, le=100)
    consistency_ft: float = Field(default=0.10, gt=0, le=10)
    reject_scatter_ft: float = Field(default=0.40, gt=0, le=100)
    max_chain_gap_ft: float = Field(default=150, gt=0, le=10000)
    exclusion_radius_ft: float = Field(default=25, gt=0, le=1000)
    context_points: int = Field(default=3, ge=3, le=12)
    correlation_rows: int = Field(default=12, ge=0, le=1000)
    max_projection_ft: float = Field(default=1500, gt=0, le=100000)
    max_range_points: int = Field(default=1000, ge=1, le=10000)


@dataclass
class Node:
    point: TopoPoint
    index: int
    distance: float


def _fit(nodes: list[Node]) -> tuple[float, float, float]:
    """Fit Z against horizontal chainage using centered coordinates."""
    xm = mean(n.distance for n in nodes)
    zm = mean(n.point.elevation for n in nodes)
    denominator = math.fsum((n.distance - xm) ** 2 for n in nodes)
    if denominator < 1e-12:
        raise ValueError("Insufficient horizontal separation for a grade model.")
    slope = math.fsum((n.distance - xm) * (n.point.elevation - zm) for n in nodes) / denominator
    intercept = zm - slope * xm
    residual = max(abs(n.point.elevation - (intercept + slope * n.distance)) for n in nodes)
    return intercept, slope, residual


def build_chains(
    points: list[TopoPoint], rules: dict[str, CodeRule], settings: DetectionSettings
) -> list[list[Node]]:
    active: dict[tuple[str, str], list[Node]] = {}
    chains: list[list[Node]] = []
    gap = settings.max_chain_gap_ft * UNITS_PER_FOOT[settings.horizontal_units]
    for index, point in enumerate(points):
        if classify(point.code, rules).role != "surface":
            continue
        base, string_id, markers = parse_code(point.code)
        key = base, string_id
        chain = active.get(key)
        distance = (
            math.hypot(
                point.easting - chain[-1].point.easting, point.northing - chain[-1].point.northing
            )
            if chain
            else 0.0
        )
        # BS/ES are string markers, not proof of a backsight or an instrument setup.
        if chain is None or "BS" in markers or distance > gap or distance <= 1e-8:
            chain = []
            chains.append(chain)
            active[key] = chain
        chain.append(Node(point, index, chain[-1].distance + distance if chain else 0.0))
        if "ES" in markers:
            active.pop(key, None)
    return chains


def _chain_events(
    chain: list[Node], setups: list[int], settings: DetectionSettings, chain_id: int
) -> list[dict]:
    scale = UNITS_PER_FOOT[settings.vertical_units]
    tolerance = settings.consistency_ft * scale
    minimum = settings.min_offset_ft * scale
    projection = settings.max_projection_ft * UNITS_PER_FOOT[settings.horizontal_units]
    events: list[dict] = []
    i = settings.context_points
    while i < len(chain):
        before = chain[i - settings.context_points : i]
        try:
            intercept, slope, fit_error = _fit(before)
        except ValueError:
            i += 1
            continue
        start = chain[i]
        offset = start.point.elevation - (intercept + slope * start.distance)
        if (
            fit_error > tolerance
            or abs(offset) < minimum
            or start.distance - before[-1].distance > projection
        ):
            i += 1
            continue
        setup_index = bisect_right(setups, start.index)
        next_setup = setups[setup_index] if setup_index < len(setups) else math.inf
        affected = [start]
        offsets = [offset]
        recovery: Node | None = None
        boundary = "unverified_end"
        j = i + 1
        while j < len(chain) and len(affected) < settings.max_range_points:
            node = chain[j]
            if node.index >= next_setup:
                boundary = "setup_boundary"
                break
            if node.distance - before[-1].distance > projection:
                boundary = "projection_limit"
                break
            residual = node.point.elevation - (intercept + slope * node.distance)
            if abs(residual) <= tolerance:
                recovery = node
                boundary = "grade_recovery"
                break
            # A different offset or a changing grade ends the evidence interval.
            if abs(residual - median(offsets)) > settings.reject_scatter_ft * scale:
                boundary = "inconsistent_offset"
                break
            affected.append(node)
            offsets.append(residual)
            j += 1
        if len(affected) >= settings.max_range_points and recovery is None:
            boundary = "range_limit"
        if recovery is not None:
            # Validate against unaffected observations on both sides of the suspect span.
            after = chain[j : j + settings.context_points]
            if len(after) < settings.context_points:
                boundary = "insufficient_recovery_context"
            else:
                try:
                    intercept, slope, fit_error = _fit(before + after)
                except ValueError:
                    i += 1
                    continue
                offsets = [n.point.elevation - (intercept + slope * n.distance) for n in affected]
                if fit_error > tolerance:
                    i += 1
                    continue
        scatter = pstdev(offsets) if len(offsets) > 1 else 0.0
        average = mean(offsets)
        if abs(average) >= minimum and scatter <= settings.reject_scatter_ft * scale:
            base, _, markers = parse_code(start.point.code)
            events.append(
                {
                    "chain_id": chain_id,
                    "feature": base,
                    "start_index": start.index,
                    "end_index": affected[-1].index,
                    "offset": average,
                    "offsets": offsets,
                    "point_ids": [n.point.point_id for n in affected],
                    "indices": [n.index for n in affected],
                    "prior_good_point": before[-1].point.point_id,
                    "next_good_point": recovery.point.point_id if recovery else None,
                    "boundary": boundary,
                    "std_dev": scatter,
                    "chain_markers": sorted(markers),
                    "model_max_error": fit_error,
                    "start_xy": [start.point.easting, start.point.northing],
                    "setup_near_start": any(
                        0 <= start.index - index <= settings.correlation_rows
                        for index in setups[
                            max(0, bisect_right(setups, start.index) - 1) : bisect_right(
                                setups, start.index
                            )
                        ]
                    ),
                }
            )
            i = max(i + 1, j + settings.context_points if recovery is not None else j)
        else:
            i += 1
    return events


def _groups(events: list[dict], settings: DetectionSettings) -> list[list[dict]]:
    groups: list[list[dict]] = []
    tolerance = settings.consistency_ft * UNITS_PER_FOOT[settings.vertical_units]
    distance_limit = settings.max_chain_gap_ft * UNITS_PER_FOOT[settings.horizontal_units]
    for event in sorted(events, key=lambda e: e["start_index"]):
        for group in reversed(groups):
            earliest = min(e["start_index"] for e in group)
            latest_end = max(e["end_index"] for e in group)
            near_start = event["start_index"] - earliest <= settings.correlation_rows
            overlap = event["start_index"] <= latest_end + settings.correlation_rows
            same_chain = any(e["chain_id"] == event["chain_id"] for e in group)
            xy = group[0]["start_xy"]
            nearby = (
                math.hypot(event["start_xy"][0] - xy[0], event["start_xy"][1] - xy[1])
                <= distance_limit
            )
            consistent = all(abs(event["offset"] - e["offset"]) <= tolerance for e in group)
            if near_start and overlap and nearby and consistent and not same_chain:
                group.append(event)
                break
        else:
            groups.append([event])
    return groups


def analyze(
    points: list[TopoPoint], code_rules: list[CodeRule], settings: DetectionSettings
) -> dict:
    if settings.reject_scatter_ft < settings.consistency_ft:
        raise ValueError("Reject scatter must be at least the consistency tolerance.")
    normalized = [r.model_copy(update={"code": r.code.strip().upper()}) for r in code_rules]
    rules = {r.code: r for r in normalized}
    if len(rules) != len(normalized):
        raise ValueError("Code list contains duplicate codes.")
    if settings.order == "point_id":
        if not all(p.point_id.isdigit() for p in points):
            raise ValueError(
                "Numeric PointID order requires all-numeric IDs; use file order for alphanumeric IDs."
            )
        points = sorted(points, key=lambda p: (int(p.point_id), p.source_row))
    roles = [classify(p.code, rules) for p in points]
    setups = [i for i, role in enumerate(roles) if role.role == "setup"]
    chains = build_chains(points, rules, settings)
    events = [
        event
        for cid, chain in enumerate(chains)
        for event in _chain_events(chain, setups, settings, cid)
    ]
    if len(events) > 5000:
        raise ValueError(
            "More than 5,000 discontinuities: split the survey or review code/tolerance settings."
        )
    radius = settings.exclusion_radius_ft * UNITS_PER_FOOT[settings.horizontal_units]
    hazard_grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (p, role) in enumerate(zip(points, roles)):
        if role.role in {"discontinuity", "ditch", "creek", "structure"}:
            hazard_grid[(math.floor(p.easting / radius), math.floor(p.northing / radius))].append(i)
    results: list[dict] = []
    scale = UNITS_PER_FOOT[settings.vertical_units]
    for group in _groups(events, settings):
        start = min(e["start_index"] for e in group)
        end = max(e["end_index"] for e in group)
        affected_indices = set(i for e in group for i in e["indices"])
        features = sorted({e["feature"] for e in group})
        offsets = [v for e in group for v in e["offsets"]]
        average, scatter = mean(offsets), pstdev(offsets) if len(offsets) > 1 else 0.0
        hazards: set[int] = set()
        for i in affected_indices:
            p = points[i]
            cx, cy = math.floor(p.easting / radius), math.floor(p.northing / radius)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for index in hazard_grid.get((cx + dx, cy + dy), []):
                        q = points[index]
                        if math.hypot(p.easting - q.easting, p.northing - q.northing) <= radius:
                            hazards.add(index)
        unknown = [points[i].point_id for i in range(start, end + 1) if roles[i].role == "unknown"]
        conflicting = [
            points[i].point_id
            for i in range(start, end + 1)
            if roles[i].role == "surface" and i not in affected_indices
        ]
        closed = all(e["boundary"] == "grade_recovery" for e in group)
        constant = scatter <= settings.consistency_ft * scale
        score_parts = {
            "feature_agreement": min(40, 8 * len(features)),
            "constant_offset": 25 if constant else -40,
            "setup_boundary": 15 if any(e["setup_near_start"] for e in group) else 0,
            "surface_features": 10,
            "independent_chains": 10 if len(group) >= 2 else 0,
        }
        if hazards:
            kinds = {roles[i].role for i in hazards}
            score_parts["terrain_exclusion"] = (
                -50 if "discontinuity" in kinds else -30 if kinds & {"ditch", "creek"} else -20
            )
        confidence = max(0, min(100, sum(score_parts.values())))
        status = (
            "SUPPRESSED"
            if hazards
            else "PROBABLE"
            if confidence > 80 and closed and constant and not conflicting
            else "REVIEW"
        )
        ready = (
            status == "PROBABLE"
            and settings.order_confirmed
            and settings.units_confirmed
            and settings.classifications_reviewed
            and not unknown
        )
        blockers = []
        if hazards:
            blockers.append("Nearby terrain/structure exclusion evidence")
        if not closed:
            blockers.append("End boundary lacks independently verified grade recovery")
        if not constant:
            blockers.append("Offset scatter exceeds the consistency tolerance")
        if conflicting:
            blockers.append("Other surface observations inside the range do not support the shift")
        if unknown:
            blockers.append("Unclassified codes occur inside the proposed range")
        if not settings.units_confirmed:
            blockers.append("Coordinate and elevation units have not been confirmed")
        if not settings.order_confirmed:
            blockers.append("Acquisition order has not been confirmed")
        if not settings.classifications_reviewed:
            blockers.append("Code classifications have not been reviewed")
        if confidence <= 80:
            blockers.append("Evidence score does not exceed 80")
        results.append(
            {
                "candidate_id": f"RHB-{len(results) + 1:04d}",
                "start_point": points[start].point_id,
                "end_point": points[end].point_id,
                "start_source_row": points[start].source_row,
                "end_source_row": points[end].source_row,
                "estimated_rod_bust": average,
                "recommended_correction": -average if ready else None,
                "offset_std_dev": scatter,
                "confidence": confidence,
                "confidence_kind": "heuristic evidence score, not a calibrated probability",
                "status": status,
                "correction_ready": ready,
                "blockers": blockers,
                "score_breakdown": score_parts,
                "supporting_features": [f"{code} {rules[code].description}" for code in features],
                "affected_point_ids": [p.point_id for p in points[start : end + 1]],
                "supporting_point_ids": [points[i].point_id for i in sorted(affected_indices)],
                "excluded_nearby": [
                    {"point_id": points[i].point_id, "code": points[i].code, "role": roles[i].role}
                    for i in sorted(hazards)
                ],
                "conflicting_surface_points": conflicting,
                "unclassified_points": unknown,
                "chain_evidence": group,
                "reason": f"{len(features)} surface feature classes support an observed-minus-expected shift of {average:+.4f} {settings.vertical_units}; scatter {scatter:.4f}. "
                + (
                    "Both sides of each supporting chain fit the local grade model. "
                    if closed
                    else "The end remains uncertain. "
                )
                + (
                    "Nearby terrain/structure evidence suppresses this candidate."
                    if hazards
                    else "No mapped exclusion feature was found within the configured radius."
                ),
            }
        )
    warnings = [
        "Point numbers alone do not establish acquisition chronology. Review the selected order.",
        "This is candidate detection, not proof of a rod-height error. Real grade changes can mimic a common offset.",
        "BS/ES/PC/PT are string/curve markers and do not alone earn setup confidence.",
    ]
    if any(r.role == "unknown" for r in roles):
        warnings.append("Some codes are unclassified and cannot provide primary evidence.")
    return {
        "settings": settings.model_dump(),
        "point_count": len(points),
        "chain_count": len(chains),
        "role_counts": dict(Counter(r.role for r in roles)),
        "candidates": results,
        "probable_count": sum(r["status"] == "PROBABLE" for r in results),
        "suppressed_count": sum(r["status"] == "SUPPRESSED" for r in results),
        "warnings": warnings,
    }
