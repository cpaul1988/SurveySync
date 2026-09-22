# -*- coding: utf-8 -*-
"""ArcGIS Pro helper: export File Geodatabase feature classes to temporary WGS84 GeoJSON."""
from __future__ import print_function
import json, os, sys, tempfile

def main():
    if len(sys.argv) < 3:
        return 2
    gdb, out_path = sys.argv[1], sys.argv[2]
    wanted = sys.argv[3] if len(sys.argv) > 3 else None
    try:
        import arcpy
        old = arcpy.env.workspace
        arcpy.env.workspace = gdb
        names = []
        for fc in arcpy.ListFeatureClasses() or []:
            names.append(fc)
        for ds in arcpy.ListDatasets(feature_type='feature') or []:
            for fc in arcpy.ListFeatureClasses(feature_dataset=ds) or []:
                names.append(os.path.join(ds, fc))
        if wanted:
            names = [n for n in names if n == wanted or os.path.basename(n) == wanted]
        layers = []
        with tempfile.TemporaryDirectory(prefix='fbs_gdb_json_') as td:
            for i, name in enumerate(names[:100]):
                src = os.path.join(gdb, name)
                dst = os.path.join(td, 'layer_%03d.geojson' % i)
                desc = arcpy.Describe(src)
                sr = getattr(desc, 'spatialReference', None)
                source_crs = ''
                try:
                    if sr and int(getattr(sr, 'factoryCode', 0) or 0):
                        source_crs = 'EPSG:%d' % int(sr.factoryCode)
                    elif sr:
                        source_crs = sr.name
                except Exception:
                    pass
                arcpy.conversion.FeaturesToJSON(src, dst, geoJSON='GEOJSON', outputToWGS84='WGS84')
                with open(dst, 'r', encoding='utf-8') as f:
                    geo = json.load(f)
                layers.append({'name': os.path.basename(name), 'source_crs': source_crs, 'geojson': geo})
        arcpy.env.workspace = old
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump({'ok': True, 'layers': layers}, f, ensure_ascii=True)
        return 0
    except Exception as exc:
        try:
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump({'ok': False, 'error': repr(exc)}, f, ensure_ascii=True)
        except Exception:
            pass
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
