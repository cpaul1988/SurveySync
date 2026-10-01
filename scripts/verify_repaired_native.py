"""Install acceptance: exercise real Windows launcher, data, shutdown and reopen.

Only a disposable CI installation is accepted. Never locates/kills a user's app.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

import psutil
from pywinauto import Desktop

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'repair-evidence'
BASE = 'http://127.0.0.1:8765'


def request(path, data=None):
    req = urllib.request.Request(BASE + path, data=None if data is None else json.dumps(data).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def port_open():
    with socket.socket() as sock:
        sock.settimeout(.2)
        return sock.connect_ex(('127.0.0.1',8765)) == 0


def native_window_ready(process):
    try:
        owned = psutil.Process(process.pid)
        pids = {owned.pid, *(child.pid for child in owned.children(recursive=True))}
        return any(window.process_id() in pids for window in Desktop(backend='win32').windows(
            title_re=r'SurveySync.*', visible_only=True))
    except psutil.Error:
        return False


def main():
    assert sys.platform == 'win32', 'Windows-only acceptance'
    OUT.mkdir(exist_ok=True)
    install = Path(os.environ['SS_REPAIR_INSTALL']).resolve()
    temp = Path(os.environ['RUNNER_TEMP']).resolve()
    assert install.is_relative_to(temp), 'Refusing non-disposable installation'
    assert not port_open(), 'Port 8765 in use; refusing to touch existing application'
    assert (install / 'SurveySync.exe').is_file()
    for relative in ('desktop.py','surveysync/manual_control.py','surveysync/control_selection.py',
                     'surveysync/leveling.py','fieldbook_sync/job_engine.py','surveysync/static/app.js'):
        assert hashlib.sha256((install/relative).read_bytes()).digest() == hashlib.sha256((ROOT/relative).read_bytes()).digest(), relative
    state = temp/'verified-native-state';state.mkdir(exist_ok=False)
    # Passive stack diagnostics are confined to the disposable child interpreter.
    # They do not change shutdown timing/behavior or replace the native bridge.
    hook = state/'diagnostic-hook';hook.mkdir()
    child_python = (install/'.venv/Scripts/python.exe').resolve()
    trace = OUT/'native-thread-stacks.log'
    code = ("from pathlib import Path\nimport sys, faulthandler\n"
            f"if Path(sys.executable).resolve() == Path({str(child_python)!r}):\n"
            f"    _ss_trace = open({str(trace)!r}, 'a', encoding='utf-8')\n"
            "    faulthandler.enable(file=_ss_trace)\n"
            "    faulthandler.dump_traceback_later(10, repeat=True, file=_ss_trace)\n")
    compile(code, 'sitecustomize.py', 'exec')
    (hook/'sitecustomize.py').write_text(code, encoding='utf-8')
    env = dict(os.environ, PYTHONPATH=str(hook), SURVEYSYNC_CONFIG_ROOT=str(state/'config'),
               SURVEYSYNC_FIELD_ROOT=str(state/'field'), WEBVIEW2_USER_DATA_FOLDER=str(state/'webview'))
    results = {'status':'FAIL','cycles':[], 'installer_scope':'unreleased repair candidate'}
    project_folder = None
    process = None
    attempt = {}
    try:
        for cycle in (1,2):
            attempt = {'cycle':cycle,'status':'STARTING'}
            results['cycles'].append(attempt)
            args = [str(install/'SurveySync.exe')]
            if project_folder: args.append(str(project_folder))
            process = subprocess.Popen(args, cwd=install, env=env)
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                try:
                    request('/api/v9/release-notes')
                    break
                except Exception:
                    assert process.poll() is None, 'Native launcher exited before startup'
                    time.sleep(.3)
            else: raise TimeoutError('Installed application did not become ready')
            # The HTTP service starts before WebView2 has a usable native window.
            # This acceptance exercises an established desktop session; the
            # separate lifecycle gate covers exit during early startup.
            deadline=time.monotonic()+60
            while time.monotonic()<deadline and not native_window_ready(process):
                assert process.poll() is None, 'Native launcher exited before its window appeared'
                time.sleep(.1)
            else:
                if not native_window_ready(process):
                    raise TimeoutError('Installed native window did not appear')
            if cycle==1:
                request('/api/v9/project/create', {'parent_folder':str(state/'projects'), 'name':'NativeRepairQA', 'crs':'EPSG:2278'})
                project_folder=next((state/'projects').rglob('survey_sync_project.json')).parent
                points=state/'control.csv'
                points.write_text('point_id,northing,easting,elevation,code\n100A,1000,2000,10,CP\n100B,1000.03,2000.01,10.02,CP\n100C,999.99,1999.98,9.99,CP\n', encoding="utf-8")
                request('/api/v9/points/import', {'file_path':str(points)})
            revisions=[]
            for i in range(2):
                data=request('/api/v9/control/ron-three-point', {'control_id':'200','point_ids':['100A','100B','100C'],'horizontal_tolerance':.1,'vertical_tolerance':.1})
                assert data['revision']==(cycle-1)*2+i+1
                assert [r['point_id'] for r in data['residuals']]==['100A','100B','100C']
                assert data['code']=='CP'
                assert 'Code: CP' in Path(data['deliverables']['final_control_txt']).read_text(encoding="utf-8")
                assert abs(data['residuals'][0]['dn'] - (1000-(1000+1000.03+999.99)/3)) < 1e-9
                revisions.append(data['revision'])
            attempt.update(status='EXIT_REQUESTED',revisions=revisions,launcher_pid=process.pid)
            start=time.monotonic()
            reply=request('/api/application/exit', {})
            attempt['reply']=reply
            process.wait(timeout=15)
            assert process.returncode==0, process.returncode
            assert not port_open(), 'Local API remains running after native exit'
            attempt.update(status='PASS',exit_seconds=round(time.monotonic()-start,3),exit_code=process.returncode,api_closed=True)
            process=None
        results['status']='PASS'
    except Exception as exc:
        attempt.update(failure=f'{type(exc).__name__}: {exc}',api_still_running=port_open())
        raise
    finally:
        for file in state.rglob('*.log'):
            if file.is_file():
                relative=str(file.relative_to(state)).replace('\\','_').replace('/','_')
                shutil.copyfile(file,OUT/('native-diagnostic-'+relative))
        if process is not None and process.poll() is None:
            import psutil
            from pywinauto import Desktop
            children=psutil.Process(process.pid).children(recursive=True)
            results['owned_processes']=[p.as_dict(attrs=['pid','name','cmdline']) for p in children]
            windows=[]
            for pid in [process.pid]+[p.pid for p in children]:
                for window in Desktop(backend='win32').windows(process=pid,visible_only=True):
                    windows.append({'pid':pid,'title':window.window_text(),'class':window.class_name()})
                    window.capture_as_image().save(OUT/f'native-timeout-{pid}-{len(windows)}.png')
            results['owned_windows']=windows
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],check=False)
        (OUT/'native-results.json').write_text(json.dumps(results,indent=2), encoding="utf-8")
    print(json.dumps(results,indent=2))


if __name__=='__main__': main()
