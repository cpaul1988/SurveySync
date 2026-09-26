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
