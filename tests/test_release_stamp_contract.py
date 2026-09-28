"""A candidate's displayed and packaged identities must match its actual stamp."""
import importlib.util
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('stamp_gate', ROOT/'scripts/validate_release_identity.py')
stamp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stamp)


def test_packaged_build_is_consistent():
    result = stamp.validate()
    assert result['release_id'] == (ROOT/'RELEASE_ID.txt').read_text(encoding='utf-8').strip()
    assert result['version'] == (ROOT/'VERSION.txt').read_text(encoding='utf-8').strip()


@pytest.mark.parametrize('path', ['RELEASE_ID.txt', 'surveysync/__init__.py', 'installer/app_launcher.go',
    'installer/SurveySync.iss', 'surveysync/static/index.html', 'fieldbook_sync/static/index.html', 'BUILD_MANIFEST.json'])
def test_gate_rejects_one_stale_surface(tmp_path, path):
    for rel in ('VERSION.txt', 'RELEASE_ID.txt', 'surveysync/__init__.py', 'installer/app_launcher.go',
                'installer/SurveySync.iss', 'surveysync/static/index.html', 'fieldbook_sync/static/index.html', 'BUILD_MANIFEST.json'):
        dest=tmp_path/rel; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/rel, dest)
    target=tmp_path/path
    target.write_text(target.read_text(encoding='utf-8').replace((ROOT/'VERSION.txt').read_text(encoding='utf-8').strip(), '0.0.0'), encoding='utf-8')
    with pytest.raises(ValueError):
        stamp.validate(tmp_path)


def test_gate_rejects_stale_desktop_panel_cache_key(tmp_path):
    for rel in ('VERSION.txt', 'RELEASE_ID.txt', 'surveysync/__init__.py', 'installer/app_launcher.go',
                'installer/SurveySync.iss', 'surveysync/static/index.html', 'fieldbook_sync/static/index.html', 'BUILD_MANIFEST.json'):
        dest=tmp_path/rel; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/rel, dest)
    target=tmp_path/'surveysync/static/index.html'
    identity=(ROOT/'RELEASE_ID.txt').read_text(encoding='utf-8').strip()
    target.write_text(target.read_text(encoding='utf-8').replace(
        'desktop_workflows.js?v='+identity, 'desktop_workflows.js?v=stale'), encoding='utf-8')
    with pytest.raises(ValueError, match='cache identity'):
        stamp.validate(tmp_path)


def test_about_and_update_prompts_display_full_build_identity():
    js = (ROOT/'surveysync/static/app.js').read_text(encoding='utf-8')
    about = js.split('function openAboutSurveySync()', 1)[1].split('function openGlobalFeedbackWizard', 1)[0]
    assert 'releaseLabel(releaseNotesData)' in about
    assert '${info.release_id||info.version}' in js
    assert '${d.current_release_id||d.current_version}' in js


def test_status_and_release_notes_share_identity():
    from fastapi.testclient import TestClient
    from fieldbook_sync.app import app
    with TestClient(app) as client:
        notes=client.get('/api/v9/release-notes').json()
        status=client.get('/api/v9/status').json()
    assert notes['release_id'] == status['release_id'] == stamp.validate()['release_id']
