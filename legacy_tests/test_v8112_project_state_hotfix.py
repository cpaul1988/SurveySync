from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "fieldbook_sync" / "static" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "fieldbook_sync" / "static" / "index.html").read_text(encoding="utf-8")


def test_load_state_function_is_present():
    assert "async function loadState(){" in JS
    assert "state=await api('/api/state')" in JS
    assert "renderProjectMeta()" in JS
    assert "renderImportedFiles()" in JS


def test_project_rename_waits_for_state_refresh():
    assert "toast('Project renamed');await loadState()" in JS


def test_v8112_static_cache_buster():
    assert "app.js?v=8.1.21" in INDEX
