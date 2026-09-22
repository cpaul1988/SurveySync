from pathlib import Path
import hashlib

ROOT=Path(__file__).resolve().parents[1]
INDEX=(ROOT/'fieldbook_sync/static/index.html').read_text(encoding='utf-8')
JS=(ROOT/'fieldbook_sync/static/app.js').read_text(encoding='utf-8')
CSS=(ROOT/'fieldbook_sync/static/styles.css').read_text(encoding='utf-8')

def test_v8_desktop_menu_labels_present():
    for label in ['File','Home','Edit','View','Data','Review','Tools','Options','Help']:
        assert f'>{label}</button>' in INDEX

def test_v8_six_product_themes_present():
    for key in ['classic','edsi','slate','midnight','lightpro','contrast']:
        assert f"{key}:{{label:" in JS
        assert f'data-theme-choice="{key}"' in INDEX

def test_v8_options_and_help_workspaces_present():
    assert 'id="tab-options"' in INDEX
    assert 'id="tab-help"' in INDEX
    assert 'id="activeThemeChip"' in INDEX

def test_v8_status_bar_present():
    for item in ['statusProject','statusEngine','statusResults','statusTheme','statusAutosave']:
        assert f'id="{item}"' in INDEX

def test_edsi_official_assets_are_packaged_and_runtime_mark_is_exact_copy():
    official=ROOT/'branding/EDSI_Official/ESDI-Logo_try.png'
    runtime=ROOT/'fieldbook_sync/static/edsi_mark.png'
    assert official.exists() and runtime.exists()
    assert hashlib.sha256(official.read_bytes()).digest()==hashlib.sha256(runtime.read_bytes()).digest()

def test_v8_version_metadata():
    assert '8.1.21' in (ROOT/'VERSION.txt').read_text(encoding='utf-8')
    assert '<title>FieldBook Sync v8.1.21</title>' in INDEX

def test_v8_ui_preferences_and_hotfix_watchdog_present():
    assert 'fbs-ui-prefs' in JS
    assert 'fbs-product-theme' in JS
    assert '6000' in JS and 'hideStartupSplash' in JS
    assert 'force-reduced-motion' in CSS



def test_v802_paddle_venv_version_preflight(tmp_path):
    from fieldbook_sync.ocr_local import _venv_version_from_cfg
    env = tmp_path / '.paddleenv'
    env.mkdir()
    (env / 'pyvenv.cfg').write_text('home = C:\\Python314\nversion = 3.14.1\n', encoding='utf-8')
    assert _venv_version_from_cfg(env) == (3, 14)


def test_v802_windows_launcher_avoids_generic_latest_python():
    text = (ROOT / 'run_windows.bat').read_text(encoding='utf-8').lower()
    assert 'py -3.13' in text
    assert 'py -3.12' in text
    assert 'py -3.11' in text
    assert 'py -3 bootstrap_windows.py' not in text


def test_v804_excel_code_import_ui_and_cache_busting_present():
    assert 'accept=".csv,.xlsx,.xlsm,.xltx,.xltm"' in INDEX
    assert 'Import Code Profile (CSV / Excel)' in INDEX
    assert '/api/profiles/import' in JS
    assert 'styles.css?v=8.1.21' in INDEX
    assert 'app.js?v=8.1.21' in INDEX


def test_v803_excel_profile_import_round_trip():
    import io
    from openpyxl import Workbook
    from fieldbook_sync.profiles import import_profile_excel
    wb = Workbook()
    ws = wb.active
    ws.title = 'Client Codes'
    ws.append(['Client code list'])
    ws.append(['Survey Code', 'Description', 'Include', 'Match Mode'])
    ws.append(['STM MH', 'Storm Manhole', 'Yes', 'Exact'])
    ws.append(['GI', 'Grate Inlet', 1, 'Starts With'])
    raw = io.BytesIO()
    wb.save(raw)
    profile = import_profile_excel('Excel Test', 'Client', raw.getvalue())
    assert [r.code for r in profile.codes] == ['STM MH', 'GI']
    assert profile.codes[1].match.value == 'starts_with'


def test_v804_visible_import_progress_and_file_lists_present():
    for item in ['surveyImportProgress','fieldbookImportProgress','surveyImportedList','fieldbookImportedList','jobDetail']:
        assert f'id="{item}"' in INDEX
    assert '/api/import-job' in JS
    assert 'renderClientUpload' in JS
    assert 'renderImportedFiles' in JS
    assert 'Imported files' in INDEX


def test_v804_hybrid_analysis_progress_is_staged_not_page_max():
    assert "provider==='hybrid'" in JS
    assert "stage==='ocr'" in JS
    assert "stage==='interpret'" in JS
    assert '45+50*' in JS


def test_v804_import_file_metadata_defaults_are_backward_compatible():
    from fieldbook_sync.models import AppState
    state=AppState()
    assert state.survey_files == []
    assert state.fieldbook_files == []


def test_v806_paddle_bridge_streams_page_events_and_uses_manifest():
    bridge=(ROOT/'paddle_bridge.py').read_text(encoding='utf-8')
    ocr=(ROOT/'fieldbook_sync/ocr_local.py').read_text(encoding='utf-8')
    assert 'page_start' in bridge and 'page_done' in bridge
    assert 'flush=True' in bridge
    assert '--manifest' in bridge
    assert 'subprocess.Popen' in ocr
    assert 'progress_callback' in ocr
    assert 'cancel_check' in ocr
    assert 'PaddleCancelled' in ocr


def test_v806_analysis_uses_streamed_paddle_progress():
    app=(ROOT/'fieldbook_sync/app.py').read_text(encoding='utf-8')
    assert 'progress_callback=_ocr_progress' in app
    assert 'cancel_check=_ocr_should_stop' in app
    assert 'Cancelling analysis and stopping the active OCR/AI worker' in app


def test_v806_paddle_transport_is_unicode_safe():
    bridge=(ROOT/'paddle_bridge.py').read_text(encoding='utf-8')
    ocr=(ROOT/'fieldbook_sync/ocr_local.py').read_text(encoding='utf-8')
    assert 'ensure_ascii=True' in bridge
    assert 'reconfigure(encoding="utf-8"' in bridge
    assert 'env["PYTHONUTF8"] = "1"' in ocr
    assert 'env["PYTHONIOENCODING"] = "utf-8"' in ocr
    assert 'encoding="utf-8"' in ocr


def test_v806_edsi_logo_uses_contain_and_wide_slot():
    assert 'html[data-product-theme="edsi"] .brand-mark' in CSS
    assert 'html[data-product-theme="edsidark"] .brand-mark' in CSS
    assert 'html[data-product-theme="edsilight"] .brand-mark' in CSS
    assert 'width:76px;height:42px;flex:0 0 76px' in CSS
    assert 'object-fit:contain' in CSS
    assert 'object-position:left center' in CSS


def test_v806_unicode_bridge_round_trip_under_legacy_windows_codepage():
    import json
    import os
    import subprocess
    import sys
    env=os.environ.copy()
    env['PYTHONIOENCODING']='cp1252'
    env['PYTHONPATH']=str(ROOT)
    code=(
        "import paddle_bridge; "
        "paddle_bridge.emit({'event':'page_done','result':{'text':'区 café Ω'}})"
    )
    proc=subprocess.run([sys.executable,'-c',code],capture_output=True,env=env,check=True)
    line=proc.stdout.decode('utf-8').strip()
    assert line.startswith('FBS_EVENT|')
    payload=json.loads(line.split('|',1)[1])
    assert payload['result']['text']=='区 café Ω'
