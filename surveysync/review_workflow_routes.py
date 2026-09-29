"""Project-bound review workflow API."""
from __future__ import annotations

import base64
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from .desktop_context import require_panel_project
from . import review_workflow as service

router = APIRouter(prefix='/api/v9/review-workflow')


def project(request):
    if not request.headers.get('X-SurveySync-Project'):
        raise HTTPException(409, 'Open a project before using the review workspace.')
    return require_panel_project(request)


def execute(request, method, *args):
    from . import router as context
    with context.project_lock:
        p = project(request)
        try:
            return method(p, *args)
        except (ValueError, OSError, UnicodeError) as exc:
            raise HTTPException(400, str(exc)) from exc


class Token(BaseModel):
    snapshot: str = Field(min_length=64,max_length=64)

class Match(BaseModel):
    point_uuid: str
    row: int = Field(ge=2)

class Revision(Token):
    csv_text: str = Field(min_length=1,max_length=8000000)
    crs: str
    horizontal_units: str
    vertical_units: str
    matches: list[Match] = Field(default_factory=list,max_length=20000)

class Reservation(BaseModel):
    start: int
    end: int
    crew: str = Field(min_length=1,max_length=160)
    note: str = Field(default='',max_length=2000)

class Recheck(Token):
    issue_ids: list[str] = Field(min_length=1,max_length=20000)
    crew: str = Field(min_length=1,max_length=160)
    instructions: str = Field(min_length=3,max_length=2000)

class Observation(BaseModel):
    point_uuid: str
    northing: float | None = Field(default=None,allow_inf_nan=False)
    easting: float | None = Field(default=None,allow_inf_nan=False)
    elevation: float | None = Field(default=None,allow_inf_nan=False)

class Returned(BaseModel):
    records: list[Observation] = Field(min_length=1,max_length=20000)
    note: str = Field(default='',max_length=2000)

class Evidence(Token):
    issue_id: str
    filename: str = Field(min_length=1,max_length=160)
    media_type: str
    base64_content: str = Field(min_length=1,max_length=14000000)

class Policy(BaseModel):
    checks: dict[str,bool]

class Ack(Token):
    reviewer: str = Field(min_length=1,max_length=160)
    note: str = Field(min_length=3,max_length=2000)

class Report(Token):
    evidence_ids: list[str] = Field(default_factory=list,max_length=200)


@router.get('/state')
def get_state(request: Request):
    def read(p):
        data = service.snapshot(p)
        return {'snapshot': data['snapshot'], 'project': data['project'], 'issues': data['issues'], 'state': service.state(p), 'readiness': service.readiness(p,data['snapshot'])}
    return execute(request,read)

@router.post('/revision')
def revision(request: Request, payload: Revision):
    return execute(request,service.revision,payload.snapshot,payload.csv_text,payload.model_dump(include={'crs','horizontal_units','vertical_units'}),[m.model_dump() for m in payload.matches])

@router.post('/reservations')
def reserve(request: Request,payload: Reservation):
    return execute(request,service.reserve,payload.start,payload.end,payload.crew,payload.note)

@router.post('/reservations/{identifier}/release')
def release(request: Request,identifier: str):
    return execute(request,service.release,identifier)

@router.post('/rechecks')
def recheck(request: Request,payload: Recheck):
    return execute(request,service.recheck,payload.snapshot,payload.issue_ids,payload.crew,payload.instructions)

@router.post('/rechecks/{identifier}/return')
def returned(request: Request,identifier: str,payload: Returned):
    return execute(request,service.return_observations,identifier,[r.model_dump() for r in payload.records],payload.note)

@router.post('/evidence')
def evidence(request: Request,payload: Evidence):
    try: content = base64.b64decode(payload.base64_content,validate=True)
    except ValueError as exc: raise HTTPException(400,'Invalid attachment encoding.') from exc
    return execute(request,service.attach,payload.snapshot,payload.issue_id,payload.filename,content,payload.media_type)

@router.post('/policy')
def policy(request: Request,payload: Policy):
    return execute(request,service.policy,payload.checks)

@router.post('/acknowledge')
def acknowledge(request: Request,payload: Ack):
    return execute(request,service.acknowledge,payload.snapshot,payload.reviewer,payload.note)

@router.post('/report')
def report(request: Request,payload: Report):
    return execute(request,service.report,payload.snapshot,payload.evidence_ids)

@router.get('/rechecks/{identifier}/package')
def package(request: Request, identifier: str):
    from fastapi.responses import Response
    content = execute(request,service.crew_package,identifier)
    return Response(content,media_type='application/zip',headers={'Content-Disposition': 'attachment; filename="SurveySync_Field_Recheck.zip"'})


@router.get('/reports/{identifier}/download')
def download_report(request: Request, identifier: str):
    from fastapi.responses import Response
    content = execute(request, service.report_bytes, identifier)
    return Response(content, media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="SurveySync_Review.zip"'})
