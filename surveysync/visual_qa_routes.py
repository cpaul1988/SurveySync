"""Project-bound visual QA endpoints. Decisions are advisory; corrections create copies."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .desktop_context import require_panel_project
from .visual_qa import corrected_archive, snapshot, source_observations, verify_correction_sources

router = APIRouter(prefix="/api/v9/visual-qa")


class ContextIn(BaseModel):
    snapshot: str = Field(min_length=64, max_length=64)
    jump: float = Field(default=2, gt=0, le=100000, allow_inf_nan=False)
    distance: float = Field(default=50, gt=0, le=1000000, allow_inf_nan=False)
    reason: str = Field(min_length=3, max_length=2000)


class ReviewIn(ContextIn):
    issue_id: str = Field(min_length=64, max_length=64)
    decision: Literal["needs_review", "confirmed", "dismissed"]


class ChangeIn(BaseModel):
    point_uuid: str = Field(min_length=1, max_length=100)
    offset: float = Field(allow_inf_nan=False, ge=-100000, le=100000)


class ExportIn(ContextIn):
    changes: list[ChangeIn] = Field(min_length=1, max_length=20000)
    confirmed: bool = False


def project_for(request):
    if not request.headers.get("X-SurveySync-Project"):
        raise HTTPException(409, "Open the Visual QA workspace before continuing.")
    return require_panel_project(request)


def current(project, payload):
    data = snapshot(project, payload.jump, payload.distance)
    if data["snapshot"] != payload.snapshot:
        raise HTTPException(
            409, "Survey evidence or settings changed. Refresh Visual QA and review again."
        )
    if len(payload.reason.strip()) < 3:
        raise ValueError("Enter a review reason of at least three nonblank characters.")
    return data


@router.get("/snapshot")
def get_snapshot(
    request: Request,
    jump: float = Query(2, gt=0, le=100000),
    distance: float = Query(50, gt=0, le=1000000),
):
    from . import router as context

    with context.project_lock:
        project = project_for(request)
        try:
            with project.db.transaction():
                return snapshot(project, jump, distance)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc


@router.post("/review")
def review(request: Request, payload: ReviewIn):
    from . import router as context

    with context.project_lock:
        project = project_for(request)
        try:
            with project.db.transaction():
                data = current(project, payload)
                if not any(i["issue_id"] == payload.issue_id for i in data["issues"]):
                    raise ValueError("Issue is not in the reviewed snapshot.")
                event = project.db.audit(
                    "QASync",
                    "VISUAL_QA_REVIEW",
                    object_type="visual_qa_issue",
                    object_id=payload.issue_id,
                    details=payload.model_dump(),
                )
            return {"event_id": event, "decision": payload.decision, "advisory_only": True}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc


@router.post("/export")
def export(request: Request, payload: ExportIn):
    from . import router as context

    with context.project_lock:
        project = project_for(request)
        try:
            if not payload.confirmed:
                raise ValueError("Explicitly confirm the correction preview before exporting.")
            with project.db.transaction():
                data = current(project, payload)
                verify_correction_sources(project, data, payload.changes)
                content, changes = corrected_archive(data, payload.changes, payload.reason.strip())
                project.db.audit(
                    "QASync",
                    "VISUAL_QA_COPY_GENERATED",
                    object_type="project",
                    object_id=data["project"]["project_id"],
                    details={
                        "snapshot": data["snapshot"],
                        "reason": payload.reason.strip(),
                        "changes": changes,
                    },
                )
            return Response(
                content,
                media_type="application/zip",
                headers={
                    "Content-Disposition": 'attachment; filename="SurveySync_Reviewed_Points.zip"'
                },
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc


@router.get("/source/{point_uuid}")
def original_source(request: Request, point_uuid: str):
    from . import router as context

    with context.project_lock:
        try:
            return source_observations(project_for(request), point_uuid)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
