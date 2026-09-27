"""Probe an already installed, hash-verified release in a disposable Windows job.

Never stage an update or submit feedback. Only temporary projects/configuration
are used. Cleanup terminates only the process tree created by this probe.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
import urllib.request

OUT = Path('audit-evidence').resolve()
OUT.mkdir(exist_ok=True)
INSTALL = Path(os.environ['SS_AUDIT_INSTALL'])
BASE = 'http://127.0.0.1:8765'


def request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE+path, data=data, headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=3) as response:
        return json.load(response)


def main():
    env = dict(os.environ)
    temp = Path(os.environ['RUNNER_TEMP']) / 'ss940-native-state'
    env.update(SURVEYSYNC_CONFIG_ROOT=str(temp/'config'), SURVEYSYNC_FIELD_ROOT=str(temp/'field'))
    result = {'source':'approved installed executable', 'checks':[], 'result':'FAIL'}
    process = subprocess.Popen([str(INSTALL/'SurveySync.exe')], cwd=INSTALL, env=env)
    result['launcher_pid'] = process.pid
    try:
        for _ in range(120):
            try:
                state = request('/api/v9/status')
                break
            except Exception:
                if process.poll() is not None:
                    raise RuntimeError('Installed launcher exited before its local API was ready; exit '+str(process.returncode))
                time.sleep(.5)
        else:
            raise RuntimeError('Installed native launcher API did not become ready within 60 seconds')
        result['checks'].append('Installed native executable starts local server')
        notes = request('/api/v9/release-notes')
        assert notes['release_id']=='9.4.0-beta.4', notes
        result['checks'].append('Installed API serves the approved release identity and notes')
        schema = request('/openapi.json')
        result['documented_path_count'] = len(schema['paths'])
        result['checks'].append('Installed complete API schema serializes')
        created = request('/api/v9/project/create', {'parent_folder':str(temp/'projects'),'name':'Native audit temporary project','crs':'EPSG:2278','horizontal_units':'us_survey_feet','vertical_units':'us_survey_feet'})
        result['project_create_response'] = created
        result['checks'].append('Installed API creates temporary project')
        time.sleep(3)
        try:
            from PIL import ImageGrab
            ImageGrab.grab().save(OUT/'native-window.png')
        except Exception as exc:
            result['screenshot_limit'] = str(exc)
        exit_response = request('/api/application/exit', {})
        result['exit_response'] = exit_response
        try:
            process.wait(timeout=12)
            result['checks'].append('Native process exits following application shutdown request')
        except subprocess.TimeoutExpired:
            result['shutdown_failure'] = 'API acknowledged shutdown but native launcher remained alive after 12 seconds; updater requests this same shutdown event.'
            try:
                result['api_still_alive'] = bool(request('/api/v9/status'))
            except Exception:
                result['api_still_alive'] = False
            raise AssertionError(result['shutdown_failure'])
        result['result'] = 'PASS'
    except Exception as exc:
        result['error'] = str(exc)
        raise
    finally:
        (OUT/'native-install-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2))
        if process.poll() is None:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)


if __name__=='__main__':
    main()
