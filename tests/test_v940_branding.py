from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "surveysync" / "static"


def test_v940_brand_palette_and_marks_are_wired():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    field_index = (ROOT / "fieldbook_sync" / "static" / "index.html").read_text(encoding="utf-8")
    field_app = (ROOT / "fieldbook_sync" / "static" / "app.js").read_text(encoding="utf-8")

    for token in ("#0F203C", "#C19D65", "#F6F4EE", "#1A2433"):
        assert token in css

    assert "/surveysync-static/surveysync_globe.svg" in index
    assert "surveysync_monogram.svg" not in index
    assert "surveysync_monogram.svg" not in app
    assert "surveysync_monogram.svg" not in field_index
    assert "/surveysync-static/favicon.ico" not in index
    assert "/surveysync-static/favicon.ico" not in app
    assert "/surveysync-static/favicon.ico" not in field_index
    assert "workflow-icons/11-fieldsync.svg" in field_index
    assert "workflow-icons/11-fieldsync.svg" in field_app


def test_v940_workflow_icon_library_complete():
    icon_dir = STATIC / "workflow-icons"
    expected = {
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
    }
    assert {p.name for p in icon_dir.glob("*.svg")} == expected
    for name in expected:
        content = (icon_dir / name).read_text(encoding="utf-8")
        assert "<svg" in content
        assert "#0F203C" in content
        assert "#C19D65" in content


def test_v940_windows_brand_icon_generated_before_build():
    build = (ROOT / "Build_SurveySync.ps1").read_text(encoding="utf-8")
    generator = (ROOT / "scripts" / "generate_surveysync_icon.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "installer" / "SurveySync.iss").read_text(encoding="utf-8")

    assert "generate_surveysync_icon.ps1" in build
    assert "16,24,32,48,64,128,256" in generator
    assert "SurveySync_globe_512.png" in generator
    assert "DrawString('S'" not in generator
    assert r"SetupIconFile=..\branding\SurveySync.ico" in installer
    assert r'IconFilename: "{app}\branding\SurveySync.ico"' in installer
