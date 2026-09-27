"""Real installed WebView2 controls and Windows file dialog; no mocked bridge.

Debugging is enabled only in the disposable child process. Nothing is changed in
user settings, production code, provider credentials or published update feeds.
"""
from __future__ import annotations
import csv
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import Error, expect, sync_playwright
import psutil
from pywinauto import Desktop
from pywinauto.keyboard import send_keys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'repair-evidence'
BASE = 'http://127.0.0.1:8765'
CDP_PORT = 18770


def open_port(port):
    with socket.socket() as sock:
        sock.settimeout(.2)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def request(path, data):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def owned_dialog(process):
    deadline = time.monotonic() + 20
    desktop = Desktop(backend='win32')
    while time.monotonic() < deadline:
        children = psutil.Process(process.pid).children(recursive=True)
        matches = []
        for child in children:
            matches.extend(desktop.windows(class_name='#32770', process=child.pid,
                                            visible_only=True, enabled_only=True))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise AssertionError('Multiple owned dialogs; refusing ambiguous input')
        time.sleep(.2)
    raise TimeoutError('The real Windows file picker did not appear')


def main():
    assert sys.platform == 'win32'
    install = Path(os.environ['SS_REPAIR_INSTALL']).resolve()
    temp = Path(os.environ['RUNNER_TEMP']).resolve()
    assert install.is_relative_to(temp) and (install / 'SurveySync.exe').is_file()
    assert not open_port(8765) and not open_port(CDP_PORT)
    state = temp / 'native-controls-state'
    state.mkdir(exist_ok=False)
    sample = state / 'point-ranges.csv'
    sample.write_text('PointID,Northing,Easting,Elevation,Code\n1001,1000,2000,10,CP\n1005,1001,2001,11,CP\n1007,1002,2002,12,CP\n', encoding='utf-8')
    before = sample.read_bytes()
    env = dict(os.environ, SURVEYSYNC_CONFIG_ROOT=str(state / 'config'),
               SURVEYSYNC_FIELD_ROOT=str(state / 'field'),
               WEBVIEW2_USER_DATA_FOLDER=str(state / 'webview'),
               WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={CDP_PORT} --remote-debugging-address=127.0.0.1')
    OUT.mkdir(exist_ok=True)
    result = {'status': 'FAIL', 'checks': [], 'errors': []}
    process = subprocess.Popen([str(install / 'SurveySync.exe')], cwd=install, env=env)
    try:
        with sync_playwright() as pw:
            deadline = time.monotonic() + 90
            while not open_port(CDP_PORT):
                assert process.poll() is None, 'Installed native process exited during startup'
                if time.monotonic() > deadline:
                    raise TimeoutError('Installed WebView2 did not expose test-only CDP port')
                time.sleep(.25)
            browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{CDP_PORT}')
            page = None
            while page is None and time.monotonic() < deadline:
                page = next((p for c in browser.contexts for p in c.pages if p.url.startswith(BASE)), None)
                if page is None:
                    time.sleep(.2)
            assert page is not None, 'Production application page was not created'
            page.on('pageerror', lambda error: result['errors'].append(str(error)))
            try:
                page.wait_for_function("typeof window.pywebview?.api?.choose_file === 'function'", timeout=20000)
                expect(page.locator('#productSplash')).to_be_hidden(timeout=20000)
                expect(page.locator('#releaseDone')).to_be_visible()
                page.locator('#releaseDone').click()
                request('/api/v9/project/create', {'parent_folder': str(state / 'projects'),
                        'name': 'NativeControlQA', 'crs': 'EPSG:2278'})
                page.reload(wait_until='domcontentloaded')
                expect(page.locator('#productSplash')).to_be_hidden(timeout=15000)
                page.locator('.module-tab[data-module="ReportSync"]').click()
                page.locator('#moduleNav .module-nav-btn').filter(has_text=re.compile('^.*Point Ranges.*$')).click()
                page.locator('#rangeSource').select_option('file')
                page.locator('#rangeBrowse').click()
                dialog = owned_dialog(process)
                result['dialog_title'] = dialog.window_text()
                dialog.capture_as_image().save(OUT / 'native-file-picker.png')
                dialog.set_focus()
                dialog.type_keys('%n')
                send_keys(str(sample), with_spaces=True, pause=.005)
                dialog.type_keys('{ENTER}')
                expect(page.locator('#rangePath')).to_have_value(str(sample), timeout=15000)
                result['checks'].append('Browse opened a real Windows dialog and returned the chosen file')
                page.locator('#rangeMinCapacity').fill('2')
                with page.expect_response(lambda r: r.url.endswith('/api/v9/reports/point-ranges') and r.request.method == 'POST') as response:
                    page.locator('#rangeRun').click()
                reply = response.value
                assert reply.ok, reply.text()
                data = reply.json()
                assert data['used_count'] == 3, data
                for kind in ('csv', 'txt', 'xlsx'):
                    output = Path(data['report_paths'][kind])
                    assert output.is_relative_to(state) and output.stat().st_size > 0
                with Path(data['report_paths']['csv']).open(encoding='utf-8-sig', newline='') as stream:
                    assert len(list(csv.reader(stream))) >= 2
                assert sample.read_bytes() == before
                expect(page.locator('#rangeResult')).to_contain_text('3 occupied PointIDs reviewed')
                page.screenshot(path=str(OUT / 'native-point-ranges.png'))
                result['checks'].append('Real PointID file generated CSV/TXT/XLSX reports without altering input')
                page.locator('#rangeBrowse').click()
                cancel_dialog = owned_dialog(process)
                cancel_dialog.type_keys('{ESC}')
                deadline = time.monotonic() + 10
                while cancel_dialog.is_visible() and time.monotonic() < deadline:
                    time.sleep(.1)
                assert not cancel_dialog.is_visible(), 'Cancelled picker remained open'
                expect(page.locator('#rangePath')).to_have_value(str(sample))
                result['checks'].append('Cancelling the native picker preserved the selected path')
                assert not result['errors'], result['errors']
                page.locator('[data-menu="fileMenu"]').click()
                start = time.monotonic()
                try:
                    page.locator('#fileMenu [data-command="exit-app"]').click()
                except Error as exc:
                    if not any(text in str(exc).lower() for text in ('closed', 'disconnected')):
                        raise
                process.wait(timeout=15)
                assert process.returncode == 0 and not open_port(8765)
                result['checks'].append('Real File -> Exit shut down the native process and API')
                result.update(status='PASS', exit_seconds=round(time.monotonic()-start, 3))
                # Do not close the browser before verifying exit: that would bypass File -> Exit.
            except Exception:
                try:
                    page.screenshot(path=str(OUT / 'native-controls-failure.png'))
                except Exception:
                    pass
                raise
    finally:
        if process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], check=False)
        (OUT / 'native-controls-results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
