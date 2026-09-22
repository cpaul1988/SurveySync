from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'fieldbook_sync' / 'static' / 'app.js').read_text(encoding='utf-8')
INDEX = (ROOT / 'fieldbook_sync' / 'static' / 'index.html').read_text(encoding='utf-8')

def test_profile_loader_exists_and_refreshes_ui():
    assert 'async function loadProfiles(selectCurrent=true)' in APP
    assert "profiles=await api('/api/profiles')" in APP
    assert 'renderProfileList();' in APP
    assert 'updateProfileHint();' in APP

def test_profile_import_calls_defined_loader():
    assert "await loadProfiles();editProfile(selectedProfileName)" in APP

def test_version_bumped():
    assert (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() == '8.1.21'
    assert '<title>FieldBook Sync v8.1.21</title>' in INDEX
