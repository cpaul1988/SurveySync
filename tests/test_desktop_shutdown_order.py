"""Real-thread drain and actual desktop wiring; not a substitute for Windows QA."""
from pathlib import Path
import ast
import threading
from unittest.mock import Mock

import pytest

from surveysync.desktop_shutdown import drain_server_before_cleanup


def test_cleanup_waits_for_real_inflight_server_work():
    started=threading.Event();release=threading.Event();cleaned=threading.Event()
    def server_work():
        started.set()
        assert release.wait(3)
    server=threading.Thread(target=server_work,daemon=False)
    server.start();assert started.wait(1)
    finished=threading.Thread(target=drain_server_before_cleanup,args=(server,cleaned.set))
    finished.start()
    try:
        assert not cleaned.wait(.05), 'Project storage closed before request/server drained'
        release.set();finished.join(2)
        assert not finished.is_alive() and not server.is_alive() and cleaned.is_set()
    finally:
        release.set();server.join(2);finished.join(2)


def test_join_is_not_a_timed_best_effort():
    server=Mock();server.is_alive.return_value=False;cleanup=Mock()
    drain_server_before_cleanup(server,cleanup)
    server.join.assert_called_once_with()
    cleanup.assert_called_once_with()


def test_cleanup_failure_propagates():
    server=Mock();server.is_alive.return_value=False
    with pytest.raises(OSError,match='database'):
        drain_server_before_cleanup(server,Mock(side_effect=OSError('database close failed')))


def test_self_join_and_unconfirmed_stop_do_not_close_storage():
    cleanup=Mock()
    with pytest.raises(RuntimeError,match='own thread'):
        drain_server_before_cleanup(threading.current_thread(),cleanup)
    server=Mock();server.is_alive.return_value=True
    with pytest.raises(RuntimeError,match='refused'):
        drain_server_before_cleanup(server,cleanup)
    cleanup.assert_not_called()


def test_desktop_uses_nondaemon_server_and_always_drains_before_marking_clean():
    tree=ast.parse((Path(__file__).resolve().parents[1]/'desktop.py').read_text())
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    threads=[n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='Thread']
    assert len(threads)==1
    assert next(k.value.value for k in threads[0].keywords if k.arg=='daemon') is False
    shutdown=next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='shutdown')
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='end_session' for n in ast.walk(shutdown))
    guarded=next(n for n in main.body if isinstance(n,ast.Try) and any(isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr=='start' for x in ast.walk(n)))
    final_calls=[n for part in guarded.finalbody for n in ast.walk(part) if isinstance(n,ast.Call)]
    assert any(isinstance(n.func,ast.Name) and n.func.id=='drain_server_before_cleanup' for n in final_calls)
    clean=next(n for n in main.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='end_session')
    assert main.body.index(clean)>main.body.index(guarded)
