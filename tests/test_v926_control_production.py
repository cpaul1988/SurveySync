from __future__ import annotations

import json
import zipfile
from pathlib import Path

from surveysync.control import (
    classify_control_import,
    import_observations,
    list_control_qc_profiles,
    list_observations,
    merge_control_metadata,
    parse_control_source,
    resolve_spatial_control_groups,
    run_best_triplet_qc,
    save_control_qc_profile,
    set_control_group_override,
)
from surveysync.crs import browse_crs_library
from surveysync.project import SurveyProject


def _rich_access_jxl(path: Path) -> Path:
    path.write_text(
        '''<?xml version="1.0" encoding="utf-8"?>
<JobXML jobName="Raw Access Control" version="6.6" product="Trimble Access">
  <FieldBook>
    <GNSSObservation>
      <PointName>100A</PointName><StartDate>2026-09-19</StartDate><StartTime>08:00:00</StartTime>
      <EpochCount>300</EpochCount><DurationSeconds>300</DurationSeconds><SatelliteCount>8</SatelliteCount>
      <PDOP>1.4</PDOP><HDOP>0.8</HDOP><VDOP>1.1</VDOP><FixType>Fixed</FixType>
      <ReceiverModel>R12i</ReceiverModel><ReceiverSerialNumber>RX100</ReceiverSerialNumber>
      <AntennaType>R12i Internal</AntennaType><AntennaHeight>2.000</AntennaHeight>
    </GNSSObservation>
    <GNSSObservation>
      <PointName>100B</PointName><StartDate>2026-09-19</StartDate><StartTime>09:10:00</StartTime>
      <EpochCount>320</EpochCount><DurationSeconds>310</DurationSeconds><SatelliteCount>9</SatelliteCount>
      <PDOP>1.2</PDOP><HDOP>0.7</HDOP><VDOP>0.9</VDOP><FixType>Fixed</FixType>
    </GNSSObservation>
    <GNSSObservation>
      <PointName>100C</PointName><StartDate>2026-09-19</StartDate><StartTime>10:20:00</StartTime>
      <EpochCount>305</EpochCount><DurationSeconds>305</DurationSeconds><SatelliteCount>10</SatelliteCount>
      <PDOP>1.3</PDOP><HDOP>0.75</HDOP><VDOP>1.0</VDOP><FixType>Fixed</FixType>
    </GNSSObservation>
  </FieldBook>
  <Reductions>
    <Point><Name>100A</Name><Code>CTRL</Code><SurveyMethod>GNSS</SurveyMethod><Grid><North>1000.000</North><East>2000.000</East><Elevation>100.000</Elevation></Grid></Point>
    <Point><Name>100B</Name><Code>CTRL</Code><SurveyMethod>GNSS</SurveyMethod><Grid><North>1000.010</North><East>2000.010</East><Elevation>100.010</Elevation></Grid></Point>
    <Point><Name>100C</Name><Code>CTRL</Code><SurveyMethod>GNSS</SurveyMethod><Grid><North>999.995</North><East>1999.995</East><Elevation>99.995</Elevation></Grid></Point>
  </Reductions>
</JobXML>''',
        encoding="utf-8",
    )
    return path


def _coordinate_only_jxl(path: Path) -> Path:
    path.write_text(
        '''<?xml version="1.0" encoding="utf-8"?>
<JOBFile jobName="TBC Grid" version="6.33" product="Trimble Business Center">
  <FieldBook/><Reductions/>
  <InventoryData>
    <Point><Name>100A</Name><Code>CTRL</Code><Grid><North>5000.000</North><East>6000.000</East><Elevation>50.000</Elevation></Grid><SurveyMethod>KeyedIn</SurveyMethod></Point>
    <Point><Name>100B</Name><Code>CTRL</Code><Grid><North>5000.010</North><East>6000.010</East><Elevation>50.010</Elevation></Grid><SurveyMethod>KeyedIn</SurveyMethod></Point>
    <Point><Name>100C</Name><Code>CTRL</Code><Grid><North>4999.995</North><East>5999.995</East><Elevation>49.995</Elevation></Grid><SurveyMethod>KeyedIn</SurveyMethod></Point>
  </InventoryData>
</JOBFile>''',
        encoding="utf-8",
    )
    return path


def test_access_jxl_rich_gnss_metadata_is_preserved_and_qc_checks_dop(tmp_path):
    project = SurveyProject.create(tmp_path, "Rich JXL", crs="EPSG:2278")
    parsed = parse_control_source(_rich_access_jxl(tmp_path / "raw.jxl"), tmp_path / "derived")
    diag = classify_control_import(parsed)
    assert diag["source_kind"] == "TRIMBLE_ACCESS_RAW_JOBXML"
    assert "PDOP" not in diag.get("missing_metadata", [])
    first = parsed["observations"][0]
    assert first["satellite_count"] == 8
    assert first["pdop"] == 1.4 and first["hdop"] == 0.8 and first["vdop"] == 1.1
    assert first["fix_type"] == "Fixed"
    assert first["receiver_model"] == "R12i" and first["receiver_serial"] == "RX100"
    assert first["antenna_type"] == "R12i Internal" and first["antenna_height"] == 2.0
    assert import_observations(project.db, parsed["observations"]) == 3

    passed = run_best_triplet_qc(
        project.db, 0.045, 0.045,
        coordinate_context=project.coordinate_settings(),
        require_field_metadata=True,
        max_pdop=2.0, max_hdop=1.0, max_vdop=1.5,
    )
    assert passed["accepted_count"] == 1
    failed = run_best_triplet_qc(
        project.db, 0.045, 0.045,
        coordinate_context=project.coordinate_settings(),
        require_field_metadata=True,
        max_pdop=1.25,
    )
    assert failed["accepted_count"] == 0
    assert failed["results"][0]["status"] == "RESHOOT"
    assert any("PDOP" in x for x in failed["results"][0]["selected"]["field_validation"]["failures"])


def test_dual_source_metadata_merge_keeps_grid_coordinates_and_adds_raw_evidence(tmp_path):
    project = SurveyProject.create(tmp_path, "Dual Source", crs="EPSG:2278")
    grid = parse_control_source(_coordinate_only_jxl(tmp_path / "grid.jxl"), tmp_path / "grid_derived")
    assert classify_control_import(grid)["source_kind"] == "TBC_INVENTORY_ONLY_JOBXML"
    import_observations(project.db, grid["observations"], "grid-source")
    before = {r["point_id"]: (r["northing"], r["easting"], r["elevation"]) for r in list_observations(project.db)}

    raw = parse_control_source(_rich_access_jxl(tmp_path / "raw.jxl"), tmp_path / "raw_derived")
    merged = merge_control_metadata(project.db, raw["observations"], "raw-source")
    assert merged["updated_observations"] == 3
    after = {r["point_id"]: r for r in list_observations(project.db)}
    assert {pid: (r["northing"], r["easting"], r["elevation"]) for pid, r in after.items()} == before
    assert after["100A"]["pdop"] == 1.4
    assert after["100A"]["receiver_model"] == "R12i"
    meta = json.loads(after["100A"]["metadata_json"] or "{}")
    assert "raw-source" in json.dumps(meta)


def test_spatial_vertical_tolerance_prevents_wrong_nearby_control_merge(tmp_path):
    rows = [
        {"observation_id":"a","point_id":"1A","control_id":"1","northing":0.0,"easting":0.0,"elevation":100.0},
        {"observation_id":"b","point_id":"1B","control_id":"1","northing":0.02,"easting":0.0,"elevation":100.01},
        {"observation_id":"c","point_id":"2C","control_id":"2","northing":0.01,"easting":0.01,"elevation":110.0},
    ]
    grouped, flags = resolve_spatial_control_groups(rows, 0.25, vertical_tolerance=0.25)
    by_id = {r["point_id"]: r for r in grouped}
    assert by_id["2C"]["_effective_control_id"] == "2"
    assert not any(f.get("point_id") == "2C" and f.get("type") == "PROBABLE_MISNUMBER" for f in flags)


def test_manual_misnumber_override_can_reassign_and_reject(tmp_path):
    project = SurveyProject.create(tmp_path, "Review")
    import_observations(project.db, [
        {"control_id":"1","point_id":"1A","northing":0.0,"easting":0.0,"elevation":10.0},
        {"control_id":"1","point_id":"1B","northing":0.01,"easting":0.0,"elevation":10.0},
        {"control_id":"2","point_id":"2C","northing":0.005,"easting":0.005,"elevation":10.0},
    ])
    rows = list_observations(project.db)
    suspect = next(r for r in rows if r["point_id"] == "2C")
    set_control_group_override(project.db, suspect["observation_id"], status="REASSIGNED", assigned_control_id="1", assigned_point_id="1C", reason="Known field typo")
    grouped, flags = resolve_spatial_control_groups(rows, 0.25, overrides={suspect["observation_id"]: {"status":"REASSIGNED","assigned_control_id":"1","assigned_point_id":"1C"}})
    chosen = next(r for r in grouped if r["point_id"] == "2C")
    assert chosen["_effective_control_id"] == "1" and chosen["_effective_point_id"] == "1C"
    assert any(f["type"] == "MANUAL_GROUPING" for f in flags)

    set_control_group_override(project.db, suspect["observation_id"], status="REJECTED", reason="Actually a different monument")
    grouped2, _ = resolve_spatial_control_groups(rows, 0.25, overrides={suspect["observation_id"]: {"status":"REJECTED"}})
    rejected = next(r for r in grouped2 if r["point_id"] == "2C")
    assert rejected["_effective_control_id"] == "2"


def test_qc_profiles_can_save_rons_standard_and_dop_limits(tmp_path):
    project = SurveyProject.create(tmp_path, "Profiles")
    profiles = list_control_qc_profiles(project.db)
    assert any(p["name"] == "Ron Control Standard" for p in profiles)
    saved = save_control_qc_profile(project.db, {
        "name":"Strict GNSS", "horizontal_tolerance":0.03, "vertical_tolerance":0.03,
        "spatial_group_tolerance":0.2, "vertical_group_tolerance":0.25,
        "require_field_metadata":True, "min_time_separation_minutes":60,
        "min_epochs":300, "min_observation_seconds":300, "min_satellites":6,
        "max_pdop":2.0, "max_hdop":1.2, "max_vdop":1.8,
    })
    assert saved["name"] == "Strict GNSS"
    loaded = next(p for p in list_control_qc_profiles(project.db) if p["name"] == "Strict GNSS")
    assert loaded["max_pdop"] == 2.0 and loaded["vertical_group_tolerance"] == 0.25


def test_esri_style_crs_tree_exposes_expected_projected_families():
    root = browse_crs_library("")
    assert [f["name"] for f in root["folders"]] == ["Geographic Coordinate Systems", "Projected Coordinate Systems"]
    projected = browse_crs_library("projected")
    names = {f["name"] for f in projected["folders"]}
    assert {"State Plane", "State Systems", "County Systems", "National Grids", "UTM", "World"}.issubset(names)
    state_plane = browse_crs_library("projected/state_plane")
    assert any(f["name"] == "NAD 1983 (2011)" for f in state_plane["folders"])


def test_resizable_dialogs_and_control_production_ui_are_exposed():
    css = Path("surveysync/static/styles.css").read_text(encoding="utf-8")
    field_css = Path("fieldbook_sync/static/styles.css").read_text(encoding="utf-8")
    html = Path("surveysync/static/index.html").read_text(encoding="utf-8")
    js = Path("surveysync/static/app.js").read_text(encoding="utf-8")
    assert "resize:both" in css and ".modal.crs-open .dialog" in css
    assert "resize:both" in field_css
    assert "SS_MODAL_SIZE_PREFIX" in js and "localStorage" in js
    assert 'id="controlMergeMetadata"' in html
    assert 'id="controlMisnumberReview"' in html
    assert 'id="controlQcProfile"' in html
    assert 'id="controlMaxPdop"' in html and 'id="controlMaxHdop"' in html and 'id="controlMaxVdop"' in html


def test_control_package_api_contains_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg"))
    from fastapi.testclient import TestClient
    from fieldbook_sync import app as field_app
    from surveysync import router as survey_router

    field_app.runtime = field_app.Runtime(tmp_path / "field_runtime")
    survey_router.config_store = survey_router.ConfigStore(tmp_path / "cfg")
    project = SurveyProject.create(tmp_path / "projects", "Package", crs="EPSG:2278")
    survey_router.current_project = project
    import_observations(project.db, [
        {"control_id":"1","point_id":"1A","northing":100.0,"easting":200.0,"elevation":10.0,"observed_utc":"2026-09-19 08:00:00","observed_time_provided":1,"epoch_count":300,"satellite_count":6},
        {"control_id":"1","point_id":"1B","northing":100.01,"easting":200.01,"elevation":10.01,"observed_utc":"2026-09-19 09:10:00","observed_time_provided":1,"epoch_count":300,"satellite_count":6},
        {"control_id":"1","point_id":"1C","northing":99.995,"easting":199.995,"elevation":9.995,"observed_utc":"2026-09-19 10:20:00","observed_time_provided":1,"epoch_count":300,"satellite_count":6},
    ])
    client = TestClient(field_app.app)
    qc = client.post("/api/v9/control/qc-best-three", json={"require_field_metadata": True})
    assert qc.status_code == 200, qc.text
    package = client.post("/api/v9/control/export-package", params={"run_id": qc.json()["run_id"]})
    assert package.status_code == 200, package.text
    p = Path(package.json()["path"])
    assert p.is_file()
    with zipfile.ZipFile(p) as zf:
        names = set(zf.namelist())
        assert "ControlSync_Provenance.json" in names
        provenance = json.loads(zf.read("ControlSync_Provenance.json"))
    assert provenance["run_id"] == qc.json()["run_id"]
    assert provenance["results"]


def test_control_delimited_header_detection_maps_common_gnss_columns(tmp_path):
    from surveysync.control_import_mapping import read_control_delimited, detect_control_mapping
    src = tmp_path / "headers.csv"
    src.write_text(
        "Point Number,Northing (US ft),Easting (US ft),Elevation (US ft),Shot Date,Shot Time,Epochs,# Sats,PDOP,HDOP,VDOP\n"
        "100A,1000.0,2000.0,10.0,2026-09-20,08:00:00,300,8,1.2,0.7,0.9\n",
        encoding="utf-8",
    )
    scan = read_control_delimited(src)
    detected = detect_control_mapping(scan["headers"], scan["rows"])
    mapping = detected["mapping"]
    assert scan["has_header"] is True
    assert mapping["point_id"] == "Point Number"
    assert mapping["northing"] == "Northing (US ft)"
    assert mapping["easting"] == "Easting (US ft)"
    assert mapping["elevation"] == "Elevation (US ft)"
    assert mapping["observed_date"] == "Shot Date"
    assert mapping["observed_utc"] == "Shot Time"
    assert mapping["epoch_count"] == "Epochs"
    assert mapping["satellite_count"] == "# Sats"
    assert mapping["pdop"] == "PDOP" and mapping["hdop"] == "HDOP" and mapping["vdop"] == "VDOP"


def test_control_import_preview_prompts_for_unknown_headers_and_honors_user_mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg"))
    from fastapi.testclient import TestClient
    from fieldbook_sync import app as field_app
    from surveysync import router as survey_router

    field_app.runtime = field_app.Runtime(tmp_path / "field_runtime")
    survey_router.config_store = survey_router.ConfigStore(tmp_path / "cfg")
    project = SurveyProject.create(tmp_path / "projects", "Mapping", crs="EPSG:2278")
    survey_router.current_project = project
    src = tmp_path / "custom.csv"
    src.write_text(
        "Station Label,Grid Y,Grid X,Level,Sv Used,Quality P\n"
        "1A,100.000,200.000,10.000,7,1.4\n"
        "1B,100.010,200.010,10.010,8,1.2\n",
        encoding="utf-8",
    )
    client = TestClient(field_app.app)
    preview = client.post("/api/v9/control/import-preview", json={"file_path": str(src)})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["mapping_required"] is True
    assert body["headers"] == ["Station Label", "Grid Y", "Grid X", "Level", "Sv Used", "Quality P"]
    # Ambiguous company headers may be partially inferred, but user mapping must be accepted.
    mapping = {
        "point_id": "Station Label",
        "northing": "Grid Y",
        "easting": "Grid X",
        "elevation": "Level",
        "satellite_count": "Sv Used",
        "pdop": "Quality P",
    }
    checked = client.post("/api/v9/control/import-preview", json={"file_path": str(src), "mapping": mapping})
    assert checked.status_code == 200 and checked.json()["ready"] is True
    imported = client.post("/api/v9/control/import-mapped", json={"file_path": str(src), "mapping": mapping, "remember_mapping": True})
    assert imported.status_code == 200, imported.text
    rows = list_observations(project.db)
    assert {r["point_id"] for r in rows} == {"1A", "1B"}
    by_id = {r["point_id"]: r for r in rows}
    assert by_id["1A"]["satellite_count"] == 7 and by_id["1A"]["pdop"] == 1.4
    # Same headers should reuse the approved mapping on the next preview.
    preview2 = client.post("/api/v9/control/import-preview", json={"file_path": str(src)})
    assert preview2.status_code == 200
    assert preview2.json()["learned_mapping_used"] is True
    assert preview2.json()["mapping"]["pdop"] == "Quality P"


def test_control_headerless_pnezd_gets_safe_synthetic_mapping(tmp_path):
    from surveysync.control_import_mapping import (
        read_control_delimited, detect_control_mapping, validate_control_mapping,
        learn_control_mapping, preview_control_delimited,
    )
    project = SurveyProject.create(tmp_path / "project", "Headerless Safety", crs="EPSG:2278")
    src = tmp_path / "headerless.txt"
    src.write_text("7A,100.0,200.0,10.0,CTRL\n7B,100.01,200.01,10.01,CTRL\n", encoding="utf-8")
    scan = read_control_delimited(src)
    detected = detect_control_mapping(scan["headers"], scan["rows"])
    assert scan["has_header"] is False
    assert detected["mapping"]["point_id"] == "Column 1"
    assert detected["mapping"]["northing"] == "Column 2"
    assert detected["mapping"]["easting"] == "Column 3"
    assert validate_control_mapping(detected["mapping"], scan["headers"]) == []
    # Even if a generic Column N layout was previously stored, headerless files
    # must not silently reuse it because another same-width file may use a different order.
    learn_control_mapping(project, scan["headers"], detected["mapping"], label="unsafe generic layout")
    preview = preview_control_delimited(project, src)
    assert preview["has_header"] is False
    assert preview["learned_mapping_used"] is False


def test_control_ui_uses_mapping_preview_before_delimited_import():
    js = Path("surveysync/static/app.js").read_text(encoding="utf-8")
    html = Path("surveysync/static/index.html").read_text(encoding="utf-8")
    assert "/api/v9/control/import-preview" in js
    assert "Column Mapping" in js
    assert "Remember this mapping" in js
    assert "detects the delimiter and headers" in html
