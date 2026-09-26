"""SurveySync horizontal alignment geometry.

Sequential tangent/circular-curve alignment model using survey azimuths measured
clockwise from north and LEFT-positive station offsets.
"""

from __future__ import annotations

import math
from typing import Any


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite.")
    return number


def _positive(name: str, value: float) -> float:
    number = _finite(name, value)
    if number <= 0:
        raise ValueError(f"{name} must be positive.")
    return number


def _norm_azimuth(value: float) -> float:
    return float(value) % 360.0


def _forward(
    northing: float, easting: float, azimuth_deg: float, distance: float
) -> tuple[float, float]:
    azimuth = math.radians(azimuth_deg)
    return (
        northing + distance * math.cos(azimuth),
        easting + distance * math.sin(azimuth),
    )


def build_horizontal_alignment(
    *,
    start_northing: float,
    start_easting: float,
    start_azimuth_deg: float,
    start_station: float,
    elements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build continuous tangent/circular-curve geometry from sequential elements."""

    if not elements:
        raise ValueError("Alignment requires at least one element.")

    current_n = _finite("Start northing", start_northing)
    current_e = _finite("Start easting", start_easting)
    current_az = _norm_azimuth(_finite("Start azimuth", start_azimuth_deg))
    current_station = _finite("Start station", start_station)
    derived: list[dict[str, Any]] = []

    for index, raw in enumerate(elements, start=1):
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in {"tangent", "curve"}:
            raise ValueError(f"Alignment element {index} kind must be tangent or curve.")

        if kind == "tangent":
            length = _positive(f"Element {index} length", raw.get("length"))
            end_n, end_e = _forward(current_n, current_e, current_az, length)
            element = {
                "index": index,
                "kind": "tangent",
                "start_station": current_station,
                "end_station": current_station + length,
                "length": length,
                "start_northing": current_n,
                "start_easting": current_e,
                "end_northing": end_n,
                "end_easting": end_e,
                "start_azimuth_deg": current_az,
                "end_azimuth_deg": current_az,
            }
            current_n, current_e = end_n, end_e
            current_station += length
        else:
            radius = _positive(f"Element {index} radius", raw.get("radius"))
            delta_deg = _positive(f"Element {index} delta", raw.get("delta_deg"))
            if delta_deg >= 180.0:
                raise ValueError(f"Alignment element {index} delta must be below 180 degrees.")
            direction = str(raw.get("direction") or "").strip().upper()
            if direction not in {"LEFT", "RIGHT"}:
                raise ValueError(f"Alignment element {index} direction must be LEFT or RIGHT.")
            turn_sign = -1.0 if direction == "LEFT" else 1.0
            length = radius * math.radians(delta_deg)
            center_azimuth = current_az + turn_sign * 90.0
            center_n, center_e = _forward(current_n, current_e, center_azimuth, radius)
            radial_start_azimuth = current_az - turn_sign * 90.0
            radial_end_azimuth = radial_start_azimuth + turn_sign * delta_deg
            end_n, end_e = _forward(center_n, center_e, radial_end_azimuth, radius)
            end_azimuth = _norm_azimuth(current_az + turn_sign * delta_deg)
            element = {
                "index": index,
                "kind": "curve",
                "direction": direction,
                "radius": radius,
                "delta_deg": delta_deg,
                "start_station": current_station,
                "end_station": current_station + length,
                "length": length,
                "start_northing": current_n,
                "start_easting": current_e,
                "end_northing": end_n,
                "end_easting": end_e,
                "center_northing": center_n,
                "center_easting": center_e,
                "start_azimuth_deg": current_az,
                "end_azimuth_deg": end_azimuth,
                "radial_start_azimuth_deg": _norm_azimuth(radial_start_azimuth),
                "radial_end_azimuth_deg": _norm_azimuth(radial_end_azimuth),
            }
            current_n, current_e = end_n, end_e
            current_az = end_azimuth
            current_station += length

        derived.append(element)

    return {
        "start_station": float(derived[0]["start_station"]),
        "end_station": current_station,
        "length": current_station - float(derived[0]["start_station"]),
        "start_northing": float(derived[0]["start_northing"]),
        "start_easting": float(derived[0]["start_easting"]),
        "start_azimuth_deg": float(derived[0]["start_azimuth_deg"]),
        "end_northing": current_n,
        "end_easting": current_e,
        "end_azimuth_deg": current_az,
        "element_count": len(derived),
        "elements": derived,
    }


def point_at_station(alignment: dict[str, Any], station: float) -> dict[str, float | int | str]:
    """Evaluate coordinate and forward tangent azimuth at an alignment station."""

    target = _finite("Station", station)
    elements = list(alignment.get("elements") or [])
    if not elements:
        raise ValueError("Alignment contains no derived elements.")
    start = float(elements[0]["start_station"])
    end = float(elements[-1]["end_station"])
    if target < start - 1e-9 or target > end + 1e-9:
        raise ValueError(f"Station {target} is outside alignment range {start} to {end}.")

    selected = elements[-1]
    for element in elements:
        if float(element["start_station"]) - 1e-9 <= target <= float(element["end_station"]) + 1e-9:
            selected = element
            break

    distance = min(
        max(target - float(selected["start_station"]), 0.0),
        float(selected["length"]),
    )
    if selected["kind"] == "tangent":
        northing, easting = _forward(
            float(selected["start_northing"]),
            float(selected["start_easting"]),
            float(selected["start_azimuth_deg"]),
            distance,
        )
        azimuth = float(selected["start_azimuth_deg"])
    else:
        direction = str(selected["direction"])
        turn_sign = -1.0 if direction == "LEFT" else 1.0
        sweep_deg = math.degrees(distance / float(selected["radius"]))
        radial_azimuth = float(selected["radial_start_azimuth_deg"]) + turn_sign * sweep_deg
        northing, easting = _forward(
            float(selected["center_northing"]),
            float(selected["center_easting"]),
            radial_azimuth,
            float(selected["radius"]),
        )
        azimuth = _norm_azimuth(float(selected["start_azimuth_deg"]) + turn_sign * sweep_deg)

    return {
        "station": target,
        "northing": northing,
        "easting": easting,
        "tangent_azimuth_deg": azimuth,
        "element_index": int(selected["index"]),
        "element_kind": str(selected["kind"]),
    }


def _signed_offset(
    *,
    tangent_azimuth_deg: float,
    nearest_northing: float,
    nearest_easting: float,
    point_northing: float,
    point_easting: float,
) -> tuple[float, str]:
    azimuth = math.radians(tangent_azimuth_deg)
    dn = math.cos(azimuth)
    de = math.sin(azimuth)
    pn = point_northing - nearest_northing
    pe = point_easting - nearest_easting
    cross = de * pn - dn * pe
    distance = math.hypot(pn, pe)
    if distance <= 1e-12:
        return 0.0, "ON"
    if cross > 0:
        return distance, "LEFT"
    return -distance, "RIGHT"


def alignment_station_offset(
    *,
    alignment: dict[str, Any],
    point_northing: float,
    point_easting: float,
) -> dict[str, Any]:
    """Find nearest station/offset on a tangent/curve alignment."""

    point_n = _finite("Point northing", point_northing)
    point_e = _finite("Point easting", point_easting)
    elements = list(alignment.get("elements") or [])
    if not elements:
        raise ValueError("Alignment contains no derived elements.")

    best: dict[str, Any] | None = None
    for element in elements:
        if element["kind"] == "tangent":
            start_n = float(element["start_northing"])
            start_e = float(element["start_easting"])
            azimuth = math.radians(float(element["start_azimuth_deg"]))
            dn = math.cos(azimuth)
            de = math.sin(azimuth)
            along = (point_n - start_n) * dn + (point_e - start_e) * de
            along = min(max(along, 0.0), float(element["length"]))
            station = float(element["start_station"]) + along
            nearest = point_at_station(alignment, station)
        else:
            center_n = float(element["center_northing"])
            center_e = float(element["center_easting"])
            radial_to_point = _norm_azimuth(
                math.degrees(math.atan2(point_e - center_e, point_n - center_n))
            )
            radial_start = float(element["radial_start_azimuth_deg"])
            direction = str(element["direction"])
            if direction == "RIGHT":
                sweep = (radial_to_point - radial_start) % 360.0
            else:
                sweep = (radial_start - radial_to_point) % 360.0

            if sweep <= float(element["delta_deg"]) + 1e-9:
                station = float(element["start_station"]) + math.radians(sweep) * float(
                    element["radius"]
                )
                nearest = point_at_station(alignment, station)
            else:
                start_point = point_at_station(alignment, float(element["start_station"]))
                end_point = point_at_station(alignment, float(element["end_station"]))
                start_distance = math.hypot(
                    point_n - float(start_point["northing"]),
                    point_e - float(start_point["easting"]),
                )
                end_distance = math.hypot(
                    point_n - float(end_point["northing"]),
                    point_e - float(end_point["easting"]),
                )
                nearest = start_point if start_distance <= end_distance else end_point
                station = float(nearest["station"])

        distance = math.hypot(
            point_n - float(nearest["northing"]),
            point_e - float(nearest["easting"]),
        )
        if best is None or distance < float(best["distance_to_alignment"]) - 1e-12:
            offset, side = _signed_offset(
                tangent_azimuth_deg=float(nearest["tangent_azimuth_deg"]),
                nearest_northing=float(nearest["northing"]),
                nearest_easting=float(nearest["easting"]),
                point_northing=point_n,
                point_easting=point_e,
            )
            best = {
                **nearest,
                "offset": offset,
                "side": side,
                "distance_to_alignment": distance,
            }

    assert best is not None
    return best


def station_offset_point(
    *,
    alignment: dict[str, Any],
    station: float,
    offset: float,
) -> dict[str, Any]:
    """Convert station and LEFT-positive offset to a survey coordinate."""

    centerline = point_at_station(alignment, station)
    offset_value = _finite("Offset", offset)
    left_azimuth = float(centerline["tangent_azimuth_deg"]) - 90.0
    northing, easting = _forward(
        float(centerline["northing"]),
        float(centerline["easting"]),
        left_azimuth,
        offset_value,
    )
    return {
        **centerline,
        "offset": offset_value,
        "northing": northing,
        "easting": easting,
        "centerline_northing": centerline["northing"],
        "centerline_easting": centerline["easting"],
    }
