from __future__ import annotations
import logging

import json
import math
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

import shapefile
from pyproj import CRS, Transformer

from .models import MapFeature, MapLayer
from .arcgis_integration import find_arcgis_pro

WGS84 = CRS.from_epsg(4326)
MAX_FEATURES_PER_LAYER = 50000
MAX_TOTAL_VERTICES_PER_FEATURE = 20000


def normalize_crs(value: str | None) -> tuple[str, str]:
    raw = (value or "").strip()
    if not raw:
        return "", ""
    crs = CRS.from_user_input(raw)
    auth = crs.to_authority()
    canonical = f"{auth[0]}:{auth[1]}" if auth else crs.to_string()
    return canonical, crs.name or canonical


def transformer_to_wgs84(source_crs: str | CRS) -> Transformer:
    return Transformer.from_crs(CRS.from_user_input(source_crs), WGS84, always_xy=True)


def transformer_from_wgs84(target_crs: str | CRS) -> Transformer:
    return Transformer.from_crs(WGS84, CRS.from_user_input(target_crs), always_xy=True)


def xy_to_wgs84(x: float, y: float, source_crs: str) -> tuple[float, float]:
    tr = transformer_to_wgs84(source_crs)
    lon, lat = tr.transform(float(x), float(y))
    return float(lon), float(lat)


def wgs84_to_xy(lon: float, lat: float, target_crs: str) -> tuple[float, float]:
    tr = transformer_from_wgs84(target_crs)
    x, y = tr.transform(float(lon), float(lat))
    return float(x), float(y)


def _sanitize_properties(props: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (props or {}).items():
        key = str(k)
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[key] = v
        else:
            try:
                out[key] = str(v)
            except Exception:
                out[key] = ""
    return out


def _transform_coords(coords: Any, transformer: Transformer | None) -> Any:
    if transformer is None:
        return coords
    if not isinstance(coords, (list, tuple)):
        return coords
    if len(coords) >= 2 and isinstance(coords[0], (int, float)) and isinstance(coords[1], (int, float)):
        x, y = transformer.transform(float(coords[0]), float(coords[1]))
        tail = list(coords[2:])
        return [float(x), float(y), *tail]
    return [_transform_coords(c, transformer) for c in coords]


def _count_vertices(coords: Any) -> int:
    if isinstance(coords, (list, tuple)):
        if len(coords) >= 2 and isinstance(coords[0], (int, float)) and isinstance(coords[1], (int, float)):
            return 1
        return sum(_count_vertices(c) for c in coords)
    return 0


def _decimate_line(coords: list, max_vertices: int = MAX_TOTAL_VERTICES_PER_FEATURE) -> list:
    n = len(coords)
    if n <= max_vertices:
        return coords
    step = max(1, math.ceil(n / max_vertices))
    result = coords[::step]
    if result and coords and result[-1] != coords[-1]:
        result.append(coords[-1])
    return result


def _limit_geometry_vertices(geometry: dict[str, Any]) -> dict[str, Any]:
    """Keep imported display layers responsive without changing survey/network evidence."""
    g = dict(geometry or {})
    typ = g.get("type")
    c = g.get("coordinates")
    if _count_vertices(c) <= MAX_TOTAL_VERTICES_PER_FEATURE:
        return g
    if typ == "LineString":
        g["coordinates"] = _decimate_line(list(c or []))
    elif typ == "MultiLineString":
        lines = list(c or [])
        per = max(100, MAX_TOTAL_VERTICES_PER_FEATURE // max(1, len(lines)))
        g["coordinates"] = [_decimate_line(list(line), per) for line in lines]
    elif typ == "Polygon":
        rings = list(c or [])
        per = max(100, MAX_TOTAL_VERTICES_PER_FEATURE // max(1, len(rings)))
        g["coordinates"] = [_decimate_line(list(ring), per) for ring in rings]
    elif typ == "MultiPolygon":
        polys = list(c or [])
        ring_count = max(1, sum(len(p) for p in polys))
        per = max(100, MAX_TOTAL_VERTICES_PER_FEATURE // ring_count)
        g["coordinates"] = [[_decimate_line(list(ring), per) for ring in poly] for poly in polys]
    return g


def _iter_lonlat(coords: Any) -> Iterable[tuple[float, float]]:
    if isinstance(coords, (list, tuple)):
        if len(coords) >= 2 and isinstance(coords[0], (int, float)) and isinstance(coords[1], (int, float)):
            yield float(coords[0]), float(coords[1])
        else:
            for child in coords:
                yield from _iter_lonlat(child)


def _bounds_for_features(features: list[MapFeature]) -> list[float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for feature in features:
        for lon, lat in _iter_lonlat(feature.geometry.get("coordinates")):
            if math.isfinite(lon) and math.isfinite(lat):
                xs.append(lon); ys.append(lat)
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _make_layer(name: str, source_name: str, source_type: str, features: list[MapFeature], source_crs: str = "EPSG:4326", warning: str = "") -> MapLayer:
    geometry_types = sorted({f.geometry.get("type", "Unknown") for f in features})
    layer = MapLayer(
        name=name,
        source_name=source_name,
        source_type=source_type,
        source_crs=source_crs,
        feature_count=len(features),
        geometry_types=geometry_types,
        features=features,
        bounds_wgs84=_bounds_for_features(features),
        warning=warning,
    )
    return layer


def _geojson_features(payload: dict[str, Any], source_crs: str | None, default_crs: str | None) -> tuple[list[MapFeature], str]:
    src = source_crs or default_crs or "EPSG:4326"
    crs_obj = payload.get("crs") if isinstance(payload, dict) else None
    if not source_crs and isinstance(crs_obj, dict):
        try:
            name = crs_obj.get("properties", {}).get("name")
            if name:
                src = name.replace("urn:ogc:def:crs:EPSG::", "EPSG:")
        except Exception:
            logging.getLogger(__name__).warning("Recovery fallback in map_gis; operation did not complete.", exc_info=True)
    canonical, _ = normalize_crs(src)
    transformer = None if CRS.from_user_input(canonical) == WGS84 else transformer_to_wgs84(canonical)
    if payload.get("type") == "FeatureCollection":
        raw_features = payload.get("features") or []
    elif payload.get("type") == "Feature":
        raw_features = [payload]
    else:
        raw_features = [{"type": "Feature", "geometry": payload, "properties": {}}]
    out: list[MapFeature] = []
    for idx, item in enumerate(raw_features[:MAX_FEATURES_PER_LAYER]):
        geom = item.get("geometry") or {}
        if not geom.get("type") or geom.get("coordinates") is None:
            continue
        transformed = {
            "type": geom["type"],
            "coordinates": _transform_coords(geom.get("coordinates"), transformer),
        }
        transformed = _limit_geometry_vertices(transformed)
        out.append(MapFeature(
            feature_id=str(item.get("id") or f"feature-{idx+1}"),
            geometry=transformed,
            properties=_sanitize_properties(item.get("properties")),
        ))
    return out, canonical


def import_geojson(path: Path, default_crs: str | None = None) -> list[MapLayer]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    features, src = _geojson_features(payload, None, default_crs)
    return [_make_layer(path.stem, path.name, "GeoJSON", features, src)]


def _kml_coord_list(text: str | None) -> list[list[float]]:
    out: list[list[float]] = []
    for token in (text or "").replace("\n", " ").replace("\t", " ").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            coord = [float(parts[0]), float(parts[1])]
            if len(parts) > 2 and parts[2] != "":
                coord.append(float(parts[2]))
            out.append(coord)
        except Exception:
            continue
    return out


def _kml_props(pm: ET.Element) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for child in pm.iter():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag in {"name", "description"} and child.text and tag not in props:
            props[tag] = child.text.strip()
        if tag == "Data":
            key = child.attrib.get("name")
            value = next((c.text for c in child if c.tag.rsplit("}",1)[-1] == "value"), None)
            if key and value is not None:
                props[key] = value
        if tag == "SimpleData" and child.attrib.get("name") and child.text is not None:
            props[child.attrib["name"]] = child.text
    return _sanitize_properties(props)


def _kml_geometries(node: ET.Element) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    tag = node.tag.rsplit("}", 1)[-1]
    if tag == "Point":
        coords = next((_kml_coord_list(c.text) for c in node.iter() if c.tag.rsplit("}",1)[-1] == "coordinates"), [])
        if coords: out.append({"type": "Point", "coordinates": coords[0]})
    elif tag == "LineString":
        coords = next((_kml_coord_list(c.text) for c in node.iter() if c.tag.rsplit("}",1)[-1] == "coordinates"), [])
        if coords: out.append({"type": "LineString", "coordinates": coords})
    elif tag == "Polygon":
        rings: list[list[list[float]]] = []
        for ring in node.iter():
            if ring.tag.rsplit("}",1)[-1] != "LinearRing": continue
            coords = next((_kml_coord_list(c.text) for c in ring.iter() if c.tag.rsplit("}",1)[-1] == "coordinates"), [])
            if coords: rings.append(coords)
        if rings: out.append({"type": "Polygon", "coordinates": rings})
    elif tag == "MultiGeometry":
        for child in list(node):
            out.extend(_kml_geometries(child))
    return out


def import_kml(path: Path, source_name: str | None = None) -> list[MapLayer]:
    root = ET.fromstring(path.read_bytes())
    features: list[MapFeature] = []
    n = 0
    for pm in root.iter():
        if pm.tag.rsplit("}", 1)[-1] != "Placemark":
            continue
        props = _kml_props(pm)
        geoms: list[dict[str, Any]] = []
        for child in list(pm):
            if child.tag.rsplit("}",1)[-1] in {"Point","LineString","Polygon","MultiGeometry"}:
                geoms.extend(_kml_geometries(child))
        for geom in geoms:
            n += 1
            features.append(MapFeature(feature_id=f"feature-{n}", geometry=_limit_geometry_vertices(geom), properties=props))
            if len(features) >= MAX_FEATURES_PER_LAYER:
                break
        if len(features) >= MAX_FEATURES_PER_LAYER:
            break
    display = source_name or path.name
    warning = "Feature limit reached; showing the first 50,000 features." if len(features) >= MAX_FEATURES_PER_LAYER else ""
    return [_make_layer(Path(display).stem, display, "KML", features, "EPSG:4326", warning)]


def import_kmz(path: Path) -> list[MapLayer]:
    with zipfile.ZipFile(path) as zf, tempfile.TemporaryDirectory(prefix="fbs_kmz_") as td:
        names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
        if not names:
            raise ValueError("The KMZ does not contain a KML document.")
        preferred = next((n for n in names if Path(n).name.lower() == "doc.kml"), names[0])
        target = Path(td) / "document.kml"
        target.write_bytes(zf.read(preferred))
        layers = import_kml(target, path.name)
        for layer in layers:
            layer.source_type = "KMZ"
        return layers


def _read_prj_for_shp(shp_path: Path) -> str | None:
    prj = shp_path.with_suffix(".prj")
    if not prj.exists():
        return None
    text = prj.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return None
    try:
        canonical, _ = normalize_crs(text)
        return canonical
    except Exception:
        return text


def import_shapefile(shp_path: Path, default_crs: str | None = None) -> list[MapLayer]:
    src = _read_prj_for_shp(shp_path) or (default_crs or "")
    if not src:
        raise ValueError(f"{shp_path.name} has no .prj file. Set the project coordinate system first, or supply a .prj sidecar.")
    canonical, _ = normalize_crs(src)
    transformer = None if CRS.from_user_input(canonical) == WGS84 else transformer_to_wgs84(canonical)
    reader = shapefile.Reader(str(shp_path))
    field_names = [f[0] for f in reader.fields[1:]]
    features: list[MapFeature] = []
    try:
        for idx, sr in enumerate(reader.iterShapeRecords()):
            if idx >= MAX_FEATURES_PER_LAYER:
                break
            geo = getattr(sr.shape, "__geo_interface__", None)
            if not geo:
                continue
            geom = {"type": geo.get("type"), "coordinates": _transform_coords(geo.get("coordinates"), transformer)}
            geom = _limit_geometry_vertices(geom)
            record_values = list(sr.record)
            props = {field_names[i]: record_values[i] for i in range(min(len(field_names), len(record_values)))}
            features.append(MapFeature(feature_id=f"feature-{idx+1}", geometry=geom, properties=_sanitize_properties(props)))
    finally:
        reader.close()
    warning = "Feature limit reached; showing the first 50,000 features." if len(features) >= MAX_FEATURES_PER_LAYER else ""
    return [_make_layer(shp_path.stem, shp_path.name, "Shapefile", features, canonical, warning)]


def _run_gdb_arcgis_pro(app_root: Path, gdb_path: Path, feature_class: str | None = None) -> list[MapLayer]:
    info = find_arcgis_pro()
    if not info.get("installed") or not info.get("propy"):
        raise ValueError("File Geodatabase feature classes require ArcGIS Pro on this computer. Zip the .gdb folder and import it on a machine with ArcGIS Pro installed.")
    helper = app_root / "arcgis_gdb_reader.py"
    if not helper.exists():
        raise RuntimeError("The ArcGIS File Geodatabase import helper is missing from FieldBook Sync.")
    with tempfile.TemporaryDirectory(prefix="fbs_gdb_out_") as td:
        out = Path(td) / "gdb_layers.json"
        args = [str(info["propy"]), str(helper), str(gdb_path), str(out)]
        if feature_class:
            args.append(feature_class)
        if os.name == "nt":
            cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", subprocess.list2cmdline(args)]
        else:
            cmd = args
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        if proc.returncode != 0 or not out.exists():
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError("ArcGIS Pro could not read the File Geodatabase." + (f"\n{detail[-2000:]}" if detail else ""))
        payload = json.loads(out.read_text(encoding="utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error") or "ArcGIS Pro could not read the File Geodatabase.")
        layers: list[MapLayer] = []
        for item in payload.get("layers", []):
            features, _ = _geojson_features(item.get("geojson") or {}, "EPSG:4326", None)
            layers.append(_make_layer(item.get("name") or "Feature Class", str(gdb_path.name), "FileGDB", features, item.get("source_crs") or "EPSG:4326", item.get("warning") or ""))
        return layers


def _extract_safe_zip(path: Path, target: Path) -> None:
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            dest = (target / info.filename).resolve()
            if target.resolve() not in dest.parents and dest != target.resolve():
                raise ValueError("Unsafe ZIP path detected.")
        zf.extractall(target)


def import_zip(path: Path, app_root: Path, default_crs: str | None = None) -> list[MapLayer]:
    with tempfile.TemporaryDirectory(prefix="fbs_gis_zip_") as td:
        root = Path(td)
        _extract_safe_zip(path, root)
        gdbs = [p for p in root.rglob("*.gdb") if p.is_dir()]
        if gdbs:
            layers: list[MapLayer] = []
            for gdb in gdbs:
                layers.extend(_run_gdb_arcgis_pro(app_root, gdb))
            return layers
        shps = list(root.rglob("*.shp"))
        if shps:
            layers = []
            for shp in shps:
                layers.extend(import_shapefile(shp, default_crs))
            return layers
        kmls = list(root.rglob("*.kml"))
        if kmls:
            layers = []
            for kml in kmls:
                layers.extend(import_kml(kml, kml.name))
            return layers
        geo = [p for p in root.rglob("*") if p.suffix.lower() in {".geojson", ".json"}]
        if geo:
            layers = []
            for p in geo:
                layers.extend(import_geojson(p, default_crs))
            return layers
        raise ValueError("The ZIP does not contain a Shapefile, KML, GeoJSON, or File Geodatabase (.gdb).")


def import_map_files(paths: list[Path], app_root: Path, project_crs: str | None = None) -> list[MapLayer]:
    """Import uploaded GIS files. Shapefile sidecars may be supplied as separate uploads."""
    layers: list[MapLayer] = []
    handled_shp_stems: set[str] = set()
    for path in paths:
        ext = path.suffix.lower()
        if ext in {".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx"}:
            continue
        if ext == ".kml":
            layers.extend(import_kml(path))
        elif ext == ".kmz":
            layers.extend(import_kmz(path))
        elif ext in {".geojson", ".json"}:
            layers.extend(import_geojson(path, project_crs))
        elif ext == ".shp":
            stem = str(path.with_suffix("")).lower()
            if stem not in handled_shp_stems:
                layers.extend(import_shapefile(path, project_crs)); handled_shp_stems.add(stem)
        elif ext == ".zip":
            layers.extend(import_zip(path, app_root, project_crs))
        else:
            raise ValueError(f"Unsupported GIS file: {path.name}. Use KML, KMZ, GeoJSON, Shapefile components/ZIP, or a zipped File Geodatabase.")
    if not layers:
        raise ValueError("No supported GIS layers were found in the selected files.")
    return layers


def crs_unit_label(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "project units"
    try:
        crs = CRS.from_user_input(raw)
        if not crs.is_projected:
            return "degrees"
        unit = (crs.axis_info[0].unit_name if crs.axis_info else "") or "project units"
        low = unit.lower()
        if "us survey" in low and "foot" in low:
            return "US survey feet"
        if low in {"foot", "feet", "international foot"} or "foot" in low:
            return "international feet"
        if "metre" in low or "meter" in low:
            return "meters"
        return unit
    except Exception:
        return "project units"

# v8.1.21 coordinate-system browser / survey alignment ------------------------

def crs_details(value: str | CRS) -> dict[str, Any]:
    crs = CRS.from_user_input(value)
    auth = crs.to_authority()
    axis_units = []
    try:
        axis_units = [a.unit_name for a in crs.axis_info if getattr(a, "unit_name", None)]
    except Exception:
        axis_units = []
    area = getattr(crs, "area_of_use", None)
    return {
        "id": f"{auth[0]}:{auth[1]}" if auth else crs.to_string(),
        "name": crs.name or crs.to_string(),
        "authority": auth[0] if auth else "",
        "code": auth[1] if auth else "",
        "units": axis_units[0] if axis_units else "",
        "type": str(getattr(crs, "type_name", "")),
        "area": {
            "name": getattr(area, "name", "") or "",
            "west": getattr(area, "west", None),
            "south": getattr(area, "south", None),
            "east": getattr(area, "east", None),
            "north": getattr(area, "north", None),
        } if area else None,
        "wkt": crs.to_wkt(),
    }


def search_coordinate_systems(query: str, limit: int = 40) -> list[dict[str, Any]]:
    """Search the local PROJ/pyproj CRS database; no web service required."""
    from pyproj.database import query_crs_info
    q = (query or "").strip().lower()
    if not q:
        return []
    out: list[dict[str, Any]] = []
    # EPSG and ESRI cover the State Plane / UTM / common custom catalog users expect.
    for auth in ("EPSG", "ESRI"):
        try:
            infos = query_crs_info(auth_name=auth)
        except Exception:
            continue
        for info in infos:
            text = f"{auth}:{info.code} {info.name} {getattr(info, 'area_of_use', '')}".lower()
            if q not in text:
                continue
            try:
                d = crs_details(f"{auth}:{info.code}")
            except Exception:
                continue
            out.append(d)
            if len(out) >= limit:
                return out
    return out


def parse_custom_crs_text(text: str, source_name: str = "custom.prj") -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("The coordinate-system file is empty.")
    # PROJJSON can be supplied as a JSON object; CRS.from_user_input accepts the object.
    candidate: Any = raw
    if raw.startswith("{"):
        try:
            candidate = json.loads(raw)
        except Exception:
            candidate = raw
    crs = CRS.from_user_input(candidate)
    d = crs_details(crs)
    d["definition"] = crs.to_wkt()
    d["source_name"] = source_name
    return d


def apply_similarity_alignment(
    x: float,
    y: float,
    *,
    scale_factor: float = 1.0,
    rotation_deg: float = 0.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> tuple[float, float]:
    """Apply a reversible 2-D similarity transform (ground/local -> project/grid)."""
    scale = float(scale_factor)
    if not math.isfinite(scale) or scale == 0:
        raise ValueError("Scale factor must be a finite non-zero number.")
    theta = math.radians(float(rotation_deg))
    dx = float(x) - float(origin_x)
    dy = float(y) - float(origin_y)
    c, s = math.cos(theta), math.sin(theta)
    gx = float(origin_x) + float(offset_x) + scale * (dx * c - dy * s)
    gy = float(origin_y) + float(offset_y) + scale * (dx * s + dy * c)
    return gx, gy


def invert_similarity_alignment(
    x: float,
    y: float,
    *,
    scale_factor: float = 1.0,
    rotation_deg: float = 0.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> tuple[float, float]:
    scale = float(scale_factor)
    if not math.isfinite(scale) or scale == 0:
        raise ValueError("Scale factor must be a finite non-zero number.")
    theta = math.radians(float(rotation_deg))
    c, s = math.cos(theta), math.sin(theta)
    dx = float(x) - float(origin_x) - float(offset_x)
    dy = float(y) - float(origin_y) - float(offset_y)
    lx = float(origin_x) + (dx * c + dy * s) / scale
    ly = float(origin_y) + (-dx * s + dy * c) / scale
    return lx, ly


def solve_similarity_alignment(control_pairs: list[dict[str, float]]) -> dict[str, Any]:
    """Least-squares 2-D Helmert/similarity solution from >=2 local/grid control pairs."""
    import numpy as np
    if len(control_pairs) < 2:
        raise ValueError("At least two control-point pairs are required.")
    rows = []
    obs = []
    for pair in control_pairs:
        lx, ly = float(pair["local_x"]), float(pair["local_y"])
        gx, gy = float(pair["grid_x"]), float(pair["grid_y"])
        # X = a*x - b*y + tx ; Y = b*x + a*y + ty
        rows.append([lx, -ly, 1.0, 0.0]); obs.append(gx)
        rows.append([ly,  lx, 0.0, 1.0]); obs.append(gy)
    A = np.asarray(rows, dtype=float)
    L = np.asarray(obs, dtype=float)
    sol, *_ = np.linalg.lstsq(A, L, rcond=None)
    a, b, tx, ty = [float(v) for v in sol]
    scale = math.hypot(a, b)
    rotation = math.degrees(math.atan2(b, a))
    residuals = []
    for pair in control_pairs:
        px = a * float(pair["local_x"]) - b * float(pair["local_y"]) + tx
        py = b * float(pair["local_x"]) + a * float(pair["local_y"]) + ty
        ex = px - float(pair["grid_x"]); ey = py - float(pair["grid_y"])
        residuals.append({"name": str(pair.get("name") or ""), "dx": ex, "dy": ey, "error": math.hypot(ex, ey)})
    rms = math.sqrt(sum(r["error"] ** 2 for r in residuals) / max(1, len(residuals)))
    # Origin zero makes the solved translation directly represent tx/ty.
    return {
        "scale_factor": scale,
        "rotation_deg": rotation,
        "offset_x": tx,
        "offset_y": ty,
        "origin_x": 0.0,
        "origin_y": 0.0,
        "residual_rms": rms,
        "residuals": residuals,
    }


def crs_area_warning(crs_value: str, lon: float, lat: float) -> str:
    try:
        crs = CRS.from_user_input(crs_value)
        area = getattr(crs, "area_of_use", None)
        if not area:
            return ""
        if not (float(area.west) <= lon <= float(area.east) and float(area.south) <= lat <= float(area.north)):
            return (
                f"Transformed survey coordinates fall outside the normal area of use for {crs.name}. "
                f"Check the coordinate system, units, and ground/grid alignment before relying on basemaps."
            )
    except Exception:
        return ""
    return ""
