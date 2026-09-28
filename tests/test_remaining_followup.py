"""Additional regressions from Windows/GIS execution and publication-contract review."""
import copy
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys

import pytest
from test_v940_pointcloud_workflows import _project
from test_v940_crs_report_gis_bridges import _template
from surveysync import report_template_mapper as tm
from surveysync import gis_bridges as gis
from surveysync.manifest_trust import load_policy
from scripts.update_manifest import build_manifest


def test_concurrent_template_registrations_preserve_both_definitions(tmp_path):
    project = _project(tmp_path)
    source = _template(tmp_path/'source.xlsx')
    with ThreadPoolExecutor(max_workers=2) as pool:
        entries = list(pool.map(lambda name: tm.register_excel_template(project, source, name=name), ['First','Second']))
    assert len({e['template_id'] for e in entries}) == 2
    assert {t['name'] for t in tm.list_templates(project)} == {'First','Second'}


@pytest.mark.parametrize('data', [[], None, 5, {'require_signature':True,'keys':{'key':4}}])
def test_malformed_packaged_trust_is_explicit_error(tmp_path, data):
    (tmp_path/'update_trust.json').write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError): load_policy(tmp_path)


def test_external_environment_does_not_leak_app_python(tmp_path, monkeypatch):
    prefix = tmp_path/'app-python'
    monkeypatch.setattr(gis.sys, 'prefix', str(prefix))
    monkeypatch.setattr(gis.sys, 'base_prefix', str(prefix))
    monkeypatch.setenv('PYTHONHOME', str(prefix))
    monkeypatch.setenv('PYTHONPATH', str(prefix/'site-packages'))
    monkeypatch.setenv('PATH', os.pathsep.join([str(prefix/'bin'),str(tmp_path/'gis')]))
    monkeypatch.setenv('LD_LIBRARY_PATH', os.pathsep.join([str(prefix/'lib'),str(tmp_path/'qgis-lib')]))
    env = gis._external_environment()
    assert 'PYTHONHOME' not in env and 'PYTHONPATH' not in env
    assert env['PATH'] == str(tmp_path/'gis')
    assert env['LD_LIBRARY_PATH'] == str(tmp_path/'qgis-lib')
    assert os.environ['PYTHONHOME'] == str(prefix)


@pytest.mark.parametrize('flag', ['--tmp-project','--tmp-location'])
def test_grass_capability_uses_advertised_option(tmp_path, monkeypatch, flag):
    monkeypatch.setattr(gis, '_run', lambda *a,**k: {'stdout':'usage: '+flag, 'stderr':''})
    assert gis._grass_temporary_flag(tmp_path/'grass') == flag


def manifest_args():
    return dict(channel='beta',version='9.4.2',release_id='9.4.2-beta.10',
                installer_url='https://example.org/v9.4.2-beta.10/setup.exe',
                release_tag='v9.4.2-beta.10',size=100,digest='a'*64,timestamp='2026-09-28T00:00:00Z')


def test_manifest_retains_physical_beta_identity_through_stable_promotion():
    data={'channels':{'developer':{'keep':True},'stable':{'version':'9.4.1','sha256':'b'*64}}}
    before=copy.deepcopy(data);args=manifest_args()
    beta=build_manifest(data,**args)
    stable=build_manifest(beta,**{**args,'channel':'stable','promoted_from':'beta'})
    assert stable['channels']['stable']['release_id']=='9.4.2-beta.10'
    assert stable['channels']['stable']['artifact_identity']=='sha256:'+'a'*64
    assert stable['channels']['developer']==before['channels']['developer'] and data==before


@pytest.mark.parametrize('changes',[{'release_id':'9.4.3-beta.10'}, {'release_tag':'v9.4.2-beta.2'}, {'installer_url':'http://example.org/setup.exe'}])
def test_manifest_identity_mismatch_never_mutates(changes):
    data={'channels':{}};args=manifest_args();args.update(changes)
    with pytest.raises(ValueError):build_manifest(data,**args)
    assert data=={'channels':{}}


def test_existing_identity_cannot_change_executable_bytes():
    args=manifest_args();data=build_manifest({},**args)
    with pytest.raises(ValueError,match='replace bytes'):build_manifest(data,**{**args,'digest':'b'*64})


def test_same_version_beta_downgrade_refused():
    args=manifest_args();data=build_manifest({},**args)
    with pytest.raises(ValueError,match='downgrade'):
        build_manifest(data,**{**args,'release_id':'9.4.2-beta.2','release_tag':'v9.4.2-beta.2'})


def test_corrupt_feed_is_not_reset_by_cli(tmp_path):
    path=tmp_path/'feed.json';path.write_bytes(b'broken-json');exe=tmp_path/'setup.exe';exe.write_bytes(b'MZtest')
    run=subprocess.run([sys.executable,'scripts/update_manifest.py','--manifest',str(path),
        '--channel','beta','--version','9.4.1','--installer',str(exe),'--installer-url','https://example.org/setup.exe',
        '--release-tag','v9.4.1'],capture_output=True)
    assert run.returncode != 0 and path.read_bytes()==b'broken-json'
