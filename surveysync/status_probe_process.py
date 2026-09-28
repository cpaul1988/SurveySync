"""Bound a read-only native AI capability probe outside the application process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


class StatusProbeError(RuntimeError):
    pass


class StatusProbeTimeout(StatusProbeError):
    pass


def _probe_command(output: Path, alias: str) -> list[str]:
    return [sys.executable, '-I', str(Path(__file__).with_name('ai_status_probe.py')), str(output), alias]


def _stop_owned_probe(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if sys.platform == 'win32':
        # Windows venv launchers can have a child runtime. Kill only this probe's
        # owned process tree, never applications selected by name or other PIDs.
        taskkill = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/taskkill.exe'
        try:
            subprocess.run([str(taskkill), '/PID', str(process.pid), '/T', '/F'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=2, check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            process.kill()
            process.wait(timeout=2)
            raise StatusProbeError('Could not confirm native probe-tree cleanup.') from exc
    if process.poll() is None:
        process.kill()
    process.wait(timeout=2)


def run_foundry_status_probe(alias: str, *, timeout_seconds: float = 4.0) -> dict:
    """Read-only status; no model download, inference, or project operation.

    Native catalog discovery can stall on unavailable networks/providers. A
    bounded subprocess prevents that SDK call from pinning a server worker or
    loading its native library into the desktop process merely for a status tile.
    """
    if not isinstance(alias, str) or not alias or len(alias) > 200 or '\x00' in alias:
        raise ValueError('Invalid model alias.')
    if not 0 < timeout_seconds <= 10:
        raise ValueError('Status probe timeout is out of range.')
    process = None
    with tempfile.TemporaryDirectory(prefix='surveysync-ai-status-') as folder:
        result_path = Path(folder)/'result.json'
        try:
            process = subprocess.Popen(_probe_command(result_path, alias),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                cwd=str(Path(__file__).resolve().parents[1]),
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0)
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                _stop_owned_probe(process)
                raise StatusProbeTimeout('Local AI status probe exceeded its deadline; readiness is unknown.') from exc
            if process.returncode != 0 or not result_path.is_file():
                raise StatusProbeError('Local AI status probe did not return a valid result.')
            if result_path.stat().st_size > 32_768:
                raise StatusProbeError('Local AI status result exceeded the size limit.')
            try:
                data = json.loads(result_path.read_text(encoding='utf-8'))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise StatusProbeError('Local AI status result is malformed.') from exc
            expected={'id','name','installed','supported','ready','needs_download','local_only','detail','state','model'}
            if not isinstance(data, dict) or set(data) != expected or data['id'] != 'foundry_local' or data['model'] != alias:
                raise StatusProbeError('Local AI status result identity is invalid.')
            for key in ('installed','supported','ready','needs_download','local_only'):
                if type(data[key]) is not bool:
                    raise StatusProbeError('Local AI status flags must be boolean.')
            if data['local_only'] is not True or any(not isinstance(data[k],str) for k in ('id','name','detail','state','model')):
                raise StatusProbeError('Local AI status result contract is invalid.')
            return data
        except OSError as exc:
            raise StatusProbeError('Local AI status probe could not start or read its result.') from exc
        finally:
            if process is not None and process.poll() is None:
                _stop_owned_probe(process)
