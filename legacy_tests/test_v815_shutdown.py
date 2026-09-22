from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / 'fieldbook_sync/static/app.js').read_text(encoding='utf-8')
APP_PY = (ROOT / 'fieldbook_sync/app.py').read_text(encoding='utf-8')
DESKTOP = (ROOT / 'desktop.py').read_text(encoding='utf-8')


def test_file_exit_uses_real_shutdown_path_not_window_close():
    assert 'async function exitApplication()' in APP_JS
    assert 'window.pywebview?.api?.exit_app' in APP_JS
    assert "/api/application/exit" in APP_JS
    assert "case'exit-app':return exitApplication();" in APP_JS
    assert "case'exit-app':try{window.close()}" not in APP_JS


def test_backend_exposes_browser_fallback_shutdown_endpoint():
    assert '@app.post("/api/application/exit")' in APP_PY
    assert 'request_application_shutdown' in APP_PY
    assert 'runtime.shutdown_event' in APP_PY
    assert 'status="INTERRUPTED"' in APP_PY


def test_native_bridge_can_close_application():
    assert 'def exit_app(self) -> bool:' in DESKTOP
    assert 'self._shutdown_callback' in DESKTOP
    assert 'request_application_shutdown' in DESKTOP
    assert 'window.destroy()' in DESKTOP


def test_native_shutdown_handles_lingering_non_daemon_ai_threads():
    assert 'not t.daemon' in DESKTOP
    assert 'os._exit(0)' in DESKTOP
    assert 'finalize_application_shutdown()' in DESKTOP


def test_browser_server_observes_shutdown_event():
    assert 'runtime.shutdown_event.wait()' in APP_PY
    assert 'server.should_exit = True' in APP_PY
    assert 'server.run()' in APP_PY
