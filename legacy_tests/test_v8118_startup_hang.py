from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = (ROOT / "desktop.py").read_text(encoding="utf-8")
APP = (ROOT / "fieldbook_sync/app.py").read_text(encoding="utf-8")
JS = (ROOT / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
REQ = (ROOT / "requirements.txt").read_text(encoding="utf-8")


def test_v8118_does_not_expose_bridge_object_recursively():
    assert "js_api=bridge" not in DESKTOP
    assert "window.expose(" in DESKTOP
    assert "bridge._window = window" in DESKTOP
    assert "bridge._shutdown_callback = request_native_shutdown" in DESKTOP
    assert "self.window" not in DESKTOP
    assert "self.shutdown_callback" not in DESKTOP


def test_v8118_exposes_only_intended_native_functions():
    expose = DESKTOP.split("window.expose(", 1)[1].split(")", 1)[0]
    for name in (
        "bridge.exit_app",
        "bridge.choose_folder",
        "bridge.choose_arcgis_project",
        "bridge.choose_aprx",
        "bridge.reveal_folder",
    ):
        assert name in expose


def test_v8118_forces_edge_webview2_on_windows_and_logs_lifecycle():
    assert 'gui="edgechromium" if sys.platform == "win32" else None' in DESKTOP
    assert "webview_shown=" in DESKTOP
    assert "webview_loaded=" in DESKTOP


def test_v8118_heavy_probes_wait_for_explicit_ui_ready_signal():
    assert '@app.post("/api/startup/ready")' in APP
    assert "start_deferred_startup_checks()" in APP
    assert "target=_deferred_startup_checks" in APP
    # No legacy import-time direct start of the probe worker.
    assert 'threading.Thread(target=_deferred_startup_checks' not in APP
    assert "setTimeout(()=>signalStartupReady(),150)" in JS


def test_v8118_release_note_continue_yields_paint_frames():
    assert "return await new Promise(resolve=>" in JS
    assert "button.textContent='Opening…'" in JS
    assert JS.count("requestAnimationFrame(") >= 2
    assert "hideStartupSplash(true)" in JS


def test_v8118_pins_tested_pywebview_and_versions_consistently():
    assert "pywebview==6.2.1" in REQ
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == "8.1.21"
    assert 'APP_NAME = "FieldBook Sync v8.1.21"' in APP
