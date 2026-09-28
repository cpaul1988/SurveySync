"""TopoSync point-cloud API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .pointcloud import (
    PointCloudError,
    import_point_cloud,
    inspect_point_cloud,
    point_cloud_sources,
    runtime_status,
    sample_points,
)

router = APIRouter()


class PointCloudPathIn(BaseModel):
    file_path: str = Field(min_length=1)


class PointCloudImportIn(PointCloudPathIn):
    notes: str = ""


class PointCloudSampleIn(PointCloudPathIn):
    max_points: int = Field(default=1000, ge=1, le=10000)


def _project(request: Request):
    from .desktop_context import require_panel_project
    return require_panel_project(request)


@router.get("/api/v9/pointcloud/status")
def pointcloud_status():
    return runtime_status()


@router.post("/api/v9/pointcloud/inspect")
def pointcloud_inspect(payload: PointCloudPathIn):
    try:
        return inspect_point_cloud(payload.file_path)
    except (OSError, PointCloudError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/pointcloud/import")
def pointcloud_import(request: Request, payload: PointCloudImportIn):
    project = _project(request)
    try:
        return import_point_cloud(project, payload.file_path, notes=payload.notes)
    except (OSError, PointCloudError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/pointcloud/sample")
def pointcloud_sample(payload: PointCloudSampleIn):
    try:
        return sample_points(payload.file_path, max_points=payload.max_points)
    except (OSError, PointCloudError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/v9/pointcloud/sources")
def pointcloud_source_list(request: Request):
    return {"sources": point_cloud_sources(_project(request))}
