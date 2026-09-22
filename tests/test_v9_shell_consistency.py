from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]

def test_fieldbook_has_no_legacy_startup_splash():
    html=(ROOT/'fieldbook_sync/static/index.html').read_text(encoding='utf-8')
    assert 'id="startupSplash"' in html
    assert 'style="display:none"' in html
    assert 'FIELD BOOK SYNC</div>' not in html

def test_fieldbook_ribbon_matches_surveysync_global_labels():
    main=(ROOT/'surveysync/static/index.html').read_text(encoding='utf-8')
    field=(ROOT/'fieldbook_sync/static/index.html').read_text(encoding='utf-8')
    labels=['File','Home','Edit','View','Data','Tools','Options','Help']
    for label in labels:
        assert f'>{label}</button>' in main
        assert f'>{label}</button>' in field
    assert 'data-menu="reviewMenu"' not in field
    for module in ['Home','FieldBookSync','ControlSync','UtilitySync','TopoSync','COGOSync','BoundarySync','GISSync','ReportSync','QASync','CrewSync']:
        assert module in main and module in field

def test_main_home_owns_release_notes_and_feedback_wizard():
    html=(ROOT/'surveysync/static/index.html').read_text(encoding='utf-8')
    js=(ROOT/'surveysync/static/app.js').read_text(encoding='utf-8')
    assert 'id="whatsNewCard"' in html
    assert 'Open Feedback Wizard' in html
    assert "location.href=`/fieldbook?${q.toString()}`" in js

def test_main_feedback_endpoint_does_not_require_project():
    py=(ROOT/'surveysync/router.py').read_text(encoding='utf-8')
    m=re.search(r'@router\.post\("/api/v9/feedback"\)(.*?)(?=\n# Restore last project)',py,re.S)
    assert m
    assert 'require_project()' not in m.group(1)
    assert 'config_store.root / "feedback"' in m.group(1)


def test_installer_uses_surveysync_globe_brand_assets():
    from PIL import Image
    import hashlib
    iss=(ROOT/'installer/SurveySync.iss').read_text(encoding='utf-8')
    assert r'SetupIconFile=..\branding\SurveySync.ico' in iss
    assert 'WizardImageFile=wizard_large.bmp' in iss
    assert 'WizardSmallImageFile=wizard_small.bmp' in iss
    # New SurveySync icon must no longer be a byte-for-byte copy of the legacy FieldBook icon.
    new_hash=hashlib.sha256((ROOT/'branding/SurveySync.ico').read_bytes()).hexdigest()
    old_hash=hashlib.sha256((ROOT/'branding/FieldBookSync.ico').read_bytes()).hexdigest()
    assert new_hash != old_hash
    assert Image.open(ROOT/'installer/wizard_small.bmp').size == (55,55)
    assert Image.open(ROOT/'installer/wizard_large.bmp').size == (164,314)

def test_theme_preferences_have_shared_backend_and_full_shell_tokens():
    cfg=(ROOT/'surveysync/config.py').read_text(encoding='utf-8')
    router=(ROOT/'surveysync/router.py').read_text(encoding='utf-8')
    mainjs=(ROOT/'surveysync/static/app.js').read_text(encoding='utf-8')
    fieldjs=(ROOT/'fieldbook_sync/static/app.js').read_text(encoding='utf-8')
    css=(ROOT/'surveysync/static/styles.css').read_text(encoding='utf-8')
    assert 'ui_appearance: str = "system"' in cfg
    assert 'ui_theme: str = "classic"' in cfg
    assert 'ui_accent: str = "default"' in cfg
    assert '@router.post("/api/v9/config/ui")' in router
    assert "scheduleSharedUiSync()" in mainjs
    assert "scheduleSharedUiSync()" in fieldjs
    for token in ('--bg:','--panel:','--sidebar-bg:','--input:','--hover:'):
        assert token in css


def test_fieldbook_global_ribbon_spans_full_window():
    root = Path(__file__).resolve().parents[1]
    html = (root / "fieldbook_sync" / "static" / "index.html").read_text(encoding="utf-8")
    css = (root / "fieldbook_sync" / "static" / "styles.css").read_text(encoding="utf-8")
    app_at = html.index('<div class="app">')
    env_at = html.index('id="globalEnvStrip"', app_at)
    menu_at = html.index('class="desktop-menubar"', app_at)
    tabs_at = html.index('class="surveysync-module-tabs"', app_at)
    sidebar_at = html.index('class="sidebar"', app_at)
    main_at = html.index('class="main-shell"', app_at)
    assert app_at < env_at < menu_at < tabs_at < sidebar_at < main_at
    assert '.app>.desktop-menubar{grid-column:1/-1;grid-row:2' in css
    assert '.app>.surveysync-module-tabs{grid-column:1/-1;grid-row:3' in css
    assert '.app>.sidebar{grid-column:1;grid-row:4' in css
    assert '.app>.main-shell{grid-column:2;grid-row:4' in css
