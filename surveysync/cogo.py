from __future__ import annotations

import math


def _finite(*values: float) -> None:
    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError("COGO inputs must be finite numbers.")


def inverse(n1: float, e1: float, n2: float, e2: float) -> dict:
    _finite(n1, e1, n2, e2)
    dn = float(n2) - float(n1)
    de = float(e2) - float(e1)
    distance = math.hypot(dn, de)
    azimuth = math.degrees(math.atan2(de, dn)) % 360.0 if distance else 0.0
    return {"delta_n": dn, "delta_e": de, "distance": distance, "azimuth_deg": azimuth}


def bearing_distance(n: float, e: float, azimuth_deg: float, distance: float) -> dict:
    _finite(n, e, azimuth_deg, distance)
    if distance < 0:
        raise ValueError("Distance cannot be negative.")
    a = math.radians(azimuth_deg % 360.0)
    dn = math.cos(a) * distance
    de = math.sin(a) * distance
    return {"northing": n + dn, "easting": e + de, "delta_n": dn, "delta_e": de}


def line_intersection(n1: float, e1: float, az1: float, n2: float, e2: float, az2: float) -> dict:
    _finite(n1,e1,az1,n2,e2,az2)
    a1, a2 = math.radians(az1), math.radians(az2)
    d1 = (math.cos(a1), math.sin(a1))
    d2 = (math.cos(a2), math.sin(a2))
    det = d1[1]*d2[0] - d1[0]*d2[1]
    if abs(det) < 1e-12:
        raise ValueError("Lines are parallel or nearly parallel.")
    dn, de = n2-n1, e2-e1
    t = (de*d2[0] - dn*d2[1]) / det
    return {"northing": n1 + t*d1[0], "easting": e1 + t*d1[1], "distance_along_first": t}
