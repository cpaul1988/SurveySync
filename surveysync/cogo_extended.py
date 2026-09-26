"""Extended COGO helpers adapted from the MIT-licensed Cogokit project.

Source inspiration/code lineage:
    https://github.com/devinmlowe/cogokit
    src/cogokit/solvers/horizontal_curve.py
License: MIT

SurveySync keeps its existing northing/easting conventions and exposes public
angles in degrees. The upstream Cogokit implementation works internally in
radians; this module adapts that interface for SurveySync.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

_D_CONST = 5729.57795130823


@dataclass(frozen=True)
class CurveElements:
    radius: float
    delta_deg: float
    tangent: float
    arc_length: float
    long_chord: float
    external: float
    middle_ordinate: float
    degree_of_curve_100ft_arc: float | None


def _finite_positive(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive finite number.")
    return number


def _resolve_radius_delta(given: dict[str, float]) -> tuple[float, float]:
    """Return (radius, delta_radians) from two independent curve elements."""

    g = dict(given)
    if "D" in g:
        g["R"] = _D_CONST / _finite_positive("Degree of curve", g["D"])

    if "R" in g:
        radius = _finite_positive("Radius", g["R"])
        if "delta" in g:
            return radius, math.radians(_finite_positive("Central angle", g["delta"]))
        if "T" in g:
            return radius, 2.0 * math.atan(_finite_positive("Tangent", g["T"]) / radius)
        if "L" in g:
            return radius, _finite_positive("Arc length", g["L"]) / radius
        if "C" in g:
            chord = _finite_positive("Long chord", g["C"])
            ratio = chord / (2.0 * radius)
            if not 0 < ratio <= 1:
                raise ValueError("Long chord is incompatible with the supplied radius.")
            return radius, 2.0 * math.asin(ratio)
        if "E" in g:
            external = _finite_positive("External", g["E"])
            return radius, 2.0 * math.acos(radius / (radius + external))
        if "M" in g:
            middle = _finite_positive("Middle ordinate", g["M"])
            ratio = 1.0 - middle / radius
            if not -1 <= ratio <= 1:
                raise ValueError("Middle ordinate is incompatible with the supplied radius.")
            return radius, 2.0 * math.acos(ratio)

    if "delta" in g:
        delta = math.radians(_finite_positive("Central angle", g["delta"]))
        half = delta / 2.0
        if "T" in g:
            return _finite_positive("Tangent", g["T"]) / math.tan(half), delta
        if "L" in g:
            return _finite_positive("Arc length", g["L"]) / delta, delta
        if "C" in g:
            return _finite_positive("Long chord", g["C"]) / (2.0 * math.sin(half)), delta
        if "E" in g:
            return _finite_positive("External", g["E"]) / (1.0 / math.cos(half) - 1.0), delta
        if "M" in g:
            return _finite_positive("Middle ordinate", g["M"]) / (1.0 - math.cos(half)), delta

    if "T" in g and "L" in g:
        tangent = _finite_positive("Tangent", g["T"])
        length = _finite_positive("Arc length", g["L"])
        target = tangent / length
        delta = 1.0
        for _ in range(50):
            half = delta / 2.0
            tan_half = math.tan(half)
            f = tan_half / delta - target
            sec2 = 1.0 / math.cos(half) ** 2
            derivative = (sec2 / 2.0 * delta - tan_half) / delta**2
            if abs(derivative) < 1e-30:
                break
            delta -= f / derivative
            if abs(f) < 1e-12:
                break
        return length / delta, delta

    if "T" in g and "C" in g:
        tangent = _finite_positive("Tangent", g["T"])
        chord = _finite_positive("Long chord", g["C"])
        ratio = chord / (2.0 * tangent)
        if not -1 <= ratio <= 1:
            raise ValueError("Tangent and long chord values are incompatible.")
        delta = 2.0 * math.acos(ratio)
        return tangent / math.tan(delta / 2.0), delta

    if "T" in g and "E" in g:
        tangent = _finite_positive("Tangent", g["T"])
        external = _finite_positive("External", g["E"])
        delta = 4.0 * math.atan(external / tangent)
        return tangent / math.tan(delta / 2.0), delta

    raise ValueError(
        "Unsupported curve-element pair. Include Radius or Central Angle, "
        "or use Tangent+Arc Length, Tangent+Long Chord, or Tangent+External."
    )


def solve_horizontal_curve(
    *,
    radius: float | None = None,
    delta_deg: float | None = None,
    tangent: float | None = None,
    arc_length: float | None = None,
    long_chord: float | None = None,
    external: float | None = None,
    middle_ordinate: float | None = None,
    degree_of_curve_100ft_arc: float | None = None,
    linear_units: str = "us_survey_feet",
) -> dict[str, float | None]:
    """Solve a simple circular curve from exactly two independent elements."""

    values = {
        "R": radius,
        "delta": delta_deg,
        "T": tangent,
        "L": arc_length,
        "C": long_chord,
        "E": external,
        "M": middle_ordinate,
        "D": degree_of_curve_100ft_arc,
    }
    units = str(linear_units or "").strip().lower()
    foot_units = {"us_survey_feet", "international_feet", "foot", "feet", "ft"}
    if degree_of_curve_100ft_arc is not None and units not in foot_units:
        raise ValueError(
            "Degree of curve uses the 100-foot arc definition and is only enabled for foot-based projects."
        )

    given = {key: float(value) for key, value in values.items() if value is not None}
    if len(given) != 2:
        raise ValueError(f"Provide exactly two curve elements; received {len(given)}.")

    radius_value, delta = _resolve_radius_delta(given)
    radius_value = _finite_positive("Radius", radius_value)
    if not math.isfinite(delta) or not 0 < delta < math.pi:
        raise ValueError("Central angle must be between 0 and 180 degrees.")

    half = delta / 2.0
    result = CurveElements(
        radius=radius_value,
        delta_deg=math.degrees(delta),
        tangent=radius_value * math.tan(half),
        arc_length=radius_value * delta,
        long_chord=2.0 * radius_value * math.sin(half),
        external=radius_value * (1.0 / math.cos(half) - 1.0),
        middle_ordinate=radius_value * (1.0 - math.cos(half)),
        degree_of_curve_100ft_arc=(_D_CONST / radius_value if units in foot_units else None),
    )
    return asdict(result)


def three_point_curve(
    *,
    n1: float,
    e1: float,
    n2: float,
    e2: float,
    n3: float,
    e3: float,
) -> dict[str, float]:
    """Return center and radius of the unique circle through three survey points."""

    values = [n1, e1, n2, e2, n3, e3]
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("Three-point curve coordinates must be finite.")

    ax, ay = float(e1), float(n1)
    bx, by = float(e2), float(n2)
    cx, cy = float(e3), float(n3)
    determinant = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(determinant) < 1e-12:
        raise ValueError("The three points are collinear; no unique circular curve exists.")

    center_e = (
        (ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)
    ) / determinant
    center_n = (
        (ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)
    ) / determinant
    radius = math.hypot(ax - center_e, ay - center_n)
    return {
        "center_northing": center_n,
        "center_easting": center_e,
        "radius": radius,
    }



def _finite_number(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number.")
    return number


def _normalized_points(points: list[dict[str, float]], *, minimum: int) -> list[tuple[float, float]]:
    cleaned: list[tuple[float, float]] = []
    for index, point in enumerate(points, start=1):
        try:
            northing = _finite_number(f"Point {index} northing", point["northing"])
            easting = _finite_number(f"Point {index} easting", point["easting"])
        except KeyError as exc:
            raise ValueError(f"Point {index} must include northing and easting.") from exc
        cleaned.append((northing, easting))
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1]:
        cleaned.pop()
    if len(cleaned) < minimum:
        raise ValueError(f"At least {minimum} distinct points are required.")
    return cleaned


def polygon_area_perimeter(*, points: list[dict[str, float]]) -> dict[str, float | int | str]:
    """Compute closed-polygon area, perimeter, centroid, and orientation."""

    vertices = _normalized_points(points, minimum=3)
    twice_area = 0.0
    perimeter = 0.0
    centroid_e_numerator = 0.0
    centroid_n_numerator = 0.0
    for index, (northing, easting) in enumerate(vertices):
        next_northing, next_easting = vertices[(index + 1) % len(vertices)]
        cross = easting * next_northing - next_easting * northing
        twice_area += cross
        centroid_e_numerator += (easting + next_easting) * cross
        centroid_n_numerator += (northing + next_northing) * cross
        perimeter += math.hypot(next_easting - easting, next_northing - northing)

    signed_area = twice_area / 2.0
    if abs(signed_area) <= 1e-12:
        raise ValueError("Polygon area is zero or numerically degenerate.")
    centroid_easting = centroid_e_numerator / (6.0 * signed_area)
    centroid_northing = centroid_n_numerator / (6.0 * signed_area)
    return {
        "vertex_count": len(vertices),
        "area": abs(signed_area),
        "signed_area": signed_area,
        "perimeter": perimeter,
        "orientation": "CCW" if signed_area > 0 else "CW",
        "centroid_northing": centroid_northing,
        "centroid_easting": centroid_easting,
    }


def alignment_station_offset(
    *,
    alignment: list[dict[str, float]],
    point: dict[str, float],
    start_station: float = 0.0,
) -> dict[str, float | int | str]:
    """Project a survey point onto a polyline alignment and return station/offset.

    Positive offset is LEFT looking ahead along the selected alignment segment.
    """

    vertices = _normalized_points(alignment, minimum=2)
    point_northing = _finite_number("Point northing", point["northing"])
    point_easting = _finite_number("Point easting", point["easting"])
    station_origin = _finite_number("Start station", start_station)

    cumulative = 0.0
    best: dict[str, float | int] | None = None
    for index in range(len(vertices) - 1):
        n1, e1 = vertices[index]
        n2, e2 = vertices[index + 1]
        dn = n2 - n1
        de = e2 - e1
        length_sq = dn * dn + de * de
        if length_sq <= 1e-24:
            continue
        segment_length = math.sqrt(length_sq)
        t_raw = ((point_northing - n1) * dn + (point_easting - e1) * de) / length_sq
        t = min(1.0, max(0.0, t_raw))
        nearest_n = n1 + t * dn
        nearest_e = e1 + t * de
        off_n = point_northing - nearest_n
        off_e = point_easting - nearest_e
        distance = math.hypot(off_n, off_e)
        candidate = {
            "distance": distance,
            "segment_index": index + 1,
            "segment_fraction": t,
            "nearest_northing": nearest_n,
            "nearest_easting": nearest_e,
            "station": station_origin + cumulative + t * segment_length,
            "segment_azimuth_deg": math.degrees(math.atan2(de, dn)) % 360.0,
            "cross": de * (point_northing - n1) - dn * (point_easting - e1),
        }
        if best is None or distance < float(best["distance"]) - 1e-12:
            best = candidate
        cumulative += segment_length

    if best is None:
        raise ValueError("Alignment contains no non-zero-length segments.")

    distance = float(best["distance"])
    cross = float(best["cross"])
    if distance <= 1e-12:
        offset = 0.0
        side = "ON"
    elif cross > 0:
        offset = distance
        side = "LEFT"
    else:
        offset = -distance
        side = "RIGHT"
    return {
        "station": float(best["station"]),
        "offset": offset,
        "side": side,
        "nearest_northing": float(best["nearest_northing"]),
        "nearest_easting": float(best["nearest_easting"]),
        "segment_index": int(best["segment_index"]),
        "segment_fraction": float(best["segment_fraction"]),
        "segment_azimuth_deg": float(best["segment_azimuth_deg"]),
        "distance_to_alignment": distance,
        "alignment_length": cumulative,
    }


def stake_horizontal_curve(
    *,
    pc_northing: float,
    pc_easting: float,
    tangent_azimuth_deg: float,
    radius: float,
    delta_deg: float,
    direction: str,
    stake_interval: float,
    start_station: float = 0.0,
    max_points: int = 5000,
) -> dict[str, object]:
    """Generate station-based stake points along a simple circular curve."""

    pc_n = _finite_number("PC northing", pc_northing)
    pc_e = _finite_number("PC easting", pc_easting)
    tangent_azimuth = _finite_number("Tangent azimuth", tangent_azimuth_deg) % 360.0
    radius_value = _finite_positive("Radius", radius)
    delta_value = _finite_positive("Central angle", delta_deg)
    if delta_value >= 180.0:
        raise ValueError("Central angle must be between 0 and 180 degrees.")
    interval = _finite_positive("Stake interval", stake_interval)
    station_origin = _finite_number("Start station", start_station)
    direction_text = str(direction or "").strip().upper()
    if direction_text not in {"LEFT", "RIGHT"}:
        raise ValueError("Curve direction must be LEFT or RIGHT.")
    if int(max_points) < 2:
        raise ValueError("max_points must be at least 2.")

    turn_sign = -1.0 if direction_text == "LEFT" else 1.0
    delta_radians = math.radians(delta_value)
    curve_length = radius_value * delta_radians
    end_station = station_origin + curve_length

    center_azimuth = math.radians(tangent_azimuth + turn_sign * 90.0)
    center_n = pc_n + radius_value * math.cos(center_azimuth)
    center_e = pc_e + radius_value * math.sin(center_azimuth)
    initial_radius_azimuth = tangent_azimuth - turn_sign * 90.0

    arc_distances = [0.0]
    next_full_station = (math.floor(station_origin / interval) + 1.0) * interval
    while next_full_station < end_station - 1e-10:
        arc_distances.append(next_full_station - station_origin)
        if len(arc_distances) >= int(max_points) - 1:
            raise ValueError(f"Stake interval produces more than {int(max_points)} points.")
        next_full_station += interval
    if curve_length > 1e-12:
        arc_distances.append(curve_length)

    stakes: list[dict[str, float | int | str]] = []
    for index, arc_distance in enumerate(arc_distances, start=1):
        theta_radians = arc_distance / radius_value
        theta_deg = math.degrees(theta_radians)
        radius_azimuth_deg = initial_radius_azimuth + turn_sign * theta_deg
        radial = math.radians(radius_azimuth_deg)
        northing = center_n + radius_value * math.cos(radial)
        easting = center_e + radius_value * math.sin(radial)
        chord = 2.0 * radius_value * math.sin(theta_radians / 2.0)
        chord_azimuth = (tangent_azimuth + turn_sign * theta_deg / 2.0) % 360.0
        stakes.append(
            {
                "index": index,
                "station": station_origin + arc_distance,
                "arc_distance": arc_distance,
                "northing": northing,
                "easting": easting,
                "deflection_deg": turn_sign * theta_deg / 2.0,
                "chord_from_pc": chord,
                "chord_azimuth_deg": chord_azimuth,
                "tangent_azimuth_deg": (tangent_azimuth + turn_sign * theta_deg) % 360.0,
            }
        )

    return {
        "direction": direction_text,
        "radius": radius_value,
        "delta_deg": delta_value,
        "curve_length": curve_length,
        "start_station": station_origin,
        "end_station": end_station,
        "center_northing": center_n,
        "center_easting": center_e,
        "pt_northing": stakes[-1]["northing"],
        "pt_easting": stakes[-1]["easting"],
        "stake_interval": interval,
        "stake_count": len(stakes),
        "stakes": stakes,
    }
