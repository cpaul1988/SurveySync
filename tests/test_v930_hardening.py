import math
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fieldbook_sync.models import SurveyPoint
from fieldbook_sync.rod_height_qc import detect_rod_height_busts

ROOT = Path(__file__).resolve().parents[1]


def point(pid, x, z):
    return SurveyPoint(point_id=pid, northing=0, easting=x, elevation=z, code='604', category='Ground')


def test_rod_qc_reports_isolated_offset_without_mutating_source():
    points = [point('1', 0, 100), point('2', 1, 100), point('3', 2, 102), point('4', 3, 100), point('5', 4, 100)]
    original = [p.model_dump() for p in points]
    found = detect_rod_height_busts(points)
    assert [r['point_id'] for r in found] == ['3']
    assert found[0]['signed_delta'] == 2
    assert [p.model_dump() for p in points] == original


def test_rod_qc_ignores_nonfinite_points_and_smooth_grade():
    points = [point(str(i), i, 100 + i * .02) for i in range(8)]
    points += [point('bad', math.nan, 102), point('inf', 4, math.inf)]
    assert detect_rod_height_busts(points) == []


def test_domain_routes_have_no_duplicate_methods_and_paths():
    from fieldbook_sync.app import app
    keys = [(method, route.path) for route in app.routes for method in getattr(route, 'methods', [])]
    assert not [key for key, count in Counter(keys).items() if count > 1]


def test_operations_keep_no_project_conflict_and_log_unexpected_errors(tmp_path, monkeypatch):
    from fieldbook_sync.app import app
    from surveysync import router, operations_routes
    monkeypatch.setattr(router, 'current_project', None)
    client = TestClient(app)
    response = client.post('/api/v9/snapshots', json={'label': 'test', 'kind': 'manual'})
    assert response.status_code == 409


def test_map_router_uses_current_runtime_after_project_switch(tmp_path, monkeypatch):
    from fieldbook_sync import app as field_app
    from fieldbook_sync.map_routes import api_map_state
    from types import SimpleNamespace
    from fieldbook_sync.models import AppState
    from threading import RLock
    a = SimpleNamespace(storage=SimpleNamespace(lock=RLock(), state=AppState()))
    b = SimpleNamespace(storage=SimpleNamespace(lock=RLock(), state=AppState()))
    a.storage.state.map_project_crs = 'EPSG:2278'
    b.storage.state.map_project_crs = 'EPSG:4326'
    monkeypatch.setattr(field_app, 'runtime', a)
    first = api_map_state()
    monkeypatch.setattr(field_app, 'runtime', b)
    second = api_map_state()
    assert first != second


def test_release_gate_fails_closed(monkeypatch):
    from scripts import release_gate
    from types import SimpleNamespace
    calls = []
    monkeypatch.setattr(release_gate.shutil, 'which', lambda _: '/node')
    monkeypatch.setattr(release_gate, 'commands', lambda *_: [['first'], ['should-not-run']])
    def failed(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=7)
    monkeypatch.setattr(release_gate.subprocess, 'run', failed)
    assert release_gate.main() == 7
    assert calls == [['first']]


def test_release_gate_requires_javascript_runtime(monkeypatch):
    from scripts import release_gate
    monkeypatch.setattr(release_gate.shutil, 'which', lambda _: None)
    assert release_gate.main() == 1


def test_bad_recent_project_metadata_does_not_mask_original_failure(tmp_path):
    from surveysync.router import _project_list_item
    (tmp_path / 'survey_sync_project.json').write_text('{broken')
    result = _project_list_item(tmp_path)
    assert isinstance(result, dict)


def test_dependency_audit_includes_windows_only_pins():
    from scripts.audit_locks import pinned_packages
    assert pinned_packages("pythonnet==3.0.5 ; sys_platform == 'win32' \\n    --hash=sha256:123") == {'pythonnet==3.0.5'}
