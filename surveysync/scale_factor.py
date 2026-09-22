from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Iterable
from uuid import uuid4

from pyproj import CRS, Proj, Transformer

from .audit import AuditDB, utc_now


@dataclass(frozen=True)
class ScaleSample:
    label: str
    factor: float
    weight: float = 1.0
    station: float | None = None
    zone: str = ""
    source: str = "manual"


def _validate(samples: Iterable[ScaleSample]) -> list[ScaleSample]:
    out = []
    for s in samples:
        if not math.isfinite(s.factor) or s.factor <= 0:
            raise ValueError(f"Scale factor for {s.label or 'sample'} must be a positive finite number.")
        if not math.isfinite(s.weight) or s.weight <= 0:
            raise ValueError(f"Weight for {s.label or 'sample'} must be greater than zero.")
        out.append(s)
    if not out:
        raise ValueError("At least one scale-factor sample is required.")
    return out


def fit_project_factor(samples: Iterable[ScaleSample], *, max_distortion_ppm: float = 20.0) -> dict:
    """Fit one project ground factor to local factor samples.

    The chosen factor minimizes weighted *relative* squared scale error rather
    than simply averaging zone factors. Segment length / project exposure can be
    supplied as the weight. This produces a reproducible candidate project factor,
    while the returned residual distortion makes clear whether one factor is safe
    enough for the project. A surveyor still approves the final project-ground setup.
    """
    rows = _validate(samples)
    numerator = sum(s.weight / s.factor for s in rows)
    denominator = sum(s.weight / (s.factor * s.factor) for s in rows)
    factor = numerator / denominator
    residuals = []
    weighted_sq = 0.0
    total_w = sum(s.weight for s in rows)
    max_abs = 0.0
    for s in rows:
        # If the true local conversion factor is s.factor and the project uses
        # ``factor``, this is the relative distance distortion at that sample.
        relative = factor / s.factor - 1.0
        ppm = relative * 1_000_000.0
        max_abs = max(max_abs, abs(ppm))
        weighted_sq += s.weight * ppm * ppm
        residuals.append({
            "label": s.label,
            "zone": s.zone,
            "station": s.station,
            "source": s.source,
            "local_factor": s.factor,
            "weight": s.weight,
            "residual_ppm": ppm,
            "distortion_ft_per_mile": relative * 5280.0,
            "distortion_in_per_mile": relative * 5280.0 * 12.0,
        })
    rms = math.sqrt(weighted_sq / total_w)
    threshold = abs(float(max_distortion_ppm))
    return {
        "project_factor": factor,
        "sample_count": len(rows),
        "max_abs_ppm": max_abs,
        "rms_ppm": rms,
        "max_distortion_ppm": threshold,
        "pass": max_abs <= threshold,
        "residuals": residuals,
        "method": "weighted_relative_least_squares",
        "formula": "min Σ w*((K-Ki)/Ki)^2",
        "review_required": True,
        "review_note": "Project factor is a deterministic best-fit candidate. Review residual distortion and approve the project-ground coordinate strategy before production use.",
    }


def projection_scale_samples(target_crs: str, points: list[dict], *, source_crs: str = "EPSG:4326") -> list[dict]:
    """Sample projection point scale at supplied locations.

    ``points`` may be in any source CRS. Coordinates are transformed to lon/lat
    before calling PROJ's factor engine. Elevation factor is intentionally not
    guessed; callers can combine this grid scale with an explicitly supplied
    elevation/combined factor if their workflow requires it.
    """
    target = CRS.from_user_input(target_crs)
    if not target.is_projected:
        raise ValueError("Target CRS must be a projected coordinate system to sample projection scale.")
    source = CRS.from_user_input(source_crs)
    to_geo = Transformer.from_crs(source, CRS.from_epsg(4326), always_xy=True)
    proj = Proj(target)
    out = []
    for idx, point in enumerate(points, start=1):
        x = float(point["x"]); y = float(point["y"])
        lon, lat = to_geo.transform(x, y)
        f = proj.get_factors(lon, lat)
        # For conformal projections the meridional and parallel scales are nearly
        # identical. Geometric mean is stable for non-identical values and makes
        # the choice explicit.
        k = math.sqrt(abs(float(f.meridional_scale) * float(f.parallel_scale)))
        out.append({
            "label": str(point.get("label") or f"Sample {idx}"),
            "x": x, "y": y, "lon": lon, "lat": lat,
            "projection_scale": k,
            "meridional_scale": float(f.meridional_scale),
            "parallel_scale": float(f.parallel_scale),
            "zone": str(point.get("zone") or ""),
            "station": point.get("station"),
            "weight": float(point.get("weight") or 1.0),
        })
    return out


def save_solution(db: AuditDB, name: str, result: dict, samples: list[dict], *, target_crs: str = "", settings: dict | None = None) -> dict:
    solution_id = uuid4().hex
    with db.connect() as conn:
        revision = int(conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM scale_factor_solutions WHERE name=?", (name,)).fetchone()[0])
        conn.execute(
            "INSERT INTO scale_factor_solutions(solution_id,ts_utc,name,revision,target_crs,project_factor,max_abs_ppm,rms_ppm,samples_json,settings_json,review_state) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (solution_id, utc_now(), name, revision, target_crs, result["project_factor"], result["max_abs_ppm"], result["rms_ppm"], json.dumps(samples, sort_keys=True), json.dumps(settings or {}, sort_keys=True), "UNREVIEWED"),
        )
    db.audit("GISSync", "PROJECT_SCALE_FACTOR_FIT", object_type="scale_factor_solution", object_id=solution_id, revision=revision, details={"name": name, "project_factor": result["project_factor"], "max_abs_ppm": result["max_abs_ppm"], "pass": result["pass"]})
    return {"solution_id": solution_id, "revision": revision}


def list_solutions(db: AuditDB, limit: int = 100) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM scale_factor_solutions ORDER BY ts_utc DESC LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["samples"] = json.loads(d.pop("samples_json") or "[]")
        d["settings"] = json.loads(d.pop("settings_json") or "{}")
        out.append(d)
    return out
