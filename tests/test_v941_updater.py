"""Newly reproduced staging defects and Windows-compatible failure cleanup."""
import io
import json
from hashlib import sha256
from pathlib import Path

import pytest
from surveysync import updater
from surveysync.config import ConfigStore


def release(body=b'MZverified installer', **changes):
    return dict(version='9.4.2', channel='stable', installer_url='https://example.com/setup.exe',
                sha256=sha256(body).hexdigest(), size_bytes=len(body), update_available=True, **changes)


@pytest.mark.parametrize('version',['../9.4.2','9.4.2/../../evil','9.4.2-beta.1','NaN','', '9.4.2.1.2','9.-1','999999.1'])
def test_reject_malformed_or_unsafe_versions(version):
    r=release(); r['version']=version
    with pytest.raises(ValueError): updater.select_release({'channels':{'stable':r}},'stable')


@pytest.mark.parametrize('url',['http://example.com/a','https://','https://user:pass@example.com/x','https://example.com/x#tag','https://example.com/a\nb','https://example.com:bad/x'])
def test_https_validation(url):
    with pytest.raises(ValueError): updater._https(url)


def test_reject_redirect_downgrade():
    req=updater.urllib.request.Request('https://example.com/a')
    with pytest.raises(ValueError): updater._HTTPSRedirect().redirect_request(req,None,302,'Found',{},'http://example.com/b')


@pytest.mark.parametrize('size',[0,-1,True,1.5,'100',5*1024**3])
def test_invalid_manifest_size(size):
    r=release();r['size_bytes']=size
    with pytest.raises(ValueError): updater.select_release({'channels':{'stable':r}},'stable')


def prepare(tmp_path,monkeypatch,body):
    store=ConfigStore(tmp_path/'config')
    monkeypatch.setattr(updater,'check',lambda _:release(body))
    monkeypatch.setattr(updater,'_open',lambda *a,**k:io.BytesIO(body))
    return store


def test_stage_verified_bytes_and_handoff(tmp_path,monkeypatch):
    body=b'MZ'+bytes(range(256))*20
    store=prepare(tmp_path,monkeypatch,body)
    r=updater.stage(store)
    assert Path(r['installer_path']).read_bytes()==body
    assert json.loads(Path(r['pending_file']).read_text())['sha256']==sha256(body).hexdigest()
    assert not list(store.root.rglob('*.download'))
    assert not list(store.root.glob('pending-*.tmp'))


@pytest.mark.parametrize('failure',['header','checksum','size','network'])
def test_failed_download_closes_handles_and_retains_previous_approval(tmp_path,monkeypatch,failure):
    body=b'NO not executable' if failure=='header' else b'MZdownload'
    store=prepare(tmp_path,monkeypatch,body)
    pending=store.root/'pending_update.json';pending.write_text('{"previous":"approval"}')
    if failure=='checksum':
        r=release(body);r['sha256']='0'*64;monkeypatch.setattr(updater,'check',lambda _:r)
    if failure=='size':
        r=release(body);r['size_bytes']=2;monkeypatch.setattr(updater,'check',lambda _:r)
    if failure=='network':
        class Broken(io.BytesIO):
            def read(self,*a): raise OSError('Injected network interruption')
        monkeypatch.setattr(updater,'_open',lambda *a,**k:Broken(body))
    with pytest.raises((ValueError,OSError)):updater.stage(store)
    assert pending.read_text()=='{"previous":"approval"}'
    assert not list(store.root.rglob('*.download'))
    assert not list(store.root.rglob('*.exe'))


def test_config_changed_while_downloading_aborts_handoff(tmp_path,monkeypatch):
    body=b'MZchange';store=prepare(tmp_path,monkeypatch,body)
    def open_changed(*a,**k):
        cfg=store.load();cfg.update_manifest_url='https://example.org/new.json';store.save(cfg)
        return io.BytesIO(body)
    monkeypatch.setattr(updater,'_open',open_changed)
    with pytest.raises(ValueError,match='configuration changed'):updater.stage(store)
    assert not (store.root/'pending_update.json').exists()


def test_concurrent_stage_refuses_second_request(tmp_path):
    updater._DOWNLOAD_LOCK.acquire()
    try:
        with pytest.raises(ValueError,match='already in progress'):updater.stage(ConfigStore(tmp_path))
    finally:updater._DOWNLOAD_LOCK.release()


def test_large_or_wrong_product_manifest_rejected(tmp_path,monkeypatch):
    for body in [b' '* (updater.MAX_MANIFEST_BYTES+1),b'{"product":"not SurveySync"}']:
        monkeypatch.setattr(updater,'_open',lambda *a,**k:io.BytesIO(body))
        with pytest.raises(ValueError):updater.fetch_manifest(ConfigStore(tmp_path))


def test_same_or_older_release_does_not_reinstall(monkeypatch):
    monkeypatch.setattr(updater,'__version__','9.4.1')
    monkeypatch.setattr(updater,'installed_release_id',lambda version:'9.4.1')
    r=release();r['version']='9.4.1'
    assert updater.select_release({'channels':{'stable':r}},'stable')['update_available'] is False
    r['version']='9.4.0'
    assert updater.select_release({'channels':{'stable':r}},'stable')['update_available'] is False
    r['version']='9.4.2'
    assert updater.select_release({'channels':{'stable':r}},'stable')['update_available'] is True


def test_release_stamps_agree():
    import surveysync
    from surveysync.router import SURVEYSYNC_RELEASE_NOTES_ID
    root=Path(__file__).resolve().parents[1]
    version=(root/'VERSION.txt').read_text().strip()
    release_id=(root/'RELEASE_ID.txt').read_text(encoding='utf-8').strip()
    from surveysync.release_identity import release_order
    assert version==surveysync.__version__
    assert SURVEYSYNC_RELEASE_NOTES_ID==release_id
    assert release_order(release_id)[0]==release_order(version)[0]
    assert f'var appVersion = "{version}"' in (root/'installer/app_launcher.go').read_text(encoding='utf-8')
    assert f'#define MyAppVersion "{version}"' in (root/'installer/SurveySync.iss').read_text(encoding='utf-8')
    assert 'Beta.4' not in (root/'installer/SurveySync.iss').read_text(encoding='utf-8')
