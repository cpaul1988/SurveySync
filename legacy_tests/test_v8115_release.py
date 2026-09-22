from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from fieldbook_sync.app import _recommend_ollama_model
from fieldbook_sync.global_mapper import _gms_quote, _validate_export_type, _validate_extension, output_name

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
JS = (ROOT / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
CSS = (ROOT / "fieldbook_sync/static/styles.css").read_text(encoding="utf-8")
APP = (ROOT / "fieldbook_sync/app.py").read_text(encoding="utf-8")


class ButtonParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.buttons: list[dict[str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "button":
            self.buttons.append(dict(attrs))


def test_v8115_version_and_release_notes_splash():
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == "8.1.21"
    assert 'APP_NAME = "FieldBook Sync v8.1.21"' in APP
    assert 'id="startupReleaseNotes"' in HTML
    assert "showReleaseNotesOnUpgrade" in JS
    assert "fbs-release-notes-seen" in JS
    assert '@app.get("/api/release-notes")' in APP


def test_v8115_feedback_center_is_carried_forward():
    assert '@app.get("/api/feedback/config")' in APP
    assert '@app.post("/api/feedback/open")' in APP
    assert 'data-command="feedback"' in HTML
    assert ('id="helpFeedbackBtn"' in HTML) or ('id="helpBugBtn"' in HTML and 'id="helpFeatureBtn"' in HTML)
    assert 'Copy Support Info' in HTML


def test_v8115_global_mapper_bridge_is_safe_and_visible():
    assert '@app.get("/api/global-mapper/status")' in APP
    assert '@app.post("/api/global-mapper/convert")' in APP
    assert 'data-command="global-mapper"' in HTML
    assert 'accept="*/*"' in HTML
    assert _validate_export_type("GEOJSON") == "GEOJSON"
    assert _validate_extension("dwg") == ".dwg"
    assert output_name("parcel weird?.dxf", "GEOJSON", ".geojson").endswith("_geojson.geojson")


def test_v8115_qwen3_vl_profiles_choose_compact_models():
    installed = ["qwen3-vl:2b-instruct", "qwen3-vl:4b-instruct", "qwen3-vl:8b-instruct"]
    assert _recommend_ollama_model(installed, profile="fast", vram_bytes=4 * 1024**3)[0] == "qwen3-vl:2b-instruct"
    assert _recommend_ollama_model(installed, profile="balanced", vram_bytes=8 * 1024**3)[0] == "qwen3-vl:4b-instruct"
    assert _recommend_ollama_model(installed, profile="maximum", vram_bytes=16 * 1024**3)[0] == "qwen3-vl:8b-instruct"
    assert 'value="fast">Fast — qwen3-vl:2b-instruct' in HTML
    assert 'value="balanced">Balanced — qwen3-vl:4b-instruct' in HTML
    assert 'value="maximum">Maximum Accuracy — qwen3-vl:8b-instruct' in HTML


def test_static_button_wiring_has_no_orphan_controls():
    parser = ButtonParser(); parser.feed(HTML)
    ignored_attrs = {
        "data-command", "data-tab", "data-provider", "data-theme-choice", "data-theme-select",
        "data-accent-choice", "data-appearance", "data-map-tool",
    }
    orphaned = []
    for attrs in parser.buttons:
        button_id = attrs.get("id")
        if not button_id or any(attrs.get(a) is not None for a in ignored_attrs):
            continue
        if button_id not in JS:
            orphaned.append(button_id)
    assert orphaned == []


def test_responsive_css_covers_small_windows():
    assert "@media(max-width:700px)" in CSS
    assert "@media(max-width:480px)" in CSS
    assert ".map-sidebar{grid-template-columns:1fr}" in CSS
    assert ".startup-splash.release-notes-mode" in CSS


def test_v8115_installer_and_gms_safety_hardening():
    bootstrap = (ROOT / "installer/bootstrapper_main.go").read_text(encoding="utf-8")
    assert "FieldBookSync_Setup_8_1_21_" in bootstrap
    assert "FieldBookSync_Setup_8_1_11_" not in bootstrap
    try:
        _gms_quote('bad\npath')
    except ValueError:
        pass
    else:
        raise AssertionError("line-break script injection should be rejected")
    try:
        _gms_quote('bad"path')
    except ValueError:
        pass
    else:
        raise AssertionError("quote characters should be rejected")


def test_no_id_menu_and_jump_buttons_use_shared_dispatchers():
    menu_bootstrap = (ROOT / "fieldbook_sync/static/menu_bootstrap.js").read_text(encoding="utf-8")
    assert "menu-trigger" in menu_bootstrap and "dataset.menu" in menu_bootstrap
    assert "$$('[data-jump]')" in JS and "dataset.jump" in JS
