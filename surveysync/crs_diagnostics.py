"""SurveySync CRS diagnostics backed by pyproj / PROJ.

PROJ remains the authoritative coordinate-operation engine. These helpers expose
operation choice, accuracy, area-of-use, units, axes, and missing-grid evidence
without changing project coordinates.
"""

from __future__ import annotations

import math
from typing import Any

from pyproj import CRS, Transformer, proj_version_str
from pyproj.exceptions import ProjError
from pyproj.transformer import AreaOfInterest, TransformerGroup

from .crs import UNIT_ALIASES
from .project import SurveyProject


class CrsDiagnosticError(ValueError):
    pass


def _area_dict(area: Any) -> dict[str, Any]:
    if area is None:
        return {}
    return {
        "name": str(getattr(area, "name", "") or ""),
        "west": float(getattr(area, "west", math.nan)),
        "south": float(getattr(area, "south", math.nan)),
        "east": float(getattr(area, "east", math.nan)),
        "north": float(getattr(area, "north", math.nan)),
    }


def _axis_list(crs: CRS) -> list[dict[str, Any]]:
    return [
        {
            "name": str(axis.name or ""),
            "abbrev": str(axis.abbrev or ""),
            "direction": str(axis.direction or ""),
            "unit_name": str(axis.unit_name or ""),
            "unit_conversion_factor": float(axis.unit_conversion_factor),
        }
        for axis in crs.axis_info
    ]


def _unit_matches_project(crs: CRS, project_units: str) -> tuple[bool, str, str]:
    axes = _axis_list(crs)
    crs_unit = str(axes[0]["unit_name"] if axes else "")
    expected = UNIT_ALIASES.get(str(project_units or ""), str(project_units or ""))
    if not crs_unit or not expected:
        return True, crs_unit, expected
    aliases = {
        "us survey foot": {"us survey foot", "us_survey_feet"},
        "foot": {"foot", "international_feet"},
        "metre": {"metre", "meter", "meters"},
    }
    actual_key = crs_unit.casefold()
    expected_key = expected.casefold()
    match = actual_key == expected_key
    for canonical, values in aliases.items():
        if actual_key in values and expected_key in values | {canonical}:
            match = True
    return match, crs_unit, expected


def crs_profile(value: str) -> dict[str, Any]:
    raw = str(value or "").strip()
    if not raw:
        raise CrsDiagnosticError("CRS is blank.")
    try:
        crs = CRS.from_user_input(raw)
    except (ProjError, ValueError) as exc:
        raise CrsDiagnosticError(f"Invalid CRS: {exc}") from exc
    auth = crs.to_authority()
    datum = crs.datum
    coordinate_operation = crs.coordinate_operation
    return {
        "input": raw,
        "name": str(crs.name or ""),
        "authority": f"{auth[0]}:{auth[1]}" if auth else "",
        "type_name": str(crs.type_name or ""),
        "is_projected": bool(crs.is_projected),
        "is_geographic": bool(crs.is_geographic),
        "is_vertical": bool(crs.is_vertical),
        "is_compound": bool(crs.is_compound),
        "datum": str(getattr(datum, "name", "") or ""),
        "ellipsoid": str(getattr(crs.ellipsoid, "name", "") or ""),
        "prime_meridian": str(getattr(crs.prime_meridian, "name", "") or ""),
        "axes": _axis_list(crs),
        "area_of_use": _area_dict(crs.area_of_use),
        "coordinate_operation": {
            "name": str(getattr(coordinate_operation, "name", "") or ""),
            "method_name": str(getattr(coordinate_operation, "method_name", "") or ""),
            "accuracy": getattr(coordinate_operation, "accuracy", None),
        }
        if coordinate_operation is not None
        else {},
        "proj_version": proj_version_str,
    }


def _grid_dict(grid: Any) -> dict[str, Any]:
    return {
        "short_name": str(getattr(grid, "short_name", "") or ""),
        "full_name": str(getattr(grid, "full_name", "") or ""),
        "package_name": str(getattr(grid, "package_name", "") or ""),
        "url": str(getattr(grid, "url", "") or ""),
        "available": bool(getattr(grid, "available", False)),
        "direct_download": bool(getattr(grid, "direct_download", False)),
        "open_license": bool(getattr(grid, "open_license", False)),
    }


def _operation_dict(operation: Any) -> dict[str, Any]:
    area = getattr(operation, "area_of_use", None)
    accuracy = getattr(operation, "accuracy", None)
    try:
        accuracy_value = float(accuracy) if accuracy is not None else None
    except (TypeError, ValueError):
        accuracy_value = None
    grids = [_grid_dict(grid) for grid in (getattr(operation, "grids", None) or [])]
    return {
        "name": str(getattr(operation, "name", "") or ""),
        "description": str(getattr(operation, "description", "") or ""),
        "accuracy_m": accuracy_value,
        "area_of_use": _area_dict(area),
        "grids": grids,
        "missing_grids": [grid for grid in grids if not grid["available"]],
    }


def _transformer_dict(transformer: Transformer) -> dict[str, Any]:
    accuracy = getattr(transformer, "accuracy", None)
    try:
        accuracy_value = float(accuracy) if accuracy is not None else None
    except (TypeError, ValueError):
        accuracy_value = None
    return {
        "name": str(getattr(transformer, "name", "") or ""),
        "description": str(getattr(transformer, "description", "") or ""),
        "accuracy_m": accuracy_value,
        "area_of_use": _area_dict(getattr(transformer, "area_of_use", None)),
        "definition": str(getattr(transformer, "definition", "") or ""),
        "has_inverse": bool(getattr(transformer, "has_inverse", False)),
    }


def _contains(area: dict[str, Any], lon: float, lat: float) -> bool:
    if not area or not math.isfinite(lon) or not math.isfinite(lat):
        return True
    west = float(area.get("west", -180.0))
    east = float(area.get("east", 180.0))
    south = float(area.get("south", -90.0))
    north = float(area.get("north", 90.0))
    lon_ok = west <= lon <= east if west <= east else (lon >= west or lon <= east)
    return lon_ok and south <= lat <= north


def _point_to_wgs84(x: float, y: float, crs: CRS) -> tuple[float, float]:
    transformer = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)
    lon, lat = transformer.transform(float(x), float(y))
    if not (math.isfinite(lon) and math.isfinite(lat)):
        raise CrsDiagnosticError("Sample coordinate could not be converted to WGS84.")
    return float(lon), float(lat)


def operation_diagnostics(
    source_crs: str,
    target_crs: str,
    *,
    sample_x: float | None = None,
    sample_y: float | None = None,
    area_of_interest: dict[str, float] | None = None,
) -> dict[str, Any]:
    try:
        source = CRS.from_user_input(source_crs)
        target = CRS.from_user_input(target_crs)
    except (ProjError, ValueError) as exc:
        raise CrsDiagnosticError(f"Invalid source or target CRS: {exc}") from exc

    if (sample_x is None) != (sample_y is None):
        raise CrsDiagnosticError("Supply both sample X/easting and Y/northing, or neither.")
    if sample_x is not None and not all(
        v is not None and math.isfinite(v) for v in (sample_x, sample_y)
    ):
        raise CrsDiagnosticError("Sample coordinates must be finite.")
    if area_of_interest:
        try:
            w, so, e, n = [float(area_of_interest[k]) for k in ("west", "south", "east", "north")]
            if not all(math.isfinite(v) for v in (w, so, e, n)) or not (
                -180 <= w <= e <= 180 and -90 <= so <= n <= 90
            ):
                raise ValueError("Invalid bounds")
        except (KeyError, ValueError, TypeError) as exc:
            raise CrsDiagnosticError(
                "Area of interest requires ordered finite longitude/latitude bounds."
            ) from exc
    aoi = None
    if area_of_interest:
        try:
            aoi = AreaOfInterest(
                west_lon_degree=float(area_of_interest["west"]),
                south_lat_degree=float(area_of_interest["south"]),
                east_lon_degree=float(area_of_interest["east"]),
                north_lat_degree=float(area_of_interest["north"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CrsDiagnosticError(
                "Area of interest requires numeric west, south, east, and north values."
            ) from exc

    try:
        group = TransformerGroup(
            source,
            target,
            always_xy=True,
            area_of_interest=aoi,
            allow_ballpark=True,
        )
    except ProjError as exc:
        raise CrsDiagnosticError(f"PROJ could not build coordinate operations: {exc}") from exc

    available = [_transformer_dict(item) for item in group.transformers]
    unavailable = [_operation_dict(item) for item in group.unavailable_operations]
    warnings: list[dict[str, Any]] = []

    missing = [grid for operation in unavailable for grid in operation["missing_grids"]]
    if missing:
        warnings.append(
            {
                "code": "MISSING_TRANSFORMATION_GRIDS",
                "severity": "REVIEW",
                "message": (
                    f"{len(missing)} required/recommended transformation grid reference(s) "
                    "are unavailable in the current PROJ environment."
                ),
                "grids": missing,
            }
        )

    if not group.best_available:
        warnings.append(
            {
                "code": "BEST_OPERATION_UNAVAILABLE",
                "severity": "REVIEW",
                "message": (
                    "PROJ reports that the best-known coordinate operation is not "
                    "available in this runtime."
                ),
            }
        )

    sample = None
    if sample_x is not None or sample_y is not None:
        if sample_x is None or sample_y is None:
            raise CrsDiagnosticError("Provide both sample_x and sample_y.")
        try:
            lon, lat = _point_to_wgs84(float(sample_x), float(sample_y), source)
            if not group.transformers:
                raise CrsDiagnosticError("No coordinate operation is available in this runtime.")
            transformed = group.transformers[0].transform(float(sample_x), float(sample_y))
        except (ProjError, ValueError, TypeError) as exc:
            raise CrsDiagnosticError(f"Sample coordinate transform failed: {exc}") from exc
        tx, ty = float(transformed[0]), float(transformed[1])
        if not all(math.isfinite(v) for v in (tx, ty, lon, lat)):
            raise CrsDiagnosticError("Sample lies outside the transform's valid domain.")
        source_area = _area_dict(source.area_of_use)
        target_lon, target_lat = _point_to_wgs84(tx, ty, target)
        sample = {
            "source": {"x": float(sample_x), "y": float(sample_y)},
            "target": {"x": tx, "y": ty},
            "source_wgs84": {"longitude": lon, "latitude": lat},
            "target_wgs84": {"longitude": target_lon, "latitude": target_lat},
            "inside_source_area_of_use": _contains(source_area, lon, lat),
            "inside_target_area_of_use": _contains(
                _area_dict(target.area_of_use), target_lon, target_lat
            ),
        }
        if not sample["inside_source_area_of_use"]:
            warnings.append(
                {
                    "code": "SOURCE_OUTSIDE_AREA_OF_USE",
                    "severity": "REVIEW",
                    "message": "Sample coordinate is outside the source CRS area of use.",
                }
            )
        if not sample["inside_target_area_of_use"]:
            warnings.append(
                {
                    "code": "TARGET_OUTSIDE_AREA_OF_USE",
                    "severity": "REVIEW",
                    "message": "Transformed sample is outside the target CRS area of use.",
                }
            )

    return {
        "source": crs_profile(source_crs),
        "target": crs_profile(target_crs),
        "best_available": bool(group.best_available),
        "available_operation_count": len(available),
        "unavailable_operation_count": len(unavailable),
        "available_operations": available,
        "unavailable_operations": unavailable,
        "sample": sample,
        "warnings": warnings,
        "status": "REVIEW" if warnings else "PASS",
    }


def project_crs_diagnostics(
    project: SurveyProject,
    *,
    target_crs: str = "",
    sample_x: float | None = None,
    sample_y: float | None = None,
) -> dict[str, Any]:
    settings = project.coordinate_settings()
    crs_text = str(settings.get("crs") or "").strip()
    if not crs_text:
        raise CrsDiagnosticError("Project CRS is not set.")
    try:
        crs = CRS.from_user_input(crs_text)
    except (ProjError, ValueError) as exc:
        raise CrsDiagnosticError(f"Project CRS is invalid: {exc}") from exc

    warnings: list[dict[str, Any]] = []
    unit_match, crs_unit, expected_unit = _unit_matches_project(
        crs, str(settings.get("horizontal_units") or "")
    )
    if crs.is_projected and not unit_match:
        warnings.append(
            {
                "code": "PROJECT_UNIT_MISMATCH",
                "severity": "REVIEW",
                "message": (
                    f"Project horizontal units are {expected_unit or '(blank)'} but "
                    f"the CRS horizontal axis uses {crs_unit or '(unknown)'}."
                ),
            }
        )

    axes = _axis_list(crs)
    if len(axes) >= 2 and axes[0]["direction"].casefold() in {"north", "south"}:
        warnings.append(
            {
                "code": "AXIS_ORDER_NOTICE",
                "severity": "INFO",
                "message": (
                    "CRS authority axis order is latitude/northing first. SurveySync "
                    "coordinate transforms use always_xy=True at the API boundary."
                ),
            }
        )

    site = dict(settings.get("local_site") or {})
    if site.get("enabled"):
        warnings.append(
            {
                "code": "LOCAL_SITE_ACTIVE",
                "severity": "INFO",
                "message": (
                    "Project coordinates use an enabled local-site/grid-to-ground transform. "
                    "CRS operations must first reverse that local transform to grid."
                ),
                "local_site": site,
            }
        )

    operation = None
    if str(target_crs or "").strip():
        operation = operation_diagnostics(
            crs_text,
            target_crs,
            sample_x=sample_x,
            sample_y=sample_y,
        )
        warnings.extend(operation["warnings"])
    elif sample_x is not None or sample_y is not None:
        if sample_x is None or sample_y is None:
            raise CrsDiagnosticError("Provide both sample_x and sample_y.")
        lon, lat = _point_to_wgs84(float(sample_x), float(sample_y), crs)
        inside = _contains(_area_dict(crs.area_of_use), lon, lat)
        if not inside:
            warnings.append(
                {
                    "code": "PROJECT_POINT_OUTSIDE_AREA_OF_USE",
                    "severity": "REVIEW",
                    "message": "Sample project coordinate is outside the configured CRS area of use.",
                }
            )

    review_warnings = [item for item in warnings if item["severity"] == "REVIEW"]
    result = {
        "project_id": project.manifest.get("project_id", ""),
        "project_name": project.manifest.get("name", ""),
        "configured_crs": crs_text,
        "configured_horizontal_units": settings.get("horizontal_units", ""),
        "profile": crs_profile(crs_text),
        "unit_check": {
            "matches": unit_match,
            "crs_unit": crs_unit,
            "configured_unit": expected_unit,
        },
        "local_site": site,
        "operation": operation,
        "warnings": warnings,
        "status": "REVIEW" if review_warnings else "PASS",
    }
    project.db.audit(
        "GISSync",
        "CRS_DIAGNOSTICS_RUN",
        object_type="project",
        object_id=str(project.manifest.get("project_id") or ""),
        details={
            "configured_crs": crs_text,
            "target_crs": str(target_crs or ""),
            "status": result["status"],
            "warning_codes": [item["code"] for item in warnings],
        },
    )
    return result
