from __future__ import annotations

import sqlite3
from pathlib import Path

from surveysync.audit import CURRENT_SCHEMA_VERSION, utc_now
from surveysync.control import import_observations, solve
from surveysync.data_manager import database_health, list_rows, maintain_database, overview, update_record
from surveysync.project import SurveyProject
from surveysync.project_templates import list_templates


def test_project_bootstrap_uses_independent_template_database(tmp_path):
    a = SurveyProject.create(tmp_path, "Alpha", template_id="control_network", client="Client A", project_number="26001", crs="EPSG:2278")
    b = SurveyProject.create(tmp_path, "Beta", template_id="standard")
    assert a.paths.db.is_file() and b.paths.db.is_file()
    assert a.paths.db != b.paths.db
    assert a.db.schema_version() == CURRENT_SCHEMA_VERSION
    assert a.manifest["project_template"]["id"] == "control_network"
    assert a.manifest["client"] == "Client A"
    assert a.manifest["project_number"] == "26001"
    assert a.manifest["database_schema_version"] == CURRENT_SCHEMA_VERSION
    assert a.manifest["modules"]["ControlSync"]["enabled"] is True
    assert a.manifest["modules"]["UtilitySync"]["enabled"] is False
    with a.db.connect() as conn:
        md = dict(conn.execute("SELECT key,value FROM project_metadata").fetchall())
    assert md["project_name"] == "Alpha"
    assert md["template_id"] == "control_network"
    assert a.paths.photos.is_dir() and a.paths.deliverables.is_dir()
    assert any(x["id"] == "sewer_utility" for x in list_templates())


def test_existing_project_schema_migration_creates_backup(tmp_path):
    p = SurveyProject.create(tmp_path, "Legacy")
    conn = sqlite3.connect(str(p.paths.db))
    try:
        conn.execute("PRAGMA user_version=1")
        conn.commit()
    finally:
        conn.close()
    reopened = SurveyProject(p.paths.root)
    assert reopened.db.schema_version() == CURRENT_SCHEMA_VERSION
    backups = list(reopened.paths.migration_backups.glob("pre_schema_v1_*.db"))
    assert backups
    assert reopened.manifest["database_schema_version"] == CURRENT_SCHEMA_VERSION


def test_project_data_manager_controlled_edit_audits_snapshots_and_stales(tmp_path):
    p = SurveyProject.create(tmp_path, "Data Manager")
    obs = [
        {"control_id":"CP1","northing":100.0,"easting":200.0,"elevation":10.0,"include":1,"notes":""},
        {"control_id":"CP1","northing":100.1,"easting":200.1,"elevation":10.1,"include":1,"notes":""},
    ]
    assert import_observations(p.db, obs) == 2
    rows = list_rows(p, "control_observations")["rows"]
    rid = rows[0]["observation_id"]
    result = update_record(p, "control_observations", rid, {"elevation": "10.25"}, "Corrected transcription from field notes")
    assert result["snapshot"] and Path(result["snapshot"]["path"]).is_file()
    with p.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM data_edit_history WHERE record_id=?", (rid,)).fetchone()[0] == 1
        stale = conn.execute("SELECT state FROM derived_result_state WHERE result_kind='control' AND object_id='CP1'").fetchone()
    assert stale[0] == "STALE"
    solve(p.db, "CP1", horizontal_tolerance=1.0, vertical_tolerance=1.0)
    with p.db.connect() as conn:
        current = conn.execute("SELECT state FROM derived_result_state WHERE result_kind='control' AND object_id='CP1'").fetchone()
    assert current[0] == "CURRENT"


def test_project_data_manager_readonly_and_database_health(tmp_path):
    p = SurveyProject.create(tmp_path, "Health")
    ov = overview(p)
    assert ov["schema_version"] == CURRENT_SCHEMA_VERSION
    assert any(x["id"] == "audit_history" and x["mode"] == "readonly" for x in ov["datasets"])
    try:
        update_record(p, "audit_history", "missing", {"action":"x"}, "no")
        assert False, "read-only dataset should reject edits"
    except ValueError as exc:
        assert "read-only" in str(exc).lower()
    h = database_health(p)
    assert h["integrity_ok"] is True
    assert h["schema_current"] is True
    maintained = maintain_database(p)
    assert maintained["ok"] is True
    assert Path(maintained["snapshot"]["path"]).is_file()


def test_v924_api_project_templates_and_data_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg"))
    from fastapi.testclient import TestClient
    from fieldbook_sync import app as field_app
    from surveysync import router as survey_router
    survey_router.config_store = survey_router.ConfigStore(tmp_path / "cfg")
    field_app.runtime = field_app.Runtime(tmp_path / "field_runtime")
    client = TestClient(field_app.app)
    templates = client.get("/api/v9/project-templates")
    assert templates.status_code == 200
    assert any(x["id"] == "control_network" for x in templates.json()["templates"])
    created = client.post("/api/v9/project/create", json={"parent_folder":str(tmp_path / "projects"),"name":"API DB","template_id":"control_network","client":"Test Client","project_number":"24001","crs":"EPSG:2278","horizontal_units":"us_survey_feet","vertical_units":"us_survey_feet"})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["database"]["schema_version"] == CURRENT_SCHEMA_VERSION
    assert body["project_template"]["id"] == "control_network"
    ov = client.get("/api/v9/data-manager/overview")
    assert ov.status_code == 200
    assert any(x["id"] == "survey_points" for x in ov.json()["datasets"])
    health = client.get("/api/v9/database/health")
    assert health.status_code == 200 and health.json()["integrity_ok"] is True
    shell = client.get("/").text
    assert "Project Data Manager" in shell
    assert "SurveySync v9.3.0" in shell
