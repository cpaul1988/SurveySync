"""Summarize reviewed candidates without pretending heuristics are probabilities."""

from __future__ import annotations

import math
import statistics

from .detection import UNITS_PER_FOOT


def summarize_reviews(reviews: list[dict]) -> dict:
    # Storage supplies newest first. A changed decision supersedes the old one.
    latest: dict[tuple, dict] = {}
    for item in reviews:
        key = (item.get("run_id"), item.get("candidate_id"))
        if all(key):
            latest.setdefault(key, item)
    rows = list(latest.values())
    confirmed = [x for x in rows if x.get("decision") == "confirmed_bust"]
    rejected = [x for x in rows if x.get("decision") == "not_bust"]
    scatters = []
    excluded = 0
    for item in confirmed:
        candidate = item.get("candidate") or {}
        scatter = candidate.get("offset_std_dev")
        unit = item.get("vertical_units")
        if (
            unit not in UNITS_PER_FOOT
            or isinstance(scatter, bool)
            or not isinstance(scatter, (int, float))
            or not math.isfinite(scatter)
            or scatter < 0
        ):
            excluded += 1
            continue
        scatters.append(float(scatter) / UNITS_PER_FOOT[unit])
    median = statistics.median(scatters) if scatters else None
    return {
        "review_count": len(rows),
        "confirmed_bust_count": len(confirmed),
        "not_bust_count": len(rejected),
        "needs_review_count": sum(x.get("decision") == "needs_review" for x in rows),
        "median_confirmed_scatter": round(median, 4) if median is not None else None,
        "scatter_units": "international_feet",
        "excluded_scatter_count": excluded,
        "suggested_consistency_ft": round(max(0.05, min(0.25, median * 2)), 3)
        if median is not None
        else None,
        "confidence_calibrated": False,
        "advisory_only": True,
        "message": "Latest decisions only; scatter is normalized to feet. This is a tolerance suggestion, not calibrated confidence. Settings and elevations are never changed automatically.",
    }
