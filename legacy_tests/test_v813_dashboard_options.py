from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'fieldbook_sync' / 'static' / 'index.html').read_text(encoding='utf-8')
JS = (ROOT / 'fieldbook_sync' / 'static' / 'app.js').read_text(encoding='utf-8')
SETUP = (ROOT / 'installer' / 'setup_ui.ps1').read_text(encoding='utf-8')


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_v813_dashboard_is_the_upgrade_startup_default():
    assert "const UI_PREFS_MIGRATION_KEY='fbs-ui-prefs-v813-dashboard-default';" in JS
    assert "p.restoreWorkspace=false;" in JS
    assert "p.startPage='dashboard';" in JS
    assert "localStorage.removeItem('fbs-last-workspace');" in JS
    assert "$('#prefRestoreWorkspace').checked=p.restoreWorkspace===true" in JS
    assert '<input id="prefRestoreWorkspace" type="checkbox"/>' in INDEX
    assert '<option value="dashboard">Dashboard</option>' in INDEX


def test_v813_top_options_menu_does_not_list_themes():
    menu = _between(INDEX, '<div id="optionsMenu"', '<div id="helpMenu"')
    assert 'data-command="options"' in menu
    assert 'data-theme-select=' not in menu
    assert 'FieldBook Classic' not in menu


def test_v813_theme_gallery_remains_inside_options_workspace():
    options = _between(INDEX, '<section id="tab-options"', '<section id="tab-help"')
    assert 'id="themeCards"' in options
    assert 'data-theme-choice="classic"' in options
    assert 'data-theme-choice="carbon"' in options
    assert 'data-theme-choice="edsidark"' in options


def test_v813_installer_header_is_ascii_safe():
    assert 'SETUP  |  v$Version' in SETUP
    assert '•' not in SETUP
    assert 'â€¢' not in SETUP
