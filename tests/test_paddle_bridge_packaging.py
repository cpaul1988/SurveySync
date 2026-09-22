from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_paddle_bridge_is_packaged_and_matches_stream_contract():
    bridge = ROOT / "paddle_bridge.py"
    assert bridge.is_file(), "paddle_bridge.py is a required installed runtime asset"
    text = bridge.read_text(encoding="utf-8")
    for token in ["FBS_EVENT|", "--manifest", "page_start", "page_done", "page_retry", "page_failed"]:
        assert token in text


def test_installer_recursively_includes_paddle_bridge():
    iss = (ROOT / "installer" / "SurveySync.iss").read_text(encoding="utf-8")
    assert 'Source: "..\\*"' in iss
    recursive_source = next(line for line in iss.splitlines() if line.strip().startswith('Source: "..\\*"'))
    assert "paddle_bridge.py" not in recursive_source


def test_automatic_mode_and_status_endpoint_gate_on_packaged_bridge():
    app = (ROOT / "fieldbook_sync" / "app.py").read_text(encoding="utf-8")
    ocr = (ROOT / "fieldbook_sync" / "ocr_local.py").read_text(encoding="utf-8")
    assert "def paddle_bridge_path" in ocr
    assert "bridge = paddle_bridge_path(app_root)" in ocr
    assert "bridge_ready = paddle_bridge_path(APP_ROOT).exists()" in app
    assert '"bridge_ready": bridge_ready' in app
    assert "Automatic will use another ready local engine" in app
