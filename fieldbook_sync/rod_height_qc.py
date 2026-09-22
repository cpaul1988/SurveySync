from __future__ import annotations

import math
from statistics import median
from typing import Any, Iterable, Sequence, cast

from .models import SurveyPoint


def _near_increment(value: float, increments: Sequence[float]) -> tuple[float | None, float]:
    positive = [abs(float(x)) for x in increments if math.isfinite(float(x)) and abs(float(x)) > 0]
    if not positive:
        return None, math.inf
    inc = min(positive, key=lambda x: abs(value - x))
    return inc, abs(value - inc)


def detect_rod_height_busts(
    points: Iterable[SurveyPoint],
    *,
    search_radius: float = 15.0,
    max_slope_percent: float = 8.0,
    increment_tolerance: float = 0.08,
    increments: Sequence[float] = (0.5, 1.0, 2.0),
    min_neighbors: int = 2,
    min_vertical_delta: float = 0.45,
) -> list[dict]:
    """Flag likely isolated rod-height/elevation busts without changing survey data.

    The detector is intentionally conservative: a point must have enough nearby XYZ
    neighbors, be vertically inconsistent with their local median, exceed the configured
    realistic local slope, and resemble a common round rod-height increment.
    """
    radius = max(float(search_radius), 0.01)
    slope_limit = max(float(max_slope_percent), 0.0)
    tol = max(float(increment_tolerance), 0.0)
    min_n = max(1, int(min_neighbors))
    usable = [
        p
        for p in points
        if p.easting is not None
        and p.northing is not None
        and p.elevation is not None
        and all(math.isfinite(float(cast(float, v))) for v in (p.easting, p.northing, p.elevation))
    ]
    if len(usable) < min_n + 1:
        return []
    grid: dict[tuple[int, int], list[SurveyPoint]] = {}
    for p in usable:
        key = (
            math.floor(float(cast(float, p.easting)) / radius),
            math.floor(float(cast(float, p.northing)) / radius),
        )
        grid.setdefault(key, []).append(p)
    out: list[dict[str, Any]] = []
    seen = set()
    for p in usable:
        x, y, z = (
            float(cast(float, p.easting)),
            float(cast(float, p.northing)),
            float(cast(float, p.elevation)),
        )
        cx, cy = math.floor(x / radius), math.floor(y / radius)
        nearby = []
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                for q in grid.get((cx + ox, cy + oy), ()):
                    if q is p:
                        continue
                    dx = float(cast(float, q.easting)) - x
                    dy = float(cast(float, q.northing)) - y
                    d = math.hypot(dx, dy)
                    if 0 < d <= radius:
                        nearby.append((d, q))
        if len(nearby) < min_n:
            continue
        elevations = [float(cast(float, q.elevation)) for _, q in nearby]
        expected = float(median(elevations))
        signed = z - expected
        delta = abs(signed)
        if delta < min_vertical_delta:
            continue
        inc, inc_err = _near_increment(delta, increments)
        if inc is None or inc_err > tol:
            continue
        nearest_dist = min(d for d, _ in nearby)
        slope_pct = (delta / max(nearest_dist, 0.01)) * 100.0
        if slope_pct < slope_limit:
            continue
        neighbor_ids = [q.point_id for _, q in sorted(nearby, key=lambda t: t[0])[:6]]
        candidate_key = (p.point_id, round(expected, 4), round(delta, 4))
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        closeness = max(0.0, 1.0 - (inc_err / max(tol, 1e-9)))
        slope_score = min(1.0, slope_pct / max(slope_limit * 3.0, 1.0))
        neighbor_score = min(1.0, len(nearby) / 5.0)
        confidence = round(100 * (0.55 * closeness + 0.30 * slope_score + 0.15 * neighbor_score), 1)
        severity = "HIGH" if confidence >= 80 else "MEDIUM"
        direction = "high" if signed > 0 else "low"
        out.append(
            {
                "point_id": p.point_id,
                "easting": x,
                "northing": y,
                "elevation": z,
                "expected_local_elevation": round(expected, 4),
                "signed_delta": round(signed, 4),
                "vertical_delta": round(delta, 4),
                "nearest_distance": round(nearest_dist, 3),
                "slope_percent": round(slope_pct, 2),
                "matched_increment": round(inc, 4),
                "increment_error": round(inc_err, 4),
                "neighbor_count": len(nearby),
                "neighbor_point_ids": neighbor_ids,
                "confidence": confidence,
                "severity": severity,
                "reason": f"Point is {delta:.3f} project units {direction} of the local median; the offset is near the {inc:g} round increment and implies {slope_pct:.1f}% local slope.",
            }
        )
    out.sort(key=lambda x: (-x["confidence"], -x["vertical_delta"], str(x["point_id"])))
    return out
