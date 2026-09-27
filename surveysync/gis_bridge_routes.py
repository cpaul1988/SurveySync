"""Optional QGIS / GRASS GIS bridge API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .gis_bridges import (
    GisBridgeError,
    bridge_status,
    qgis_algorithm_help,
    qgis_algorithms,
    run_grass_module,
    run_qgis_algorithm,
)

router = APIRouter()


class QgisHelpIn(BaseModel):
    algorithm_id: str = Field(min_length=1)


class QgisRunIn(BaseModel):
    algorithm_id: str = Field(min_length=1)
    parameters: dict = Field(default_factory=dict)
    timeout_seconds: int = Field(default=600, ge=5, le=3600)


class GrassRunIn(BaseModel):
    module: str = Field(min_length=1)
    parameters: dict = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    crs: str = ""
    timeout_seconds: int = Field(default=600, ge=5, le=3600)


def _project():
    from . import router as main_router

    return main_router.require_project()


@router.get("/api/v9/gis-bridges/status")
def gis_bridge_status():
    return bridge_status()


@router.get("/api/v9/gis-bridges/qgis/algorithms")
def gis_qgis_algorithms():
    try:
        return qgis_algorithms()
    except GisBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/gis-bridges/qgis/help")
def gis_qgis_help(payload: QgisHelpIn):
    try:
        return qgis_algorithm_help(payload.algorithm_id)
    except GisBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/gis-bridges/qgis/run")
def gis_qgis_run(payload: QgisRunIn):
    try:
        return run_qgis_algorithm(
            _project(),
            payload.algorithm_id,
            payload.parameters,
            timeout_seconds=payload.timeout_seconds,
        )
    except GisBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/gis-bridges/grass/run")
def gis_grass_run(payload: GrassRunIn):
    try:
        return run_grass_module(
            _project(),
            payload.module,
            payload.parameters,
            flags=payload.flags,
            crs=payload.crs,
            timeout_seconds=payload.timeout_seconds,
        )
    except GisBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc
