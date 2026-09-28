"""Optional QGIS / GRASS GIS bridge API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
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
    executable: str = ""


class QgisRunIn(BaseModel):
    algorithm_id: str = Field(min_length=1)
    executable: str = ""
    parameters: dict = Field(default_factory=dict)
    timeout_seconds: int = Field(default=600, ge=5, le=3600)


class GrassRunIn(BaseModel):
    module: str = Field(min_length=1)
    executable: str = ""
    parameters: dict = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    crs: str = ""
    timeout_seconds: int = Field(default=600, ge=5, le=3600)


def _project(request: Request):
    from .desktop_context import require_panel_project

    return require_panel_project(request)


@router.get("/api/v9/gis-bridges/status")
def gis_bridge_status(qgis_executable: str = "", grass_executable: str = ""):
    return bridge_status(qgis_executable or None, grass_executable or None)


@router.get("/api/v9/gis-bridges/qgis/algorithms")
def gis_qgis_algorithms(executable: str = ""):
    try:
        return qgis_algorithms(executable=executable or None)
    except GisBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/gis-bridges/qgis/help")
def gis_qgis_help(payload: QgisHelpIn):
    try:
        return qgis_algorithm_help(payload.algorithm_id, executable=payload.executable or None)
    except GisBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/gis-bridges/qgis/run")
def gis_qgis_run(request: Request, payload: QgisRunIn):
    try:
        return run_qgis_algorithm(
            _project(request),
            payload.algorithm_id,
            payload.parameters,
            timeout_seconds=payload.timeout_seconds,
            executable=payload.executable or None,
        )
    except GisBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/gis-bridges/grass/run")
def gis_grass_run(request: Request, payload: GrassRunIn):
    try:
        return run_grass_module(
            _project(request),
            payload.module,
            payload.parameters,
            flags=payload.flags,
            crs=payload.crs,
            timeout_seconds=payload.timeout_seconds,
            executable=payload.executable or None,
        )
    except GisBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc
