from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from surveysync.audit import AuditDB, CURRENT_SCHEMA_VERSION
from surveysync.cogo_extended import solve_horizontal_curve, three_point_curve
from surveysync.delivery import build_deliverable_package
from surveysync.project import SurveyProject
from surveysync.qa import run_project_qa

ROOT = Path(__file__).resolve().parents[1]


def test_cogokit_derived_horizontal_curve_reference_case():
    result = solve_horizontal_curve(radius=500.0, delta_deg=30.0)

    assert result["radius"] == 500.0
    assert result["delta_deg"] == pytest.approx(30.0, abs=1e-12)
    assert result["tangent"] == pytest.approx(133.9745962, abs=1e-7)
    assert result["arc_length"] == pytest.approx(261.7993878, abs=1e-7)
    assert result["long_chord"] == pytest.approx(258.8190451, abs=1e-7)
    assert result["degree_of_curve_100ft_arc"] == pytest.approx(11.4591559026, abs=1e-9)


def test_horizontal_curve_rejects_degree_of_curve_for_metric_projects():
    with pytest.raises(ValueError, match="100-foot arc"):
        solve_horizontal_curve(
            degree_of_curve_100ft_arc=10.0,
            delta_deg=30.0,
            linear_units="meters",
        )


def test_horizontal_curve_rejects_wrong_element_count():
    with pytest.raises(ValueError, match="exactly two"):
        solve_horizontal_curve(radius=500.0)


def test_three_point_curve_uses_survey_northing_easting_convention():
    result = three_point_curve(
        n1=0.0,
        e1=0.0,
        n2=0.0,
        e2=2.0,
        n3=2.0,
        e3=0.0,
    )
    assert result["center_northing"] == pytest.approx(1.0)
    assert result["center_easting"] == pytest.approx(1.0)
    assert result["radius"] == pytest.approx(math.sqrt(2.0))


def test_extended_cogo_api_records_audited_results(tmp_path, monkeypatch):
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
            "name": "Curve API",
            "crs": "EPSG:2278",
            "horizontal_units": "us_survey_feet",
            "vertical_units": "us_survey_feet",
        },
    )
    assert created.status_code == 200, created.text

    curve = client.post(
        "/api/v9/cogo/curve",
        json={"radius": 500.0, "delta_deg": 30.0},
    )
    assert curve.status_code == 200, curve.text
    assert curve.json()["arc_length"] == pytest.approx(261.7993878, abs=1e-7)

    three = client.post(
        "/api/v9/cogo/three-point-curve",
        json={"n1": 0, "e1": 0, "n2": 0, "e2": 2, "n3": 2, "e3": 0},
    )
    assert three.status_code == 200, three.text

    actions = [row["action"] for row in survey_router.current_project.db.recent_audit(20)]
    assert "HORIZONTAL_CURVE" in actions
    assert "THREE_POINT_CURVE" in actions


def test_audit_chain_detects_tampering(tmp_path):
    db = AuditDB(tmp_path / "audit.sqlite")
    assert db.schema_version() == CURRENT_SCHEMA_VERSION
    assert db.verify_audit_chain()["ok"] is True

    first = db.audit("Core", "ONE", details={"value": 1})
    db.audit("Core", "TWO", details={"value": 2})
    healthy = db.verify_audit_chain()
    assert healthy["ok"] is True
    assert healthy["event_count"] == 2
    assert len(healthy["chain_id"]) == 32
    assert len(healthy["head_hash"]) == 64

    with db.connect() as conn:
        conn.execute(
            "UPDATE audit_events SET details_json=? WHERE event_id=?",
            (json.dumps({"value": 999}), first),
        )

    broken = db.verify_audit_chain()
    assert broken["ok"] is False
    assert broken["broken_seq"] == 1
    assert "hash mismatch" in broken["reason"].lower()


def test_audit_chain_identity_prevents_cross_project_transplant(tmp_path):
    source = AuditDB(tmp_path / "source.sqlite")
    target = AuditDB(tmp_path / "target.sqlite")
    source.audit("Core", "SOURCE_EVENT", details={"project": "source"})
    target.audit("Core", "TARGET_EVENT", details={"project": "target"})

    with source.connect() as src, target.connect() as dst:
        event = src.execute("SELECT * FROM audit_events ORDER BY rowid LIMIT 1").fetchone()
        chain = src.execute("SELECT * FROM audit_chain ORDER BY seq LIMIT 1").fetchone()
        dst.execute("DELETE FROM audit_chain")
        dst.execute("DELETE FROM audit_events")
        dst.execute(
            "INSERT INTO audit_events(event_id,ts_utc,actor,module,action,object_type,object_id,revision,details_json) VALUES(?,?,?,?,?,?,?,?,?)",
            tuple(event),
        )
        dst.execute(
            "INSERT INTO audit_chain(seq,event_id,hash_version,prev_hash,event_hash) VALUES(?,?,?,?,?)",
            tuple(chain),
        )

    result = target.verify_audit_chain()
    assert result["ok"] is False
    assert "hash mismatch" in result["reason"].lower()


def test_v5_project_audit_events_are_backfilled_into_chain(tmp_path):
    path = tmp_path / "legacy.sqlite"
    db = AuditDB(path)
    db.audit("Core", "OLD_ONE", details={"legacy": 1})
    db.audit("Core", "OLD_TWO", details={"legacy": 2})

    with db.connect() as conn:
        conn.execute("DELETE FROM audit_chain")
        conn.execute("PRAGMA user_version=5")

    reopened = AuditDB(path)
    integrity = reopened.verify_audit_chain()
    assert reopened.schema_version() == CURRENT_SCHEMA_VERSION
    assert integrity["ok"] is True
    assert integrity["event_count"] == 2
    assert integrity["chain_count"] == 2


def test_project_health_surfaces_audit_chain_integrity(tmp_path):
    project = SurveyProject.create(
        tmp_path,
        "Audit Health",
        crs="EPSG:2278",
        horizontal_units="us_survey_feet",
        vertical_units="us_survey_feet",
    )
    healthy = run_project_qa(project)
    audit_check = next(item for item in healthy["checks"] if item["code"] == "HEALTH_AUDIT_CHAIN")
    assert audit_check["status"] == "PASS"

    with project.db.connect() as conn:
        first = conn.execute("SELECT event_id FROM audit_events ORDER BY rowid LIMIT 1").fetchone()
        conn.execute(
            "UPDATE audit_events SET action='TAMPERED' WHERE event_id=?",
            (first[0],),
        )

    broken = run_project_qa(project)
    audit_check = next(item for item in broken["checks"] if item["code"] == "HEALTH_AUDIT_CHAIN")
    assert audit_check["status"] == "ERROR"
    assert broken["readiness"] == "BLOCKING"


def test_deliverable_manifest_contains_verified_audit_head(tmp_path):
    project = SurveyProject.create(
        tmp_path,
        "Deliverable Audit",
        crs="EPSG:2278",
        horizontal_units="us_survey_feet",
        vertical_units="us_survey_feet",
    )
    result = build_deliverable_package(project)
    with zipfile.ZipFile(result["path"]) as archive:
        manifest = json.loads(archive.read("SurveySync_Manifest.json"))

    audit = manifest["audit_chain"]
    assert audit["verified"] is True
    assert audit["event_count"] >= 1
    assert len(audit["chain_id"]) == 32
    assert len(audit["head_hash"]) == 64


def test_release_workflow_enforces_candidate_then_main_promotion():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "Beta publication must run from a tested development/candidate branch, not main." in workflow
    assert "Stable promotion must run from main after the tested Beta candidate has been merged." in workflow


def test_third_party_attribution_and_integration_plan_present():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "OPEN_SOURCE_INTEGRATION_PLAN.md").read_text(encoding="utf-8")
    assert "devinmlowe/cogokit" in notices
    assert "block/buzz" in notices
    assert "hujinghaoabcd/pySurveying" in plan
    assert "mrahnis/jxl2txt" in plan


import pytest
