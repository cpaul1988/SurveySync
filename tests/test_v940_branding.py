from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def test_v940_brand_assets_are_wired_into_both_shells():
    main_html = (ROOT / "surveysync" / "static" / "index.html").read_text(encoding="utf-8")
    main_js = (ROOT / "surveysync" / "static" / "app.js").read_text(encoding="utf-8")
    field_html = (ROOT / "fieldbook_sync" / "static" / "index.html").read_text(encoding="utf-8")
    field_js = (ROOT / "fieldbook_sync" / "static" / "app.js").read_text(encoding="utf-8")

    assert "/surveysync-static/favicon.ico" in main_html
    assert "UNIFYING GLOBAL DATA" in main_html
    assert 'id="productSplash"' in main_html
    assert "setTimeout(dismissProductSplash,700)" in main_js
    assert "MODULE_WORKFLOW_ICONS" in main_js
    assert "surveysync_logo.jpg" not in main_js
    assert "openAboutSurveySync" in main_js

    assert "/surveysync-static/favicon.ico" in field_html
    assert "/surveysync-static/workflow-icons/11-fieldsync.svg" in field_html
    assert "icon:'/surveysync-static/workflow-icons/11-fieldsync.svg'" in field_js
    assert "icon:'/static/edsi_mark.png'" in field_js


def test_v940_workflow_icon_library_is_complete():
    icon_dir = ROOT / "surveysync" / "static" / "workflow-icons"
    expected = [
        "01-job-setup.svg",
        "02-gnss-rtk.svg",
        "03-total-station.svg",
        "04-leveling.svg",
        "05-feature-codes.svg",
        "06-stakeout.svg",
        "07-point-database.svg",
        "08-traverse.svg",
        "09-surfaces-contours.svg",
        "10-boundary-parcels.svg",
        "11-fieldsync.svg",
        "12-reports-export.svg",
    ]
    assert sorted(p.name for p in icon_dir.glob("*.svg")) == expected
    for name in expected:
        text = (icon_dir / name).read_text(encoding="utf-8")
        assert "#0F203C" in text
        assert "#C19D65" in text
        assert "#F6F4EE" in text


def test_v940_windows_icon_and_installer_branding():
    new_icon = ROOT / "branding" / "SurveySync.ico"
    old_icon = ROOT / "branding" / "FieldBookSync.ico"
    desktop = (ROOT / "desktop.py").read_text(encoding="utf-8")
    installer = (ROOT / "installer" / "SurveySync.iss").read_text(encoding="utf-8")

    assert new_icon.is_file()
    assert hashlib.sha256(new_icon.read_bytes()).hexdigest() != hashlib.sha256(old_icon.read_bytes()).hexdigest()
    assert 'window_icon = root / "branding" / "SurveySync.ico"' in desktop
    assert "icon=str(window_icon) if window_icon.exists() else None" in desktop
    assert r"SetupIconFile=..\branding\SurveySync.ico" in installer
    assert r"UninstallDisplayIcon={app}\branding\SurveySync.ico" in installer

    assert Image.open(ROOT / "installer" / "wizard_large.bmp").size == (164, 314)
    assert Image.open(ROOT / "installer" / "wizard_small.bmp").size == (55, 55)


def test_v940_palette_tokens_are_present():
    main_css = (ROOT / "surveysync" / "static" / "styles.css").read_text(encoding="utf-8")
    field_css = (ROOT / "fieldbook_sync" / "static" / "styles.css").read_text(encoding="utf-8")
    guidelines = (ROOT / "branding" / "BRAND_GUIDELINES.md").read_text(encoding="utf-8")

    for color in ("#0F203C", "#C19D65", "#F6F4EE", "#1A2433"):
        assert color in main_css or color in guidelines
    assert "--survey-menubar-bg:#0F203C" in field_css
    assert "UNIFYING GLOBAL DATA" in guidelines
