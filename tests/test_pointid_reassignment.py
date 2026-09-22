from __future__ import annotations

from fastapi.testclient import TestClient

from fieldbook_sync.aggregate import aggregate_results
from fieldbook_sync.models import EvidenceBasis, PageEvidence, PipeMeasurement, SurveyPoint


def _evidence(point_id: str) -> PageEvidence:
    return PageEvidence(
        matched_point_id=point_id,
        source_name="book.pdf",
        page_number=7,
        page_id="book-p7",
        point_id_raw=point_id,
        point_id_confidence=0.97,
        dipped="YES",
        basis=EvidenceBasis.MEASUREMENT,
        dipped_confidence=0.96,
        evidence="DIP 4.62 8 PVC",
        pipes=[PipeMeasurement(dip=4.62, diameter_in=8.0, material="PVC")],
        bbox=[100, 100, 400, 300],
        primary_engine="PaddleOCR-VL",
        secondary_engine="Qwen3-VL",
        model_agreement=True,
        evidence_sources=["PaddleOCR-VL", "Qwen3-VL"],
        evidence_decision="AUTO_ACCEPT",
    )


def _setup_runtime(tmp_path, monkeypatch):
    from fieldbook_sync import app as field_app

    rt = field_app.Runtime(tmp_path / "fieldbook")
    monkeypatch.setattr(field_app, "runtime", rt)
    points = [
        SurveyPoint(point_id="3187", northing=1000.0, easting=2000.0, elevation=10.0, code="MH", category="Structure"),
        SurveyPoint(point_id="3181", northing=1100.0, easting=2100.0, elevation=11.0, code="MH", category="Structure"),
    ]
    rt.storage.state.survey_points = points
    rt.storage.state.results = aggregate_results(points, [_evidence("3187")], status_rule=rt.status_rule)
    rt.storage.save()
    return field_app, rt


def test_review_can_reassign_pointid_and_preserve_survey_identity(tmp_path, monkeypatch):
    field_app, rt = _setup_runtime(tmp_path, monkeypatch)
    client = TestClient(field_app.app)

    response = client.put(
        "/api/results/3187",
        json={
            "point_id": "3181",
            "reassignment_reason": "Reviewer read the handwritten PointID as 3181.",
            "status": "YES",
            "dip_status": "YES",
            "review_state": "EDITED",
            "notes": "PointID corrected during review.",
            "pipes": [{"dip": 4.62, "diameter_in": 8.0, "material": "PVC"}],
        },
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["point_id"] == "3181"
    assert saved["northing"] == 1100.0 and saved["easting"] == 2100.0
    assert saved["point_id_reassigned_from"] == "3187"
    assert saved["evidence_records"][0]["matched_point_id"] == "3181"
    # Immutable observation: OCR/raw text still says what the engine originally saw.
    assert saved["evidence_records"][0]["point_id_raw"] == "3187"
    assert "REVIEWER_POINTID_REASSIGNMENT" in saved["evidence_records"][0]["validation_flags"]

    source = next(r for r in rt.storage.state.results if r.point_id == "3187")
    assert source.northing == 1000.0 and source.easting == 2000.0
    assert not source.evidence_records and not source.pipes
    assert source.point_id_reassigned_to == "3181"
    assert source.manually_overridden is True

    event = rt.storage.state.history[-1]
    assert event.action == "Reassign PointID"
    assert set(event.related_before) == {"3187", "3181"}
    assert set(event.related_after) == {"3187", "3181"}


def test_pointid_reassignment_is_atomic_undo_redo(tmp_path, monkeypatch):
    field_app, rt = _setup_runtime(tmp_path, monkeypatch)
    client = TestClient(field_app.app)
    payload = {
        "point_id": "3181",
        "status": "YES",
        "dip_status": "YES",
        "review_state": "EDITED",
        "notes": "Corrected association",
        "pipes": [{"dip": 4.62, "diameter_in": 8.0, "material": "PVC"}],
    }
    assert client.put("/api/results/3187", json=payload).status_code == 200

    assert client.post("/api/undo").status_code == 200
    old = next(r for r in rt.storage.state.results if r.point_id == "3187")
    target = next(r for r in rt.storage.state.results if r.point_id == "3181")
    assert old.evidence_records and old.evidence_records[0].matched_point_id == "3187"
    assert not target.evidence_records

    assert client.post("/api/redo").status_code == 200
    old = next(r for r in rt.storage.state.results if r.point_id == "3187")
    target = next(r for r in rt.storage.state.results if r.point_id == "3181")
    assert not old.evidence_records
    assert target.evidence_records and target.evidence_records[0].matched_point_id == "3181"


def test_reassignment_refuses_to_overwrite_existing_reviewed_target(tmp_path, monkeypatch):
    field_app, rt = _setup_runtime(tmp_path, monkeypatch)
    target = next(r for r in rt.storage.state.results if r.point_id == "3181")
    target.manually_overridden = True
    target.notes = "Already reviewed"
    rt.storage.save()
    client = TestClient(field_app.app)
    response = client.put(
        "/api/results/3187",
        json={
            "point_id": "3181",
            "status": "YES",
            "dip_status": "YES",
            "review_state": "EDITED",
            "notes": "attempt",
            "pipes": [],
        },
    )
    assert response.status_code == 409
    assert "already has field-book evidence or reviewed edits" in response.text


def test_review_ui_exposes_editable_imported_pointid_selector():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "fieldbook_sync" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="editPointId"' in js
    assert 'list="reviewPointList"' in js
    assert 'point_id:newId' in js
    assert 'Reassign this field-book evidence from Point' in js
