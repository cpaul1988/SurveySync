"""CRS diagnostic API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .crs_diagnostics import (
    CrsDiagnosticError,
    crs_profile,
    operation_diagnostics,
    project_crs_diagnostics,
)

router = APIRouter()


class CrsProfileIn(BaseModel):
    crs: str = Field(min_length=1)


class CrsOperationIn(BaseModel):
    source_crs: str = Field(min_length=1)
    target_crs: str = Field(min_length=1)
    sample_x: float | None = None
    sample_y: float | None = None
    area_of_interest: dict[str, float] | None = None


class ProjectCrsDiagnosticIn(BaseModel):
    target_crs: str = ""
    sample_x: float | None = None
    sample_y: float | None = None


def _project(request: Request):
    from .desktop_context import require_panel_project
    return require_panel_project(request)


@router.post("/api/v9/crs/profile")
def crs_profile_route(payload: CrsProfileIn):
    try:
        return crs_profile(payload.crs)
    except CrsDiagnosticError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/crs/operations")
def crs_operations_route(payload: CrsOperationIn):
    try:
        return operation_diagnostics(
            payload.source_crs,
            payload.target_crs,
            sample_x=payload.sample_x,
            sample_y=payload.sample_y,
            area_of_interest=payload.area_of_interest,
        )
    except CrsDiagnosticError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/crs/project-diagnostics")
def project_crs_diagnostics_route(request: Request, payload: ProjectCrsDiagnosticIn):
    try:
        return project_crs_diagnostics(
            _project(request),
            target_crs=payload.target_crs,
            sample_x=payload.sample_x,
            sample_y=payload.sample_y,
        )
    except CrsDiagnosticError as exc:
        raise HTTPException(400, str(exc)) from exc
