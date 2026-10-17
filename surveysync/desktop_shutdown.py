"""Finish HTTP work before closing project storage or finalizing the interpreter.

In a Python-hosted CLR desktop, daemon request/server threads must not outlive
normal main-thread teardown. A timeout is not confirmation that they stopped.
This helper never kills a thread/process or converts a failed cleanup to success.
"""
from __future__ import annotations

import threading
from typing import Callable


def drain_server_before_cleanup(server_thread: threading.Thread, cleanup: Callable[[], None]) -> None:
    if server_thread is threading.current_thread():
        raise RuntimeError("Cannot drain the desktop server from its own thread")
    # In-flight HTTP operations retain their own normal operation deadlines.
    # Do not start interpreter finalization just because an arbitrary join timeout
    # elapsed: that can race request workers and native/CLR reference cleanup.
    server_thread.join()
    if server_thread.is_alive():
        raise RuntimeError("Desktop server did not stop; project cleanup refused")
    cleanup()
