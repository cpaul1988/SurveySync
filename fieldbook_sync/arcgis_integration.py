from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .exporter import export_shapefiles_to_folder
from .models import AppState

log = logging.getLogger(__name__)
_JSON_PREFIX = "FBS_JSON:"


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        key = os.path.normcase(str(p))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _candidate_pro_roots() -> list[Path]:
    roots: list[Path] = []
    for env_name in ("ProgramFiles", "PROGRAMFILES", "LOCALAPPDATA"):
        raw = os.environ.get(env_name)
        if raw:
            base = Path(raw)
            roots.extend([base / "ArcGIS" / "Pro", base / "Programs" / "ArcGIS" / "Pro"])
    if sys.platform == "win32":
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for key_name in (r"SOFTWARE\ESRI\ArcGISPro", r"SOFTWARE\WOW6432Node\ESRI\ArcGISPro"):
                    try:
                        with winreg.OpenKey(hive, key_name) as key:
                            for value_name in ("InstallDir", "InstallLocation"):
                                try:
                                    value, _ = winreg.QueryValueEx(key, value_name)
                                    if value:
                                        roots.append(Path(value))
                                except OSError:
                                    pass
                    except OSError:
                        pass
        except Exception:
            logging.getLogger(__name__).warning("Recovery fallback in arcgis_integration; operation did not complete.", exc_info=True)
    return _dedupe_paths(roots)


def find_arcgis_pro() -> dict[str, Any]:
    override = os.environ.get("ARCGIS_PRO_HOME", "").strip()
    roots = ([Path(override)] if override else []) + _candidate_pro_roots()
    for root in roots:
        propy = root / "bin" / "Python" / "scripts" / "propy.bat"
        exe = root / "bin" / "ArcGISPro.exe"
        if propy.exists():
            return {
                "installed": True,
                "product": "pro",
                "display_name": "ArcGIS Pro",
                "install_dir": str(root),
                "python": str(propy),
                "propy": str(propy),
                "exe": str(exe) if exe.exists() else None,
                "arcgis_exe": str(exe) if exe.exists() else None,
            }
    return {
        "installed": False,
        "product": "pro",
        "display_name": "ArcGIS Pro",
        "install_dir": None,
        "python": None,
        "propy": None,
        "exe": None,
        "arcgis_exe": None,
    }


def _desktop_registry_entries() -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    if sys.platform != "win32":
        return entries
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for base_name in (r"SOFTWARE\ESRI", r"SOFTWARE\WOW6432Node\ESRI"):
                try:
                    with winreg.OpenKey(hive, base_name) as base:
                        i = 0
                        while True:
                            try:
                                sub = winreg.EnumKey(base, i)
                                i += 1
                            except OSError:
                                break
                            if not sub.lower().startswith("desktop10"):
                                continue
                            try:
                                with winreg.OpenKey(base, sub) as key:
                                    install = None
                                    for value_name in ("InstallDir", "InstallLocation"):
                                        try:
                                            value, _ = winreg.QueryValueEx(key, value_name)
                                            if value:
                                                install = Path(value)
                                                break
                                        except OSError:
                                            pass
                                    version = sub[len("Desktop"):]
                                    try:
                                        real, _ = winreg.QueryValueEx(key, "RealVersion")
                                        if real:
                                            version = str(real)
                                    except OSError:
                                        pass
                                    if install:
                                        entries.append((version, install))
                            except OSError:
                                pass
                except OSError:
                    pass
    except Exception:
        logging.getLogger(__name__).warning("Recovery fallback in arcgis_integration; operation did not complete.", exc_info=True)
    return entries


def _version_sort_key(value: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", value or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def _candidate_desktop_pythons(version: str | None = None, install_dir: Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get("ARCGIS_DESKTOP_PYTHON", "").strip()
    if override:
        candidates.append(Path(override))
    system_drive = os.environ.get("SystemDrive", "C:")
    roots = [Path(system_drive + os.sep) / "Python27", Path(system_drive + os.sep) / "Python26"]
    if version:
        short = ".".join(re.findall(r"\d+", version)[:2])
        for root in roots:
            candidates.extend([
                root / ("ArcGIS" + short) / "python.exe",
                root / ("ArcGISx64" + short) / "python.exe",
            ])
    for root in roots:
        if root.exists():
            try:
                candidates.extend(sorted(root.glob("ArcGIS10*/python.exe"), reverse=True))
                candidates.extend(sorted(root.glob("ArcGISx6410*/python.exe"), reverse=True))
            except Exception:
                logging.getLogger(__name__).warning("Recovery fallback in arcgis_integration; operation did not complete.", exc_info=True)
    if install_dir:
        candidates.extend([
            install_dir / "Python27" / "python.exe",
            install_dir / "Python26" / "python.exe",
            install_dir / "bin" / "Python" / "python.exe",
        ])
    return _dedupe_paths(candidates)


def find_arcgis_desktop() -> dict[str, Any]:
    override_home = os.environ.get("ARCGIS_DESKTOP_HOME", "").strip()
    entries = _desktop_registry_entries()
    if override_home:
        entries.insert(0, (os.environ.get("ARCGIS_DESKTOP_VERSION", "10.x"), Path(override_home)))
    entries.sort(key=lambda item: _version_sort_key(item[0]), reverse=True)

    # Registry-backed detection is preferred because ArcMap can be installed outside C:\Program Files.
    for version, install in entries:
        arcmap_candidates = [install / "bin" / "ArcMap.exe", install / "ArcMap.exe"]
        arcmap = next((p for p in arcmap_candidates if p.exists()), None)
        python_exe = next((p for p in _candidate_desktop_pythons(version, install) if p.exists()), None)
        if arcmap or python_exe:
            return {
                "installed": bool(python_exe),
                "product": "desktop",
                "display_name": "ArcGIS Desktop / ArcMap 10.x",
                "version": version,
                "install_dir": str(install),
                "python": str(python_exe) if python_exe else None,
                "exe": str(arcmap) if arcmap else None,
                "arcmap_exe": str(arcmap) if arcmap else None,
                "note": None if python_exe else "ArcMap was detected, but its ArcPy Python environment was not found.",
            }

    # Last-resort default-location detection for machines with incomplete registry entries.
    for p in _candidate_desktop_pythons():
        if p.exists():
            version_match = re.search(r"ArcGIS(?:x64)?(10(?:\.\d+)*)", str(p), re.I)
            version = version_match.group(1) if version_match else "10.x"
            arcmap = None
            for pf_name in ("ProgramFiles(x86)", "ProgramFiles"):
                raw = os.environ.get(pf_name)
                if not raw:
                    continue
                root = Path(raw) / "ArcGIS" / ("Desktop" + version)
                candidate = root / "bin" / "ArcMap.exe"
                if candidate.exists():
                    arcmap = candidate
                    break
            return {
                "installed": True,
                "product": "desktop",
                "display_name": "ArcGIS Desktop / ArcMap 10.x",
                "version": version,
                "install_dir": str(arcmap.parent.parent) if arcmap else None,
                "python": str(p),
                "exe": str(arcmap) if arcmap else None,
                "arcmap_exe": str(arcmap) if arcmap else None,
                "note": None,
            }

    return {
        "installed": False,
        "product": "desktop",
        "display_name": "ArcGIS Desktop / ArcMap 10.x",
        "version": None,
        "install_dir": None,
        "python": None,
        "exe": None,
        "arcmap_exe": None,
        "note": None,
    }


def find_arcgis_products() -> dict[str, Any]:
    pro = find_arcgis_pro()
    desktop = find_arcgis_desktop()
    return {
        "installed": bool(pro["installed"] or desktop["installed"]),
        "pro": pro,
        "desktop": desktop,
        "products": [p for p in (pro, desktop) if p["installed"]],
    }


def _bridge_path(app_root: Path, product: str) -> Path:
    filename = "arcgis_bridge.py" if product == "pro" else "arcgis_desktop_bridge.py"
    p = app_root / filename
    if not p.exists():
        raise RuntimeError(f"ArcGIS bridge helper is missing: {p}")
    return p


def _parse_bridge_response(proc: subprocess.CompletedProcess[str], product_name: str) -> dict[str, Any]:
    combined = "\n".join(x for x in [proc.stdout, proc.stderr] if x).strip()
    payload = None
    for line in reversed((proc.stdout or "").splitlines()):
        if line.startswith(_JSON_PREFIX):
            try:
                payload = json.loads(line[len(_JSON_PREFIX):])
            except Exception:
                payload = None
            break
    if payload is None:
        raise RuntimeError(f"{product_name} did not return a valid response.\n{combined[-3000:]}")
    if not payload.get("ok"):
        detail = payload.get("detail") or ""
        raise RuntimeError((payload.get("error") or f"{product_name} operation failed.") + (f"\n{detail}" if detail else ""))
    return payload


def _run_propy(app_root: Path, args: list[str], timeout: int = 120) -> dict[str, Any]:
    info = find_arcgis_pro()
    if not info["installed"] or not info["propy"]:
        raise RuntimeError("ArcGIS Pro was not detected on this computer.")
    bridge = _bridge_path(app_root, "pro")
    command_args = [str(info["propy"]), str(bridge), *args]
    if os.name == "nt":
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        cmd = [comspec, "/d", "/s", "/c", subprocess.list2cmdline(command_args)]
    else:
        cmd = command_args
    log.debug("ArcGIS Pro bridge command: %s", command_args)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    return _parse_bridge_response(proc, "ArcGIS Pro")


def _run_arcmap_python(app_root: Path, args: list[str], timeout: int = 120) -> dict[str, Any]:
    info = find_arcgis_desktop()
    python_exe = info.get("python")
    if not info["installed"] or not python_exe:
        raise RuntimeError("ArcGIS Desktop / ArcMap 10.x with ArcPy was not detected on this computer.")
    bridge = _bridge_path(app_root, "desktop")
    command_args = [str(python_exe), str(bridge), *args]
    log.debug("ArcMap bridge command: %s", command_args)
    proc = subprocess.run(command_args, capture_output=True, text=True, timeout=timeout, check=False)
    return _parse_bridge_response(proc, "ArcMap")


def _project_type(project_path: str | Path) -> str:
    suffix = Path(project_path).suffix.lower()
    if suffix == ".aprx":
        return "pro"
    if suffix == ".mxd":
        return "desktop"
    raise ValueError("Choose an ArcGIS Pro .aprx project or an ArcMap .mxd document.")


def list_project_maps(app_root: Path, project_path: str) -> dict[str, Any]:
    path = Path(project_path).expanduser()
    product = _project_type(path)
    if not path.is_absolute() or not path.exists():
        raise ValueError("Choose an existing ArcGIS Pro .aprx project or ArcMap .mxd document.")
    if product == "pro":
        payload = _run_propy(app_root, ["list-maps", str(path)], timeout=90)
        payload.setdefault("project_type", "pro")
        return payload
    payload = _run_arcmap_python(app_root, ["list-maps", str(path)], timeout=90)
    payload.setdefault("project_type", "arcmap")
    return payload


def _safe_project_folder_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", (name or "FieldBookSync").strip()).strip(" .")
    return name[:80] or "FieldBookSync"


def _backup_project(project: Path) -> Path:
    backup_dir = project.parent / "FieldBookSync_Backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"{project.stem}_before_FieldBookSync_{stamp}{project.suffix}"
    shutil.copy2(project, backup)
    return backup


def export_to_arcgis(
    state: AppState,
    app_root: Path,
    output_folder: str,
    *,
    project_path: str | None = None,
    aprx_path: str | None = None,  # backward compatibility with v6.x callers
    map_name: str | None = None,
    include_network: bool = True,
    assign_map_crs: bool = False,
    replace_existing: bool = True,
    create_project_subfolder: bool = True,
    backup_project: bool = True,
    backup_aprx: bool | None = None,  # backward compatibility
    open_project_after: bool = False,
) -> dict[str, Any]:
    folder = Path(output_folder).expanduser()
    if not folder.is_absolute():
        raise ValueError("The Shapefile output location must be an absolute folder path.")
    folder.mkdir(parents=True, exist_ok=True)
    if create_project_subfolder:
        folder = folder / _safe_project_folder_name(state.project_name)
        folder.mkdir(parents=True, exist_ok=True)

    shp = export_shapefiles_to_folder(state, folder, include_network=include_network)
    structures = shp["structures"]
    network = shp.get("network")
    result: dict[str, Any] = {
        "ok": True,
        "output_folder": str(folder),
        "shapefiles": shp,
        "added_to_arcgis": False,
        "backup_project": None,
        "backup_aprx": None,
        "project_type": None,
    }

    target_project = project_path or aprx_path
    if target_project:
        if not map_name:
            raise ValueError("Choose a map/data frame before adding the Shapefiles.")
        project = Path(target_project).expanduser()
        product = _project_type(project)
        if not project.is_absolute() or not project.exists():
            raise ValueError("Choose an existing ArcGIS Pro .aprx project or ArcMap .mxd document.")
        result["project_type"] = "pro" if product == "pro" else "arcmap"

        do_backup = backup_project if backup_aprx is None else backup_aprx
        if do_backup:
            backup = _backup_project(project)
            result["backup_project"] = str(backup)
            result["backup_aprx"] = str(backup) if product == "pro" else None

        if product == "pro":
            args = [
                "add-layers", "--aprx", str(project), "--map", map_name,
                "--structures", structures,
            ]
            if include_network and network:
                args += ["--network", network]
            if assign_map_crs:
                args += ["--assign-map-crs"]
            if replace_existing:
                args += ["--replace-existing"]
            bridge_result = _run_propy(app_root, args, timeout=180)
            product_info = find_arcgis_pro()
        else:
            args = [
                "add-layers", "--mxd", str(project), "--map", map_name,
                "--structures", structures,
            ]
            if include_network and network:
                args += ["--network", network]
            if assign_map_crs:
                args += ["--assign-map-crs"]
            if replace_existing:
                args += ["--replace-existing"]
            bridge_result = _run_arcmap_python(app_root, args, timeout=180)
            product_info = find_arcgis_desktop()

        result["added_to_arcgis"] = True
        result["arcgis"] = bridge_result

        if open_project_after:
            exe = product_info.get("exe")
            try:
                if exe and Path(exe).exists():
                    subprocess.Popen([str(exe), str(project)], close_fds=True)
                elif os.name == "nt":
                    os.startfile(str(project))  # type: ignore[attr-defined]
                else:
                    raise RuntimeError("No ArcGIS application executable was found.")
                result["opened_project"] = True
            except Exception as exc:
                result["opened_project"] = False
                result["open_warning"] = str(exc)
    return result
