from __future__ import annotations

import json
from pathlib import Path

import shapefile
from pyproj import CRS

from fieldbook_sync.map_gis import import_kml, import_shapefile, normalize_crs, wgs84_to_xy, xy_to_wgs84
from fieldbook_sync.models import AppState, ManualNetworkEdge, MapBookmark, MapLayer


def test_map_state_models_are_backward_compatible():
    state = AppState()
    assert state.map_project_crs == ""
    assert state.map_layers == []
    assert state.map_bookmarks == []
    assert state.manual_network_edges == []
    layer = MapLayer(name="Parcels")
    assert layer.layer_id.startswith("layer-")
    assert layer.opacity == 0.85
    bookmark = MapBookmark(name="North Area")
    assert bookmark.bookmark_id.startswith("bookmark-")
    edge = ManualNetworkEdge(from_point="1", to_point="2")
    assert edge.locked is True


def test_project_crs_round_trip_texas_south_central():
    canonical, name = normalize_crs("EPSG:2278")
    assert canonical == "EPSG:2278"
    assert name
    x, y = wgs84_to_xy(-95.36, 29.76, canonical)
    lon, lat = xy_to_wgs84(x, y, canonical)
    assert abs(lon - (-95.36)) < 1e-6
    assert abs(lat - 29.76) < 1e-6


def test_import_kml_point_line_polygon(tmp_path: Path):
    kml = tmp_path / "sample.kml"
    kml.write_text('''<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document>
      <Placemark><name>A</name><Point><coordinates>-95.36,29.76,0</coordinates></Point></Placemark>
      <Placemark><name>L</name><LineString><coordinates>-95.36,29.76 -95.35,29.77</coordinates></LineString></Placemark>
      <Placemark><name>P</name><Polygon><outerBoundaryIs><LinearRing><coordinates>-95.36,29.76 -95.35,29.76 -95.35,29.77 -95.36,29.76</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
    </Document></kml>''', encoding="utf-8")
    layers = import_kml(kml)
    assert len(layers) == 1
    layer = layers[0]
    assert layer.feature_count == 3
    assert set(layer.geometry_types) == {"LineString", "Point", "Polygon"}
    assert layer.bounds_wgs84[0] <= -95.36
    assert layer.bounds_wgs84[3] >= 29.77


def test_import_shapefile_with_prj(tmp_path: Path):
    shp = tmp_path / "points.shp"
    w = shapefile.Writer(str(shp), shapeType=shapefile.POINT)
    w.field("PointID", "C", 20)
    w.point(-95.36, 29.76); w.record("1001")
    w.close()
    shp.with_suffix(".prj").write_text(CRS.from_epsg(4326).to_wkt(), encoding="utf-8")
    layer = import_shapefile(shp)[0]
    assert layer.feature_count == 1
    assert layer.features[0].properties["PointID"].strip() == "1001"
    coords = layer.features[0].geometry["coordinates"]
    assert abs(coords[0] + 95.36) < 1e-8
    assert abs(coords[1] - 29.76) < 1e-8


def test_v814_map_workspace_ui_and_routes_present():
    root = Path(__file__).resolve().parents[1]
    html = (root / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
    js = (root / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    app = (root / "fieldbook_sync/app.py").read_text(encoding="utf-8")
    req = (root / "requirements.txt").read_text(encoding="utf-8")
    assert '<option value="aerial">Aerial</option>' in html
    assert '<option value="navigation">Navigation</option>' in html
    assert '<option value="topo">Topographic</option>' in html
    for item in ["mapImportBtn", "mapMeasureDistance", "mapMeasureArea", "mapMeasureBearing", "mapIdentifyTool", "mapSelectTool", "mapGotoXYBtn", "mapProfileBtn"]:
        assert item in html
    assert "MAP_TILE_URLS" in js
    assert "traceConnected" in js
    assert "connectSelected" in js
    assert "exportSelected" in js
    assert "dragenter" in js and "importMapFiles" in js
    for route in ["/api/map/state", "/api/map/import", "/api/map/crs", "/api/map/transform", "/api/map/bookmarks", "/api/network/manual"]:
        assert route in app
    assert "await upload.read()" not in app
    assert "pyproj" in req
    assert (root / "arcgis_gdb_reader.py").exists()


def test_v814_version_metadata_and_assets():
    root = Path(__file__).resolve().parents[1]
    html = (root / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
    app = (root / "fieldbook_sync/app.py").read_text(encoding="utf-8")
    assert '<title>FieldBook Sync v8.1.21</title>' in html
    assert 'styles.css?v=8.1.21' in html
    assert 'app.js?v=8.1.21' in html
    assert 'APP_NAME = "FieldBook Sync v8.1.21"' in app
    assert 'version="8.1.21"' in app
