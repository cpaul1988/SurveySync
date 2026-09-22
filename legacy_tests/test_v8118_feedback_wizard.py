from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import fieldbook_sync.feedback as feedback
from fieldbook_sync.feedback import (
    _remote_values,
    create_report,
    list_reports,
    report_log_path,
    submit_to_tracker_endpoint,
    valid_tracker_endpoint,
)

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "fieldbook_sync/app.py").read_text(encoding="utf-8")
JS = (ROOT / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
HTML = (ROOT / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
CSS = (ROOT / "fieldbook_sync/static/styles.css").read_text(encoding="utf-8")


def test_v8118_feedback_wizard_replaces_browser_first_reporting():
    assert "openFeedbackWizard" in JS
    assert "Create Feedback Log" in JS
    assert "helpBugBtn" in HTML
    assert "helpFeatureBtn" in HTML
    assert "helpFeedbackLogBtn" in HTML
    assert ".feedback-steps" in CSS
    assert "Feedback Wizard…" in HTML


def test_feedback_api_has_local_log_direct_intake_and_retry_paths():
    assert '@app.post("/api/feedback/report")' in APP
    assert '@app.get("/api/feedback/reports")' in APP
    assert '@app.get("/api/feedback/log")' in APP
    assert '@app.post("/api/feedback/retry")' in APP
    assert '@app.post("/api/feedback/open-folder")' in APP
    assert "create_feedback_report" in APP
    assert "submit_to_tracker_endpoint" in APP
    assert "submit_to_google_form" not in APP
    assert "google_apps_script" in APP


def test_local_feedback_log_is_append_only_and_retains_attachments(tmp_path):
    upload = SimpleNamespace(
        filename="screen shot.png",
        content_type="image/png",
        file=BytesIO(b"fake-png-bytes"),
    )
    report = create_report(
        storage_root=tmp_path,
        report={
            "report_type": "Bug",
            "title": "Continue freezes",
            "description": "Window becomes unresponsive.",
            "app_version": "8.1.21",
            "sync": {"status": "local_only"},
        },
        attachments=[upload],
    )
    assert report["report_id"].startswith("FBL-")
    assert report["attachments"][0]["name"] == "screen shot.png"
    assert (tmp_path / "feedback" / "reports" / report["report_id"] / "attachments" / "screen shot.png").exists()
    log = report_log_path(tmp_path)
    assert log.exists()
    text = log.read_text(encoding="utf-8")
    assert "Continue freezes" in text
    assert report["report_id"] in text
    items = list_reports(tmp_path)
    assert items[0]["title"] == "Continue freezes"


def test_direct_tracker_endpoint_validation():
    assert valid_tracker_endpoint("https://script.google.com/macros/s/ABC123/exec")
    assert not valid_tracker_endpoint("https://docs.google.com/forms/d/e/abc/viewform")
    assert not valid_tracker_endpoint("http://script.google.com/macros/s/ABC123/exec")
    assert not valid_tracker_endpoint("https://evil.example/macros/s/ABC123/exec")


def test_remote_tracker_payload_contains_local_log_id_and_context():
    values = _remote_values({
        "report_id": "FBL-TEST",
        "report_type": "Feature Request",
        "title": "Add surface import",
        "description": "Need LandXML surface support",
        "app_version": "8.1.21",
        "context": {"project_name": "Demo", "job_state": "Idle", "provider": "hybrid"},
    })
    assert values["local_report_id"] == "FBL-TEST"
    assert values["project_name"] == "Demo"
    assert values["job_state"] == "Idle"
    assert values["provider"] == "hybrid"


def test_direct_tracker_submission_uploads_selected_support_files(tmp_path, monkeypatch):
    report_dir = tmp_path / "feedback" / "reports" / "FBL-TEST"
    attach = report_dir / "attachments" / "shot.png"
    attach.parent.mkdir(parents=True)
    attach.write_bytes(b"png-data")
    diag = report_dir / "Diagnostics.zip"
    diag.write_bytes(b"zip-data")
    report = {
        "report_id": "FBL-TEST",
        "created_utc": "2026-09-12T19:00:00Z",
        "report_type": "Bug",
        "title": "Updater issue",
        "description": "Test",
        "app_version": "8.1.21",
        "attachments": [{"name": "shot.png", "relative_path": "attachments/shot.png", "content_type": "image/png"}],
        "diagnostic_bundle": {"name": "Diagnostics.zip", "relative_path": "Diagnostics.zip"},
        "context": {},
    }
    captured = {}

    class Response:
        status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return {"ok": True, "intake_id": "FBR-0027", "row": 27, "attachment_folder_url": "https://drive.google.com/drive/folders/demo"}

    def fake_post(url, *, json, headers, timeout, allow_redirects):
        captured["url"] = url
        captured["json"] = json
        return Response()

    monkeypatch.setattr(feedback.requests, "post", fake_post)
    result = submit_to_tracker_endpoint("https://script.google.com/macros/s/ABC123/exec", report, report_dir)
    assert result["status"] == "synced"
    assert result["intake_id"] == "FBR-0027"
    assert captured["json"]["report"]["local_report_id"] == "FBL-TEST"
    assert len(captured["json"]["files"]) == 2
    assert all("data_base64" in f for f in captured["json"]["files"])


def test_tracker_http_500_with_files_retries_metadata_only(tmp_path, monkeypatch):
    report_dir = tmp_path / "feedback" / "reports" / "FBL-RETRY"
    attach = report_dir / "attachments" / "shot.png"
    attach.parent.mkdir(parents=True)
    attach.write_bytes(b"png-data")
    report = {
        "report_id": "FBL-RETRY",
        "created_utc": "2026-09-13T19:00:00Z",
        "report_type": "Bug",
        "title": "Feedback HTTP 500",
        "description": "Attachment submission failed.",
        "app_version": "9.0.2",
        "attachments": [{"name": "shot.png", "relative_path": "attachments/shot.png", "content_type": "image/png"}],
        "context": {},
    }
    calls = []

    class Response:
        def __init__(self, status_code, data=None, text=""):
            self.status_code = status_code
            self._data = data or {}
            self.text = text
        def json(self):
            return self._data

    def fake_post(url, *, json, headers, timeout, allow_redirects):
        calls.append(json)
        if len(calls) == 1:
            return Response(500, text="Apps Script Drive error")
        return Response(200, {"ok": True, "intake_id": "FBR-0101", "row": 101})

    monkeypatch.setattr(feedback.requests, "post", fake_post)
    result = submit_to_tracker_endpoint("https://script.google.com/macros/s/ABC123/exec", report, report_dir)
    assert len(calls) == 2
    assert len(calls[0]["files"]) == 1
    assert calls[1]["files"] == []
    assert result["status"] == "synced"
    assert result["metadata_only_retry"] is True
    assert result["remote_files_uploaded"] is False
    assert any("deferred" in x.lower() for x in result["skipped_files"])


def test_surveysync_feedback_uses_official_config_before_legacy_local_override():
    assert "raw.githubusercontent.com/cpaul1988/SurveySync/main/feedback.json" in APP
    assert "cfg?.intake_url||cfg?.submit_url||localStorage.getItem(FEEDBACK_ENDPOINT_LOCAL_KEY)" in JS
    # A stale v8 per-machine endpoint must no longer override the official SurveySync endpoint.
    assert "localStorage.getItem(FEEDBACK_ENDPOINT_LOCAL_KEY)||cfg?.intake_url" not in JS
