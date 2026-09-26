"""Cross-section, earthwork, and slope-catch calculations for SurveySync.

Algorithms are adapted from the MIT-licensed Cogokit cross-section/stakeout
modules, but exposed as plain SurveySync data structures with explicit units and
reviewable outputs.
"""

from __future__ import annotations

import math
from typing import Any


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite.")
    return number


def _profile(points: list[dict[str, Any]], *, relative: bool = False) -> list[tuple[float, float]]:
    if len(points) < 2:
        raise ValueError("A profile requires at least two points.")
    cleaned: list[tuple[float, float]] = []
    value_key = "relative_elevation" if relative else "elevation"
    for index, point in enumerate(points, start=1):
        cleaned.append(
            (
                _finite(f"Profile point {index} offset", point.get("offset")),
                _finite(f"Profile point {index} {value_key}", point.get(value_key)),
            )
        )
    cleaned.sort(key=lambda item: item[0])
    if any(abs(cleaned[i + 1][0] - cleaned[i][0]) <= 1e-12 for i in range(len(cleaned) - 1)):
        raise ValueError("Profile offsets must be unique.")
    return cleaned


def _interp(profile: list[tuple[float, float]], offset: float) -> float:
    x = float(offset)
    if x <= profile[0][0]:
        p0, p1 = profile[0], profile[1]
    elif x >= profile[-1][0]:
        p0, p1 = profile[-2], profile[-1]
    else:
        p0 = p1 = profile[0]
        for i in range(len(profile) - 1):
            if profile[i][0] <= x <= profile[i + 1][0]:
                p0, p1 = profile[i], profile[i + 1]
                break
    t = (x - p0[0]) / (p1[0] - p0[0])
    return p0[1] + t * (p1[1] - p0[1])


def cross_section_cut_fill(
    *,
    ground_points: list[dict[str, Any]],
    design_points: list[dict[str, Any]],
    design_centerline_elevation: float,
) -> dict[str, Any]:
    """Compute cut/fill area over the overlap of ground and design profiles."""

    ground = _profile(ground_points)
    design_rel = _profile(design_points, relative=True)
    design_cl = _finite("Design centerline elevation", design_centerline_elevation)

    common_min = max(ground[0][0], design_rel[0][0])
    common_max = min(ground[-1][0], design_rel[-1][0])
    if common_max <= common_min:
        raise ValueError("Ground and design profiles do not overlap.")

    offsets = sorted(
        {common_min, common_max}
        | {x for x, _ in ground if common_min <= x <= common_max}
        | {x for x, _ in design_rel if common_min <= x <= common_max}
    )
    if len(offsets) < 2:
        raise ValueError("Cross section has insufficient overlapping profile width.")

    rows: list[dict[str, float]] = []
    differences: list[float] = []
    for offset in offsets:
        ground_elev = _interp(ground, offset)
        design_elev = design_cl + _interp(design_rel, offset)
        diff = ground_elev - design_elev
        differences.append(diff)
        rows.append(
            {
                "offset": offset,
                "ground_elevation": ground_elev,
                "design_elevation": design_elev,
                "difference": diff,
            }
        )

    cut = 0.0
    fill = 0.0
    for i in range(len(offsets) - 1):
        width = offsets[i + 1] - offsets[i]
        d0 = differences[i]
        d1 = differences[i + 1]
        if d0 >= 0 and d1 >= 0:
            cut += (d0 + d1) * 0.5 * width
        elif d0 <= 0 and d1 <= 0:
            fill += (abs(d0) + abs(d1)) * 0.5 * width
        else:
            fraction = d0 / (d0 - d1)
            first_width = width * fraction
            second_width = width - first_width
            if d0 > 0:
                cut += abs(d0) * 0.5 * first_width
                fill += abs(d1) * 0.5 * second_width
            else:
                fill += abs(d0) * 0.5 * first_width
                cut += abs(d1) * 0.5 * second_width

    return {
        "cut_area": cut,
        "fill_area": fill,
        "net_area_cut_positive": cut - fill,
        "width": common_max - common_min,
        "offset_min": common_min,
        "offset_max": common_max,
        "profile": rows,
    }


def average_end_area_earthwork(*, sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute cut/fill volumes between ordered sections by average end area."""

    if len(sections) < 2:
        raise ValueError("At least two cross sections are required.")
    cleaned: list[dict[str, float]] = []
    for index, section in enumerate(sections, start=1):
        cleaned.append(
            {
                "station": _finite(f"Section {index} station", section.get("station")),
                "cut_area": max(0.0, _finite(f"Section {index} cut area", section.get("cut_area"))),
                "fill_area": max(
                    0.0, _finite(f"Section {index} fill area", section.get("fill_area"))
                ),
            }
        )
    cleaned.sort(key=lambda row: row["station"])
    for i in range(len(cleaned) - 1):
        if cleaned[i + 1]["station"] <= cleaned[i]["station"]:
            raise ValueError("Cross-section stations must be unique.")

    intervals: list[dict[str, float]] = []
    cumulative_cut = 0.0
    cumulative_fill = 0.0
    for first, second in zip(cleaned, cleaned[1:], strict=True):
        distance = second["station"] - first["station"]
        cut_volume = (first["cut_area"] + second["cut_area"]) * 0.5 * distance
        fill_volume = (first["fill_area"] + second["fill_area"]) * 0.5 * distance
        cumulative_cut += cut_volume
        cumulative_fill += fill_volume
        intervals.append(
            {
                "station_from": first["station"],
                "station_to": second["station"],
                "distance": distance,
                "cut_volume": cut_volume,
                "fill_volume": fill_volume,
                "net_volume_cut_positive": cut_volume - fill_volume,
                "cumulative_cut": cumulative_cut,
                "cumulative_fill": cumulative_fill,
                "mass_haul_ordinate": cumulative_cut - cumulative_fill,
            }
        )

    return {
        "method": "average_end_area",
        "section_count": len(cleaned),
        "interval_count": len(intervals),
        "total_cut_volume": cumulative_cut,
        "total_fill_volume": cumulative_fill,
        "net_volume_cut_positive": cumulative_cut - cumulative_fill,
        "intervals": intervals,
    }


def slope_catch_2d(
    *,
    ground_points: list[dict[str, Any]],
    design_points: list[dict[str, Any]],
    design_centerline_elevation: float,
    side: str,
) -> dict[str, Any]:
    """Intersect the outer design-template slope with a ground profile."""

    ground = _profile(ground_points)
    design = _profile(design_points, relative=True)
    design_cl = _finite("Design centerline elevation", design_centerline_elevation)
    side_text = str(side or "").strip().upper()
    if side_text not in {"LEFT", "RIGHT"}:
        raise ValueError("Slope-catch side must be LEFT or RIGHT.")

    candidates = (
        [p for p in design if p[0] <= 0]
        if side_text == "LEFT"
        else [p for p in design if p[0] >= 0]
    )
    if len(candidates) < 2:
        raise ValueError(f"Design template needs at least two {side_text.lower()}-side points.")
    candidates.sort(key=lambda item: item[0])

    if side_text == "LEFT":
        outer, inner = candidates[0], candidates[1]
    else:
        inner, outer = candidates[-2], candidates[-1]

    slope = (outer[1] - inner[1]) / (outer[0] - inner[0])
    outer_offset = outer[0]
    outer_elevation = design_cl + outer[1]

    ground_segments = list(zip(ground, ground[1:], strict=True))
    if side_text == "LEFT":
        ground_segments = list(reversed(ground_segments))

    for p0, p1 in ground_segments:
        seg_min, seg_max = min(p0[0], p1[0]), max(p0[0], p1[0])
        if side_text == "RIGHT" and seg_max < outer_offset:
            continue
        if side_text == "LEFT" and seg_min > outer_offset:
            continue

        g_slope = (p1[1] - p0[1]) / (p1[0] - p0[0])
        denominator = slope - g_slope
        if abs(denominator) <= 1e-12:
            continue
        offset = (p0[1] - g_slope * p0[0] - outer_elevation + slope * outer_offset) / denominator
        if seg_min - 1e-9 <= offset <= seg_max + 1e-9:
            if side_text == "RIGHT" and offset < outer_offset - 1e-9:
                continue
            if side_text == "LEFT" and offset > outer_offset + 1e-9:
                continue
            elevation = outer_elevation + slope * (offset - outer_offset)
            return {
                "side": side_text,
                "catch_offset": offset,
                "catch_elevation": elevation,
                "template_extension_slope": slope,
                "outer_template_offset": outer_offset,
                "outer_template_elevation": outer_elevation,
                "extrapolated": False,
            }

    edge_offset, edge_ground = ground[-1] if side_text == "RIGHT" else ground[0]
    elevation = outer_elevation + slope * (edge_offset - outer_offset)
    return {
        "side": side_text,
        "catch_offset": edge_offset,
        "catch_elevation": elevation,
        "template_extension_slope": slope,
        "outer_template_offset": outer_offset,
        "outer_template_elevation": outer_elevation,
        "extrapolated": True,
        "ground_edge_elevation": edge_ground,
        "warning": "No profile intersection was found before the ground-profile edge.",
    }
