"""Horizontal-alignment and LandXML routes for SurveySync 9.3.2."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from .api_models import (
    CogoAlignmentDefinitionIn,
    CogoAlignmentStakePointIn,
    CogoAlignmentStationIn,
    CogoAlignmentStationOffsetIn,
    LandXmlExportIn,
    LandXmlImportIn,
)
from .horizontal_alignment import (
    alignment_station_offset,
    build_horizontal_alignment,
    point_at_station,
    station_offset_point,
)
from .landxml_io import export_landxml, import_landxml

router = APIRouter()


def _project():
    from . import router as main_router

    return main_router.require_project()


def _build(payload: CogoAlignmentDefinitionIn) -> dict:
    return build_horizontal_alignment(
        start_northing=payload.start_northing,
        start_easting=payload.start_easting,
        start_azimuth_deg=payload.start_azimuth_deg,
        start_station=payload.start_station,
        elements=[element.model_dump(exclude_none=True) for element in payload.elements],
    )


@router.post("/api/v9/cogo/alignment/build")
def alignment_build(payload: CogoAlignmentDefinitionIn):
    project = _project()
    try:
        result = _build(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    project.db.audit(
        "COGOSync",
        "ALIGNMENT_BUILD",
        details={
            "input": payload.model_dump(),
            "result_summary": {
                "element_count": result["element_count"],
                "length": result["length"],
                "end_station": result["end_station"],
            },
        },
    )
    return result


@router.post("/api/v9/cogo/alignment/point")
def alignment_point(payload: CogoAlignmentStationIn):
    project = _project()
    try:
        alignment = _build(payload.alignment)
        result = point_at_station(alignment, payload.station)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    project.db.audit(
        "COGOSync",
        "ALIGNMENT_POINT",
        details={"station": payload.station, "result": result},
    )
    return result


@router.post("/api/v9/cogo/alignment/station-offset")
def alignment_offset(payload: CogoAlignmentStationOffsetIn):
    project = _project()
    try:
        alignment = _build(payload.alignment)
        result = alignment_station_offset(
            alignment=alignment,
            point_northing=payload.point_northing,
            point_easting=payload.point_easting,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    project.db.audit(
        "COGOSync",
        "ALIGNMENT_STATION_OFFSET",
        details={
            "point_northing": payload.point_northing,
            "point_easting": payload.point_easting,
            "result": result,
        },
    )
    return result


@router.post("/api/v9/cogo/alignment/stake-point")
def alignment_stake_point(payload: CogoAlignmentStakePointIn):
    project = _project()
    try:
        alignment = _build(payload.alignment)
        result = station_offset_point(
            alignment=alignment,
            station=payload.station,
            offset=payload.offset,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    project.db.audit(
        "COGOSync",
        "ALIGNMENT_STAKE_POINT",
        details={"station": payload.station, "offset": payload.offset, "result": result},
    )
    return result


@router.post("/api/v9/landxml/import")
def landxml_import(payload: LandXmlImportIn):
    project = _project()
    try:
        source = Path(payload.file_path).expanduser().resolve()
        evidence = project.import_source(
            source,
            "COGOSync",
            notes="LandXML 1.2 source imported for alignment/parcel review.",
        )
        result = import_landxml(Path(evidence["stored_path"]))
    except (OSError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    project.db.audit(
        "COGOSync",
        "LANDXML_IMPORTED",
        object_type="source",
        object_id=str(evidence["source_id"]),
        details={
            "source_id": evidence["source_id"],
            "sha256": evidence["sha256"],
            "point_count": result["point_count"],
            "parcel_count": result["parcel_count"],
            "alignment_count": result["alignment_count"],
            "warnings": result["warnings"],
        },
    )
    return {"source": evidence, **result}


@router.post("/api/v9/landxml/export")
def landxml_export(payload: LandXmlExportIn):
    project = _project()
    try:
        if payload.output_path.strip():
            output_path = Path(payload.output_path).expanduser().resolve()
        else:
            output_path = project.paths.exports / "LandXML" / "SurveySync_LandXML.xml"
        result = export_landxml(
            output_path=output_path,
            points=[point.model_dump() for point in payload.points],
            parcels=[parcel.model_dump() for parcel in payload.parcels],
            alignments=[alignment.model_dump() for alignment in payload.alignments],
        )
    except (OSError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    project.db.audit(
        "COGOSync",
        "LANDXML_EXPORTED",
        object_type="deliverable",
        object_id=str(result["path"]),
        details=result,
    )
    return result
