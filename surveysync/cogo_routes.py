"""Extended COGOSync API routes kept outside the frozen main router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .api_models import CogoCrossSectionIn, CogoCurveStakeIn, CogoEarthworkIn, CogoPolygonIn, CogoSlopeCatchIn, CogoStationOffsetIn, CogoVerticalCurveIn
from .cogo_extended import alignment_station_offset, polygon_area_perimeter, solve_vertical_curve, stake_horizontal_curve\nfrom .earthwork import average_end_area_earthwork, cross_section_cut_fill, slope_catch_2d

router = APIRouter()


def _project():
    from . import router as main_router

    return main_router.require_project()


@router.post("/api/v9/cogo/polygon")
def cogo_polygon(payload: CogoPolygonIn):
    project = _project()
    try:
        result = polygon_area_perimeter(points=[point.model_dump() for point in payload.points])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    project.db.audit("COGOSync", "POLYGON_METRICS", details=payload.model_dump() | {"result": result})
    return result


@router.post("/api/v9/cogo/station-offset")
def cogo_station_offset(payload: CogoStationOffsetIn):
    project = _project()
    try:
        result = alignment_station_offset(
            alignment=[point.model_dump() for point in payload.alignment],
            point=payload.point.model_dump(),
            start_station=payload.start_station,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    project.db.audit("COGOSync", "STATION_OFFSET", details=payload.model_dump() | {"result": result})
    return result


@router.post("/api/v9/cogo/curve-stake")
def cogo_curve_stake(payload: CogoCurveStakeIn):
    project = _project()
    try:
        result = stake_horizontal_curve(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit_result = {
        "stake_count": result["stake_count"],
        "end_station": result["end_station"],
        "pt_northing": result["pt_northing"],
        "pt_easting": result["pt_easting"],
    }
    project.db.audit("COGOSync", "CURVE_STAKE", details=payload.model_dump() | {"result": audit_result})
    return result


@router.post("/api/v9/cogo/vertical-curve")
def cogo_vertical_curve(payload: CogoVerticalCurveIn):
    project = _project()
    try:
        result = solve_vertical_curve(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    project.db.audit(
        "COGOSync",
        "VERTICAL_CURVE",
        details=payload.model_dump() | {
            "result": {
                "bvc_station": result["bvc_station"],
                "evc_station": result["evc_station"],
                "k_value": result["k_value"],
                "high_low_station": result["high_low_station"],
                "sample_count": result["sample_count"],
            }
        },
    )
    return result


@router.post("/api/v9/cogo/cross-section")
def cogo_cross_section(payload: CogoCrossSectionIn):
    project = _project()
    try:
        result = cross_section_cut_fill(
            ground_points=[point.model_dump() for point in payload.ground_points],
            design_points=[point.model_dump() for point in payload.design_points],
            design_centerline_elevation=payload.design_centerline_elevation,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    project.db.audit("COGOSync", "CROSS_SECTION_AREA", details=payload.model_dump() | {"result": result})
    return result


@router.post("/api/v9/cogo/earthwork")
def cogo_earthwork(payload: CogoEarthworkIn):
    project = _project()
    try:
        result = average_end_area_earthwork(
            sections=[section.model_dump() for section in payload.sections]
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    project.db.audit("COGOSync", "EARTHWORK_VOLUME", details=payload.model_dump() | {"result": result})
    return result


@router.post("/api/v9/cogo/slope-catch")
def cogo_slope_catch(payload: CogoSlopeCatchIn):
    project = _project()
    try:
        result = slope_catch_2d(
            ground_points=[point.model_dump() for point in payload.ground_points],
            design_points=[point.model_dump() for point in payload.design_points],
            design_centerline_elevation=payload.design_centerline_elevation,
            side=payload.side,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    project.db.audit("COGOSync", "SLOPE_CATCH", details=payload.model_dump() | {"result": result})
    return result
