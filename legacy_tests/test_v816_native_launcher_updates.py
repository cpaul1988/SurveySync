from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = (ROOT / 'installer' / 'setup_ui.ps1').read_text(encoding='utf-8')
LAUNCHER = (ROOT / 'installer' / 'app_launcher.go').read_text(encoding='utf-8')
APP = (ROOT / 'fieldbook_sync' / 'app.py').read_text(encoding='utf-8')
JS = (ROOT / 'fieldbook_sync' / 'static' / 'app.js').read_text(encoding='utf-8')
HTML = (ROOT / 'fieldbook_sync' / 'static' / 'index.html').read_text(encoding='utf-8')
BUILD = (ROOT / 'Build_Setup_EXE.bat').read_text(encoding='utf-8')
PAYLOAD = (ROOT / 'installer' / 'build_payload.py').read_text(encoding='utf-8')


def test_native_launcher_is_built_and_installer_shortcuts_target_it():
    assert 'app_launcher.go' in BUILD
    assert '-o "..\\FieldBookSync.exe"' in BUILD
    assert "$launcher=Join-Path $InstallDir 'FieldBookSync.exe'" in SETUP
    assert "New-Shortcut (Join-Path $programs 'FieldBook Sync.lnk') $launcher ''" in SETUP
    assert "Start-Process -FilePath $launcher" in SETUP


def test_fbs_association_targets_native_launcher():
    assert "$launcher = Join-Path $InstallDir 'FieldBookSync.exe'" in SETUP
    assert "$cmd = '\"{0}\" \"%1\"' -f $launcher" in SETUP


def test_launcher_supervises_hidden_python_child_and_logs_failures():
    assert 'CleverBirdDevelopment.FieldBookSync' in LAUNCHER
    assert 'CREATE_NO_WINDOW' not in LAUNCHER  # Go constant is camel-case, not raw shell text
    assert 'createNoWindow' in LAUNCHER
    assert 'Job Object' in LAUNCHER
    assert 'jobObjectLimitKillOnJobClose' in LAUNCHER
    assert 'launcher.log' in LAUNCHER
    assert 'cmd.Wait()' in LAUNCHER


def test_payload_excludes_build_output_but_includes_root_launcher():
    assert "'output'" in PAYLOAD
    assert "Path('installer/app_launcher.go')" in PAYLOAD


def test_help_menu_exposes_update_check():
    assert 'data-command="check-updates"' in HTML
    assert "case'check-updates':return checkForUpdates();" in JS
    assert 'async function checkForUpdates()' in JS


def test_backend_update_endpoints_and_hash_verification_exist():
    assert '@app.get("/api/update/check")' in APP
    assert '@app.post("/api/update/open-folder")' in APP
    assert '@app.post("/api/update/download-install")' in APP
    assert 'hashlib.sha256()' in APP
    assert 'actual_hash != expected_hash' in APP
    assert 'UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/cpaul1988/FieldBookSync/main/update.json"' in APP
    assert 'chunk[:2] != b"MZ"' in APP
    assert 'text/html' in APP


def test_version_is_816():
    assert (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() == '8.1.21'
    assert 'APP_NAME = "FieldBook Sync v8.1.21"' in APP
