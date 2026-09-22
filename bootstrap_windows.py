"""Fast Windows bootstrap for SurveySync v9.3.0.

Creates the private .venv on first run and only re-runs pip when requirements.txt
changes. This keeps normal launches fast while preserving the easy ZIP-based setup.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import shutil
import re
import os
import ctypes
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements.lock"
MARKER = VENV / ".surveysync_requirements.sha256"


def _bootstrap_log_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SurveySync" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base / "bootstrap.log"


def _log(message: str) -> None:
    try:
        with _bootstrap_log_path().open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} | {message}\n")
    except Exception:
        pass


def _message_box(message: str, *, error: bool = True) -> None:
    if os.name != "nt":
        return
    try:
        flags = 0x00000010 if error else 0x00000040
        ctypes.windll.user32.MessageBoxW(None, message, "SurveySync", flags)
    except Exception:
        pass


def _venv_python() -> Path:
    return VENV / "Scripts" / "python.exe"


def _venv_version() -> tuple[int, int] | None:
    cfg = VENV / "pyvenv.cfg"
    if not cfg.exists():
        return None
    try:
        for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("version") and "=" in line:
                m = re.match(r"(\d+)\.(\d+)", line.split("=", 1)[1].strip())
                if m:
                    return int(m.group(1)), int(m.group(2))
    except OSError:
        pass
    return None


def _backup_incompatible_venv() -> None:
    version = _venv_version()
    if version and version >= (3, 14):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = ROOT / f".venv_python{version[0]}{version[1]}_backup_{stamp}"
        print(f"[SurveySync] Existing .venv uses Python {version[0]}.{version[1]}, which can conflict with current Windows native packages.")
        print(f"[SurveySync] Preserving it as {backup.name} and rebuilding only the app environment.")
        shutil.move(str(VENV), str(backup))


def _requirements_digest() -> str:
    h = hashlib.sha256()
    h.update(REQ.read_bytes())
    h.update(b"\nsurveysync-bootstrap-v9.3.0")
    return h.hexdigest()


def _run(args: list[str]) -> None:
    _log("RUN " + " ".join(str(x) for x in args))
    completed = subprocess.run(args, cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    if completed.stdout:
        _log(completed.stdout.rstrip())


def ensure_environment() -> Path:
    if not ((3, 11) <= sys.version_info[:2] <= (3, 13)):
        raise RuntimeError(
            f"SurveySync currently requires Python 3.11, 3.12, or 3.13 on Windows. "
            f"This launcher is using Python {sys.version_info.major}.{sys.version_info.minor}. "
            "Python 3.14 is intentionally avoided because PaddlePaddle/native dependencies are not yet reliably compatible. "
            "Install Python 3.13 x64 side-by-side, then run SurveySync again."
        )
    _backup_incompatible_venv()
    py = _venv_python()
    if not py.exists():
        print("[SurveySync] First-time setup: creating a private Python environment...")
        _log("First-time setup: creating private Python environment")
        _run([sys.executable, "-m", "venv", str(VENV)])

    expected = _requirements_digest()
    actual = MARKER.read_text(encoding="utf-8").strip() if MARKER.exists() else ""
    if actual != expected:
        print("[SurveySync] Installing/updating application components...")
        _log("Installing/updating application components")
        _run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"])
        _run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "--require-hashes", "-r", str(REQ)])
        MARKER.write_text(expected, encoding="utf-8")
    else:
        print("[SurveySync] Application components are ready.")
        _log("Application components are ready")
    return py


def main() -> int:
    browser = False
    forwarded: list[str] = []
    for arg in sys.argv[1:]:
        if arg == "--browser":
            browser = True
        else:
            forwarded.append(arg)
    try:
        py = ensure_environment()
        target = ROOT / ("run_browser.py" if browser else "desktop.py")
        label = "browser fallback" if browser else "desktop app"
        print(f"[SurveySync] Opening {label}...")
        _log(f"Opening {label}")
        return subprocess.call([str(py), str(target), *forwarded], cwd=ROOT)
    except Exception as exc:
        message = (
            f"SurveySync could not start:\n\n{exc}\n\n"
            "A diagnostic log was written to:\n" + str(_bootstrap_log_path()) +
            "\n\nFor a visible troubleshooting console, run:\nrun_windows.bat --console"
        )
        _log("ERROR | " + repr(exc))
        print()
        print(message)
        _message_box(message, error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
