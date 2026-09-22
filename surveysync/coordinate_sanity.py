from __future__ import annotations

import math
from statistics import median

from .project import SurveyProject


def _finite_float(value) -> float | None:
    """Return a finite float or None without changing the source value."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def inspect_points(project: SurveyProject) -> dict:
    """Conservative coordinate/unit sanity checks.

    Coordinates are validated as *row-aligned pairs*. A row is included in
    geometric statistics only when both Northing and Easting are finite. This
    is important: independently filtering the two axes can pair a Northing
    from one point with an Easting from another and can then attribute an
    outlier to the wrong PointID.

    This function never transforms, swaps, or repairs coordinates. It only
    raises review flags when patterns look suspicious enough that a surveyor
    should confirm CRS/units or source data.
    """
    with project.db.connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT point_id,northing,easting,elevation,crs,horizontal_units "
                "FROM canonical_points WHERE northing IS NOT NULL AND easting IS NOT NULL"
            ).fetchall()
        ]
    if not rows:
        return {"status": "NO_POINTS", "flags": [], "stats": {"count": 0, "valid_pair_count": 0, "invalid_pair_count": 0}}

    valid_pairs: list[tuple[dict, float, float]] = []
    invalid_point_ids: list[str] = []
    for row in rows:
        northing = _finite_float(row.get("northing"))
        easting = _finite_float(row.get("easting"))
        if northing is None or easting is None:
            invalid_point_ids.append(str(row.get("point_id") or ""))
            continue
        valid_pairs.append((row, northing, easting))

    flags: list[dict] = []
    if invalid_point_ids:
        flags.append(
            {
                "code": "INVALID_COORDINATE_ROWS",
                "message": f"{len(invalid_point_ids)} point(s) contain a non-finite Northing/Easting pair and were excluded from coordinate statistics.",
                "point_ids": invalid_point_ids[:25],
            }
        )

    if not valid_pairs:
        return {
            "status": "NO_VALID_COORDINATES",
            "flags": flags or [{"code": "INVALID_COORDINATES", "message": "No finite coordinate pairs are available."}],
            "stats": {"count": len(rows), "valid_pair_count": 0, "invalid_pair_count": len(invalid_point_ids)},
        }

    valid_rows = [item[0] for item in valid_pairs]
    ns = [item[1] for item in valid_pairs]
    es = [item[2] for item in valid_pairs]
    count = len(valid_pairs)
    project_crs = str(project.manifest.get("crs") or "").strip()
    units = str(project.manifest.get("horizontal_units") or "").strip()

    latlon_like = sum(1 for _, n, e in valid_pairs if -90 <= n <= 90 and -180 <= e <= 180)
    swapped_latlon_like = sum(1 for _, n, e in valid_pairs if -180 <= n <= 180 and -90 <= e <= 90)
    if count and latlon_like / count >= 0.8 and project_crs and "4326" not in project_crs and "wgs 84" not in project_crs.lower():
        flags.append({"code": "LATLON_IN_PROJECTED_PROJECT", "message": "Most coordinates look like latitude/longitude, but the project CRS appears projected.", "ratio": latlon_like / count})
    if count and swapped_latlon_like / count >= 0.8 and latlon_like / count < 0.5:
        flags.append({"code": "POSSIBLE_NORTHING_EASTING_SWAP", "message": "Coordinate ranges look consistent with a possible Northing/Easting or latitude/longitude swap. Review before transformation."})

    n_span = max(ns) - min(ns)
    e_span = max(es) - min(es)
    n_med = median(ns)
    e_med = median(es)
    magnitudes = [math.hypot(n, e) for _, n, e in valid_pairs]
    mag_med = median(magnitudes)
    if units in {"us_survey_feet", "international_feet"} and 0 < mag_med < 10000 and project_crs and "4326" not in project_crs:
        flags.append({"code": "SMALL_COORDINATE_MAGNITUDE", "message": "Project is configured in feet but coordinate magnitudes are unusually small for a projected grid. Confirm units/local-grid intent."})
    if units == "meters" and mag_med > 20_000_000:
        flags.append({"code": "LARGE_METER_COORDINATES", "message": "Coordinate magnitudes are unusually large for meters. Confirm units and CRS."})

    # Robust outlier check based on distance from the coordinate medians. Do
    # not include the total project span in the threshold: a single remote
    # point inflates that span and can otherwise make the outlier impossible
    # to flag. Point IDs come from the same row-aligned tuples as the distance.
    distances = [(row, math.hypot(n - n_med, e - e_med)) for row, n, e in valid_pairs]
    positive = sorted(distance for _, distance in distances if distance > 0)
    if len(positive) >= 5:
        typical = median(positive)
        threshold = max(typical * 100.0, 1.0)
        outliers = [str(row.get("point_id") or "") for row, distance in distances if distance > threshold]
        if outliers:
            flags.append({"code": "REMOTE_COORDINATE_OUTLIER", "message": f"{len(outliers)} point(s) are extremely far from the project coordinate cluster.", "point_ids": outliers[:25]})

    # Mixed per-point metadata is also dangerous because exports may silently mix contexts.
    crs_values = sorted({str(r.get("crs") or "").strip() for r in rows if str(r.get("crs") or "").strip()})
    unit_values = sorted({str(r.get("horizontal_units") or "").strip() for r in rows if str(r.get("horizontal_units") or "").strip()})
    if len(crs_values) > 1:
        flags.append({"code": "MIXED_POINT_CRS", "message": "Canonical points contain more than one CRS metadata value.", "values": crs_values[:10]})
    if len(unit_values) > 1:
        flags.append({"code": "MIXED_POINT_UNITS", "message": "Canonical points contain more than one horizontal-unit value.", "values": unit_values})

    return {
        "status": "WARN" if flags else "PASS",
        "flags": flags,
        "stats": {
            "count": len(rows),
            "valid_pair_count": count,
            "invalid_pair_count": len(invalid_point_ids),
            "northing_min": min(ns),
            "northing_max": max(ns),
            "easting_min": min(es),
            "easting_max": max(es),
            "northing_span": n_span,
            "easting_span": e_span,
            "median_magnitude": mag_med,
        },
    }
