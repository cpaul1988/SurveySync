"""FBR-0018: actual project binding, stale views, safe switching and snapshots."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from fieldbook_sync import app as field
from fieldbook_sync.models import AppState
from fieldbook_sync.project_binding import apply_identity
from fieldbook_sync.project_files import create_project_bundle
from surveysync import router as shell
from surveysync.config import ConfigStore
from surveysync.fieldbook_session import FieldBookSessionMiddleware, changing_project, current_context
from surveysync.project import SurveyProject


@pytest.fixture
def session(tmp_path, monkeypatch):
    original = field.runtime
    monkeypatch.setattr(shell, 'config_store', ConfigStore(tmp_path / 'config'))
    monkeypatch.setattr(shell, 'current_project', None)
    monkeypatch.setattr(field, 'runtime', field.Runtime(tmp_path / 'neutral'))
    monkeypatch.setattr(field, '_automatic_ai_status', lambda *a, **k: {})
    client = TestClient(field.app)
    try:
        yield client, tmp_path
    finally:
        field.runtime.job_store.close()
        field.runtime = original


def open_project(tmp_path, name):
    project = SurveyProject.create(tmp_path, name)
    shell._set_current(project)
    return project


def test_name_id_root_and_reopen_stay_authoritative(session):
    client, tmp = session
    project = open_project(tmp, 'test')
    context = client.get('/api/v9/fieldbook/context').json()
    state = client.get('/api/state', headers={'X-SurveySync-Project': context['token']}).json()
    assert context['bound'] is True
    assert state['project_name'] == 'test'
    assert Path(state['autosave_path']).parent == project.paths.fieldbook_root
    assert state['project_context']['project_id'] == project.manifest['project_id']
    runtime = field.runtime
    shell._set_current(SurveyProject(project.paths.root))
    assert field.runtime is runtime  # no restart just for selecting same job
    disk = json.loads(runtime.storage.state_path.read_text())
    assert disk['project_name'] == 'test'
    assert disk['surveysync_project_id'] == project.manifest['project_id']


def test_project_switch_isolates_data_and_rejects_stale_requests_and_downloads(session):
    client, tmp = session
    project_a = open_project(tmp, 'Alpha')
    token_a = current_context()['token']
    field.runtime.storage.state.legacy_project_name = 'Only Alpha'
    field.runtime.storage.save()
    project_b = open_project(tmp, 'Beta')
    assert field.runtime.storage.state.legacy_project_name == ''
    assert field.runtime.storage.root == project_b.paths.fieldbook_root
    for path in ['/api/state', '/api/project/download', '/api/export']:
        assert client.get(path, headers={'X-SurveySync-Project': token_a}).status_code == 409
        assert client.get(path, params={'ss_project': token_a}).status_code == 409
    shell._set_current(SurveyProject(project_a.paths.root))
    assert field.runtime.storage.state.project_name == 'Alpha'
    assert field.runtime.storage.state.legacy_project_name == 'Only Alpha'


def test_root_or_recorded_id_mismatch_blocks_actual_data_operations(session):
    client, tmp = session
    open_project(tmp, 'test')
    original_root = field.runtime.storage.root
    field.runtime.storage.root = tmp / 'wrong'
    assert client.post('/api/reset').status_code == 409
    field.runtime.storage.root = original_root
    field.runtime.storage.state.surveysync_project_id = 'wrong-id'
    assert client.get('/api/export').status_code == 409
    assert client.get('/api/v9/fieldbook/context').json()['bound'] is False


def test_wrong_saved_project_id_refused_without_replacing_old_runtime(session):
    _, tmp = session
    open_project(tmp, 'Alpha')
    old = field.runtime
    other = SurveyProject.create(tmp, 'Beta')
    other.paths.fieldbook_root.mkdir(parents=True, exist_ok=True)
    (other.paths.fieldbook_root / 'project.json').write_text(AppState(surveysync_project_id='other-id').model_dump_json())
    with pytest.raises(ValueError, match='different SurveySync project'):
        shell._set_current(other)
    assert field.runtime is old
    assert shell.current_project.manifest['name'] == 'Alpha'
    assert old.job_store.has_resumable_jobs() is False  # old ledger remains usable


@pytest.mark.parametrize('worker', ['analysis', 'import', 'batch', 'network'])
def test_busy_workers_block_project_switch(session, worker):
    _, tmp = session
    open_project(tmp, 'Alpha')
    old = field.runtime
    if worker == 'analysis': old.job.running = True
    elif worker == 'import': old.import_job.running = True
    elif worker == 'batch': old.batch_thread = SimpleNamespace(is_alive=lambda: True)
    else: old.live_network_rebuild_running = True
    with pytest.raises(RuntimeError, match='Cannot switch'):
        shell._set_current(SurveyProject.create(tmp, 'Beta'))
    assert field.runtime is old


def test_failed_candidate_constructor_keeps_old_project(session, monkeypatch):
    _, tmp = session
    open_project(tmp, 'Alpha')
    old = field.runtime
    project_b = SurveyProject.create(tmp, 'Beta')
    monkeypatch.setattr(field, 'Runtime', Mock(side_effect=OSError('disk unavailable')))
    with pytest.raises(OSError): shell._set_current(project_b)
    assert field.runtime is old
    assert shell.current_project.manifest['name'] == 'Alpha'
    old.storage.save()


def test_snapshot_import_and_reset_do_not_replace_shared_identity(session):
    client, tmp = session
    project = open_project(tmp, 'test')
    source = AppState(project_name='Old job', surveysync_project_id='source-id')
    source.map_project_crs = 'EPSG:2278'
    bundle = create_project_bundle(source, tmp / 'empty', tmp / 'bundles')
    field.load_project_path_into_runtime(bundle)
    state = field.runtime.storage.state
    assert state.project_name == 'test'
    assert state.surveysync_project_id == project.manifest['project_id']
    assert state.legacy_project_name == 'Old job'
    assert state.map_project_crs == 'EPSG:2278'  # never silently transform source coordinates
    assert client.post('/api/project/name', json={'name':'different'}).status_code == 409
    assert client.post('/api/reset').status_code == 200
    assert field.runtime.storage.state.project_name == 'test'
    assert current_context()['bound'] is True


def test_recovery_from_foreign_project_cannot_change_identity(session):
    client, tmp = session
    open_project(tmp, 'test')
    original = deepcopy(field.runtime.storage.state)
    foreign = AppState(project_name='different', surveysync_project_id='different-id')
    field.runtime.storage.recovery_path.write_text(foreign.model_dump_json())
    # Use direct function to observe validation without a TestClient transport wrapper.
    with pytest.raises(HTTPException): field.api_recovery_restore()
    assert field.runtime.storage.state == original


def test_request_lease_includes_final_stream_and_always_releases(session):
    _, tmp = session
    open_project(tmp, 'test')
    events = []
    async def downstream(scope, receive, send):
        with pytest.raises(HTTPException):
            with changing_project(): pass
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'done','more_body':False})
    async def send(message):
        with pytest.raises(HTTPException):
            with changing_project(): pass
        events.append(message['type'])
    async def receive(): return {'type':'http.request', 'body':b'', 'more_body':False}
    asyncio.run(FieldBookSessionMiddleware(downstream)(
        {'type':'http','path':'/api/export','method':'GET','headers':[],'query_string':b''}, receive, send))
    with changing_project(): pass
    assert events == ['http.response.start', 'http.response.body']


def test_no_project_feedback_allowed_but_data_mutations_refused(session, monkeypatch):
    client, _ = session
    monkeypatch.setattr(field, '_feedback_config', lambda: {})
    headers = {'X-SurveySync-Project':'__none__'}
    assert client.get('/api/feedback/reports', headers=headers).status_code == 200
    assert client.get('/api/state', headers=headers).status_code == 200
    assert client.post('/api/reset', headers=headers).status_code == 409
    assert client.get('/api/export', headers=headers).status_code == 409


def test_feedback_worker_keeps_originating_root_after_switch(session, monkeypatch):
    _, tmp = session
    open_project(tmp, 'Alpha')
    root = field.runtime.storage.root
    report_id = 'FBL-test'
    report = root / 'feedback' / 'reports' / report_id / 'report.json'
    report.parent.mkdir(parents=True)
    report.write_text('{"report_id":"FBL-test"}')
    open_project(tmp, 'Beta')
    updates = []
    monkeypatch.setattr(field, 'submit_to_tracker_endpoint', lambda *args: {'intake_id':'test'})
    monkeypatch.setattr(field, 'update_feedback_sync', lambda path, *args: updates.append(path))
    field._sync_feedback_report(report_id, 'https://example.invalid', root)
    assert updates == [root, root]


def test_shared_identity_preserves_legacy_title_without_modifying_coordinates(tmp_path):
    storage = SimpleNamespace(survey_sync_context={'project_id':'test','name':'Shared'})
    state = AppState(project_name='Original', map_project_crs='EPSG:2278')
    apply_identity(storage, state)
    assert (state.project_name,state.legacy_project_name,state.map_project_crs) == ('Shared','Original','EPSG:2278')
