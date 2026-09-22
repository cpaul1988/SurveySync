"""ArcGIS Pro bridge for FieldBook Sync.

This file is intentionally dependency-light and is executed by ArcGIS Pro's own
Python environment (propy.bat), not by the FieldBook Sync virtual environment.
It prints one machine-readable line prefixed with ``FBS_JSON:``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def emit(payload: dict) -> None:
    print("FBS_JSON:" + json.dumps(payload, ensure_ascii=False))


def fail(message: str, *, detail: str | None = None, code: int = 2) -> int:
    emit({"ok": False, "error": message, "detail": detail or ""})
    return code


def _map_info(m) -> dict:
    sr = getattr(m, "spatialReference", None)
    return {
        "name": m.name,
        "spatial_reference": getattr(sr, "name", "Unknown") if sr else "Unknown",
        "wkid": int(getattr(sr, "factoryCode", 0) or 0) if sr else 0,
        "map_type": getattr(m, "mapType", "MAP"),
    }


def list_maps(aprx_path: str) -> int:
    try:
        import arcpy
    except Exception as exc:
        return fail("ArcPy could not be imported from the ArcGIS Pro Python environment.", detail=str(exc))

    p = Path(aprx_path)
    if not p.exists() or p.suffix.lower() != ".aprx":
        return fail("The selected ArcGIS Pro project does not exist or is not an .aprx file.")
    try:
        aprx = arcpy.mp.ArcGISProject(str(p))
        maps = [_map_info(m) for m in aprx.listMaps()]
        emit({"ok": True, "project": str(p), "read_only": bool(aprx.isReadOnly), "maps": maps})
        return 0
    except Exception as exc:
        return fail("ArcGIS Pro could not read the selected project.", detail=repr(exc))


def _same_path(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except Exception:
        return False


def add_layers(
    aprx_path: str,
    map_name: str,
    structures_path: str,
    network_path: str | None,
    assign_map_crs: bool,
    replace_existing: bool,
) -> int:
    try:
        import arcpy
    except Exception as exc:
        return fail("ArcPy could not be imported from the ArcGIS Pro Python environment.", detail=str(exc))

    aprx_file = Path(aprx_path)
    shp_paths = [Path(structures_path)] + ([Path(network_path)] if network_path else [])
    if not aprx_file.exists() or aprx_file.suffix.lower() != ".aprx":
        return fail("The selected ArcGIS Pro project does not exist or is not an .aprx file.")
    missing = [str(p) for p in shp_paths if not p.exists()]
    if missing:
        return fail("One or more exported shapefiles are missing.", detail="; ".join(missing))

    try:
        aprx = arcpy.mp.ArcGISProject(str(aprx_file))
        if aprx.isReadOnly:
            return fail(
                "The ArcGIS Pro project opened read-only. Close other ArcGIS Pro sessions using this project and try again."
            )
        maps = [m for m in aprx.listMaps() if m.name == map_name]
        if not maps:
            return fail(f"Map '{map_name}' was not found in the selected ArcGIS Pro project.")
        m = maps[0]
        map_sr = getattr(m, "spatialReference", None)

        if assign_map_crs:
            if not map_sr or not getattr(map_sr, "name", None) or map_sr.name in {"Unknown", "Unknown Coordinate System"}:
                return fail("The selected map has an unknown coordinate system, so it cannot be assigned to the shapefiles.")
            for shp in shp_paths:
                arcpy.management.DefineProjection(str(shp), map_sr)

        added = []
        for shp in shp_paths:
            if replace_existing:
                for lyr in list(m.listLayers()):
                    try:
                        if getattr(lyr, "supports", lambda _x: False)("DATASOURCE") and _same_path(lyr.dataSource, str(shp)):
                            m.removeLayer(lyr)
                    except Exception:
                        continue
            lyr = m.addDataFromPath(str(shp))
            try:
                if shp.stem.lower() == "structures":
                    lyr.name = "FieldBook Sync - Structures"
                elif shp.stem.lower() == "network_connections":
                    lyr.name = "FieldBook Sync - Network Connections"
            except Exception:
                pass
            added.append({"path": str(shp), "layer_name": getattr(lyr, "name", shp.stem)})

        aprx.save()
        emit({
            "ok": True,
            "project": str(aprx_file),
            "map": _map_info(m),
            "assigned_map_crs": bool(assign_map_crs),
            "added": added,
        })
        return 0
    except Exception as exc:
        return fail("ArcGIS Pro could not add/save the exported shapefiles.", detail=repr(exc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_maps = sub.add_parser("list-maps")
    p_maps.add_argument("aprx")

    p_add = sub.add_parser("add-layers")
    p_add.add_argument("--aprx", required=True)
    p_add.add_argument("--map", required=True, dest="map_name")
    p_add.add_argument("--structures", required=True)
    p_add.add_argument("--network", default="")
    p_add.add_argument("--assign-map-crs", action="store_true")
    p_add.add_argument("--replace-existing", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "list-maps":
        return list_maps(args.aprx)
    if args.command == "add-layers":
        return add_layers(
            args.aprx,
            args.map_name,
            args.structures,
            args.network or None,
            args.assign_map_crs,
            args.replace_existing,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
