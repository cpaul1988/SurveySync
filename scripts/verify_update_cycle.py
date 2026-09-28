"""Real Windows update replacement in disposable installations only.

A real test-only beta.0 installer uses the candidate code with only its build
identity stamps changed. Replacement by beta.1 exercises the same numeric
version. Separate fixtures use unmodified published 9.4.1 and 9.4.0 installers;
the latter's known shutdown bug requires one normal window close. Neither fixture is published or distributed.
TLS, staging, hashes, native helper, real Setup, and reopen are not mocked.
"""
from __future__ import annotations
import datetime as dt
import functools
import hashlib
import http.server
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error

import psutil
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pywinauto import Desktop

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'repair-evidence'
BASE = 'http://127.0.0.1:8765'
TARGET = (ROOT/'VERSION.txt').read_text(encoding='utf-8-sig').strip()
TARGET_ID = (ROOT/'RELEASE_ID.txt').read_text(encoding='utf-8-sig').strip()


def api(path, data=None):
    req = urllib.request.Request(BASE+path, data=None if data is None else json.dumps(data).encode(),
                                 headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        message = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'{path}: HTTP {exc.code}: {message}') from exc


def ready(version, timeout=90, release_id=None):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        try:
            info=api('/api/v9/release-notes')
            if info['version']==version and (release_id is None or info.get('release_id')==release_id):
                return
        except (OSError,ValueError):
            pass
        time.sleep(.3)
    raise TimeoutError('Application did not start at version '+version)


def no_service():
    with socket.socket() as sock:
        sock.settimeout(.2)
        return sock.connect_ex(('127.0.0.1',8765)) != 0


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def certificate(folder):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'SurveySync disposable test CA')])
    now=dt.datetime.now(dt.timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-dt.timedelta(minutes=5))
          .not_valid_after(now+dt.timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
          .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
          .sign(key,hashes.SHA256()))
    certpath=folder/'local-ca.pem';keypath=folder/'local-key.pem'
    certpath.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    return certpath,keypath


def install(executable, destination, env, log):
    command=[str(executable),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',f'/DIR={destination}',f'/LOG={log}']
    result=subprocess.run(command,env=env,timeout=600,check=False)
    assert result.returncode==0, f'Fixture install failed: {result.returncode}; {log}'
    assert (destination/'SurveySync.exe').is_file()


def point_snapshot(project):
    # Locate the canonical database, not the separately scoped job ledger.
    for path in [*project.rglob('*.sqlite'),*project.rglob('*.sqlite3'),*project.rglob('*.db')]:
        conn=sqlite3.connect(str(path))
        try:
            if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='canonical_points'").fetchone():
                return [list(r) for r in conn.execute('SELECT point_id,northing,easting,elevation,description FROM canonical_points ORDER BY point_id')]
        finally:conn.close()
    raise AssertionError('Canonical point database not found')


def finish_wizard(report, timeout=600):
    desktop=Desktop(backend='win32');until=time.monotonic()+timeout
    while time.monotonic()<until:
        windows=desktop.windows(class_name='TWizardForm',visible_only=True)
        assert len(windows)<=1, 'Ambiguous setup window; refusing interaction'
        if windows:
            wizard=windows[0]
            if not report.get('wizard_title'):
                report['wizard_title']=wizard.window_text()
                wizard.capture_as_image().save(OUT/(report['fixture']+'-setup.png'))
            buttons=wizard.descendants(class_name='TNewButton')
            for text in ('&Finish','&Install','&Next >','&Next','Next >','Next','Install','Finish'):
                matches=[b for b in buttons if b.window_text()==text and b.is_enabled() and b.is_visible()]
                if matches:
                    report['wizard_actions'].append(text)
                    print(f"{report['fixture']}: real Setup click {text}", flush=True)
                    matches[0].click()
                    if 'Finish' in text:return
                    time.sleep(.6)
                    break
        time.sleep(.4)
    if windows:
        report['wizard_controls']=[(c.class_name(),c.window_text()) for c in windows[0].descendants() if c.is_visible()]
    raise TimeoutError('Real replacement Setup did not finish')


def close_old_window(process):
    ids=[process.pid]+[p.pid for p in psutil.Process(process.pid).children(recursive=True)]
    matches=[]
    for pid in ids:
        matches.extend(Desktop(backend='win32').windows(process=pid,title_re=r'SurveySync.*',visible_only=True))
    assert len(matches)==1, 'Old native window selection was ambiguous'
    matches[0].close()


def kill_owned_install(destination):
    exe=str((destination/'SurveySync.exe').resolve()).casefold()
    for item in psutil.process_iter(['pid','exe']):
        if str(item.info.get('exe') or '').casefold()==exe:
            subprocess.run(['taskkill','/PID',str(item.pid),'/T','/F'],check=False,capture_output=True)


def cycle(name, fixture, candidate, webroot, url, certpath, state, *, initial_version='9.4.0', initial_release_id=None):
    destination=state/'program'
    config=state/'local'/'SurveySync'
    env=dict(os.environ, LOCALAPPDATA=str(state/'local'),SURVEYSYNC_CONFIG_ROOT=str(config),
             SURVEYSYNC_FIELD_ROOT=str(state/'field'),SSL_CERT_FILE=str(certpath),
             WEBVIEW2_USER_DATA_FOLDER=str(state/'webview'))
    env.pop('PYTHONPATH',None)
    report={'fixture':name,'status':'FAIL','wizard_actions':[]}
    process=None
    try:
        assert no_service(), 'Do not touch an existing local application'
        install(fixture,destination,env,OUT/(name+'-initial-setup.log'))
        if name=='new-updater-version-only-predecessor':
            core=destination/'surveysync/__init__.py'
            original=core.read_text(encoding='utf-8')
            assert f'__version__ = "{TARGET}"' in original
            core.write_text(original.replace(f'__version__ = "{TARGET}"','__version__ = "9.4.0"'),encoding='utf-8')
            (destination/'VERSION.txt').write_text('9.4.0\n',encoding='utf-8')
            (destination/'RELEASE_ID.txt').write_text('9.4.0\n',encoding='utf-8')
            shutil.rmtree(destination/'surveysync/__pycache__',ignore_errors=True)
            subprocess.run(['go','build','-trimpath','-ldflags','-s -w -H=windowsgui -X main.appVersion=9.4.0',
                            '-o',str(destination/'SurveySync.exe'),'installer/app_launcher.go'],cwd=ROOT,check=True)
            report['fixture_changes']=['Core version only: 9.4.0','VERSION.txt only: 9.4.0','Launcher version only: 9.4.0; logic unchanged']
        process=subprocess.Popen([str(destination/'SurveySync.exe')],cwd=destination,env=env)
        ready(initial_version, release_id=initial_release_id)
        api('/api/v9/project/create',{'parent_folder':str(state/'projects'),'name':'UpdatePreservation','crs':'EPSG:2278'})
        project=next((state/'projects').rglob('survey_sync_project.json')).parent
        source=state/'source.csv'
        header = 'point_id' if name=='released-9.4.0-migration' else 'PointID'
        source.write_text(header+',Northing,Easting,Elevation,Code\n001A,1000,2000,10,CP\n001B,1001,2001,11,CP\n001C,1002,2002,12,CP\n',encoding='utf-8')
        api('/api/v9/points/import',{'file_path':str(source)})
        prior=point_snapshot(project)
        sentinel=project/'user-preservation-note.txt';sentinel.write_text('User data must survive replacement.',encoding='utf-8')
        preserved={str(source):sha(source),str(sentinel):sha(sentinel)}
        appearance={'appearance':'dark','theme':'carbon','accent':'teal'}
        api('/api/v9/config/ui',appearance)
        api('/api/v9/update/config',{'update_manifest_url':url+'/manifest.json'})
        pending=config/'pending_update.json'
        answer=api('/api/v9/update/check-and-install',{'confirm_install':False})
        assert answer['action']=='confirmation_required' and answer['version']==TARGET,answer
        if initial_release_id:
            assert initial_version == TARGET and initial_release_id != TARGET_ID
            assert answer.get('release_id')==TARGET_ID, answer
            report['numbered_beta_identity']={'from':initial_release_id,'to':TARGET_ID,'same_numeric_version':True}
        assert not pending.exists() and not no_service()
        answer=api('/api/v9/update/check-and-install',{'confirm_install':True})
        assert answer['action']=='installing' and answer['sha256']==sha(candidate),answer
        assert sha(answer['installer_path'])==sha(candidate)
        if name=='released-9.4.0-migration':
            # Document the old defect; do not rewrite the installed old code.
            time.sleep(3)
            if process.poll() is None:
                close_old_window(process)
                report['manual_old_window_close']=True
        process.wait(timeout=20)
        assert process.returncode==0
        status=config/'updates/update_helper_status.json'
        until=time.monotonic()+30
        helper={}
        while time.monotonic()<until:
            if status.exists():
                helper=json.loads(status.read_text(encoding='utf-8'))
                assert helper['state'] not in ('error','installer_failed'),helper
                if helper['state']=='installer_started':break
            time.sleep(.2)
        else:raise TimeoutError('Native helper did not start Setup')
        report['helper_start']=helper
        finish_wizard(report)
        ready(TARGET,timeout=120,release_id=TARGET_ID)
        assert (destination/'RELEASE_ID.txt').read_text(encoding='utf-8-sig').strip()==TARGET_ID
        assert (destination/'VERSION.txt').read_text(encoding='utf-8').strip()==TARGET
        for relative in ('desktop.py','surveysync/__init__.py','surveysync/updater.py','installer/update_helper.go'):
            # Git checks out Windows source as CRLF; both exact installed/tested
            # bytes must match; no newline normalization conceals a mismatch.
            assert sha(destination/relative)==sha(ROOT/relative),relative
        assert point_snapshot(project)==prior
        assert all(sha(p)==digest for p,digest in preserved.items())
        assert api('/api/v9/config/ui')==appearance
        assert api('/api/v9/update/check')['update_available'] is False
        if name in ('new-updater-version-only-predecessor','same-version-numbered-beta'):
            until=time.monotonic()+20
            while time.monotonic()<until:
                helper=json.loads(status.read_text(encoding='utf-8'))
                if helper['state']=='installed':break
                assert helper['state']!='installer_failed',helper
                time.sleep(.2)
            assert helper['state']=='installed',helper
            report['helper_final']=helper
            receipt=json.loads((config/'installed_update.json').read_text(encoding='utf-8'))
            assert receipt['release_id']==TARGET_ID and receipt['sha256']==sha(candidate),receipt
            report['verified_receipt']=receipt
        assert not pending.exists(), 'Successful installation left an active handoff'
        api('/api/application/exit',{})
        until=time.monotonic()+20
        while not no_service() and time.monotonic()<until:time.sleep(.2)
        assert no_service()
        report.update(status='PASS',target_version=TARGET,target_release_id=TARGET_ID,installer_sha256=sha(candidate),canonical_points=prior,
                      source_bytes_unchanged=True,project_and_settings_preserved=True)
    except Exception as exc:
        report['failure'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        kill_owned_install(destination)
        log=config/'logs/update_helper.log'
        if log.exists():shutil.copyfile(log,OUT/(name+'-helper.log'))
        log=config/'logs/update_setup.log'
        if log.exists():shutil.copyfile(log,OUT/(name+'-replacement-setup.log'))
        (OUT/(name+'-result.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def main():
    assert sys.platform=='win32' and os.environ.get('GITHUB_ACTIONS')=='true'
    temp=Path(os.environ['RUNNER_TEMP']).resolve()
    state=temp/'SurveySync941UpdateCycle';state.mkdir(exist_ok=False)
    OUT.mkdir(exist_ok=True)
    webroot=state/'https';webroot.mkdir()
    candidate=ROOT/'installer/output'/f'SurveySync_Setup_{TARGET_ID}.exe'
    assert candidate.is_file()
    shutil.copyfile(candidate,webroot/'setup.exe')
    certpath,keypath=certificate(webroot)
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(webroot)))
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(certpath,keypath)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    url=f'https://127.0.0.1:{server.server_port}'
    rel={'version':TARGET,'release_id':TARGET_ID,'installer_url':url+'/setup.exe','size_bytes':candidate.stat().st_size,'sha256':sha(candidate)}
    (webroot/'manifest.json').write_text(json.dumps({'product':'SurveySync','channels':{'beta':rel}}),encoding='utf-8')
    threading.Thread(target=server.serve_forever,daemon=True).start()
    results={'status':'FAIL','cycles':[]}
    try:
        from build_beta_fixture import build_fixture
        beta_fixture, predecessor_id, stamp_changes=build_fixture(ROOT,state)
        folder=state/'numbered-beta';folder.mkdir()
        result=cycle('same-version-numbered-beta',beta_fixture,candidate,webroot,url,certpath,folder,
                     initial_version=TARGET,initial_release_id=predecessor_id)
        result['predecessor_fixture_stamp_changes']=stamp_changes
        result['predecessor_installer_sha256']=sha(beta_fixture)
        results['cycles'].append(result)
        released=ROOT/'released-baseline/SurveySync_Setup_9.4.1.exe'
        assert sha(released)=='9fe7bf8a2b5512ab2886ec79b2bec179df665562b3d6b70eb70cb38d04d03c42'
        folder=state/'released-941';folder.mkdir()
        results['cycles'].append(cycle('released-9.4.1-migration',released,candidate,webroot,url,certpath,folder,
                                      initial_version='9.4.1'))
        old=ROOT/'released-baseline/SurveySync_Setup_9.4.0.exe'
        assert sha(old)=='1660d9bdb329e61242c48b0dfe6d4a254d2d05220829a83cf54b901a10a5ae17'
        folder=state/'released';folder.mkdir()
        results['cycles'].append(cycle('released-9.4.0-migration',old,candidate,webroot,url,certpath,folder))
        results['status']='PASS'
    finally:
        server.shutdown();server.server_close()
        (OUT/'update-cycle-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()
