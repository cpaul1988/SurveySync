"""CAD review routes: bounded upload, immutable evidence, mandatory project identity."""

import threading
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from .desktop_context import require_panel_project
from . import cad_review as cad
from . import cad_review_workflow as workflow
from .cad_geometry import closure

router = APIRouter(prefix="/api/v9/cad")
_worker = threading.BoundedSemaphore(1)


def project_for(request):
    if not request.headers.get("X-SurveySync-Project"):
        raise HTTPException(409, "Open CAD Review before continuing.")
    return require_panel_project(request)


class Selection(BaseModel):
    entity_id: str = Field(min_length=1, max_length=500)
    reverse: bool = False


class ReviewIn(BaseModel):
    review_id: str = Field(pattern="^[0-9a-f]{32}$")
    snapshot: str = Field(pattern="^[0-9a-f]{64}$")
    state_token: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    before_review_id: str | None = Field(default=None, pattern="^[0-9a-f]{32}$")
    before_snapshot: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    selections: list[Selection] = Field(default_factory=list, max_length=1000)


def checked(project, payload):
    data = cad.read(project, payload.review_id)
    if data["snapshot"] != payload.snapshot:
        raise ValueError("CAD evidence changed. Reopen the review.")
    return data


@router.post("/import")
def import_drawing(
    request: Request,
    file: UploadFile = File(...),
    drawing_units: str = Form(...),
    alignment_confirmed: bool = Form(False),
    gap_search_ft: float = Form(1.0),
):
    from . import router as context

    if not _worker.acquire(blocking=False):
        raise HTTPException(409, "Another CAD import is running. Try again when it finishes.")
    try:
        with context.project_lock:
            project = project_for(request)
            expected = cad.context(project)
            if not alignment_confirmed:
                raise ValueError(
                    "Confirm the DXF shares the project coordinate origin, axes and CRS."
                )
            if not (file.filename or "").lower().endswith(".dxf"):
                raise ValueError("Select a DXF file; DWG is not supported.")
            if expected["crs"]:
                from pyproj import CRS

                if CRS.from_user_input(expected["crs"]).is_geographic:
                    raise ValueError(
                        "CAD review requires a projected or local linear coordinate system."
                    )
        raw = file.file.read(cad.MAX_BYTES + 1)
        drawing = cad.parse_bytes(raw, drawing_units, expected["horizontal_units"], gap_search_ft)
        with context.project_lock:
            if project_for(request) is not project:
                raise HTTPException(409, "Project changed during DXF import; no result retained.")
            return cad.retain(project, raw, file.filename or "drawing.dxf", drawing, expected)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        _worker.release()


@router.get("/reviews")
def reviews(request: Request):
    from . import router as context

    with context.project_lock:
        try:
            return {"reviews": cad.list_reviews(project_for(request))}
        except (OSError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc


@router.get("/reviews/{review_id}")
def get_review(request: Request, review_id: str):
    from . import router as context

    with context.project_lock:
        try:
            return cad.read(project_for(request), review_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc


@router.post("/closure")
def check_closure(request: Request, payload: ReviewIn):
    from . import router as context

    with context.project_lock:
        try:
            return closure(
                checked(project_for(request), payload), [s.model_dump() for s in payload.selections]
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc


@router.post("/report")
def export_report(request: Request, payload: ReviewIn):
    from . import router as context

    with context.project_lock:
        try:
            project = project_for(request)
            data = checked(project, payload)
            review_state = workflow.state(project, data)
            if payload.state_token != review_state["token"]:
                raise ValueError("Drawing decisions changed. Reopen the review before exporting.")
            comparison = comparison_for(project, data, payload)
            output = workflow.report(
                data, [s.model_dump() for s in payload.selections], review_state, comparison
            )
            project.db.audit(
                "BoundarySync",
                "CAD_REVIEW_REPORT",
                object_type="cad_review",
                object_id=payload.review_id,
                details={
                    "snapshot": data["snapshot"],
                    "state_token": review_state["token"],
                    "comparison_before": comparison["before"] if comparison else None,
                    "selections": [s.model_dump() for s in payload.selections],
                    "source_modified": False,
                },
            )
            return Response(
                output,
                media_type="application/zip",
                headers={"Content-Disposition": 'attachment; filename="SurveySync_CAD_Review.zip"'},
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc


class DecisionIn(ReviewIn):
    finding_id: str = Field(pattern="^[0-9a-f]{64}$")
    status: str = Field(pattern="^(needs_review|confirmed|dismissed)$")
    note: str = Field(min_length=1, max_length=4000)
    reviewer: str = Field(min_length=1, max_length=120)


def comparison_for(project, data, payload):
    if not payload.before_review_id and not payload.before_snapshot:
        return None
    if not payload.before_review_id or not payload.before_snapshot:
        raise ValueError("Select and compare the earlier drawing first.")
    before = cad.read(project, payload.before_review_id)
    if before["snapshot"] != payload.before_snapshot:
        raise ValueError("Earlier drawing evidence changed. Compare again.")
    return workflow.compare(before, data)


@router.post("/state")
def get_state(request: Request, payload: ReviewIn):
    from . import router as context

    with context.project_lock:
        try:
            project = project_for(request)
            return workflow.state(project, checked(project, payload))
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc


@router.post("/decision")
def save_decision(request: Request, payload: DecisionIn):
    from . import router as context

    with context.project_lock:
        try:
            project = project_for(request)
            return workflow.decide(
                project,
                checked(project, payload),
                payload.finding_id,
                payload.status,
                payload.note,
                payload.reviewer,
                payload.state_token,
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc


@router.post("/compare")
def compare_drawings(request: Request, payload: ReviewIn):
    from . import router as context

    with context.project_lock:
        try:
            project = project_for(request)
            result = comparison_for(project, checked(project, payload), payload)
            if result is None:
                raise ValueError("Choose an earlier drawing to compare.")
            return result
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
