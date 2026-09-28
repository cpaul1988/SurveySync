"""ReportSync Excel Template Mapper API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .report_template_mapper import (
    ReportTemplateError,
    delete_template,
    inspect_excel_template,
    list_templates,
    register_excel_template,
    render_excel_template,
    save_template_mapping,
)

router = APIRouter()


class ExcelTemplateInspectIn(BaseModel):
    file_path: str = Field(min_length=1)


class ExcelTemplateRegisterIn(BaseModel):
    file_path: str = Field(min_length=1)
    name: str = ""
    mapping: dict | None = None


class ExcelTemplateMappingIn(BaseModel):
    template_id: str = Field(min_length=1)
    mapping: dict


class ExcelTemplateRenderIn(BaseModel):
    template_id: str = Field(min_length=1)
    output_path: str = ""


class ExcelTemplateDeleteIn(BaseModel):
    template_id: str = Field(min_length=1)


def _project(request: Request):
    from .desktop_context import require_panel_project

    return require_panel_project(request)


@router.post("/api/v9/reports/templates/inspect")
def report_template_inspect(payload: ExcelTemplateInspectIn):
    try:
        return inspect_excel_template(payload.file_path)
    except ReportTemplateError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/v9/reports/templates")
def report_templates(request: Request):
    return {"templates": list_templates(_project(request))}


@router.post("/api/v9/reports/templates")
def report_template_register(request: Request, payload: ExcelTemplateRegisterIn):
    try:
        return register_excel_template(
            _project(request),
            payload.file_path,
            name=payload.name,
            mapping=payload.mapping,
        )
    except (ReportTemplateError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/reports/templates/mapping")
def report_template_mapping_save(request: Request, payload: ExcelTemplateMappingIn):
    try:
        return save_template_mapping(_project(request), payload.template_id, payload.mapping)
    except (ReportTemplateError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/reports/templates/render")
def report_template_render(request: Request, payload: ExcelTemplateRenderIn):
    try:
        return render_excel_template(
            _project(request),
            payload.template_id,
            output_path=payload.output_path or None,
        )
    except (ReportTemplateError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/v9/reports/templates/delete")
def report_template_delete(request: Request, payload: ExcelTemplateDeleteIn):
    try:
        return delete_template(_project(request), payload.template_id)
    except (ReportTemplateError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/v9/reports/templates/details")
def report_template_details(request: Request, template_id: str):
    from .report_template_mapper import template_details

    try:
        return template_details(_project(request), template_id)
    except (ReportTemplateError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
