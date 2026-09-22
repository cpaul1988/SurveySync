# -*- coding: utf-8 -*-
"""ArcGIS Desktop / ArcMap 10.x bridge for FieldBook Sync.

This helper is intentionally written using Python 2.6/2.7-compatible syntax so it
can be executed by the Python environment installed with legacy ArcGIS Desktop 10.x.
It communicates with FieldBook Sync by printing one JSON line prefixed FBS_JSON:.
"""
from __future__ import print_function

import json
import os
import sys
import shutil
import tempfile

JSON_PREFIX = "FBS_JSON:"


def emit(payload):
    try:
        text = json.dumps(payload, ensure_ascii=True)
    except Exception:
        text = json.dumps({"ok": False, "error": "Could not encode ArcMap bridge response."})
    print(JSON_PREFIX + text)


def fail(message, detail="", code=2):
    emit({"ok": False, "error": message, "detail": detail or ""})
    return code


def _option(args, name, default=None):
    try:
        idx = args.index(name)
    except ValueError:
        return default
    if idx + 1 >= len(args):
        return default
    return args[idx + 1]


def _flag(args, name):
    return name in args


def _same_path(a, b):
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except Exception:
        return False


def _sr_info(sr):
    if sr is None:
        return {"spatial_reference": "Unknown", "wkid": 0}
    try:
        name = getattr(sr, "name", None) or "Unknown"
    except Exception:
        name = "Unknown"
    wkid = 0
    for attr in ("factoryCode", "PCSCode", "GCSCode"):
        try:
            value = int(getattr(sr, attr, 0) or 0)
            if value:
                wkid = value
                break
        except Exception:
            pass
    return {"spatial_reference": name, "wkid": wkid}


def list_maps(mxd_path):
    try:
        import arcpy
    except Exception as exc:
        return fail("ArcPy could not be imported from the ArcGIS Desktop Python environment.", repr(exc))

    if not os.path.isfile(mxd_path) or not mxd_path.lower().endswith(".mxd"):
        return fail("The selected ArcMap document does not exist or is not an .mxd file.")

    mxd = None
    try:
        mxd = arcpy.mapping.MapDocument(mxd_path)
        maps = []
        for df in arcpy.mapping.ListDataFrames(mxd):
            info = _sr_info(getattr(df, "spatialReference", None))
            maps.append({
                "name": df.name,
                "spatial_reference": info["spatial_reference"],
                "wkid": info["wkid"],
                "map_type": "DATA_FRAME",
            })
        emit({
            "ok": True,
            "project": mxd_path,
            "project_type": "arcmap",
            "read_only": False,
            "maps": maps,
        })
        return 0
    except Exception as exc:
        return fail("ArcMap could not read the selected MXD.", repr(exc))
    finally:
        try:
            del mxd
        except Exception:
            pass


def add_layers(mxd_path, data_frame_name, structures_path, network_path, assign_map_crs, replace_existing):
    try:
        import arcpy
    except Exception as exc:
        return fail("ArcPy could not be imported from the ArcGIS Desktop Python environment.", repr(exc))

    if not os.path.isfile(mxd_path) or not mxd_path.lower().endswith(".mxd"):
        return fail("The selected ArcMap document does not exist or is not an .mxd file.")
    shp_paths = [structures_path]
    if network_path:
        shp_paths.append(network_path)
    missing = [p for p in shp_paths if not os.path.isfile(p)]
    if missing:
        return fail("One or more exported shapefiles are missing.", "; ".join(missing))

    mxd = None
    try:
        mxd = arcpy.mapping.MapDocument(mxd_path)
        frames = [df for df in arcpy.mapping.ListDataFrames(mxd) if df.name == data_frame_name]
        if not frames:
            return fail("Data frame '%s' was not found in the selected ArcMap document." % data_frame_name)
        df = frames[0]
        map_sr = getattr(df, "spatialReference", None)
        sr_name = getattr(map_sr, "name", "Unknown") if map_sr else "Unknown"

        if assign_map_crs:
            if not map_sr or not sr_name or sr_name in ("Unknown", "Unknown Coordinate System"):
                return fail("The selected ArcMap data frame has an unknown coordinate system, so it cannot be assigned to the shapefiles.")
            for shp in shp_paths:
                arcpy.DefineProjection_management(shp, map_sr)

        added = []
        temp_dir = tempfile.mkdtemp(prefix="fbs_arcmap_")
        try:
            for index, shp in enumerate(shp_paths):
                if replace_existing:
                    for lyr in list(arcpy.mapping.ListLayers(mxd, "", df)):
                        try:
                            if lyr.supports("DATASOURCE") and _same_path(lyr.dataSource, shp):
                                arcpy.mapping.RemoveLayer(df, lyr)
                        except Exception:
                            pass

                base = os.path.splitext(os.path.basename(shp))[0].lower()
                if base == "structures":
                    display_name = "FieldBook Sync - Structures"
                elif base == "network_connections":
                    display_name = "FieldBook Sync - Network Connections"
                else:
                    display_name = os.path.splitext(os.path.basename(shp))[0]

                # arcpy.mapping.AddLayer requires a Layer object. ArcMap's Layer() function
                # is documented for .lyr files rather than raw shapefiles, so create a
                # temporary feature layer and save it as a .lyr first.
                gp_name = "FBS_%d" % index
                arcpy.MakeFeatureLayer_management(shp, gp_name)
                layer_file = os.path.join(temp_dir, "layer_%d.lyr" % index)
                arcpy.SaveToLayerFile_management(gp_name, layer_file, "ABSOLUTE")
                lyr = arcpy.mapping.Layer(layer_file)
                try:
                    lyr.name = display_name
                except Exception:
                    pass
                arcpy.mapping.AddLayer(df, lyr, "TOP")
                added.append({"path": shp, "layer_name": getattr(lyr, "name", display_name)})
        finally:
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

        mxd.save()
        sr = _sr_info(map_sr)
        emit({
            "ok": True,
            "project": mxd_path,
            "project_type": "arcmap",
            "map": {
                "name": df.name,
                "spatial_reference": sr["spatial_reference"],
                "wkid": sr["wkid"],
                "map_type": "DATA_FRAME",
            },
            "assigned_map_crs": bool(assign_map_crs),
            "added": added,
        })
        return 0
    except Exception as exc:
        return fail("ArcMap could not add/save the exported shapefiles.", repr(exc))
    finally:
        try:
            del mxd
        except Exception:
            pass


def main(argv=None):
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        return fail("No ArcMap bridge command was supplied.")
    command = args[0]
    rest = args[1:]
    if command == "list-maps":
        if not rest:
            return fail("An MXD path is required.")
        return list_maps(rest[0])
    if command == "add-layers":
        mxd = _option(rest, "--mxd", "")
        frame = _option(rest, "--map", "")
        structures = _option(rest, "--structures", "")
        network = _option(rest, "--network", "")
        if not mxd or not frame or not structures:
            return fail("MXD, data frame, and structures shapefile are required.")
        return add_layers(
            mxd,
            frame,
            structures,
            network or None,
            _flag(rest, "--assign-map-crs"),
            _flag(rest, "--replace-existing"),
        )
    return fail("Unknown ArcMap bridge command: %s" % command)


if __name__ == "__main__":
    sys.exit(main())
