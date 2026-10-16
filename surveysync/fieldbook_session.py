"""Shared FieldBook project identity and request/switch coordination.

The gate holds only a counter lock across request boundaries, never a threading
lock across an ASGI await. Project changes fail fast while a request or worker
owns the old workspace; streaming exports keep their lease through final send.
"""
from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from threading import RLock, get_ident
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException
from starlette.responses import JSONResponse

_lock = RLock()
_active_requests = 0
_switch_owner: int | None = None
_switch_depth = 0
router = APIRouter()


def path_key(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).expanduser().resolve()))


def project_identity(project) -> dict:
    root = path_key(project.paths.root)
    project_id = str(project.manifest['project_id'])
    return {
        'project_id': project_id,
        'name': str(project.manifest['name']),
        'root': str(project.paths.root.resolve()),
        'fieldbook_root': str(project.paths.fieldbook_root.resolve()),
        'crs': str(project.manifest.get('crs', '')),
        'horizontal_units': project.manifest.get('horizontal_units', ''),
        'vertical_units': project.manifest.get('vertical_units', ''),
        'token': hashlib.sha256((project_id + '\0' + root).encode()).hexdigest(),
    }


@contextmanager
def changing_project():
    """Exclude requests until both the engine and shell point at the new project."""
    global _switch_owner, _switch_depth
    owner = get_ident()
    with _lock:
        if _active_requests or (_switch_owner is not None and _switch_owner != owner):
            raise HTTPException(409, 'FieldBookSync is busy. Finish the current operation before switching projects.')
        _switch_owner = owner
        _switch_depth += 1
    try:
        yield
    finally:
        with _lock:
            _switch_depth -= 1
            if not _switch_depth:
                _switch_owner = None


def current_context() -> dict:
    from . import router as shell
    from fieldbook_sync import app as field

    project = shell.current_project
    if project is None:
        return {'project_id': '', 'name': 'No project open', 'token': '__none__',
                'bound': False, 'root': '', 'fieldbook_root': ''}
    context = project_identity(project)
    storage = field.runtime.storage
    recorded = getattr(storage, 'survey_sync_context', None) or {}
    context['bound'] = (
        path_key(storage.root) == path_key(context['fieldbook_root'])
        and recorded.get('project_id') == context['project_id']
        and recorded.get('token') == context['token']
        and storage.state.surveysync_project_id == context['project_id']
    )
    return context


@router.get('/api/v9/fieldbook/context')
def context_status():
    with _lock:
        if _switch_owner is not None:
            raise HTTPException(409, 'The active project is changing. Retry when it finishes.')
        return current_context()


# These read-only endpoints initialize the existing feedback wizard. No-project
# support may write a feedback report but never survey data or project settings.
_SUPPORT_READS = frozenset({
    '/api/state', '/api/profiles', '/api/field-note-profiles', '/api/ai/status',
    '/api/performance', '/api/paddle/status', '/api/ollama/models',
    '/api/global-mapper/status', '/api/update/check', '/api/update/status',
})
_CROSS_MODULE = frozenset({
    '/api/v9/fieldbook/migrate', '/api/v9/utility/sync-fieldbook',
    '/api/v9/reports/fieldbook-pdf', '/api/v9/level/extract-fieldbook',
    '/api/v9/utility/recalculate-inverts', '/api/v9/utility/analyze',
    '/api/v9/utility/completion-kmz', '/api/v9/attachments/auto-photos',
    '/api/v9/config/ai',
})


def support_request(path: str, method: str) -> bool:
    return (path.startswith('/api/feedback') or path == '/api/startup/ready'
            or (method == 'GET' and path in _SUPPORT_READS))


class FieldBookSessionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        global _active_requests
        path = scope.get('path', '')
        relevant = (path.startswith('/api/') and not path.startswith('/api/v9/')) or path in _CROSS_MODULE
        if scope['type'] != 'http' or not relevant:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get('headers', []))
        token = headers.get(b'x-surveysync-project', b'').decode('utf-8', 'replace')
        query = parse_qs(scope.get('query_string', b'').decode('utf-8', 'replace'))
        token = token or query.get('ss_project', [''])[0]
        message = ''
        support = support_request(path, scope['method']) or path.startswith('/api/update/') or path in {'/api/application/exit', '/api/v9/config/ai'}
        with _lock:
            if _switch_owner is not None:
                message = 'The active project is changing. Retry when it finishes.'
            else:
                context = current_context()
                if token and token != context['token']:
                    message = 'This FieldBookSync view belongs to a different project. Reopen it from the module tab.'
                elif context['project_id'] and not context['bound'] and not support:
                    message = 'FieldBookSync project ID or storage does not match SurveySync. Reopen the intended project before continuing.'
                elif token == '__none__' and not support:
                    message = 'Open a SurveySync project before using FieldBookSync data tools. Feedback remains available without a project.'
            if not message:
                _active_requests += 1
        if message:
            await JSONResponse({'detail': message, 'code': 'FBS_PROJECT_CONTEXT'}, status_code=409)(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            with _lock:
                _active_requests -= 1
