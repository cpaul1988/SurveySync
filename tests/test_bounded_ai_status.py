"""A read-only capability tile must not pin GUI shutdown inside native SDK code."""
import importlib.util
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from surveysync import ai_runtime as ai
from surveysync import status_probe_process as probe


def valid(alias='fixture-model'):
    return ai.ComponentStatus('foundry_local','Microsoft Foundry Local',installed=True,
        supported=True,ready=True,state='ready',model=alias).to_dict()


def command_for(script, tmp_path, monkeypatch):
    source=tmp_path/'probe.py';source.write_text(script,encoding='utf-8')
    monkeypatch.setattr(probe,'_probe_command',lambda output,alias:[sys.executable,'-I',str(source),str(output),alias])


def test_real_child_returns_valid_status_without_importing_sdk_in_parent(tmp_path,monkeypatch):
    payload=valid()
    command_for('from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('+repr(json.dumps(payload))+',encoding="utf-8")\n',tmp_path,monkeypatch)
    result=probe.run_foundry_status_probe('fixture-model',timeout_seconds=3)
    assert result==payload


def test_real_blocked_child_is_terminated_and_not_retried(tmp_path,monkeypatch):
    command_for('import time\ntime.sleep(30)\n',tmp_path,monkeypatch)
    original=probe.subprocess.Popen;children=[]
    def spawn(*a,**kw):
        process=original(*a,**kw)
        # subprocess.run(taskkill) also uses Popen on Windows; count only the
        # probe command when asserting that a timed-out probe is not retried.
        if a[0][:2] == [sys.executable, '-I']:
            children.append(process)
        return process
    monkeypatch.setattr(probe.subprocess,'Popen',spawn)
    start=time.monotonic()
    with pytest.raises(probe.StatusProbeTimeout):
        probe.run_foundry_status_probe('fixture-model',timeout_seconds=.2)
    assert time.monotonic()-start<5
    assert len(children)==1 and children[0].poll() is not None


@pytest.mark.parametrize('kind',['invalid-json','wrong-id','nonboolean','missing-key','oversized','nonlocal'])
def test_probe_rejects_bad_results(tmp_path,monkeypatch,kind):
    payload=valid()
    if kind=='wrong-id':payload['id']='other'
    elif kind=='nonboolean':payload['ready']=1
    elif kind=='missing-key':del payload['model']
    elif kind=='nonlocal':payload['local_only']=False
    text='not json' if kind=='invalid-json' else ('x'*32769 if kind=='oversized' else json.dumps(payload))
    command_for('from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('+repr(text)+',encoding="utf-8")\n',tmp_path,monkeypatch)
    with pytest.raises(probe.StatusProbeError):probe.run_foundry_status_probe('fixture-model',timeout_seconds=3)


def test_windows_cleanup_targets_only_owned_process_tree(monkeypatch):
    process=Mock(pid=2468);process.poll.side_effect=[None,None];process.wait.return_value=0
    run=Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(probe.sys,'platform','win32')
    monkeypatch.setattr(probe.subprocess,'run',run)
    probe._stop_owned_probe(process)
    command=run.call_args.args[0]
    assert command[1:]==['/PID','2468','/T','/F']
    assert Path(command[0]).name.lower()=='taskkill.exe' and Path(command[0]).parent.name=='System32'
    assert '/IM' not in command
    assert run.call_args.kwargs['timeout']==2


@pytest.mark.parametrize('error,state',[(probe.StatusProbeTimeout('deadline'),'probe_timeout'),(probe.StatusProbeError('failed'),'probe_failed')])
def test_status_timeout_or_failure_never_claims_ready(monkeypatch,error,state):
    monkeypatch.setattr(ai,'_is_windows',lambda:True)
    monkeypatch.setattr(importlib.util,'find_spec',lambda name:object())
    def fail(alias):raise error
    monkeypatch.setattr(probe,'run_foundry_status_probe',fail)
    monkeypatch.setattr(ai,'_get_foundry_manager',lambda:pytest.fail('SDK loaded in parent'))
    result=ai._probe_foundry_local('fixture-model')
    assert not result.ready and not result.needs_download and result.state==state


def test_successful_component_status_is_preserved(monkeypatch):
    monkeypatch.setattr(ai,'_is_windows',lambda:True)
    monkeypatch.setattr(importlib.util,'find_spec',lambda name:object())
    monkeypatch.setattr(probe,'run_foundry_status_probe',lambda alias:valid(alias))
    monkeypatch.setattr(ai,'_get_foundry_manager',lambda:pytest.fail('SDK loaded in parent'))
    assert ai._probe_foundry_local('fixture-model').to_dict()==valid()


def test_overlapping_forced_refreshes_share_one_completed_probe(monkeypatch):
    entered=threading.Event();release=threading.Event();second_started=threading.Event();calls=[];results=[]
    monkeypatch.setattr(ai,'_status_cache',None)
    monkeypatch.setattr(ai,'_probe_windows_ocr',lambda:ai.ComponentStatus('windows_ocr','OCR'))
    monkeypatch.setattr(ai,'_probe_windows_language',lambda:ai.ComponentStatus('windows_language','Language'))
    def blocked():
        calls.append(1);entered.set();assert release.wait(3)
        return ai.ComponentStatus(**valid())
    monkeypatch.setattr(ai,'_probe_foundry_local',blocked)
    def refresh(second=False):
        if second:second_started.set()
        results.append(ai.get_local_ai_status(force=True))
    a=threading.Thread(target=refresh);b=threading.Thread(target=refresh,args=(True,))
    try:
        a.start();assert entered.wait(2);b.start();assert second_started.wait(2)
        time.sleep(.05);release.set();a.join(3);b.join(3)
        assert not a.is_alive() and not b.is_alive()
        assert len(calls)==1 and len(results)==2
        results[0]['foundry_local']['ready']=False
        assert results[1]['foundry_local']['ready'] is True
    finally:
        release.set();a.join(3)
        if b.ident is not None:b.join(3)


def test_status_api_does_not_probe_twice_on_refresh(monkeypatch,tmp_path):
    from surveysync import router
    from surveysync.config import ConfigStore
    called=[]
    monkeypatch.setattr(router,'config_store',ConfigStore(tmp_path/'config'))
    monkeypatch.setattr(router,'get_local_ai_status',lambda **kw:pytest.fail('Duplicate capability probe'))
    def detailed(**kw):called.append(kw);return {'foundry_local':valid()}
    monkeypatch.setattr(router,'_fieldbook_app_module',lambda:SimpleNamespace(_automatic_ai_status=detailed))
    assert router.ai_status(refresh=True)['foundry_local']['ready'] is True
    assert called==[{'force':True}]
