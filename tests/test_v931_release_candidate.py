from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def test_v931_version_surfaces_are_consistent():
    from surveysync import __version__

    version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    installer = (ROOT / "installer" / "SurveySync.iss").read_text(encoding="utf-8")
    desktop = (ROOT / "desktop.py").read_text(encoding="utf-8")
    shell = (ROOT / "surveysync" / "static" / "index.html").read_text(encoding="utf-8")

    assert version == __version__ == "9.3.1"
    assert '#define MyAppVersion "9.3.1"' in installer
    assert "SurveySync_Setup_9.3.1" in installer
    assert "VersionInfoVersion=9.3.1.0" in installer
    assert 'APP_NAME = "SurveySync v9.3.1"' in desktop
    assert "<title>SurveySync v9.3.1</title>" in shell


def test_startup_update_check_is_not_nested_in_storage_event():
    js = (ROOT / "surveysync" / "static" / "app.js").read_text(encoding="utf-8")

    assert js.count("const SS_UPDATE_CHECK_KEY='surveysync-last-update-check';") == 1
    assert js.count("setTimeout(()=>startupUpdateCheck(false),900);") == 1
    assert "window.addEventListener('storage',e=>{" in js
    assert "if(![SS_APPEARANCE_KEY,SS_PRODUCT_THEME_KEY,SS_ACCENT_KEY].includes(e.key))return;" in js
    assert "window.addEventListener('storage',e=>{if([SS_APPEARANCE_KEY" not in js


def test_file_association_switches_do_not_begin_recovery_session():
    desktop = (ROOT / "desktop.py").read_text(encoding="utf-8")

    register = desktop.index('if "--register-fbs" in args_raw:')
    unregister = desktop.index('if "--unregister-fbs" in args_raw:')
    begin = desktop.index("begin_session(ss_config_store.root)")
    assert register < begin
    assert unregister < begin


def test_session_recovery_distinguishes_clean_and_interrupted_runs(tmp_path):
    from surveysync.session_recovery import begin_session, end_session, recovery_summary

    first = begin_session(tmp_path)
    assert first["active"] is True
    end_session(tmp_path)

    clean = begin_session(tmp_path)
    assert clean["previous_unclean"] is None
    end_session(tmp_path)

    interrupted = begin_session(tmp_path)
    assert interrupted["active"] is True
    next_session = begin_session(tmp_path)
    assert next_session["previous_unclean"]["session_id"] == interrupted["session_id"]
    assert recovery_summary(tmp_path, None)["unclean_shutdown_detected"] is True


def test_data_inspector_cache_refreshes_active_project_context(tmp_path, monkeypatch):
    from surveysync import data_inspector

    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(data_inspector, "_cache_root", lambda: cache)

    context = {
        "project_open": True,
        "project_name": "Project A",
        "project_path": str(tmp_path / "a"),
        "crs": "EPSG:2278",
        "horizontal_units": "US survey feet",
        "vertical_units": "US survey feet",
    }
    monkeypatch.setattr(data_inspector, "_project_context", lambda: dict(context))

    source = tmp_path / "points.csv"
    source.write_text(
        "PointID,Northing,Easting,Elevation,Code\n"
        + "\n".join(f"{i},{1000+i},{2000+i},{50+i/10},604" for i in range(1, 10)),
        encoding="utf-8",
    )

    first = data_inspector.inspect_path(str(source))
    assert first["cached"] is False
    assert first["project_context"]["project_name"] == "Project A"
    assert first["crs_status"] == "Current project CRS: EPSG:2278"

    context.update(
        {
            "project_name": "Project B",
            "project_path": str(tmp_path / "b"),
            "crs": "EPSG:26915",
            "horizontal_units": "meters",
            "vertical_units": "meters",
        }
    )
    second = data_inspector.inspect_path(str(source))
    assert second["cached"] is True
    assert second["project_context"]["project_name"] == "Project B"
    assert second["crs_status"] == "Current project CRS: EPSG:26915"
    assert second["units_status"] == "Current project units: meters / meters"


def test_toposync_qc_profile_crud(tmp_path, monkeypatch):
    from surveysync.topo import profiles

    monkeypatch.setattr(profiles, "workspace", lambda: (tmp_path, None))
    saved = profiles.save_profile(
        profile_id="Road QC",
        name="Road QC",
        description="Production roadway QC",
        settings={"min_offset_ft": 0.4},
        rules=[{"code": "604", "role": "surface"}],
    )

    assert saved["profile_id"] == "road-qc"
    assert saved["advisory_only"] is True
    assert profiles.list_profiles()[0]["name"] == "Road QC"
    assert profiles.delete_profile("road-qc")["deleted"] is True
    assert profiles.list_profiles() == []


def test_toposync_review_history_and_calibration(tmp_path, monkeypatch):
    from surveysync.topo import routes
    from surveysync.topo.storage import save_record

    monkeypatch.setattr(routes, "workspace", lambda: (tmp_path, None))
    run_id = save_record(
        tmp_path,
        {
            "kind": "analysis",
            "source_name": "road.csv",
            "source_sha256": "abc",
            "algorithm_version": "rod-height-chain-v1",
            "result": {
                "point_count": 20,
                "probable_count": 1,
                "suppressed_count": 0,
                "settings": {},
                "candidates": [
                    {
                        "candidate_id": "RHB-0001",
                        "start_point": "100",
                        "end_point": "120",
                        "estimated_rod_bust": -1.83,
                        "offset_std_dev": 0.04,
                        "confidence": 92,
                        "supporting_features": ["671", "694", "871"],
                    }
                ],
            },
        },
    )

    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    reviewed = client.post(
        f"/api/v9/topo/runs/{run_id}/review",
        json={
            "candidate_id": "RHB-0001",
            "decision": "confirmed_bust",
            "reason": "Confirmed against field notes and adjacent pavement chains.",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["advisory_only"] is True

    history = client.get("/api/v9/topo/runs")
    assert history.status_code == 200
    assert history.json()["runs"][0]["run_id"] == run_id

    calibration = client.get("/api/v9/topo/reviews/calibration")
    assert calibration.status_code == 200
    body = calibration.json()
    assert body["review_count"] == 1
    assert body["confirmed_bust_count"] == 1
    assert body["suggested_consistency_ft"] == 0.08
    assert body["advisory_only"] is True
