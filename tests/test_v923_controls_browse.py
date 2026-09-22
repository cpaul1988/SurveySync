from pathlib import Path

from surveysync.control import analyze_all, import_observations, list_control_ids, list_observations, parse_control_csv
from surveysync.project import SurveyProject


def test_bulk_control_database_import_and_analyze(tmp_path):
    p = SurveyProject.create(tmp_path, "Control DB", crs="EPSG:2278")
    src = tmp_path / "control_all.csv"
    src.write_text(
        "Control ID,Northing,Easting,Elevation,Shot ID,Session\n"
        "CP1,100.000,200.000,10.000,A,S1\n"
        "CP1,100.020,200.010,10.010,B,S1\n"
        "CP1,100.010,199.990,9.995,C,S2\n"
        "CP2,500.000,600.000,20.000,A,S1\n"
        "CP2,500.030,600.000,20.020,B,S2\n"
        "CP3,900.000,1000.000,30.000,A,S1\n",
        encoding="utf-8",
    )
    rows = parse_control_csv(src)
    assert len(rows) == 6
    assert rows[0]["control_id"] == "CP1"
    assert rows[0]["shot_id"] == "A"
    assert rows[0]["session_id"] == "S1"
    assert import_observations(p.db, rows) == 6

    controls = {r["control_id"]: r for r in list_control_ids(p.db)}
    assert controls["CP1"]["observation_count"] == 3
    assert controls["CP2"]["observation_count"] == 2
    assert controls["CP3"]["observation_count"] == 1
    assert len(list_observations(p.db)) == 6

    result = analyze_all(p.db, "arithmetic", 0.10, 0.10, min_observations=2)
    assert result["control_count"] == 3
    assert result["solved_count"] == 2
    assert result["skipped_count"] == 1
    by_id = {r["control_id"]: r for r in result["results"]}
    assert by_id["CP1"]["status"] == "PASS"
    assert by_id["CP2"]["status"] == "PASS"
    assert by_id["CP3"]["status"] == "INSUFFICIENT_SHOTS"
    with p.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_observations").fetchone()[0] == 6
        assert conn.execute("SELECT COUNT(*) FROM control_solutions").fetchone()[0] == 2


def test_bulk_control_api_import_analyze_and_observation_database(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg"))
    from fastapi.testclient import TestClient
    from fieldbook_sync import app as field_app
    from surveysync import router as survey_router

    field_app.runtime = field_app.Runtime(tmp_path / "fieldbook_runtime")
    survey_router.config_store = survey_router.ConfigStore(tmp_path / "cfg")
    p = SurveyProject.create(tmp_path / "projects", "API Control", crs="EPSG:2278")
    survey_router.current_project = p
    client = TestClient(field_app.app)

    src = tmp_path / "all_control.csv"
    src.write_text(
        "control_id,northing,easting,elevation\n"
        "A,1,2,3\nA,1.01,2.01,3.01\n"
        "B,10,20,30\nB,10.01,20.01,30.01\n",
        encoding="utf-8",
    )
    res = client.post("/api/v9/control/import-analyze", json={
        "file_path": str(src), "method": "arithmetic", "horizontal_tolerance": 0.1,
        "vertical_tolerance": 0.1, "min_observations": 2,
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported_count"] == 4
    assert body["solved_count"] == 2
    assert Path(body["report_path"]).is_file()
    obs = client.get("/api/v9/control/observations").json()
    assert len(obs["observations"]) == 4
    assert {x["control_id"] for x in obs["controls"]} == {"A", "B"}
    retry = client.post("/api/v9/control/import-analyze", json={
        "file_path": str(src), "method": "arithmetic", "horizontal_tolerance": 0.1,
        "vertical_tolerance": 0.1, "min_observations": 2,
    }).json()
    assert retry["already_imported"] is True
    assert retry["imported_count"] == 0
    assert len(client.get("/api/v9/control/observations").json()["observations"]) == 4


def test_main_shell_marks_every_manual_path_box_for_browsing():
    html = Path("surveysync/static/index.html").read_text(encoding="utf-8")
    app = Path("surveysync/static/app.js").read_text(encoding="utf-8")
    desktop = Path("desktop.py").read_text(encoding="utf-8")
    for element_id in (
        "fbsPath", "controlPath", "batchPaths", "levelPath", "traversePath",
        "suppGisPath", "photoFolder", "ftfPath", "spatialPath",
    ):
        marker = f'id="{element_id}"'
        pos = html.index(marker)
        tag_start = html.rfind("<", 0, pos)
        tag_end = html.index(">", pos)
        tag = html[tag_start:tag_end + 1]
        assert 'data-browse=' in tag, element_id
    assert "function installPathBrowsers()" in app
    assert "chooseFiles" in app
    assert "def choose_files" in desktop
    assert "bridge.choose_files" in desktop


def test_trimble_browse_uses_resilient_native_picker_fallback():
    html = Path("surveysync/static/index.html").read_text(encoding="utf-8")
    app = Path("surveysync/static/app.js").read_text(encoding="utf-8")
    assert 'id="trimbleJobBrowse"' in html
    assert "$('#trimbleJobBrowse').onclick" in app
    assert "Native file picker failed; using local fallback" in app
    assert "/api/v9/dialog/select-file?initial_directory=" in app
