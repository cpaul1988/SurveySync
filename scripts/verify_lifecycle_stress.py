"""Repeated installed-native lifecycle acceptance on disposable Windows runners.

No retries convert a failing cycle to success. API exit intentionally includes
requests made as soon as the local service is ready, before the WebView has
necessarily finished loading. Normal WM_CLOSE exercises the window-close path.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request

import psutil
from pywinauto import Desktop

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'lifecycle-evidence'
BASE = 'http://127.0.0.1:8765'


def request(path, data=None):
    req = urllib.request.Request(BASE + path,
        data=None if data is None else json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def service_open():
    with socket.socket() as sock:
        sock.settimeout(.2)
        return sock.connect_ex(('127.0.0.1', 8765)) == 0


def snapshot(project):
    for file in [*project.rglob('*.sqlite'), *project.rglob('*.sqlite3'), *project.rglob('*.db')]:
        with sqlite3.connect(str(file)) as conn:
            if conn.execute("SELECT name FROM sqlite_master WHERE name='canonical_points'").fetchone():
                return [list(row) for row in conn.execute(
                    'SELECT point_id,northing,easting,elevation,description FROM canonical_points ORDER BY point_id')]
    raise AssertionError('Canonical database not found')


def owned_windows(process):
    ids = [process.pid] + [p.pid for p in psutil.Process(process.pid).children(recursive=True)]
    return [window for pid in ids for window in Desktop(backend='win32').windows(
        process=pid, title_re=r'SurveySync.*', visible_only=True)]


def main():
    assert sys.platform == 'win32' and os.environ.get('GITHUB_ACTIONS') == 'true'
    temp = Path(os.environ['RUNNER_TEMP']).resolve()
    install = Path(os.environ['SS_REPAIR_INSTALL']).resolve()
    assert install.is_relative_to(temp) and (install/'SurveySync.exe').is_file()
    cycles = int(os.environ.get('SS_LIFECYCLE_CYCLES', '24'))
    assert 6 <= cycles <= 100
    assert not service_open(), 'Refusing to touch a pre-existing local service'
    OUT.mkdir(exist_ok=True)
    state = temp/'SurveySyncLifecycleStress'
    state.mkdir(exist_ok=False)
    config = state/'config'
    hook = state/'hook'; hook.mkdir()
    child = (install/'.venv/Scripts/python.exe').resolve()
    hook_code = ("from pathlib import Path\nimport sys, os, faulthandler\n"
        f"if Path(sys.executable).resolve() == Path({str(child)!r}):\n"
        "    _ss_trace = open(os.environ['SS_LIFECYCLE_TRACE'], 'a', encoding='utf-8')\n"
        "    faulthandler.enable(file=_ss_trace)\n"
        "    faulthandler.dump_traceback_later(8, repeat=True, file=_ss_trace)\n")
    compile(hook_code, 'sitecustomize.py', 'exec')
    (hook/'sitecustomize.py').write_text(hook_code, encoding='utf-8')
    env = dict(os.environ, PYTHONPATH=str(hook), SURVEYSYNC_CONFIG_ROOT=str(config),
        SURVEYSYNC_FIELD_ROOT=str(state/'field'), WEBVIEW2_USER_DATA_FOLDER=str(state/'webview'))
    report = {'status': 'FAIL', 'cycles': [], 'requested_cycles': cycles,
        'baseline_installer': os.environ.get('SS_INSTALLER_SHA256', ''),
        'expected_release_id': (install/'RELEASE_ID.txt').read_text(encoding='utf-8-sig').strip()}
    projects = []; preserved = {}; source = state/'source.csv'
    source.write_text('PointID,Northing,Easting,Elevation,Code\n001A,1000,2000,10,CP\n001B,1001,2001,11,CP\n001C,1002,2002,12,CP\n', encoding='utf-8')
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    process = None
    try:
        for index in range(cycles):
            mode = ('project-switch', 'early-api-exit', 'native-window-close')[index % 3]
            record = {'cycle': index + 1, 'mode': mode, 'status': 'FAIL'}
            report['cycles'].append(record)
            assert not service_open(), 'Previous disposable process did not stop'
            env['SS_LIFECYCLE_TRACE'] = str(OUT/f'cycle-{index+1:02d}-stacks.log')
            started = time.monotonic()
            process = subprocess.Popen([str(install/'SurveySync.exe')], cwd=install, env=env)
            try:
                deadline = started + 90
                while time.monotonic() < deadline:
                    assert process.poll() is None, f'Launcher exited during startup: {process.returncode}'
                    try:
                        release = request('/api/v9/release-notes')
                        break
                    except (OSError, ValueError):
                        time.sleep(.1)
                else:
                    raise TimeoutError('Native service did not start')
                assert release['release_id'] == report['expected_release_id'], release
                record['startup_seconds'] = round(time.monotonic() - started, 3)
                if not projects:
                    for name in ('LifecycleA', 'LifecycleB'):
                        request('/api/v9/project/create', {'parent_folder': str(state/'projects'), 'name': name, 'crs': 'EPSG:2278'})
                        project = next(path.parent for path in (state/'projects').rglob('survey_sync_project.json')
                            if json.loads(path.read_text(encoding='utf-8'))['name'] == name)
                        request('/api/v9/points/import', {'file_path': str(source)})
                        projects.append(project); preserved[str(project)] = snapshot(project)
                if mode == 'project-switch':
                    for project in [projects[0], projects[1], projects[0], projects[1], projects[0]]:
                        request('/api/v9/project/open', {'path': str(project)})
                    time.sleep((0, .3, 1.5, 3)[(index//3) % 4])
                elif mode == 'native-window-close':
                    deadline = time.monotonic() + 25
                    while time.monotonic() < deadline:
                        windows = owned_windows(process)
                        if len(windows) == 1:
                            break
                        assert len(windows) < 2, 'Ambiguous native window selection'
                        time.sleep(.1)
                    else:
                        raise TimeoutError('Native window did not appear')
                    time.sleep((0, .2, 1, 2)[(index//3) % 4])
                before_exit = time.monotonic()
                if mode == 'native-window-close':
                    windows[0].post_message(0x0010)
                else:
                    record['exit_reply'] = request('/api/application/exit', {})
                process.wait(timeout=max(.01, 15 - (time.monotonic()-before_exit)))
                record['exit_seconds'] = round(time.monotonic()-before_exit, 3)
                assert process.returncode == 0, f'Native launcher exit code {process.returncode}'
                assert not service_open(), 'API still running after launcher exit'
                session = json.loads((config/'support/session_state.json').read_text(encoding='utf-8'))
                assert session['active'] is False and session['clean_exit'] is True, session
                for project in projects:
                    assert snapshot(project) == preserved[str(project)], 'Canonical points changed'
                assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
                record.update(status='PASS', api_closed=True, clean_exit=True, source_points_preserved=True)
            except Exception as exc:
                record['failure'] = f'{type(exc).__name__}: {exc}'
                record['api_open_at_failure'] = service_open()
                if process.poll() is None:
                    try:
                        record['processes'] = [p.as_dict(attrs=['pid', 'name', 'cmdline'])
                            for p in psutil.Process(process.pid).children(recursive=True)]
                        for number, window in enumerate(owned_windows(process)):
                            window.capture_as_image().save(OUT/f'cycle-{index+1:02d}-window-{number}.png')
                    except (psutil.Error, OSError):
                        pass
            finally:
                if process.poll() is None:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                        check=False, capture_output=True)
                process = None
                print(json.dumps(record), flush=True)
                (OUT/'lifecycle-results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                time.sleep(.3)
        failed = [row for row in report['cycles'] if row['status'] != 'PASS']
        assert not failed, f'{len(failed)}/{cycles} lifecycle cycles failed; retained all evidence'
        report['status'] = 'PASS'
    finally:
        if process is not None and process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], check=False)
        for file in config.rglob('*.log'):
            shutil.copyfile(file, OUT/str(file.relative_to(config)).replace('\\', '_').replace('/', '_'))
        (OUT/'lifecycle-results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
