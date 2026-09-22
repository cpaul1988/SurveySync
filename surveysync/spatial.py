from __future__ import annotations

import base64
import datetime as dt
import decimal
import json
import logging
import math
import sqlite3
import struct
from pathlib import Path
from typing import Any
from uuid import uuid4

from pyproj import CRS, Transformer

from .audit import AuditDB, utc_now
from .project import SurveyProject

logger = logging.getLogger(__name__)


def typed_json_value(value: Any) -> Any:
    """Convert common GIS attribute values to loss-aware JSON representations."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return {"__type__": type(value).__name__, "value": value.isoformat()}
    if isinstance(value, decimal.Decimal):
        return {"__type__": "decimal", "value": str(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__type__": "binary", "base64": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (list, tuple)):
        return [typed_json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): typed_json_value(v) for k, v in value.items()}
    return {"__type__": type(value).__name__, "value": str(value)}


def _field_type(value: Any) -> str:
    if value is None: return "null"
    if isinstance(value, bool): return "boolean"
    if isinstance(value, int): return "integer"
    if isinstance(value, float): return "float"
    if isinstance(value, str): return "text"
    if isinstance(value, dt.datetime): return "datetime"
    if isinstance(value, dt.date): return "date"
    if isinstance(value, dt.time): return "time"
    if isinstance(value, decimal.Decimal): return "decimal"
    if isinstance(value, (bytes, bytearray, memoryview)): return "binary"
    if isinstance(value, (list, tuple)): return "array"
    if isinstance(value, dict): return "object"
    return type(value).__name__


def infer_schema(features: list[dict]) -> dict:
    fields: dict[str, set[str]] = {}
    for feature in features:
        for key, value in (feature.get("properties") or {}).items():
            fields.setdefault(str(key), set()).add(_field_type(value))
    return {name: sorted(types) for name, types in sorted(fields.items())}


def _layer_payload(layer) -> dict:
    features = []
    for f in layer.features:
        raw_props = dict(f.properties or {})
        features.append({
            "type": "Feature",
            "id": f.feature_id,
            "geometry": f.geometry,
            "properties": {str(k): typed_json_value(v) for k, v in raw_props.items()},
            "_field_types": {str(k): _field_type(v) for k, v in raw_props.items()},
        })
    return {
        "type": "FeatureCollection",
        "name": layer.name,
        "source_name": layer.source_name,
        "source_type": layer.source_type,
        "source_crs": layer.source_crs,
        "geometry_types": list(layer.geometry_types),
        "bounds_wgs84": layer.bounds_wgs84,
        "warning": layer.warning,
        "features": features,
    }


def import_standard_layers(paths: list[Path], app_root: Path, project_crs: str | None = None) -> list[dict]:
    from fieldbook_sync.map_gis import import_map_files
    layers = import_map_files(paths, app_root, project_crs)
    return [_layer_payload(layer) for layer in layers]



# -- Lightweight ASCII DXF reader ---------------------------------------------

def _dxf_pairs(path: Path) -> list[tuple[int, str]]:
    lines=Path(path).read_text(encoding='utf-8',errors='replace').splitlines()
    pairs=[]
    for i in range(0,len(lines)-1,2):
        try:code=int(lines[i].strip())
        except Exception:continue
        pairs.append((code,lines[i+1].strip()))
    return pairs


def import_dxf(path: Path, source_crs: str | None) -> list[dict]:
    """Read common survey DXF entities without requiring a CAD runtime.

    POINT, LINE and LWPOLYLINE are imported directly. ARC and CIRCLE are sampled
    into line strings for reference/QC display. Coordinates are treated as the
    explicitly configured project/source CRS and converted to WGS84 for the
    shared GIS workspace. DWG remains a native-CAD/bridge workflow because it is
    a proprietary binary format and SurveySync will not pretend to parse it.
    """
    pairs=_dxf_pairs(path)
    in_entities=False;entities=[];current=None
    for code,value in pairs:
        if code==0 and value=='SECTION':
            current=None;continue
        if code==2 and value=='ENTITIES':in_entities=True;continue
        if code==0 and value=='ENDSEC' and in_entities:
            if current:
                entities.append(current)
            in_entities=False;current=None;continue
        if not in_entities:continue
        if code==0:
            if current:entities.append(current)
            current={'type':value.upper(),'data':[]}
        elif current is not None:current['data'].append((code,value))
    if current:entities.append(current)
    transformer=None
    if source_crs:
        try:
            src=CRS.from_user_input(source_crs)
            if src != CRS.from_epsg(4326):transformer=Transformer.from_crs(src,CRS.from_epsg(4326),always_xy=True)
        except Exception as exc:raise ValueError(f'DXF import needs a valid project/source CRS: {exc}') from exc
    else:raise ValueError('Set the project CRS before importing DXF so CAD coordinates are not guessed.')

    def xy(x,y):
        if transformer:return list(transformer.transform(float(x),float(y)))
        return [float(x),float(y)]
    features=[]
    for idx,ent in enumerate(entities,start=1):
        typ=ent['type'];data=ent['data'];props={'EntityType':typ}
        for c,v in data:
            if c==8:props['Layer']=v
            elif c==62:props['ColorIndex']=v
            elif c==6:props['Linetype']=v
        geom=None
        try:
            if typ=='POINT':
                vals={c:v for c,v in data};geom={'type':'Point','coordinates':xy(vals[10],vals[20])}
            elif typ=='LINE':
                vals={c:v for c,v in data};geom={'type':'LineString','coordinates':[xy(vals[10],vals[20]),xy(vals[11],vals[21])]}
            elif typ=='LWPOLYLINE':
                coords=[];pending_x=None;closed=False
                for c,v in data:
                    if c==70:
                        try:closed=bool(int(v)&1)
                        except Exception:
                            logger.debug("Could not parse DXF polyline closed flag %r.", v, exc_info=True)
                    elif c==10:pending_x=float(v)
                    elif c==20 and pending_x is not None:
                        coords.append(xy(pending_x,float(v)));pending_x=None
                if closed and coords and coords[0]!=coords[-1]:coords.append(coords[0])
                if len(coords)>=2:geom={'type':'LineString','coordinates':coords};props['Closed']=closed
            elif typ in {'ARC','CIRCLE'}:
                vals={c:v for c,v in data};cx=float(vals[10]);cy=float(vals[20]);r=float(vals[40]);a1=0.0 if typ=='CIRCLE' else float(vals.get(50,0));a2=360.0 if typ=='CIRCLE' else float(vals.get(51,360));
                if a2<a1:a2+=360
                steps=max(12,min(180,int(abs(a2-a1)/5)+1));coords=[]
                for j in range(steps+1):
                    a=math.radians(a1+(a2-a1)*j/steps);coords.append(xy(cx+r*math.cos(a),cy+r*math.sin(a)))
                geom={'type':'LineString','coordinates':coords};props['Radius']=r
        except Exception as exc:props['_geometry_warning']=str(exc)
        if geom:features.append({'type':'Feature','id':str(idx),'geometry':geom,'properties':{k:typed_json_value(v) for k,v in props.items()},'_field_types':{k:_field_type(v) for k,v in props.items()}})
    if not features:raise ValueError('No supported POINT/LINE/LWPOLYLINE/ARC/CIRCLE entities were found in the DXF.')
    return [{'type':'FeatureCollection','name':path.stem,'source_name':path.name,'source_type':'DXF','source_crs':source_crs or '','geometry_types':sorted({f['geometry']['type'] for f in features}),'bounds_wgs84':None,'warning':'DXF curves are sampled for GIS/QC display; original CAD file remains immutable source evidence.','features':features}]

# -- GeoPackage reader -------------------------------------------------------

def _read_u32(data: bytes, pos: int, little: bool) -> tuple[int, int]:
    return struct.unpack_from("<I" if little else ">I", data, pos)[0], pos + 4


def _read_f64(data: bytes, pos: int, little: bool) -> tuple[float, int]:
    return struct.unpack_from("<d" if little else ">d", data, pos)[0], pos + 8


def _parse_wkb(data: bytes, pos: int = 0) -> tuple[dict, int]:
    little = data[pos] == 1; pos += 1
    typ, pos = _read_u32(data, pos, little)
    # Strip ISO WKB Z/M flags and PostGIS high bits when present.
    base = typ & 0xFF if typ >= 0x20000000 else typ % 1000
    dims = 2
    if 1000 <= typ < 2000 or typ & 0x80000000: dims = 3

    def coord(p: int) -> tuple[list[float], int]:
        x, p = _read_f64(data, p, little); y, p = _read_f64(data, p, little)
        vals = [x, y]
        if dims >= 3:
            z, p = _read_f64(data, p, little); vals.append(z)
        return vals, p

    if base == 1:
        c, pos = coord(pos); return {"type": "Point", "coordinates": c}, pos
    if base == 2:
        n, pos = _read_u32(data, pos, little); cs = []
        for _ in range(n): c, pos = coord(pos); cs.append(c)
        return {"type": "LineString", "coordinates": cs}, pos
    if base == 3:
        nr, pos = _read_u32(data, pos, little); rings = []
        for _ in range(nr):
            n, pos = _read_u32(data, pos, little); ring = []
            for _ in range(n): c, pos = coord(pos); ring.append(c)
            rings.append(ring)
        return {"type": "Polygon", "coordinates": rings}, pos
    if base in {4, 5, 6, 7}:
        n, pos = _read_u32(data, pos, little); geoms = []
        for _ in range(n):
            g, pos = _parse_wkb(data, pos); geoms.append(g)
        names = {4:"MultiPoint", 5:"MultiLineString", 6:"MultiPolygon", 7:"GeometryCollection"}
        if base == 7:
            return {"type": names[base], "geometries": geoms}, pos
        return {"type": names[base], "coordinates": [g.get("coordinates") for g in geoms]}, pos
    raise ValueError(f"Unsupported WKB geometry type {typ}.")


def _gpkg_wkb(blob: bytes) -> tuple[dict, int]:
    if not blob or blob[:2] != b"GP":
        geom, _ = _parse_wkb(blob, 0); return geom, 0
    flags = blob[3]
    little = bool(flags & 1)
    envelope_code = (flags >> 1) & 0x07
    srs_id = struct.unpack_from("<i" if little else ">i", blob, 4)[0]
    envelope_doubles = {0:0, 1:4, 2:6, 3:6, 4:8}.get(envelope_code, 0)
    pos = 8 + envelope_doubles * 8
    geom, _ = _parse_wkb(blob, pos)
    return geom, int(srs_id)


def _transform_coords(coords: Any, transformer: Transformer | None) -> Any:
    if transformer is None: return coords
    if isinstance(coords, list) and len(coords) >= 2 and all(isinstance(v, (int, float)) for v in coords[:2]):
        x, y = transformer.transform(float(coords[0]), float(coords[1]))
        return [x, y, *coords[2:]]
    if isinstance(coords, list): return [_transform_coords(v, transformer) for v in coords]
    return coords


def import_geopackage(path: Path, max_features_per_layer: int = 100000) -> list[dict]:
    con = sqlite3.connect(str(path)); con.row_factory = sqlite3.Row
    try:
        geom_rows = con.execute("SELECT table_name,column_name,srs_id,geometry_type_name FROM gpkg_geometry_columns").fetchall()
        srs_rows = {int(r["srs_id"]): dict(r) for r in con.execute("SELECT * FROM gpkg_spatial_ref_sys").fetchall()}
        layers = []
        for meta in geom_rows:
            table = meta["table_name"]; geom_col = meta["column_name"]
            columns = con.execute(f'PRAGMA table_info("{table.replace(chr(34), chr(34)*2)}")').fetchall()
            col_names = [r["name"] for r in columns]
            features = []
            cur = con.execute(f'SELECT * FROM "{table.replace(chr(34), chr(34)*2)}" LIMIT ?', (max_features_per_layer,))
            target_srs = int(meta["srs_id"])
            srs = srs_rows.get(target_srs, {})
            crs_text = ""
            org = str(srs.get("organization") or "")
            org_id = srs.get("organization_coordsys_id")
            if org and org.upper() not in {"NONE", "UNDEFINED"} and org_id not in (None, -1, 0):
                crs_text = f"{org}:{org_id}"
            elif srs.get("definition") and str(srs["definition"]).lower() != "undefined":
                crs_text = str(srs["definition"])
            transformer = None
            if crs_text:
                try:
                    crs = CRS.from_user_input(crs_text)
                    if crs != CRS.from_epsg(4326): transformer = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)
                except Exception:
                    transformer = None
            for idx, row in enumerate(cur, start=1):
                raw = dict(row); blob = raw.pop(geom_col, None)
                if blob is None: continue
                try:
                    geom, _ = _gpkg_wkb(bytes(blob))
                    if "coordinates" in geom: geom["coordinates"] = _transform_coords(geom["coordinates"], transformer)
                except Exception as exc:
                    geom = {"type": "GeometryCollection", "geometries": []}
                    raw["_geometry_warning"] = str(exc)
                features.append({"type":"Feature","id":str(raw.get("fid") or raw.get("id") or idx),"geometry":geom,"properties":{k:typed_json_value(v) for k,v in raw.items()},"_field_types":{k:_field_type(v) for k,v in raw.items()}})
            layers.append({
                "type":"FeatureCollection", "name":table, "source_name":path.name, "source_type":"GeoPackage", "source_crs":crs_text,
                "geometry_types":[meta["geometry_type_name"]], "bounds_wgs84":None, "warning":"", "features":features,
            })
        return layers
    finally:
        con.close()


def import_spatial(project: SurveyProject, paths: list[Path], app_root: Path, *, role: str = "reference") -> list[dict]:
    if not paths: raise ValueError("Choose at least one spatial data file.")
    project_crs = project.manifest.get("crs") or None
    all_layers: list[dict] = []
    gpkg_paths = [p for p in paths if p.suffix.lower() == ".gpkg"]
    dxf_paths = [p for p in paths if p.suffix.lower() == ".dxf"]
    standard_paths = [p for p in paths if p.suffix.lower() not in {".gpkg",".dxf"}]
    if standard_paths: all_layers.extend(import_standard_layers(standard_paths, app_root, project_crs))
    for path in gpkg_paths: all_layers.extend(import_geopackage(path))
    for path in dxf_paths: all_layers.extend(import_dxf(path, project_crs))

    dest_dir = project.paths.derived / "GISSync" / "layers"; dest_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for layer in all_layers:
        layer_id = uuid4().hex
        out_path = dest_dir / f"{layer_id}.geojson"
        out_path.write_text(json.dumps(layer, ensure_ascii=False, indent=2), encoding="utf-8")
        schema = infer_schema(layer.get("features") or [])
        source_name = str(layer.get("source_name") or "")
        source_path = next((p for p in paths if p.name == source_name), None)
        source_id = None
        if source_path and source_path.is_file():
            try: source_id = project.import_source(source_path, "GISSync", f"Spatial layer role: {role}").get("source_id")
            except Exception: source_id = None
        with project.db.connect() as conn:
            conn.execute(
                "INSERT INTO spatial_layers(layer_id,ts_utc,name,source_id,source_format,source_crs,role,feature_count,schema_json,stored_json_path) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (layer_id, utc_now(), layer.get("name") or source_name or "Layer", source_id, layer.get("source_type") or "", layer.get("source_crs") or "", role, len(layer.get("features") or []), json.dumps(schema, sort_keys=True), str(out_path.relative_to(project.paths.root))),
            )
        project.db.audit("GISSync", "SPATIAL_LAYER_IMPORTED", object_type="spatial_layer", object_id=layer_id, details={"name":layer.get("name"),"role":role,"feature_count":len(layer.get("features") or []),"schema":schema})
        saved.append({"layer_id":layer_id,"name":layer.get("name"),"role":role,"feature_count":len(layer.get("features") or []),"source_type":layer.get("source_type"),"source_crs":layer.get("source_crs"),"schema":schema,"stored_path":str(out_path)})
    return saved


def list_layers(db: AuditDB) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM spatial_layers ORDER BY ts_utc DESC").fetchall()
    out=[]
    for row in rows:
        d=dict(row); d["schema"] = json.loads(d.pop("schema_json") or "{}"); out.append(d)
    return out
