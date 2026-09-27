from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from surveysync.pointcloud import PointCloudError, inspect_point_cloud, runtime_status
from surveysync.project import SurveyProject
from surveysync.workflow_engine import (
    approve_run,
    engine_status,
    export_workflows_yaml,
    import_workflows_yaml,
    list_runs,
    list_workflows,
    save_workflow,
    start_workflow,
)


def _write_minimal_las(path: Path) -> Path:
    point_count = 3
    header_size = 227
    point_record_length = 20
    data = bytearray(header_size + point_count * point_record_length)
    data[0:4] = b"LASF"
    data[24] = 1
    data[25] = 2
    struct.pack_into("<H", data, 94, header_size)
    struct.pack_into("<I", data, 96, header_size)
    struct.pack_into("<I", data, 100, 0)
    data[104] = 0
    struct.pack_into("<H", data, 105, point_record_length)
    struct.pack_into("<I", data, 107, point_count)
    struct.pack_into("<d", data, 131, 0.01)
    struct.pack_into("<d", data, 139, 0.01)
    struct.pack_into("<d", data, 147, 0.01)
    struct.pack_into("<d", data, 155, 1000.0)
    struct.pack_into("<d", data, 163, 2000.0)
    struct.pack_into("<d", data, 171, 100.0)
    struct.pack_into("<d", data, 179, 1010.0)
    struct.pack_into("<d", data, 187, 1000.0)
    struct.pack_into("<d", data, 195, 2020.0)
    struct.pack_into("<d", data, 203, 2000.0)
    struct.pack_into("<d", data, 211, 110.0)
    struct.pack_into("<d", data, 219, 100.0)
    path.write_bytes(data)
    return path


def _project(tmp_path: Path) -> SurveyProject:
    return SurveyProject.create(
        tmp_path,
        "Integration Project",
        crs="EPSG:2278",
        horizontal_units="us_survey_feet",
        vertical_units="us_survey_feet",
    )


def test_native_las_header_inspection_requires_no_optional_dependency(tmp_path):
    path = _write_minimal_las(tmp_path / "surface.las")

    result = inspect_point_cloud(path)

    assert result["metadata"]["reader"] == "native_las_header"
    assert result["metadata"]["version"] == "1.2"
    assert result["metadata"]["point_count"] == 3
    assert result["metadata"]["point_format"] == 0
    assert result["metadata"]["bounds"] == {
        "min_x": 1000.0,
        "min_y": 2000.0,
        "min_z": 100.0,
        "max_x": 1010.0,
        "max_y": 2020.0,
        "max_z": 110.0,
    }
    assert result["runtime"]["native_las_metadata"] is True


def test_invalid_las_signature_is_rejected(tmp_path):
    path = tmp_path / "bad.las"
    path.write_bytes(b"NOTLAS" + b"\x00" * 300)

    with pytest.raises(PointCloudError, match="valid LAS header"):
        inspect_point_cloud(path)


def test_point_cloud_import_preserves_immutable_source_and_audits(tmp_path):
    project = _project(tmp_path)
    path = _write_minimal_las(tmp_path / "control_surface.las")

    from surveysync.pointcloud import import_point_cloud, point_cloud_sources

    result = import_point_cloud(project, path, notes="Acceptance fixture")
    stored = Path(result["source"]["stored_path"])

    assert stored.is_file()
    assert stored.read_bytes() == path.read_bytes()
    assert result["metadata"]["point_count"] == 3
    assert [row["original_name"] for row in point_cloud_sources(project)] == [
        "control_surface.las"
    ]
    actions = [row["action"] for row in project.db.recent_audit(20)]
    assert "POINT_CLOUD_IMPORTED" in actions
    assert "SOURCE_IMPORTED" in actions


def test_workflow_yaml_round_trip_and_safe_manual_run(tmp_path):
    project = _project(tmp_path)
    saved = save_workflow(
        project,
        {
            "name": "Manual Review",
            "trigger": "manual",
            "actions": [
                {
                    "type": "create_review_item",
                    "params": {
                        "code": "CHECK_CONTROL",
                        "message": "Review the active control before delivery.",
                    },
                }
            ],
        },
    )

    exported = export_workflows_yaml(project)
    assert "create_review_item" in exported
    assert saved["workflow_id"] in exported

    imported = import_workflows_yaml(project, exported)
    assert imported["count"] == 1
    assert list_workflows(project)[0]["name"] == "Manual Review"

    run = start_workflow(project, saved["workflow_id"])
    assert run["status"] == "COMPLETED"
    assert run["results"][0]["action_type"] == "create_review_item"
    assert project.db.qa_issues()[0]["code"] == "CHECK_CONTROL"


def test_high_impact_workflow_stops_for_explicit_approval(tmp_path):
    project = _project(tmp_path)
    workflow = save_workflow(
        project,
        {
            "name": "Package After Approval",
            "trigger": "manual",
            "actions": [
                {"type": "run_qa"},
                {
                    "type": "build_deliverable",
                    "params": {
                        "profile_id": "client_deliverable",
                        "label": "Approved automation package",
                    },
                },
            ],
        },
    )

    run = start_workflow(project, workflow["workflow_id"])
    assert run["status"] == "WAITING_APPROVAL"
    assert run["next_action_index"] == 1
    assert run["pending_action"]["type"] == "build_deliverable"

    with project.db.connect() as conn:
        before = int(conn.execute("SELECT COUNT(*) FROM deliverables").fetchone()[0])
    assert before == 0

    completed = approve_run(
        project,
        run["run_id"],
        approved=True,
        note="Reviewed by survey lead",
    )
    assert completed["status"] == "COMPLETED"

    with project.db.connect() as conn:
        after = int(conn.execute("SELECT COUNT(*) FROM deliverables").fetchone()[0])
    assert after == 1
    assert any(row["status"] == "COMPLETED" for row in list_runs(project))


def test_high_impact_workflow_can_be_rejected_without_side_effect(tmp_path):
    project = _project(tmp_path)
    workflow = save_workflow(
        project,
        {
            "name": "Notify Later",
            "trigger": "manual",
            "actions": [{"type": "send_notification"}],
        },
    )

    waiting = start_workflow(project, workflow["workflow_id"])
    assert waiting["status"] == "WAITING_APPROVAL"

    rejected = approve_run(
        project,
        waiting["run_id"],
        approved=False,
        note="Do not send externally.",
    )
    assert rejected["status"] == "REJECTED"

    with project.db.connect() as conn:
        count = int(conn.execute("SELECT COUNT(*) FROM notification_events").fetchone()[0])
    assert count == 0


def test_source_import_trigger_runs_enabled_workflow_automatically(tmp_path):
    project = _project(tmp_path)
    workflow = save_workflow(
        project,
        {
            "name": "Review Every New Source",
            "trigger": "source_imported",
            "actions": [
                {
                    "type": "create_review_item",
                    "params": {
                        "code": "SOURCE_REVIEW",
                        "message": "Review newly imported source evidence.",
                    },
                }
            ],
        },
    )
    source = tmp_path / "raw.csv"
    source.write_text("Point,North,East\n1,10,20\n", encoding="utf-8")

    imported = project.import_source(source, "Core", "Workflow trigger test")

    assert imported["source_id"]
    runs = [
        row
        for row in list_runs(project)
        if row["workflow_id"] == workflow["workflow_id"]
    ]
    assert runs and runs[0]["status"] == "COMPLETED"
    assert any(row["code"] == "SOURCE_REVIEW" for row in project.db.qa_issues())


def test_workflow_engine_reports_approval_policy():
    status = engine_status()

    assert status["actions"]["run_qa"]["requires_approval"] is False
    assert status["actions"]["build_deliverable"]["requires_approval"] is True
    assert status["actions"]["send_notification"]["requires_approval"] is True
    assert "source_imported" in status["triggers"]


def test_pointcloud_and_workflow_routes_are_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg"))

    from fieldbook_sync import app as field_app
    from surveysync import router as survey_router

    survey_router.config_store = survey_router.ConfigStore(tmp_path / "cfg")
    survey_router.current_project = None
    field_app.runtime = field_app.Runtime(tmp_path / "field_runtime")
    client = TestClient(field_app.app)

    created = client.post(
        "/api/v9/project/create",
        json={
            "parent_folder": str(tmp_path / "projects"),
            "name": "Integration API",
            "crs": "EPSG:2278",
            "horizontal_units": "us_survey_feet",
            "vertical_units": "us_survey_feet",
        },
    )
    assert created.status_code == 200, created.text

    point_status = client.get("/api/v9/pointcloud/status")
    assert point_status.status_code == 200
    assert point_status.json()["native_las_metadata"] is True

    workflow_status = client.get("/api/v9/workflows/status")
    assert workflow_status.status_code == 200
    assert workflow_status.json()["actions"]["build_deliverable"]["requires_approval"] is True

    saved = client.post(
        "/api/v9/workflows",
        json={
            "name": "API Review",
            "trigger": "manual",
            "actions": [
                {
                    "type": "create_review_item",
                    "params": {"code": "API_REVIEW", "message": "Review from API workflow."},
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    run = client.post(
        "/api/v9/workflows/run",
        json={"workflow_id": saved.json()["workflow_id"], "context": {}},
    )
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "COMPLETED"

    # The existing operations router is now explicitly included as part of the
    # integration route group, matching endpoints already used by the UI.
    review = client.get("/api/v9/review-center")
    assert review.status_code == 200, review.text


def test_workflow_run_files_are_plain_json_and_project_scoped(tmp_path):
    project = _project(tmp_path)
    workflow = save_workflow(
        project,
        {
            "name": "Persistent State",
            "trigger": "manual",
            "actions": [{"type": "build_deliverable"}],
        },
    )
    run = start_workflow(project, workflow["workflow_id"])

    run_path = project.paths.root / ".surveysync" / "workflow_runs" / f"{run['run_id']}.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))

    assert payload["status"] == "WAITING_APPROVAL"
    assert payload["workflow_id"] == workflow["workflow_id"]
