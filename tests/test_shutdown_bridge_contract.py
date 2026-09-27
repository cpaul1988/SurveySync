"""Actual bridge/callback code under isolated contracts, not native Windows acceptance."""
import ast
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def bridge_class():
    tree = ast.parse((ROOT/'desktop.py').read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NativeBridge')
    namespace = {'Path':Path}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'desktop.py','exec'),namespace)
    return namespace['NativeBridge']


def test_exposed_exit_invokes_orderly_callback():
    bridge = bridge_class()()
    callback = Mock()
    window = Mock()
    bridge._shutdown_callback = callback
    bridge._window = window
    assert bridge.exit_app() is True
    callback.assert_called_once_with()
    window.destroy.assert_not_called()


def test_bridge_exit_reports_callback_failure():
    bridge = bridge_class()()
    bridge._shutdown_callback = Mock(side_effect=RuntimeError('injected'))
    assert bridge.exit_app() is False


def test_actual_watch_callback_consumes_shutdown_event():
    tree=ast.parse((ROOT/'desktop.py').read_text(encoding="utf-8"))
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    watch=next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='watch_shutdown')
    event=threading.Event()
    callback=Mock()
    namespace={'field_app':SimpleNamespace(runtime=SimpleNamespace(shutdown_event=event)), 'shutdown':callback}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[watch],type_ignores=[])),'desktop.py','exec'),namespace)
    thread=threading.Thread(target=namespace['watch_shutdown'],daemon=True)
    thread.start()
    callback.assert_not_called()
    event.set()
    thread.join(2)
    assert not thread.is_alive()
    callback.assert_called_once_with()
    start_calls=[n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='start' and isinstance(n.func.value,ast.Name) and n.func.value.id=='webview']
    assert len(start_calls)==1 and isinstance(start_calls[0].args[0],ast.Name) and start_calls[0].args[0].id=='watch_shutdown'
