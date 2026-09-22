from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

from surveysync.comparison import compare_point_source
from surveysync.continuity import autosave_tick, compare_snapshot, create_snapshot, restore_snapshot
from surveysync.delivery import build_deliverable_package, export_points, load_profiles, save_profile
from surveysync.operations import explain, project_map_geojson, project_timeline, review_center
from surveysync.project import SurveyProject
from surveysync.qa import run_project_qa
from surveysync.qa_rules import load_rules, save_rules
from surveysync.staging import commit_stage, load_mapping_profiles, stage_import
from surveysync.task_queue import list_tasks, submit


def _project(tmp_path, name="Ops"):
    return SurveyProject.create(tmp_path, name, crs="EPSG:2278")


def _write_points(path: Path, rows: list[tuple]):
    text = "PtNo,North,East,Elev,Desc\n" + "\n".join(
        f"{pid},{n},{e},{'' if z is None else z},{desc}" for pid, n, e, z, desc in rows
    ) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def test_health_rules_and_coordinate_sanity_are_project_wide(tmp_path):
    p = _project(tmp_path)
    f = _write_points(tmp_path / "pts.csv", [("1", 1000, 2000, 10, "A"), ("2", 1010, 2010, None, "B")])
    st = stage_import(p, f); commit_stage(p, st["stage_id"])
    health = run_project_qa(p)
    assert health["readiness"] in {"READY", "REVIEW"}
    codes = {c["code"] for c in health["checks"]}
    assert "HEALTH_DUPLICATE_POINT_IDS" in codes
    assert "HEALTH_COORDINATE_SANITY" in codes
    assert "HEALTH_MISSING_ELEVATIONS" in codes

    rules = load_rules(p)
    rules["missing_elevations"]["enabled"] = False
    save_rules(p, rules)
    health2 = run_project_qa(p)
    disabled = next(c for c in health2["checks"] if c["code"] == "HEALTH_MISSING_ELEVATIONS")
    assert disabled["status"] == "SKIP"


def test_import_staging_learns_mapping_and_never_overwrites_duplicate_pointids(tmp_path):
    p = _project(tmp_path)
    f = _write_points(tmp_path / "crew.csv", [("100", 1, 2, 3, "IP"), ("101", 4, 5, 6, "CP")])
    st = stage_import(p, f)
    assert st["mapping"]["point_id"] == "PtNo"
    first = commit_stage(p, st["stage_id"])
    assert first["inserted"] == 2 and not first["conflicts"]
    assert load_mapping_profiles(p)

    st2 = stage_import(p, f)
    second = commit_stage(p, st2["stage_id"])
    assert second["inserted"] == 0
    assert second["conflicts"] == ["100", "101"]
    with p.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM canonical_points").fetchone()[0] == 2


def test_timeline_snapshots_restore_and_autosave(tmp_path):
    p = _project(tmp_path)
    f = _write_points(tmp_path / "pts.csv", [("1", 100, 200, 10, "A")])
    commit_stage(p, stage_import(p, f)["stage_id"])
    snap = create_snapshot(p, label="Before change")
    with p.db.connect() as conn:
        conn.execute("UPDATE canonical_points SET description='CHANGED' WHERE point_id='1'")
    cmp = compare_snapshot(p, snap["snapshot_id"])
    assert cmp["counts"]["points"]["delta"] == 0
    restored = restore_snapshot(p, snap["snapshot_id"])
    assert restored["restored"] is True
    with p.db.connect() as conn:
        assert conn.execute("SELECT description FROM canonical_points WHERE point_id='1'").fetchone()[0] == "A"
    assert any(x["action"] == "PROJECT_SNAPSHOT_RESTORED" for x in project_timeline(p))
    auto = autosave_tick(p, interval_seconds=60)
    assert "created" in auto


def test_file_and_project_comparison(tmp_path):
    p = _project(tmp_path / "a", "A")
    base = _write_points(tmp_path / "base.csv", [("1", 100, 200, 10, "A"), ("2", 110, 210, 11, "B")])
    commit_stage(p, stage_import(p, base)["stage_id"])
    revised = _write_points(tmp_path / "revised.csv", [("1", 100.1, 200, 10, "A"), ("3", 120, 220, 12, "C")])
    diff = compare_point_source(p, revised, horizontal_tolerance=0.01)
    assert diff["summary"] == {"added": 1, "removed": 1, "changed": 1, "unchanged": 0}

    p2 = _project(tmp_path / "b", "B")
    commit_stage(p2, stage_import(p2, revised)["stage_id"])
    project_diff = compare_point_source(p, p2.paths.root, horizontal_tolerance=0.01)
    assert project_diff["summary"]["changed"] == 1


def test_export_profiles_and_deliverable_package_manifest(tmp_path):
    p = _project(tmp_path)
    f = _write_points(tmp_path / "pts.csv", [("1", 100, 200, 10, "A")])
    commit_stage(p, stage_import(p, f)["stage_id"])
    profile = save_profile(p, {"id": "cad_review", "name": "CAD Review", "formats": ["csv", "pnezd"], "precision": 3})
    assert profile["id"] == "cad_review"
    run = export_points(p, "cad_review")
    assert len(run["files"]) == 2
    package = build_deliverable_package(p, profile_id="client_deliverable", label="Issue A")
    z = Path(package["path"])
    assert z.is_file()
    with zipfile.ZipFile(z) as zf:
        manifest = json.loads(zf.read("SurveySync_Manifest.json"))
    assert manifest["project_id"] == p.manifest["project_id"]
    assert manifest["files"]


def test_map_review_center_and_why_explanations(tmp_path):
    p = _project(tmp_path)
    f = _write_points(tmp_path / "pts.csv", [("1", 100, 200, 10, "A")])
    commit_stage(p, stage_import(p, f)["stage_id"])
    health = run_project_qa(p)
    fc = project_map_geojson(p)
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 1
    review = review_center(p)
    assert review["count"] >= 1
    point = next(x for x in review["items"] if x["kind"] == "point_review")
    why = explain(p, "point", point["object_id"])
    assert "review" in why["why"].lower()
    qa = next((x for x in review["items"] if x["kind"] == "qa"), None)
    if qa:
        evidence = explain(p, "qa", qa["id"])
        assert evidence["evidence"] is not None


def test_background_task_queue_records_completion_and_failure(tmp_path):
    p = _project(tmp_path)
    submit(p, "unit", "Successful task", lambda progress, cancelled: (progress(.5, "Half"), {"ok": True})[1])
    submit(p, "unit", "Failed task", lambda progress, cancelled: (_ for _ in ()).throw(RuntimeError("boom")))
    deadline = time.time() + 5
    rows = []
    while time.time() < deadline:
        rows = list_tasks(p)
        if len(rows) >= 2 and all(x["status"] in {"COMPLETED", "FAILED"} for x in rows[:2]):
            break
        time.sleep(.05)
    statuses = {x["label"]: x["status"] for x in rows}
    assert statuses["Successful task"] == "COMPLETED"
    assert statuses["Failed task"] == "FAILED"
    review = review_center(p)
    assert any(x["kind"] == "background_task" for x in review["items"])


def test_v921_api_operations_center(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg"))
    from fastapi.testclient import TestClient
    from fieldbook_sync import app as field_app
    from surveysync import router as survey_router

    field_app.runtime = field_app.Runtime(tmp_path / "fieldbook_runtime")
    survey_router.config_store = survey_router.ConfigStore(tmp_path / "cfg")
    p = _project(tmp_path / "projects", "API")
    survey_router.current_project = p
    client = TestClient(field_app.app)

    f = _write_points(tmp_path / "api_points.csv", [("10", 500, 600, 12, "CP")])
    staged = client.post("/api/v9/import/stage", json={"file_path": str(f), "kind": "points", "mapping": {}, "preview_rows": 5})
    assert staged.status_code == 200, staged.text
    sid = staged.json()["stage_id"]
    committed = client.post("/api/v9/import/commit", json={"stage_id": sid, "learn": True})
    assert committed.status_code == 200 and committed.json()["inserted"] == 1

    health = client.post("/api/v9/qa/run")
    assert health.status_code == 200 and "readiness" in health.json()
    snap = client.post("/api/v9/snapshots", json={"label": "API snapshot", "kind": "manual"})
    assert snap.status_code == 200
    assert client.get("/api/v9/timeline").status_code == 200
    assert client.get("/api/v9/review-center").status_code == 200
    assert client.get("/api/v9/project-map").json()["type"] == "FeatureCollection"
    assert client.get("/api/v9/export-profiles").status_code == 200


def test_snapshot_backup_explicitly_closes_sqlite_handles(tmp_path, monkeypatch):
    """Guard the Windows snapshot cleanup path against sqlite handle leaks."""
    import surveysync.continuity as continuity

    created = []

    class FakeConnection:
        def __init__(self, path):
            self.path = str(path)
            self.closed = False
            self.committed = False
            self.backed_up_to = None
            created.append(self)

        def backup(self, target):
            self.backed_up_to = target

        def commit(self):
            self.committed = True

        def close(self):
            self.closed = True

    monkeypatch.setattr(continuity.sqlite3, "connect", lambda path: FakeConnection(path))
    continuity._db_backup(tmp_path / "source.db", tmp_path / "dest.db")

    assert len(created) == 2
    assert created[0].backed_up_to is created[1]
    assert created[1].committed is True
    assert all(conn.closed for conn in created)
