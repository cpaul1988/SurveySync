"""SurveySync declarative workflow API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
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
    params: dict = {}


class WorkflowSaveIn(BaseModel):
    workflow_id: str = ""
    name: str = Field(min_length=1)
    enabled: bool = True
    trigger: str = "manual"
    description: str = ""
    actions: list[WorkflowActionIn] = Field(min_length=1)


class WorkflowRunIn(BaseModel):
    workflow_id: str = Field(min_length=1)
    context: dict = {}


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


def _project():
    from . import router as main_router

    return main_router.require_project()


@router.get("/api/v9/workflows/status")
def workflow_status():
    return engine_status()


@router.get("/api/v9/workflows")
def workflows():
    return {"workflows": list_workflows(_project())}


@router.post("/api/v9/workflows")
def workflow_save(payload: WorkflowSaveIn):
    try:
        return save_workflow(_project(), payload.model_dump())
    except (WorkflowError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/workflows/delete")
def workflow_delete(payload: WorkflowDeleteIn):
    try:
        return delete_workflow(_project(), payload.workflow_id)
    except (WorkflowError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/workflows/run")
def workflow_run(payload: WorkflowRunIn):
    try:
        return start_workflow(_project(), payload.workflow_id, context=payload.context)
    except (WorkflowError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/workflows/approve")
def workflow_approve(payload: WorkflowApprovalIn):
    try:
        return approve_run(
            _project(),
            payload.run_id,
            approved=payload.approved,
            note=payload.note,
        )
    except (WorkflowError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/v9/workflow-runs")
def workflow_runs(limit: int = 100):
    return {"runs": list_runs(_project(), limit)}


@router.post("/api/v9/workflows/dispatch")
def workflow_dispatch(payload: WorkflowDispatchIn):
    try:
        runs = dispatch_trigger(_project(), payload.trigger, context=payload.context)
    except (WorkflowError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"trigger": payload.trigger, "run_count": len(runs), "runs": runs}


@router.get("/api/v9/workflows/export-yaml", response_class=PlainTextResponse)
def workflow_export_yaml():
    return PlainTextResponse(export_workflows_yaml(_project()), media_type="text/yaml")


@router.post("/api/v9/workflows/import-yaml")
def workflow_import_yaml(payload: WorkflowYamlIn):
    try:
        return import_workflows_yaml(_project(), payload.yaml_text)
    except (WorkflowError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
