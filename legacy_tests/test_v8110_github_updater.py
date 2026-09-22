from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "fieldbook_sync" / "app.py").read_text(encoding="utf-8")
JS = (ROOT / "fieldbook_sync" / "static" / "app.js").read_text(encoding="utf-8")
PROVISION = (ROOT / "installer" / "provision_runtime.ps1").read_text(encoding="utf-8")
BUILD = (ROOT / "Build_Setup_EXE.bat").read_text(encoding="utf-8")


def test_github_is_the_stable_update_default():
    assert 'UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/cpaul1988/FieldBookSync/main/update.json"' in APP
    assert 'UPDATE_RELEASES_URL = "https://github.com/cpaul1988/FieldBookSync/releases"' in APP
    assert 'update_provider = "github"' in PROVISION
    assert 'github_manifest' in PROVISION


def test_legacy_drive_overrides_are_migrated_in_memory():
    assert '_is_legacy_drive_url' in APP
    assert 'legacy_file_id' in APP
    assert '"drive" in legacy_mode' in APP


def test_update_download_rejects_preview_pages_and_non_exes():
    assert '"text/html" in content_type' in APP
    assert '"application/json" in content_type' in APP
    assert 'chunk[:2] != b"MZ"' in APP
    assert 'downloaded != expected_size' in APP
    assert 'actual_hash != expected_hash' in APP


def test_manifest_builder_emits_direct_github_asset_url_and_size():
    assert "releases/download/v8.1.21/FieldBookSync_Setup_8.1.21.exe" in BUILD
    assert "size_bytes=[int64]'%SIZE%'" in BUILD
    assert "channel='test-candidate'" in BUILD


def test_update_ui_calls_out_github_source():
    assert 'Checking the configured FieldBook Sync update channel' in JS
    assert "'GitHub':'Custom HTTPS'" in JS
    assert 'Open Releases' in JS
