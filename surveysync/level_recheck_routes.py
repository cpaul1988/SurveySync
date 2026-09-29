"""Project-bound LevelSync recheck API."""
from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import level_rechecks

router = APIRouter()


class RequestIn(BaseModel):
    run_id: str
    setup_no: int = Field(ge=1)
    closure_tolerance: float = Field(gt=0)
    crew: str = Field(min_length=1, max_length=160)
    instructions: str = Field(min_length=3, max_length=2000)


class ReturnIn(BaseModel):
    file_path: str


class ReviewIn(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    reviewer: str = Field(min_length=1, max_length=160)
    note: str = Field(min_length=3, max_length=2000)


def _call(method, *args):
    from . import router as context
    with context.project_lock:
        try:
            return method(context.require_project(), *args)
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
            raise HTTPException(400, str(exc)) from exc


@router.get("/api/v9/level/rechecks")
def requests():
    return {"requests": _call(level_rechecks.list_requests)}


@router.post("/api/v9/level/rechecks")
def request(payload: RequestIn):
    return _call(level_rechecks.create_request, payload.run_id, payload.setup_no, payload.closure_tolerance, payload.crew, payload.instructions)


@router.get("/api/v9/level/rechecks/{identifier}/crew-package")
def crew_package(identifier: str):
    content = _call(level_rechecks.request_package, identifier)
    return Response(content, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="Level_Recheck_Request.zip"'})


@router.post("/api/v9/level/rechecks/{identifier}/return")
def stage(identifier: str, payload: ReturnIn):
    return _call(level_rechecks.stage_return, identifier, payload.file_path)


@router.post("/api/v9/level/rechecks/{identifier}/review")
def review(identifier: str, payload: ReviewIn):
    return _call(level_rechecks.review_return, identifier, payload.decision, payload.reviewer, payload.note)


@router.get("/api/v9/level/rechecks/{identifier}/approved-package")
def approved(identifier: str):
    content = _call(level_rechecks.approved_package, identifier)
    return Response(content, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="Level_Recheck_Approved.zip"'})
