from __future__ import annotations

import csv
import io
import json
import sqlite3
from contextlib import closing
from zipfile import ZipFile

import pytest
import surveysync.level_rechecks as level_rechecks

from surveysync.leveling import import_run, solve_saved_run, solution_history, _load_observations
from surveysync.level_rechecks import create_request, request_package, stage_return, review_return, approved_package, list_requests
from surveysync.project import SurveyProject


def _sight(point, bs=None, fs=None):
    row = {"point_id": point}
    for side, reading in (("bs", bs), ("fs", fs)):
        if reading is not None:
            row.update({f"{side}_upper": reading + .01, f"{side}_middle": reading, f"{side}_lower": reading - .01})
    return row


def setup(tmp_path, station=False):
    project = SurveyProject.create(tmp_path / "projects", "Ron Levels")
    rows = ([_sight("BM", bs=1), _sight("TP", bs=1, fs=1.2), _sight("END", fs=1)] if station
            else [_sight("TP1", bs=1, fs=.9), _sight("BM", bs=1, fs=1.2)])
    run_id = import_run(project.db, "Loop A", rows, start_elevation=100, known_end_elevation=100, adjustment_method="none")
    solved = solve_saved_run(project.db, run_id, closure_tolerance=.02,
                             row_layout="station_rows" if station else "differential_setups")
    assert solved["closure_pass"] is False
    return project, run_id, solved


def return_file(tmp_path, request, *, passing=True):
    path = tmp_path / "crew.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["SequenceNo", "PointID", "Side", "Upper", "Middle", "Lower", "Distance", "Notes"])
        for sight in request["sights"]:
            reading = (1.0 if sight["side"] == "BS" or request["row_layout"] == "station_rows" else (1.1 if passing else 1.2))
            writer.writerow([sight["sequence_no"], sight["point_id"], sight["side"], reading+.01, reading, reading-.01, "", "Crew rechecked"])
    return path


def test_reviewed_level_recheck_preserves_originals_and_revises_closure(tmp_path):
    project, run_id, original = setup(tmp_path)
    request = create_request(project, run_id, 2, .02, "Ron", "Reobserve the second setup")
    with ZipFile(io.BytesIO(request_package(project, request["id"]))) as z:
        assert json.loads(z.read("Request.json"))["setup_no"] == 2
        assert len(z.read("Returned_Level_Template.csv").decode().splitlines()) == 3
    staged = stage_return(project, request["id"], return_file(tmp_path, request))
    assert staged["return"]["preview"]["status"] == "PASS"
    assert abs(staged["return"]["preview"]["closure"]) < 1e-9
    with project.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM level_recheck_sights").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM level_solutions WHERE run_id=?", (run_id,)).fetchone()[0] == 1
    approved = review_return(project, request["id"], "APPROVE", "Ron", "Readings verified")
    assert approved["review"]["revision"] == 2
    history = solution_history(project.db, run_id)
    assert history[0]["active"] and history[0]["qc"]["closure_pass"]
    assert history[0]["adjusted"] is False
    assert len(history[0]["settings"]["recheck_sight_ids"]) == 2
    assert history[1]["solution_id"] == original["solution_id"]
    with project.db.connect() as conn:
        assert conn.execute("SELECT foresight FROM level_observations WHERE run_id=? AND sequence_no=2", (run_id,)).fetchone()[0] is None
    assert _load_observations(project.db, run_id)[1][1]["fs_middle"] == 1.1
    with ZipFile(io.BytesIO(approved_package(project, request["id"]))) as z:
        assert "Accepted_Level.csv" in z.namelist()
        assert json.loads(z.read("Review.json"))["return"]["sha256"] == staged["return"]["sha256"]
    assert approved_package(project, request["id"])
    with project.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM deliverables WHERE kind='approved_level_recheck'").fetchone()[0] == 1


def test_reject_stale_and_failed_return_do_not_change_active_solution(tmp_path):
    project, run_id, original = setup(tmp_path)
    request = create_request(project, run_id, 2, .02, "Ron", "Reobserve the second setup")
    stage_return(project, request["id"], return_file(tmp_path, request, passing=False))
    with pytest.raises(ValueError, match="pass closure"):
        review_return(project, request["id"], "APPROVE", "Ron", "Still failed")
    assert review_return(project, request["id"], "REJECT", "Ron", "Still failed")["status"] == "REJECTED"
    second = create_request(project, run_id, 2, .02, "Ron", "Reobserve the second setup")
    stage_return(project, second["id"], return_file(tmp_path, second))
    with project.db.connect() as conn:
        conn.execute("UPDATE level_observations SET notes='changed' WHERE run_id=? AND sequence_no=1", (run_id,))
    with pytest.raises(ValueError, match="changed after staging"):
        review_return(project, second["id"], "APPROVE", "Ron", "Looks good")
    assert solution_history(project.db, run_id)[0]["solution_id"] == original["solution_id"]
    assert list_requests(project)[-1]["status"] == "STAGED"


def test_station_row_return_updates_only_requested_sight(tmp_path):
    project, run_id, _ = setup(tmp_path, station=True)
    request = create_request(project, run_id, 1, .02, "Ron", "Reobserve the first setup")
    assert [(s["sequence_no"], s["side"]) for s in request["sights"]] == [(1,"BS"),(2,"FS")]
    stage_return(project, request["id"], return_file(tmp_path, request))
    review_return(project, request["id"], "APPROVE", "Ron", "TP sight checked")
    rows = _load_observations(project.db, run_id)[1]
    assert rows[1]["fs_middle"] == 1.0
    assert rows[1]["bs_middle"] == 1.0
    assert solution_history(project.db, run_id)[0]["qc"]["closure_pass"]


def test_separate_sights_and_incomplete_return(tmp_path):
    project = SurveyProject.create(tmp_path / "projects", "Separate sights")
    run_id = import_run(project.db, "Loop B", [_sight("BM", bs=1), _sight("TP", fs=.9),
                                                _sight("TP", bs=1), _sight("END", fs=1.2)],
                        start_elevation=100, known_end_elevation=100, adjustment_method="none")
    solve_saved_run(project.db, run_id, closure_tolerance=.02, row_layout="separate_sights")
    request = create_request(project, run_id, 2, .02, "Ron", "Reobserve final setup")
    assert [(s["sequence_no"], s["side"]) for s in request["sights"]] == [(3,"BS"),(4,"FS")]
    path = return_file(tmp_path, request)
    path.write_text("\n".join(path.read_text().splitlines()[:2]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="both requested"):
        stage_return(project, request["id"], path)
    stage_return(project, request["id"], return_file(tmp_path, request))
    review_return(project, request["id"], "APPROVE", "Ron", "Both sights verified")
    assert solution_history(project.db, run_id)[0]["qc"]["closure_pass"]


def test_project_api_and_source_hash_guard(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from fieldbook_sync import app as field_app
    from surveysync import router as survey_router

    project, run_id, _ = setup(tmp_path)
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg"))
    field_app.runtime = field_app.Runtime(tmp_path / "runtime")
    survey_router.config_store = survey_router.ConfigStore(tmp_path / "cfg")
    survey_router.current_project = project
    client = TestClient(field_app.app)
    created = client.post("/api/v9/level/rechecks", json={"run_id":run_id,"setup_no":2,"closure_tolerance":.02,"crew":"Ron","instructions":"Reobserve setup 2"})
    assert created.status_code == 200, created.text
    item = created.json()
    assert client.get(f"/api/v9/level/rechecks/{item['id']}/crew-package").status_code == 200
    staged = client.post(f"/api/v9/level/rechecks/{item['id']}/return", json={"file_path":str(return_file(tmp_path,item))})
    assert staged.status_code == 200, staged.text
    path = staged.json()["return"]["stored_path"]
    from pathlib import Path
    Path(path).chmod(0o600)
    Path(path).write_text("tampered", encoding="utf-8")
    denied = client.post(f"/api/v9/level/rechecks/{item['id']}/review", json={"decision":"APPROVE","reviewer":"Ron","note":"Looked good"})
    assert denied.status_code == 400 and "source changed" in denied.json()["detail"]
    assert solution_history(project.db, run_id)[0]["revision"] == 1


def test_existing_level_project_migrates_with_backup(tmp_path):
    project, run_id, _ = setup(tmp_path)
    with closing(sqlite3.connect(project.paths.db)) as conn:
        conn.execute("PRAGMA user_version=6")
        conn.commit()
    reopened = SurveyProject(project.paths.root)
    assert reopened.db.schema_version() == 7
    assert list(reopened.paths.migration_backups.glob("pre_schema_v6_*.db"))
    assert solution_history(reopened.db, run_id)[0]["revision"] == 1
    with reopened.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM level_recheck_sights").fetchone()[0] == 0


def test_approval_state_failure_rolls_back_solution_and_sights(tmp_path, monkeypatch):
    project, run_id, original = setup(tmp_path)
    request = create_request(project, run_id, 2, .02, "Ron", "Reobserve the second setup")
    stage_return(project, request["id"], return_file(tmp_path, request))
    def failed_save(*_args):
        raise OSError("state write failed")
    with monkeypatch.context() as patch:
        patch.setattr(level_rechecks, "_save", failed_save)
        with pytest.raises(OSError, match="state write failed"):
            review_return(project, request["id"], "APPROVE", "Ron", "Readings verified")
    assert list_requests(project)[0]["status"] == "STAGED"
    assert solution_history(project.db, run_id)[0]["solution_id"] == original["solution_id"]
    with project.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM level_recheck_sights").fetchone()[0] == 0


def test_legacy_json_rechecks_are_imported_once_into_transactional_state(tmp_path):
    project, run_id, _ = setup(tmp_path)
    path = project.paths.module_root / "ControlSync" / "level_rechecks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"requests": [{"id": "legacy", "status": "REJECTED"}]}))
    assert list_requests(project)[0]["id"] == "legacy"
    path.write_text(json.dumps({"requests": []}))
    assert list_requests(project)[0]["id"] == "legacy"


def test_truncated_return_reports_invalid_row(tmp_path):
    project, run_id, _ = setup(tmp_path)
    request = create_request(project, run_id, 2, .02, "Ron", "Reobserve the second setup")
    path = tmp_path / "short.csv"
    path.write_text("SequenceNo,PointID,Side,Upper,Middle,Lower\n2,BM,BS,1\n")
    with pytest.raises(ValueError, match="row 2 is missing"):
        stage_return(project, request["id"], path)
