from __future__ import annotations

import csv
import io
import json
import sqlite3
from zipfile import ZipFile

import pytest

from surveysync.control import import_observations, parse_control_csv, run_best_triplet_qc
from surveysync.control_reshoots import (
    approved_package,
    create_request,
    list_requests,
    request_package,
    review_return,
    stage_return,
)
from surveysync.project import SurveyProject


def setup_failed_control(tmp_path):
    project = SurveyProject.create(tmp_path / "projects", "Ron Reshoot", crs="EPSG:2278")
    source = tmp_path / "initial.csv"
    source.write_text("P,N,E,elev,Code\n8A,500.000,600.000,20.000,CTRL\n8B,500.120,600.000,20.000,CTRL\n8C,500.000,600.120,20.120,CTRL\n", encoding="utf-8")
    assert import_observations(project.db, parse_control_csv(source)) == 3
    run = run_best_triplet_qc(project.db, .045, .045, coordinate_context=project.coordinate_settings(), require_field_metadata=False)
    assert run["results"][0]["status"] == "RESHOOT"
    return project, run


def returned_file(tmp_path, ids):
    path = tmp_path / "return.csv"
    path.write_text("PointID,ControlID,Northing,Easting,Elevation\n" + "".join(
        f"{point_id},8,{500 + i*.005:.3f},{600 + i*.005:.3f},{20 + i*.005:.3f}\n" for i, point_id in enumerate(ids)), encoding="utf-8")
    return path


def test_reshoot_round_trip_keeps_return_staged_until_review(tmp_path):
    project, run = setup_failed_control(tmp_path)
    request = create_request(project, run["run_id"], "8", "Ron", "Reobserve each control shot independently")
    assert request["reserved_point_ids"] == ["8D", "8E", "8F"]
    with ZipFile(io.BytesIO(request_package(project, request["id"]))) as archive:
        assert json.loads(archive.read("Request.json"))["reserved_point_ids"] == request["reserved_point_ids"]
        assert list(csv.reader(io.StringIO(archive.read("Returned_Control_Template.csv").decode())))[1][0] == "8D"
    with pytest.raises(ValueError, match="reviewer must approve"):
        approved_package(project, request["id"])
    staged = stage_return(project, request["id"], returned_file(tmp_path, request["reserved_point_ids"]))
    assert staged["status"] == "STAGED"
    assert staged["return"]["preview"]["status"] == "PASS"
    assert staged["return"]["preview"]["uses_returned_shot"]
    with project.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_observations").fetchone()[0] == 3
    assert list_requests(project)[0]["status"] == "STAGED"
    approved = review_return(project, request["id"], "APPROVE", "Ron", "Field metadata and residuals checked")
    assert approved["status"] == "APPROVED"
    assert approved["review"]["after"]["status"] == "PASS"
    with project.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_observations").fetchone()[0] == 6
    with ZipFile(io.BytesIO(approved_package(project, request["id"]))) as archive:
        assert "8D" in archive.read("Accepted_Control.csv").decode()
        review = json.loads(archive.read("Review.json"))
        assert review["review"]["reviewer"] == "Ron"
        assert review["return"]["sha256"] == staged["return"]["sha256"]
    assert approved_package(project, request["id"])
    with project.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM deliverables WHERE kind='approved_reshoot'").fetchone()[0] == 1


def test_rejected_and_stale_returns_cannot_enter_control_database(tmp_path):
    project, run = setup_failed_control(tmp_path)
    request = create_request(project, run["run_id"], "8", "Crew A", "Reobserve control eight")
    path = returned_file(tmp_path, request["reserved_point_ids"])
    staged = stage_return(project, request["id"], path)
    assert review_return(project, request["id"], "REJECT", "Ron", "Bad field notes")["status"] == "REJECTED"
    with project.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_observations").fetchone()[0] == 3
    with pytest.raises(ValueError, match="Stage a returned file"):
        review_return(project, request["id"], "APPROVE", "Ron", "Try again")
    second = create_request(project, run["run_id"], "8", "Crew B", "Reobserve with full metadata")
    assert second["reserved_point_ids"] == ["8D", "8E", "8F"]
    stage_return(project, second["id"], path)
    with project.db.connect() as conn:
        conn.execute("UPDATE control_observations SET include=0 WHERE point_id='8A'")
    with pytest.raises(ValueError, match="changed after staging"):
        review_return(project, second["id"], "APPROVE", "Ron", "Looks good")
    assert list_requests(project)[1]["status"] == "STAGED"


def test_partial_or_wrong_control_return_is_refused(tmp_path):
    project, run = setup_failed_control(tmp_path)
    request = create_request(project, run["run_id"], "8", "Crew A", "Reobserve each point")
    path = returned_file(tmp_path, request["reserved_point_ids"][:2])
    with pytest.raises(ValueError, match="exactly one observation"):
        stage_return(project, request["id"], path)
    with pytest.raises(ValueError, match="already has an open"):
        create_request(project, run["run_id"], "8", "Crew B", "Duplicate request")


def test_failed_return_cannot_be_approved(tmp_path):
    project, run = setup_failed_control(tmp_path)
    request = create_request(project, run["run_id"], "8", "Ron", "Reobserve each shot")
    path = tmp_path / "bad-return.csv"
    path.write_text("PointID,ControlID,Northing,Easting,Elevation\n" + "".join(
        f"{point_id},8,{500+i*.2:.3f},{600+i*.2:.3f},{20+i*.2:.3f}\n"
        for i, point_id in enumerate(request["reserved_point_ids"])), encoding="utf-8")
    staged = stage_return(project, request["id"], path)
    assert staged["return"]["preview"]["status"] == "RESHOOT"
    with pytest.raises(ValueError, match="must pass QC"):
        review_return(project, request["id"], "APPROVE", "Ron", "Rejected by QC")
    with project.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_observations").fetchone()[0] == 3


def test_preview_closes_its_temporary_database_before_cleanup(tmp_path, monkeypatch):
    from surveysync import control_reshoots

    project, run = setup_failed_control(tmp_path)
    request = create_request(project, run["run_id"], "8", "Ron", "Reobserve each shot")
    original_connect = sqlite3.connect
    preview_connections = []

    def tracked_connect(database, *args, **kwargs):
        connection = original_connect(database, *args, **kwargs)
        if str(database).endswith("preview.db"):
            preview_connections.append(connection)
        return connection

    monkeypatch.setattr(control_reshoots.sqlite3, "connect", tracked_connect)
    stage_return(project, request["id"], returned_file(tmp_path, request["reserved_point_ids"]))
    assert preview_connections
    for connection in preview_connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")


def test_approval_does_not_revise_an_unrelated_control(tmp_path):
    project, _ = setup_failed_control(tmp_path)
    other = tmp_path / "other.csv"
    other.write_text("P,N,E,elev,Code\n7A,100,200,10,CTRL\n7B,100.005,200.005,10.005,CTRL\n7C,100.010,200.010,10.010,CTRL\n", encoding="utf-8")
    import_observations(project.db, parse_control_csv(other))
    run = run_best_triplet_qc(project.db, .045, .045, coordinate_context=project.coordinate_settings(), require_field_metadata=False)
    with project.db.connect() as conn:
        before = [tuple(row) for row in conn.execute("SELECT solution_id,revision FROM control_solutions WHERE control_id='7'")]
    request = create_request(project, run["run_id"], "8", "Ron", "Reobserve control eight")
    stage_return(project, request["id"], returned_file(tmp_path, request["reserved_point_ids"]))
    approved = review_return(project, request["id"], "APPROVE", "Ron", "Residuals checked")
    assert approved["review"]["after"]["status"] == "PASS"
    with project.db.connect() as conn:
        after = [tuple(row) for row in conn.execute("SELECT solution_id,revision FROM control_solutions WHERE control_id='7'")]
    assert after == before


def test_control_reshoot_project_api_and_hash_verification(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from fieldbook_sync import app as field_app
    from surveysync import router as survey_router

    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg"))
    project, run = setup_failed_control(tmp_path)
    field_app.runtime = field_app.Runtime(tmp_path / "runtime")
    survey_router.config_store = survey_router.ConfigStore(tmp_path / "cfg")
    survey_router.current_project = project
    client = TestClient(field_app.app)
    created = client.post("/api/v9/control/reshoots", json={"run_id": run["run_id"], "control_id": "8", "crew": "Ron", "instructions": "Reobserve three shots"})
    assert created.status_code == 200, created.text
    identifier = created.json()["id"]
    assert client.get(f"/api/v9/control/reshoots/{identifier}/crew-package").status_code == 200
    assert client.get(f"/api/v9/control/reshoots/{identifier}/approved-package").status_code == 400
    path = returned_file(tmp_path, created.json()["reserved_point_ids"])
    staged = client.post(f"/api/v9/control/reshoots/{identifier}/return", json={"file_path": str(path)})
    assert staged.status_code == 200, staged.text
    assert client.get("/api/v9/control/reshoots").json()["requests"][0]["status"] == "STAGED"
    source = staged.json()["return"]["stored_path"]
    from pathlib import Path
    Path(source).chmod(0o600)
    Path(source).write_bytes(b"tampered")
    denied = client.post(f"/api/v9/control/reshoots/{identifier}/review", json={"decision": "APPROVE", "reviewer": "Ron", "note": "Checked shots"})
    assert denied.status_code == 400
    assert "source changed" in denied.json()["detail"]
    with project.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM control_observations").fetchone()[0] == 3
