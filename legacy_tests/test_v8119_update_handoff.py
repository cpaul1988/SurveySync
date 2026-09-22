from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = (ROOT / 'desktop.py').read_text(encoding='utf-8')
APP_JS = (ROOT / 'fieldbook_sync' / 'static' / 'app.js').read_text(encoding='utf-8')
APP_PY = (ROOT / 'fieldbook_sync' / 'app.py').read_text(encoding='utf-8')


def test_native_desktop_watches_application_shutdown_event():
    assert 'def watch_application_shutdown()' in DESKTOP
    assert 'runtime.shutdown_event.wait()' in DESKTOP
    assert 'name="FBS-native-shutdown-watch"' in DESKTOP
    assert 'window.destroy()' in DESKTOP


def test_update_button_explicitly_requests_native_exit_after_staging():
    anchor = "api('/api/update/download-install',{method:'POST',timeoutMs:0})"
    assert anchor in APP_JS
    segment = APP_JS[APP_JS.index(anchor):APP_JS.index(anchor) + 1600]
    assert "window.pywebview?.api?.exit_app" in segment
    assert "window.pywebview.api.exit_app()" in segment
    assert "fetch('/api/application/exit',{method:'POST',keepalive:true})" in segment


def test_server_logs_verified_update_handoff_before_shutdown():
    assert 'Verified update v%s staged at %s; requesting native shutdown handoff' in APP_PY
    assert 'request_application_shutdown(f"Updating FieldBook Sync to v{latest}."' in APP_PY


def test_version_is_8119():
    assert (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() == '8.1.21'
