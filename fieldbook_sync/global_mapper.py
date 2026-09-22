from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

GM_TYPE_RE = re.compile(r"^[A-Z0-9_./+-]{1,80}$")
EXT_RE = re.compile(r"^\.[A-Za-z0-9]{1,12}$")


def _candidate_paths() -> list[Path]:
    found: list[Path] = []
    env = str(os.environ.get("GLOBAL_MAPPER_EXE") or "").strip().strip('"')
    if env:
        found.append(Path(env))
    which = shutil.which("global_mapper.exe") or shutil.which("global_mapper64.exe")
    if which:
        found.append(Path(which))
    roots = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("LOCALAPPDATA"),
    ]
    patterns = (
        "GlobalMapper*/global_mapper.exe",
        "Global Mapper*/global_mapper.exe",
        "GlobalMapper*/global_mapper64.exe",
        "Global Mapper*/global_mapper64.exe",
        "Programs/GlobalMapper*/global_mapper.exe",
    )
    for root in roots:
        if not root:
            continue
        rp = Path(root)
        if not rp.exists():
            continue
        for pattern in patterns:
            try:
                found.extend(sorted(rp.glob(pattern), reverse=True))
            except OSError:
                continue
    # Preserve order while de-duplicating.
    out: list[Path] = []
    seen: set[str] = set()
    for p in found:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def find_global_mapper() -> Path | None:
    for path in _candidate_paths():
        try:
            if path.is_file():
                return path.resolve()
        except OSError:
            continue
    return None


def status() -> dict[str, Any]:
    exe = find_global_mapper()
    return {
        "installed": bool(exe),
        "executable": str(exe) if exe else "",
        "mode": "Global Mapper scripting bridge" if exe else "Native FieldBook Sync formats only",
        "environment_override": str(os.environ.get("GLOBAL_MAPPER_EXE") or ""),
    }


def _gms_quote(value: str | Path) -> str:
    # Global Mapper's script language accepts quoted Windows paths. Reject line
    # breaks so an uploaded filename can never inject another script command.
    text = str(value)
    if "\r" in text or "\n" in text or '"' in text:
        raise ValueError("Global Mapper paths cannot contain line breaks or quote characters.")
    return '"' + text + '"'


def _validate_export_type(export_type: str) -> str:
    value = str(export_type or "").strip().upper()
    if not GM_TYPE_RE.fullmatch(value):
        raise ValueError("Global Mapper export TYPE must contain only letters, numbers, underscore, dot, slash, plus, or dash.")
    return value


def _validate_extension(extension: str) -> str:
    value = str(extension or "").strip()
    if value and not value.startswith("."):
        value = "." + value
    if not EXT_RE.fullmatch(value):
        raise ValueError("Output extension must look like .dwg, .tif, .las, .csv, or .geojson.")
    return value.lower()


def run_conversion(
    input_path: Path,
    output_path: Path,
    *,
    export_type: str,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    exe = find_global_mapper()
    if not exe:
        raise RuntimeError(
            "Global Mapper was not found. Install Global Mapper or set GLOBAL_MAPPER_EXE to its executable path."
        )
    if not input_path.is_file():
        raise ValueError(f"Input file does not exist: {input_path.name}")
    typ = _validate_export_type(export_type)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    script = "\n".join([
        "GLOBAL_MAPPER_SCRIPT VERSION=1.00 ENABLE_PROGRESS=NO SHOW_WARNINGS=NO LOG_TO_COMMAND_PROMPT=YES",
        f"IMPORT FILENAME={_gms_quote(input_path.resolve())}",
        f"EXPORT_ANY TYPE={typ} FILENAME={_gms_quote(output_path.resolve())}",
        "UNLOAD_ALL",
        "",
    ])
    with tempfile.TemporaryDirectory(prefix="fbs_gm_") as td:
        gms = Path(td) / "fieldbook_sync_convert.gms"
        gms.write_text(script, encoding="utf-8")
        try:
            proc = subprocess.run(
                [str(exe), str(gms)],
                cwd=str(input_path.parent),
                capture_output=True,
                text=True,
                timeout=max(30, int(timeout_seconds)),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Global Mapper conversion timed out after {timeout_seconds} seconds.") from exc
        except OSError as exc:
            raise RuntimeError(f"Global Mapper could not be started: {exc}") from exc
    if not output_path.exists() or output_path.stat().st_size <= 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
        suffix = f" Details: {detail}" if detail else ""
        raise RuntimeError(f"Global Mapper did not create the requested output ({typ}).{suffix}")
    return {
        "ok": True,
        "export_type": typ,
        "input": input_path.name,
        "output": output_path.name,
        "size_bytes": output_path.stat().st_size,
        "return_code": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-4000:],
    }


def convert_vector_to_geojson(input_path: Path, output_path: Path) -> dict[str, Any]:
    return run_conversion(input_path, output_path, export_type="GEOJSON")


def output_name(input_name: str, export_type: str, extension: str) -> str:
    typ = _validate_export_type(export_type)
    ext = _validate_extension(extension)
    stem = Path(input_name or "converted").stem or "converted"
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" .") or "converted"
    return f"{safe}_{typ.lower()}{ext}"
