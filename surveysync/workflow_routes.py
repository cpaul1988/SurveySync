"""SurveySync declarative workflow API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .workflow_engine import (
    WorkflowError,
    approve_run,
    delete_workflow,
    dispatch_trigger,
    engine_status,
    export_workflows_yaml,
    import_workflows_yaml,
    list_runs,
    list_workflows,
    save_workflow,
    start_workflow,
)

router = APIRouter()


class WorkflowActionIn(BaseModel):
    type: str = Field(min_length=1)
    params: dict = Field(default_factory=dict)


class WorkflowSaveIn(BaseModel):
    workflow_id: str = ""
    name: str = Field(min_length=1)
    enabled: bool = True
    trigger: str = "manual"
    description: str = ""
    actions: list[WorkflowActionIn] = Field(min_length=1)


class WorkflowRunIn(BaseModel):
    workflow_id: str = Field(min_length=1)
    context: dict = Field(default_factory=dict)


class WorkflowApprovalIn(BaseModel):
    run_id: str = Field(min_length=1)
    approved: bool
    note: str = ""


class WorkflowDeleteIn(BaseModel):
    workflow_id: str = Field(min_length=1)


class WorkflowDispatchIn(BaseModel):
    trigger: str = Field(min_length=1)
    context: dict = {}


class WorkflowYamlIn(BaseModel):
    yaml_text: str = Field(min_length=1)


def _project(request: Request):
    from .desktop_context import require_panel_project
    return require_panel_project(request)


@router.get("/api/v9/workflows/status")
def workflow_status():
    return engine_status()


@router.get("/api/v9/workflows")
def workflows(request: Request):
    return {"workflows": list_workflows(_project(request))}


@router.post("/api/v9/workflows")
def workflow_save(request: Request, payload: WorkflowSaveIn):
    try:
        return save_workflow(_project(request), payload.model_dump())
    except (WorkflowError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/workflows/delete")
def workflow_delete(request: Request, payload: WorkflowDeleteIn):
    try:
        return delete_workflow(_project(request), payload.workflow_id)
    except (WorkflowError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/workflows/run")
def workflow_run(request: Request, payload: WorkflowRunIn):
    try:
        return start_workflow(_project(request), payload.workflow_id, context=payload.context)
    except (WorkflowError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/workflows/approve")
def workflow_approve(request: Request, payload: WorkflowApprovalIn):
    try:
        return approve_run(
            _project(request),
            payload.run_id,
            approved=payload.approved,
            note=payload.note,
        )
    except (WorkflowError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/v9/workflow-runs")
def workflow_runs(request: Request, limit: int = 100):
    return {"runs": list_runs(_project(request), limit)}


@router.post("/api/v9/workflows/dispatch")
def workflow_dispatch(request: Request, payload: WorkflowDispatchIn):
    try:
        runs = dispatch_trigger(_project(request), payload.trigger, context=payload.context)
    except (WorkflowError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"trigger": payload.trigger, "run_count": len(runs), "runs": runs}


@router.get("/api/v9/workflows/export-yaml", response_class=PlainTextResponse)
def workflow_export_yaml(request: Request):
    return PlainTextResponse(export_workflows_yaml(_project(request)), media_type="text/yaml")


@router.post("/api/v9/workflows/import-yaml")
def workflow_import_yaml(request: Request, payload: WorkflowYamlIn):
    try:
        return import_workflows_yaml(_project(request), payload.yaml_text)
    except (WorkflowError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/workflows/save-yaml")
def workflow_save_yaml_file(request: Request):
    from uuid import uuid4
    project = _project(request)
    path = project.paths.reports / "Workflows" / ("workflows_" + uuid4().hex + ".yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(export_workflows_yaml(project), encoding="utf-8")
    return {"output_path": str(path)}
