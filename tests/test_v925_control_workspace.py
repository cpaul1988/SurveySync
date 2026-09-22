from __future__ import annotations

from pathlib import Path

from surveysync.control import import_observations, parse_control_csv, parse_control_source, run_best_triplet_qc
from surveysync.crs import browse_crs_library, grid_to_local, local_to_grid, search_crs_library
from surveysync.project import SurveyProject


def test_project_coordinate_library_and_local_site_round_trip(tmp_path):
    hits = search_crs_library("Missouri East", limit=25)
    assert hits
    assert any("Missouri East" in item["name"] for item in hits)

    project = SurveyProject.create(tmp_path, "Local Site")
    site = {
        "enabled": True,
        "name": "Modified Ground",
        "grid_origin_northing": 1_000_000.0,
        "grid_origin_easting": 500_000.0,
        "local_origin_northing": 10_000.0,
        "local_origin_easting": 20_000.0,
        "grid_to_ground_factor": 1.00012345,
        "rotation_deg": 0.75,
    }
    project.set_coordinate_system("EPSG:26996", "meters", "meters", site)
    settings = project.coordinate_settings()
    assert settings["crs"] == "EPSG:26996"
    assert settings["local_site"]["enabled"] is True
    assert settings["local_site"]["grid_to_ground_factor"] == site["grid_to_ground_factor"]

    e, n = grid_to_local(500_250.0, 1_000_400.0, settings["local_site"])
    ge, gn = local_to_grid(e, n, settings["local_site"])
    assert abs(ge - 500_250.0) < 1e-8
    assert abs(gn - 1_000_400.0) < 1e-8

    reopened = SurveyProject(project.paths.root)
    assert reopened.coordinate_settings()["local_site"]["name"] == "Modified Ground"
    with reopened.db.connect() as conn:
        row = conn.execute("SELECT * FROM project_coordinate_settings WHERE setting_id='active'").fetchone()
    assert row is not None and row["local_site_enabled"] == 1


def test_tbc_style_control_import_groups_suffixes_and_selects_best_three(tmp_path):
    project = SurveyProject.create(tmp_path, "Control Workspace", crs="EPSG:2278")
    source = tmp_path / "tbc_control.csv"
    source.write_text(
        "P,N,E,elev,Code\n"
        "7A,100.000,200.000,10.000,CTRL\n"
        "7B,100.020,200.010,10.010,CTRL\n"
        "7C,99.990,199.995,9.995,CTRL\n"
        "7D,100.200,200.200,10.200,CTRL\n"
        "8A,500.000,600.000,20.000,CTRL\n"
        "8B,500.120,600.000,20.000,CTRL\n"
        "8C,500.000,600.120,20.120,CTRL\n",
        encoding="utf-8",
    )
    rows = parse_control_csv(source)
    assert [r["control_id"] for r in rows[:4]] == ["7", "7", "7", "7"]
    assert [r["point_id"] for r in rows[:4]] == ["7A", "7B", "7C", "7D"]
    assert import_observations(project.db, rows) == 7

    result = run_best_triplet_qc(
        project.db,
        0.045,
        0.045,
        coordinate_context=project.coordinate_settings(),
    )
    by_id = {item["control_id"]: item for item in result["results"]}
    assert by_id["7"]["status"] == "PASS"
    assert set(by_id["7"]["selected"]["point_ids"]) == {"7A", "7B", "7C"}
    assert by_id["7"]["selected"]["code"] == "CTRL"
    assert by_id["8"]["status"] == "RESHOOT"
    assert by_id["8"]["reshoot_point_ids"] == ["8D", "8E", "8F"]
    assert result["accepted_count"] == 1
    assert result["reshoot_count"] == 1
    with project.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_qc_runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM control_qc_candidates WHERE control_id='7'").fetchone()[0] == 4
        selected = conn.execute("SELECT point_ids_json FROM control_qc_candidates WHERE control_id='7' AND selected=1").fetchone()
    assert "7A" in selected[0] and "7D" not in selected[0]


def test_control_workspace_api_coordinate_setup_qc_and_custom_export(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg"))
    from fastapi.testclient import TestClient
    from fieldbook_sync import app as field_app
    from surveysync import router as survey_router

    field_app.runtime = field_app.Runtime(tmp_path / "field_runtime")
    survey_router.config_store = survey_router.ConfigStore(tmp_path / "cfg")
    project = SurveyProject.create(tmp_path / "projects", "API Control")
    survey_router.current_project = project
    client = TestClient(field_app.app)

    library = client.get("/api/v9/crs/library", params={"query": "Missouri East", "limit": 20})
    assert library.status_code == 200, library.text
    assert library.json()["results"]

    coordinate = client.post(
        "/api/v9/project/coordinate-system",
        json={
            "crs": "EPSG:26996",
            "horizontal_units": "meters",
            "vertical_units": "meters",
            "local_site": {
                "enabled": True,
                "name": "Site Ground",
                "grid_origin_northing": 0,
                "grid_origin_easting": 0,
                "local_origin_northing": 0,
                "local_origin_easting": 0,
                "grid_to_ground_factor": 1.0,
                "rotation_deg": 0.0,
            },
        },
    )
    assert coordinate.status_code == 200, coordinate.text
    assert coordinate.json()["local_site"]["enabled"] is True

    source = tmp_path / "control.csv"
    source.write_text(
        "P,N,E,elev,Code,Time,Epochs,Duration_Minutes,Satellites\n"
        "12A,4300000.000,600000.000,100.000,CTRL,08:00 AM,300,5,5\n"
        "12B,4300000.010,600000.010,100.010,CTRL,09:15 AM,300,5,6\n"
        "12C,4299999.995,599999.995,99.995,CTRL,10:30 AM,300,5,7\n",
        encoding="utf-8",
    )
    imported = client.post("/api/v9/control/import", json={"file_path": str(source)})
    assert imported.status_code == 200, imported.text
    workspace = client.get("/api/v9/control/workspace")
    assert workspace.status_code == 200
    assert workspace.json()["observations"][0]["point_id"].startswith("12")

    qc = client.post("/api/v9/control/qc-best-three", json={"horizontal_tolerance": 0.045, "vertical_tolerance": 0.045, "reshoot_count": 3})
    assert qc.status_code == 200, qc.text
    body = qc.json()
    assert body["accepted_count"] == 1
    assert Path(body["deliverables"]["accepted_csv"]).is_file()
    assert Path(body["deliverables"]["reshoot_csv"]).is_file()
    assert Path(body["deliverables"]["xlsx"]).is_file()

    custom = client.post(
        "/api/v9/control/qc-export",
        json={
            "run_id": body["run_id"],
            "fields": ["control_id", "northing", "easting", "code", "latitude", "longitude", "source_observations", "field_qc_status", "minimum_time_gap_minutes", "output_crs"],
            "coordinate_mode": "project",
            "target_crs": "",
            "output_format": "csv",
            "profile_name": "Accepted Control Test",
        },
    )
    assert custom.status_code == 200, custom.text
    export_path = Path(custom.json()["path"])
    assert export_path.is_file()
    text = export_path.read_text(encoding="utf-8-sig")
    assert "latitude" in text and "longitude" in text and "code" in text and "12A" in text
    assert "field_qc_status" in text and "minimum_time_gap_minutes" in text and "PASS" in text

    profiles = client.get("/api/v9/control/export-profiles")
    assert profiles.status_code == 200, profiles.text
    assert any(x["profile"].get("profile_name") == "Accepted Control Test" for x in profiles.json()["profiles"])

    geographic = client.post(
        "/api/v9/control/qc-export",
        json={
            "run_id": body["run_id"],
            "fields": ["control_id", "northing", "easting", "code"],
            "coordinate_mode": "geographic",
            "target_crs": "",
            "output_format": "csv",
            "profile_name": "Geographic Control Test",
        },
    )
    assert geographic.status_code == 200, geographic.text
    assert geographic.json()["fields"] == ["control_id", "latitude", "longitude", "code"]
    geo_text = Path(geographic.json()["path"]).read_text(encoding="utf-8-sig")
    assert "latitude" in geo_text and "longitude" in geo_text and "northing" not in geo_text

    bad_target = client.post(
        "/api/v9/control/qc-export",
        json={
            "run_id": body["run_id"],
            "fields": ["control_id", "northing", "easting"],
            "coordinate_mode": "target",
            "target_crs": "EPSG:4326",
            "output_format": "csv",
            "profile_name": "Bad Target",
        },
    )
    assert bad_target.status_code == 400


def test_control_workspace_ui_exposes_tbc_style_flow():
    html = Path("surveysync/static/index.html").read_text(encoding="utf-8")
    js = Path("surveysync/static/app.js").read_text(encoding="utf-8")
    assert "Control Survey Workspace" in html
    assert "Local Site / modified-ground settings" in html
    assert 'id="hTol" type="number" value="0.045"' in html
    assert 'id="vTol" type="number" value="0.045"' in html
    assert 'id="controlRunBest3"' in html
    assert 'id="controlSpatialTol"' in html
    assert 'id="controlRequireFieldMetadata"' in html
    assert 'id="controlMinTimeGap"' in html
    assert 'id="controlMinEpochs"' in html
    assert 'id="controlMinDuration"' in html
    assert 'id="controlMinSatellites"' in html
    assert 'id="controlMapCanvas"' in html
    assert 'id="controlCustomExport"' in html
    assert 'id="controlSavedExportProfile"' in html
    assert 'value="code" checked' in html
    assert "/api/v9/crs/library" in js
    assert "/api/v9/control/qc-best-three" in js
    assert "/api/v9/control/qc-export" in js
    assert "/api/v9/control/export-profiles" in js


def test_control_id_column_with_shot_suffixes_groups_by_numeric_base(tmp_path):
    project = SurveyProject.create(tmp_path, "Control ID Suffix")
    source = tmp_path / "control_id_suffix.csv"
    source.write_text(
        "control_id,northing,easting,elevation,description\n"
        "100A,100.000,200.000,10.000,CTRL\n"
        "100B,100.020,200.010,10.010,CTRL\n"
        "100C,99.990,199.995,9.995,CTRL\n",
        encoding="utf-8",
    )
    rows = parse_control_csv(source)
    assert [r["control_id"] for r in rows] == ["100", "100", "100"]
    assert [r["point_id"] for r in rows] == ["100A", "100B", "100C"]


def test_legacy_split_control_ids_are_auto_repaired_before_qc(tmp_path):
    project = SurveyProject.create(tmp_path, "Legacy Split")
    observations = [
        {"control_id":"100","point_id":"100A","northing":0.0,"easting":0.0,"elevation":0.0},
        {"control_id":"100","point_id":"100B","northing":1.0,"easting":0.0,"elevation":0.0},
        {"control_id":"100","point_id":"100C","northing":0.0,"easting":1.0,"elevation":1.0},
    ]
    assert import_observations(project.db, observations) == 3
    # Simulate a project imported by the older parser that incorrectly stored the
    # full shot label as the control id.
    with project.db.connect() as conn:
        conn.execute("UPDATE control_observations SET control_id=point_id")

    result = run_best_triplet_qc(project.db, 0.045, 0.045, coordinate_context=project.coordinate_settings())
    assert result["control_count"] == 1
    item = result["results"][0]
    assert item["control_id"] == "100"
    assert set(item["existing_point_ids"]) == {"100A", "100B", "100C"}
    assert item["reshoot_point_ids"] == ["100D", "100E", "100F"]
    with project.db.connect() as conn:
        groups = [r[0] for r in conn.execute("SELECT DISTINCT control_id FROM control_observations ORDER BY control_id")]
    assert groups == ["100"]


def test_spatial_grouping_flags_and_uses_probable_misnumber_for_qc(tmp_path):
    project = SurveyProject.create(tmp_path, "Spatial Misnumber")
    observations = [
        {"control_id":"1","point_id":"1A","northing":100.000,"easting":200.000,"elevation":10.000},
        {"control_id":"1","point_id":"1B","northing":100.010,"easting":200.000,"elevation":10.010},
        # Surveyor intended 1C but keyed 2C. Location and unused C suffix corroborate Control 1.
        {"control_id":"2","point_id":"2C","northing":99.995,"easting":200.005,"elevation":9.995},
    ]
    import_observations(project.db, observations)
    result = run_best_triplet_qc(
        project.db, 0.045, 0.045,
        coordinate_context={"horizontal_units":"us_survey_feet"},
        spatial_group_tolerance=0.25,
    )
    assert result["control_count"] == 1
    assert result["accepted_count"] == 1
    assert result["spatial_grouping"]["probable_misnumber_count"] == 1
    flag = result["spatial_grouping"]["flags"][0]
    assert flag["type"] == "PROBABLE_MISNUMBER"
    assert flag["point_id"] == "2C"
    assert flag["suggested_control_id"] == "1"
    assert flag["suggested_point_id"] == "1C"
    item = result["results"][0]
    assert item["control_id"] == "1"
    assert set(item["existing_point_ids"]) == {"1A", "1B", "2C"}
    assert set(item["analysis_point_ids"]) == {"1A", "1B", "1C"}
    assert item["numbering_flags"][0]["point_id"] == "2C"


def test_spatial_misnumber_counts_inferred_suffix_before_reshoot_ids(tmp_path):
    project = SurveyProject.create(tmp_path, "Spatial Misnumber Reshoot")
    observations = [
        {"control_id":"1","point_id":"1A","northing":0.000,"easting":0.000,"elevation":0.000},
        {"control_id":"1","point_id":"1B","northing":0.080,"easting":0.000,"elevation":0.000},
        {"control_id":"2","point_id":"2C","northing":0.160,"easting":0.000,"elevation":0.000},
    ]
    import_observations(project.db, observations)
    result = run_best_triplet_qc(
        project.db, 0.045, 0.045,
        coordinate_context={"horizontal_units":"us_survey_feet"},
        spatial_group_tolerance=0.25,
    )
    item = result["results"][0]
    assert item["status"] == "RESHOOT"
    assert set(item["analysis_point_ids"]) == {"1A", "1B", "1C"}
    assert item["reshoot_point_ids"] == ["1D", "1E", "1F"]

def test_control_field_requirements_parse_and_pass_strict_qc(tmp_path):
    project = SurveyProject.create(tmp_path, "Field Requirements")
    source = tmp_path / "field_requirements.csv"
    source.write_text(
        "P,N,E,elev,Time,Epochs,Duration_Minutes,Satellites\n"
        "20A,100.000,200.000,10.000,08:00 AM,300,,5\n"
        "20B,100.010,200.000,10.010,09:00 AM,250,5,6\n"
        "20C,99.995,200.005,9.995,10:15 AM,300,,7\n",
        encoding="utf-8",
    )
    rows=parse_control_csv(source)
    assert rows[0]["epoch_count"] == 300
    assert rows[1]["duration_seconds"] == 300.0
    assert rows[2]["satellite_count"] == 7
    assert rows[0]["observed_time_provided"] == 1
    import_observations(project.db, rows)
    result=run_best_triplet_qc(
        project.db,0.045,0.045,
        coordinate_context={"horizontal_units":"us_survey_feet"},
        require_field_metadata=True,
        min_time_separation_minutes=60,
        min_epochs=300,
        min_duration_seconds=300,
        min_satellites=5,
    )
    assert result["accepted_count"] == 1
    selected=result["results"][0]["selected"]
    assert selected["field_validation"]["status"] == "PASS"
    assert selected["field_validation"]["time_separation"]["minimum_gap_minutes"] == 60.0


def test_control_field_requirements_reject_short_spacing_and_low_satellites(tmp_path):
    project = SurveyProject.create(tmp_path, "Field Requirements Fail")
    observations=[
        {"control_id":"30","point_id":"30A","northing":100.000,"easting":200.000,"elevation":10.000,"observed_utc":"08:00 AM","observed_time_provided":1,"epoch_count":300,"satellite_count":5},
        {"control_id":"30","point_id":"30B","northing":100.010,"easting":200.000,"elevation":10.010,"observed_utc":"08:30 AM","observed_time_provided":1,"epoch_count":300,"satellite_count":6},
        {"control_id":"30","point_id":"30C","northing":99.995,"easting":200.005,"elevation":9.995,"observed_utc":"10:00 AM","observed_time_provided":1,"duration_seconds":300,"satellite_count":4},
    ]
    import_observations(project.db,observations)
    result=run_best_triplet_qc(
        project.db,0.045,0.045,coordinate_context={"horizontal_units":"us_survey_feet"},
        require_field_metadata=True,min_time_separation_minutes=60,min_epochs=300,min_duration_seconds=300,min_satellites=5,
    )
    item=result["results"][0]
    assert item["status"] == "RESHOOT"
    fv=item["selected"]["field_validation"]
    assert fv["status"] == "FAIL"
    assert any("less than 60" in x for x in fv["failures"])
    assert any("fewer than 5 satellites" in x for x in fv["failures"])


def test_control_field_requirements_missing_metadata_is_review_when_strict(tmp_path):
    project=SurveyProject.create(tmp_path,"Missing Field Metadata")
    import_observations(project.db,[
        {"control_id":"40","point_id":"40A","northing":0.000,"easting":0.000,"elevation":0.000},
        {"control_id":"40","point_id":"40B","northing":0.010,"easting":0.000,"elevation":0.010},
        {"control_id":"40","point_id":"40C","northing":0.000,"easting":0.010,"elevation":0.005},
    ])
    strict=run_best_triplet_qc(project.db,0.045,0.045,coordinate_context={"horizontal_units":"us_survey_feet"},require_field_metadata=True)
    assert strict["accepted_count"] == 0
    assert strict["results"][0]["status"] == "REVIEW"
    assert strict["results"][0]["selected"]["field_validation"]["status"] == "UNVERIFIED"


def _control_jxl(path: Path) -> Path:
    path.write_text(
        '''<?xml version="1.0" encoding="utf-8"?>
<JobXML jobName="Control JOB" version="6.6" product="Trimble Access">
  <Environment><CoordinateSystem><CoordinateSystemName>Missouri East</CoordinateSystemName></CoordinateSystem></Environment>
  <FieldBook>
    <GNSSObservation><PointName>100A</PointName><StartDate>2026-09-19</StartDate><StartTime>08:00:00</StartTime><EpochCount>300</EpochCount><DurationSeconds>300</DurationSeconds><SatelliteCount>7</SatelliteCount></GNSSObservation>
    <GNSSObservation><PointName>100B</PointName><StartDate>2026-09-19</StartDate><StartTime>09:10:00</StartTime><EpochCount>320</EpochCount><DurationSeconds>310</DurationSeconds><SatelliteCount>8</SatelliteCount></GNSSObservation>
    <GNSSObservation><PointName>100C</PointName><StartDate>2026-09-19</StartDate><StartTime>10:20:00</StartTime><EpochCount>300</EpochCount><DurationSeconds>300</DurationSeconds><SatelliteCount>9</SatelliteCount></GNSSObservation>
  </FieldBook>
  <Reductions>
    <Point><Name>100A</Name><Code>CTRL</Code><SurveyMethod>GNSS</SurveyMethod><Grid><North>1000.000</North><East>2000.000</East><Elevation>100.000</Elevation></Grid></Point>
    <Point><Name>100B</Name><Code>CTRL</Code><SurveyMethod>GNSS</SurveyMethod><Grid><North>1000.010</North><East>2000.010</East><Elevation>100.010</Elevation></Grid></Point>
    <Point><Name>100C</Name><Code>CTRL</Code><SurveyMethod>GNSS</SurveyMethod><Grid><North>999.995</North><East>1999.995</East><Elevation>99.995</Elevation></Grid></Point>
  </Reductions>
</JobXML>''', encoding="utf-8")
    return path


def test_controlsync_jobxml_import_preserves_gnss_metadata(tmp_path):
    from surveysync.control import parse_control_source
    parsed = parse_control_source(_control_jxl(tmp_path / "control.jxl"), tmp_path / "derived")
    assert parsed["format"] == "trimble_jobxml"
    rows = parsed["observations"]
    assert [r["control_id"] for r in rows] == ["100", "100", "100"]
    assert [r["point_id"] for r in rows] == ["100A", "100B", "100C"]
    assert rows[0]["observed_utc"] == "2026-09-19 08:00:00"
    assert rows[0]["epoch_count"] == 300
    assert rows[0]["duration_seconds"] == 300.0
    assert rows[0]["satellite_count"] == 7
    assert parsed["field_metadata_counts"] == {"shot_time":3,"epochs":3,"duration":3,"satellites":3}


def test_controlsync_api_accepts_trimble_job_directly(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg_job"))
    from fastapi.testclient import TestClient
    from fieldbook_sync import app as field_app
    from surveysync import router as survey_router
    import surveysync.control as control_module

    field_app.runtime = field_app.Runtime(tmp_path / "field_runtime_job")
    survey_router.config_store = survey_router.ConfigStore(tmp_path / "cfg_job")
    project = SurveyProject.create(tmp_path / "projects", "Trimble Control", crs="EPSG:2278")
    survey_router.current_project = project
    client = TestClient(field_app.app)

    job = tmp_path / "control.job"
    job.write_bytes(b"trimble proprietary placeholder")
    jxl = _control_jxl(tmp_path / "converted.jxl")

    def fake_prepare(source, work_dir, **kwargs):
        return jxl, {"converted": True, "input_path": str(source), "jobxml_path": str(jxl), "generator_path": "TEST"}

    monkeypatch.setattr(control_module, "prepare_jobxml", fake_prepare)
    imported = client.post("/api/v9/control/import", json={"file_path": str(job)})
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["format"] == "trimble_jobxml"
    assert body["count"] == 3
    assert body["conversion"]["converted"] is True
    assert body["field_metadata_counts"]["shot_time"] == 3

    workspace = client.get("/api/v9/control/workspace").json()
    assert {x["control_id"] for x in workspace["observations"]} == {"100"}
    qc = client.post("/api/v9/control/qc-best-three", json={"require_field_metadata": True})
    assert qc.status_code == 200, qc.text
    result = qc.json()["results"][0]
    assert result["status"] == "PASS"
    assert set(result["selected"]["point_ids"]) == {"100A", "100B", "100C"}


def test_controlsync_ui_mentions_trimble_job_direct_import():
    html = Path("surveysync/static/index.html").read_text(encoding="utf-8")
    assert "Trimble Access JOB/JobXML directly" in html
    assert "CSV, TXT, TSV, JOB or JXL" in html


def test_crs_browser_uses_projected_geographic_and_state_plane_folders():
    root = browse_crs_library("")
    names = {x["name"] for x in root["folders"]}
    assert "Projected Coordinate Systems" in names
    assert "Geographic Coordinate Systems" in names
    projected = browse_crs_library("projected")
    assert any(x["path"] == "projected/state_plane" for x in projected["folders"])
    datums = browse_crs_library("projected/state_plane")
    nad2011 = next(x for x in datums["folders"] if x["name"] == "NAD 1983 (2011)")
    states = browse_crs_library(nad2011["path"])
    missouri = next(x for x in states["folders"] if x["name"] == "Missouri")
    systems = browse_crs_library(missouri["path"])["systems"]
    assert any("Missouri East" in x["name"] for x in systems)
    assert any(x["id"] in {"EPSG:6512", "ESRI:102696"} for x in systems)


def test_crs_browser_api_and_ui_are_folder_based(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg_browser"))
    from fastapi.testclient import TestClient
    from fieldbook_sync import app as field_app
    from surveysync import router as survey_router

    field_app.runtime = field_app.Runtime(tmp_path / "field_runtime_browser")
    survey_router.config_store = survey_router.ConfigStore(tmp_path / "cfg_browser")
    survey_router.current_project = SurveyProject.create(tmp_path / "projects_browser", "CRS Browser")
    client = TestClient(field_app.app)
    result = client.get("/api/v9/crs/browser", params={"path": "projected/state_plane/nad_1983_2011/missouri"})
    assert result.status_code == 200, result.text
    assert any("Missouri East" in x["name"] for x in result.json()["systems"])
    js = Path("surveysync/static/app.js").read_text(encoding="utf-8")
    css = Path("surveysync/static/styles.css").read_text(encoding="utf-8")
    assert "/api/v9/crs/browser" in js
    assert "Projected and Geographic systems are organized into folders" in js
    assert ".crs-browser-grid" in css


def test_controlsync_tbc_inventory_jxl_ignores_nonshot_reference_points(tmp_path):
    path = tmp_path / "tbc_control_inventory.jxl"
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<JOBFile jobName="TBC Control" version="6.33" product="Trimble Business Center" productVersion="43.0">
  <FieldBook/><Reductions/>
  <InventoryData>
    <Point><Name>PRS150287182554</Name><Grid><North>325298.4</North><East>272023.9</East><Elevation>164.0</Elevation></Grid><SurveyMethod>KeyedIn</SurveyMethod></Point>
    <Point><Name>100A</Name><Code>CTRL</Code><Grid><North>304725.10</North><East>273455.20</East><Elevation>152.70</Elevation></Grid></Point>
    <Point><Name>100B</Name><Code>CTRL</Code><Grid><North>304725.11</North><East>273455.21</East><Elevation>152.71</Elevation></Grid></Point>
    <Point><Name>100C</Name><Code>CTRL</Code><Grid><North>304725.09</North><East>273455.195</East><Elevation>152.695</Elevation></Grid></Point>
  </InventoryData>
</JOBFile>""", encoding="utf-8")
    parsed = parse_control_source(path, tmp_path / "derived")
    assert [r["point_id"] for r in parsed["observations"]] == ["100A", "100B", "100C"]
    assert parsed["metadata"]["point_source"] == "InventoryData"
    assert parsed["metadata"]["ignored_reference_points"] == ["PRS150287182554"]
