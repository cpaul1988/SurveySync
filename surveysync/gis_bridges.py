"""Optional external QGIS / GRASS GIS processing bridges.

SurveySync does not import GPL GIS runtimes. It discovers installed executables and
invokes them as separate processes with shell=False.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .project import SurveyProject

_QGIS_ALGORITHM = re.compile(r"^[A-Za-z0-9_.:-]+$")
_GRASS_MODULE = re.compile(r"^(?:g|r|v|db|i)\.[A-Za-z0-9_.-]+$")
_PARAM_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_MAX_OUTPUT = 250_000


class GisBridgeError(RuntimeError):
    pass


def _existing(candidates: list[str | Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        raw = str(item or "").strip().strip('"')
        if not raw:
            continue
        path = Path(raw).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        if key in seen or not resolved.is_file():
            continue
        seen.add(key)
        found.append(resolved)
    return found


def _qgis_candidates() -> list[Path]:
    candidates: list[str | Path] = []
    env = os.environ.get("SURVEYSYNC_QGIS_PROCESS", "")
    if env:
        candidates.append(env)
    for name in (
        "qgis_process.exe",
        "qgis_process",
        "qgis_process-qgis.exe",
        "qgis_process-qgis.bat",
    ):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    roots = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(r"C:\OSGeo4W"),
    ]
    patterns = (
        "QGIS*/bin/qgis_process*.exe",
        "QGIS*/bin/qgis_process*.bat",
        "bin/qgis_process*.exe",
        "bin/qgis_process*.bat",
    )
    for root in roots:
        if not root.exists():
            continue
        for pattern in patterns:
            candidates.extend(sorted(root.glob(pattern), reverse=True))
    return _existing(candidates)


def _grass_candidates() -> list[Path]:
    candidates: list[str | Path] = []
    env = os.environ.get("SURVEYSYNC_GRASS", "")
    if env:
        candidates.append(env)
    for name in (
        "grass.exe",
        "grass",
        "grass.bat",
        "grass85.bat",
        "grass84.bat",
        "grass83.bat",
    ):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    roots = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(r"C:\OSGeo4W"),
    ]
    patterns = (
        "GRASS GIS*/grass*.bat",
        "GRASS GIS*/grass*.exe",
        "QGIS*/apps/grass/grass*.bat",
        "apps/grass/grass*.bat",
    )
    for root in roots:
        if not root.exists():
            continue
        for pattern in patterns:
            candidates.extend(sorted(root.glob(pattern), reverse=True))
    return _existing(candidates)


def find_qgis_process(explicit: str | Path | None = None) -> Path | None:
    candidates = _existing([explicit]) if explicit else _qgis_candidates()
    return candidates[0] if candidates else None


def find_grass(explicit: str | Path | None = None) -> Path | None:
    candidates = _existing([explicit]) if explicit else _grass_candidates()
    return candidates[0] if candidates else None


def _external_environment() -> dict[str, str]:
    """Do not inject SurveySync's Python runtime into separately installed GIS."""
    env = dict(os.environ)
    for name in (
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONUSERBASE",
        "VIRTUAL_ENV",
        "__PYVENV_LAUNCHER__",
    ):
        env.pop(name, None)
    roots = []
    for prefix in (sys.prefix, sys.base_prefix):
        root = Path(prefix).resolve()
        if str(root) not in {"/", "/usr", "/usr/local"}:
            roots.append(root)
    for name in ("PATH", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        if name not in env:
            continue
        kept = []
        for entry in env[name].split(os.pathsep):
            if not entry:
                continue
            candidate = Path(entry).resolve()
            if not any(candidate.is_relative_to(root) for root in roots):
                kept.append(entry)
        if kept:
            env[name] = os.pathsep.join(kept)
        else:
            env.pop(name, None)
    return env


def _grass_temporary_flag(executable: Path) -> str:
    help_result = _run([str(executable), "--help"], timeout_seconds=20)
    help_text = help_result["stdout"] + "\n" + help_result["stderr"]
    for flag in ("--tmp-project", "--tmp-location"):
        if flag in help_text:
            return flag
    raise GisBridgeError("GRASS launcher does not advertise a supported temporary-project option.")


def _run(
    command: list[str],
    *,
    timeout_seconds: int,
    cwd: str | Path | None = None,
) -> dict[str, Any]:
    if Path(command[0]).suffix.lower() in {".bat", ".cmd"} and any(
        any(c in value for c in '&|<>^%!\r\n"') for value in command[1:]
    ):
        raise GisBridgeError(
            "Unsafe characters for a Windows batch launcher; use a native executable or simpler paths."
        )
    timeout = max(5, min(int(timeout_seconds), 3600))
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
            cwd=str(Path(cwd).expanduser().resolve()) if cwd else None,
            shell=False,
            env=_external_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        raise GisBridgeError(f"GIS process timed out after {timeout} seconds.") from exc
    except OSError as exc:
        raise GisBridgeError(f"GIS process could not start: {exc}") from exc

    stdout = str(completed.stdout or "")
    stderr = str(completed.stderr or "")
    if len(stdout) > _MAX_OUTPUT:
        stdout = stdout[:_MAX_OUTPUT] + "\n...[output truncated]"
    if len(stderr) > _MAX_OUTPUT:
        stderr = stderr[:_MAX_OUTPUT] + "\n...[output truncated]"
    return {
        "return_code": int(completed.returncode),
        "stdout": stdout,
        "stderr": stderr,
        "command": command,
    }


def _version(executable: Path, args: list[str]) -> str:
    try:
        result = _run([str(executable), *args], timeout_seconds=20)
    except GisBridgeError:
        return ""
    text = (result["stdout"] or result["stderr"]).strip()
    return text.splitlines()[0][:300] if text else ""


def bridge_status(qgis_executable=None, grass_executable=None) -> dict[str, Any]:
    qgis = find_qgis_process(qgis_executable)
    grass = find_grass(grass_executable)
    return {
        "qgis": {
            "ready": bool(qgis),
            "path": str(qgis or ""),
            "version": _version(qgis, ["--version"]) if qgis else "",
            "integration": "external qgis_process",
        },
        "grass": {
            "ready": bool(grass),
            "path": str(grass or ""),
            "version": _version(grass, ["--version"]) if grass else "",
            "integration": "external grass temporary-project --exec",
        },
        "embedded_gpl_code": False,
        "shell_execution": False,
        "note": (
            "QGIS and GRASS are optional external processing engines. SurveySync "
            "does not vendor or import their GPL application code."
        ),
    }


def qgis_algorithms(*, executable: str | Path | None = None) -> dict[str, Any]:
    exe = find_qgis_process(executable)
    if exe is None:
        raise GisBridgeError("QGIS qgis_process was not found.")
    result = _run([str(exe), "list"], timeout_seconds=120)
    if result["return_code"] != 0:
        raise GisBridgeError(
            "qgis_process list failed."
            + (f" {result['stderr'].strip()[-1000:]}" if result["stderr"].strip() else "")
        )
    algorithms = []
    for line in result["stdout"].splitlines():
        stripped = line.strip()
        if not stripped or " " not in stripped:
            continue
        candidate = stripped.split()[0]
        if ":" in candidate and _QGIS_ALGORITHM.fullmatch(candidate):
            algorithms.append(
                {
                    "id": candidate,
                    "label": stripped[len(candidate) :].strip(),
                }
            )
    return {
        "executable": str(exe),
        "count": len(algorithms),
        "algorithms": algorithms,
        "raw_output": result["stdout"] if not algorithms else "",
    }


def qgis_algorithm_help(
    algorithm_id: str,
    *,
    executable: str | Path | None = None,
) -> dict[str, Any]:
    algorithm = str(algorithm_id or "").strip()
    if not _QGIS_ALGORITHM.fullmatch(algorithm):
        raise GisBridgeError("Invalid QGIS algorithm ID.")
    exe = find_qgis_process(executable)
    if exe is None:
        raise GisBridgeError("QGIS qgis_process was not found.")
    result = _run([str(exe), "help", algorithm], timeout_seconds=120)
    if result["return_code"] != 0:
        raise GisBridgeError(
            f"QGIS algorithm help failed for {algorithm}."
            + (f" {result['stderr'].strip()[-1000:]}" if result["stderr"].strip() else "")
        )
    return {"algorithm_id": algorithm, "executable": str(exe), "help": result["stdout"]}


def _parameter_args(parameters: dict[str, Any]) -> list[str]:
    args = []
    for key, value in parameters.items():
        name = str(key or "").strip()
        if not _PARAM_NAME.fullmatch(name):
            raise GisBridgeError(f"Invalid processing parameter name: {key}")
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif value is None:
            rendered = ""
        elif isinstance(value, float) and not math.isfinite(value):
            raise GisBridgeError(f"Processing parameter {name} must be finite.")
        elif isinstance(value, (str, int, float)):
            rendered = str(value)
        else:
            raise GisBridgeError(
                f"Processing parameter {name} must be a string, number, boolean, or null."
            )
        args.append(f"{name}={rendered}")
    return args


def run_qgis_algorithm(
    project: SurveyProject,
    algorithm_id: str,
    parameters: dict[str, Any],
    *,
    timeout_seconds: int = 600,
    executable: str | Path | None = None,
) -> dict[str, Any]:
    algorithm = str(algorithm_id or "").strip()
    if not _QGIS_ALGORITHM.fullmatch(algorithm):
        raise GisBridgeError("Invalid QGIS algorithm ID.")
    exe = find_qgis_process(executable)
    if exe is None:
        raise GisBridgeError("QGIS qgis_process was not found.")
    args = _parameter_args(parameters)
    command = [str(exe), "run", algorithm, "--", *args]
    result = _run(command, timeout_seconds=timeout_seconds, cwd=project.paths.root)
    parsed = None
    stripped = result["stdout"].strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
    project.db.audit(
        "GISSync",
        "QGIS_PROCESS_RUN",
        object_type="external_processing",
        object_id=algorithm,
        details={
            "algorithm_id": algorithm,
            "parameters": parameters,
            "return_code": result["return_code"],
            "executable": str(exe),
        },
    )
    return {**result, "algorithm_id": algorithm, "parsed_output": parsed}


def run_grass_module(
    project: SurveyProject,
    module: str,
    parameters: dict[str, Any],
    *,
    flags: list[str] | None = None,
    crs: str = "",
    timeout_seconds: int = 600,
    executable: str | Path | None = None,
) -> dict[str, Any]:
    module_name = str(module or "").strip()
    if not _GRASS_MODULE.fullmatch(module_name):
        raise GisBridgeError("GRASS module must be a standard g.*, r.*, v.*, db.*, or i.* module.")
    exe = find_grass(executable)
    if exe is None:
        raise GisBridgeError("GRASS GIS launcher was not found.")
    project_crs = str(crs or project.manifest.get("crs") or "").strip()
    if not project_crs:
        raise GisBridgeError("A CRS is required to create the temporary GRASS project.")

    clean_flags = []
    for flag in flags or []:
        value = str(flag or "").strip().lstrip("-")
        if not re.fullmatch(r"[A-Za-z]+", value):
            raise GisBridgeError(f"Invalid GRASS flag: {flag}")
        clean_flags.append("-" + value)

    parameter_args = _parameter_args(parameters)
    command = [
        str(exe),
        _grass_temporary_flag(exe),
        project_crs,
        "--exec",
        module_name,
        *clean_flags,
        *parameter_args,
    ]
    result = _run(command, timeout_seconds=timeout_seconds, cwd=project.paths.root)
    project.db.audit(
        "GISSync",
        "GRASS_PROCESS_RUN",
        object_type="external_processing",
        object_id=module_name,
        details={
            "module": module_name,
            "parameters": parameters,
            "flags": clean_flags,
            "crs": project_crs,
            "return_code": result["return_code"],
            "executable": str(exe),
        },
    )
    return {**result, "module": module_name, "crs": project_crs}
