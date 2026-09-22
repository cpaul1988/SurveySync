from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg"))
    from fieldbook_sync import app as field_app
    from surveysync import router as survey_router

    field_app.runtime = field_app.Runtime(tmp_path / "fieldbook_runtime")
    survey_router.config_store = survey_router.ConfigStore(tmp_path / "cfg")
    survey_router.current_project = None
    return field_app, survey_router, TestClient(field_app.app)


def test_surveysync_update_requires_explicit_confirmation_before_stage(tmp_path, monkeypatch):
    field_app, survey_router, client = _client(tmp_path, monkeypatch)
    stage_calls = []
    shutdown_calls = []

    monkeypatch.setattr(
        survey_router,
        "update_check",
        lambda store: {
            "version": "9.1.4",
            "channel": "stable",
            "update_available": True,
            "required": False,
            "release_notes": "Reliability update",
        },
    )
    monkeypatch.setattr(
        survey_router,
        "update_stage",
        lambda store: stage_calls.append(str(store.root)) or {"version": "9.1.4", "installer_path": "SurveySync_Setup_9.1.4.exe"},
    )
    monkeypatch.setattr(field_app, "request_application_shutdown", lambda reason: shutdown_calls.append(reason))

    res = client.post("/api/v9/update/check-and-install")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["action"] == "confirmation_required"
    assert stage_calls == []
    assert shutdown_calls == []

    class ImmediateThread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(survey_router.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(survey_router.time, "sleep", lambda seconds: None)
    confirmed = client.post("/api/v9/update/check-and-install", json={"confirm_install": True})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["action"] == "installing"
    assert stage_calls
    assert shutdown_calls and "Updating SurveySync to v9.1.4" in shutdown_calls[0]


def test_legacy_fieldbook_update_route_requires_confirmation_before_stage(tmp_path, monkeypatch):
    field_app, _survey_router, client = _client(tmp_path, monkeypatch)
    stage_calls = []
    shutdown_calls = []

    monkeypatch.setattr(
        field_app,
        "surveysync_update_check",
        lambda store: {
            "version": "9.1.4",
            "channel": "stable",
            "update_available": True,
            "required": False,
            "release_notes": "Reliability update",
        },
    )
    monkeypatch.setattr(
        field_app,
        "surveysync_update_stage",
        lambda store: stage_calls.append(str(store.root)) or {"version": "9.1.4", "installer_path": "SurveySync_Setup_9.1.4.exe"},
    )
    monkeypatch.setattr(field_app, "request_application_shutdown", lambda reason: shutdown_calls.append(reason))

    res = client.post("/api/update/download-install")
    assert res.status_code == 200, res.text
    assert res.json()["action"] == "confirmation_required"
    assert stage_calls == []
    assert shutdown_calls == []

    class ImmediateThread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(field_app.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(field_app.time, "sleep", lambda seconds: None)
    confirmed = client.post("/api/update/download-install", json={"confirm_install": True})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["version"] == "9.1.4"
    assert stage_calls
    assert shutdown_calls and "Updating SurveySync to v9.1.4" in shutdown_calls[0]


def test_project_save_as_creates_valid_atomic_bundle(tmp_path, monkeypatch):
    field_app, _survey_router, client = _client(tmp_path, monkeypatch)
    field_app.runtime.storage.state.project_name = "Save As Demo"
    field_app.runtime.storage.save()

    target_without_suffix = tmp_path / "exports" / "renamed_project"
    res = client.post("/api/project/save-as", json={"path": str(target_without_suffix)})
    assert res.status_code == 200, res.text
    body = res.json()
    target = target_without_suffix.with_suffix(".fbs")
    assert body["atomic"] is True
    assert body["path"] == str(target.resolve())
    assert target.exists()
    assert zipfile.is_zipfile(target)
    with zipfile.ZipFile(target) as zf:
        assert {"project.json", "README.txt"}.issubset(set(zf.namelist()))
        project = json.loads(zf.read("project.json").decode("utf-8"))
    assert project["project_name"] == "Save As Demo"


def test_diagnostics_error_log_routes_and_bundle_are_privacy_safe(tmp_path, monkeypatch):
    _field_app, survey_router, client = _client(tmp_path, monkeypatch)
    from surveysync.diagnostics import record_error

    record_error(
        survey_router.config_store.root,
        component="test",
        code="TST-001",
        message="Synthetic failure",
        context={"api_token": "secret-token", "path": str(tmp_path / "survey.pdf")},
    )

    errors = client.get("/api/v9/diagnostics/errors")
    assert errors.status_code == 200, errors.text
    first = errors.json()["errors"][0]
    assert first["message"] == "Synthetic failure"
    assert first["context"]["api_token"] == "<redacted>"

    log = client.get("/api/v9/diagnostics/error-log")
    assert log.status_code == 200
    assert b"Synthetic failure" in log.content

    bundle = client.post("/api/v9/diagnostics/export")
    assert bundle.status_code == 200, bundle.text
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as zf:
        names = set(zf.namelist())
        assert {"system.json", "config_redacted.json", "project_summary.json", "PRIVACY.txt", "diagnostics/error_log.jsonl"}.issubset(names)
        redacted = zf.read("diagnostics/error_log.jsonl").decode("utf-8")
    assert "secret-token" not in redacted
    assert "<redacted>" in redacted


def test_error_log_sync_payload_routes_to_error_log_sheet(monkeypatch):
    from surveysync import diagnostics

    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b'{"ok": true, "row": 12, "error_log_id": "ERR-12"}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return Response()

    monkeypatch.setattr(diagnostics.urllib.request, "urlopen", fake_urlopen)
    result = diagnostics.submit_error_log(
        "https://script.google.com/macros/s/ABC123/exec",
        [{"error_id": "SSE-1", "message": "Boom", "context": {"secret_key": "abc"}}],
        app_version="9.1.4",
    )
    assert result["status"] == "synced"
    assert captured["payload"]["route"] == "error_log"
    assert captured["payload"]["target_sheet"] == "Error Log"
    assert captured["payload"]["application"] == "SurveySync"
    assert captured["payload"]["errors"][0]["context"]["secret_key"] == "<redacted>"


def test_feedback_payload_routes_to_intake_sheet(tmp_path, monkeypatch):
    import fieldbook_sync.feedback as feedback

    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"ok": True, "intake_id": "FBR-0012", "row": 12}

    def fake_post(url, *, json, headers, timeout, allow_redirects):
        captured["payload"] = json
        captured["headers"] = headers
        return Response()

    monkeypatch.setattr(feedback.requests, "post", fake_post)
    result = feedback.submit_to_tracker_endpoint(
        "https://script.google.com/macros/s/ABC123/exec",
        {"report_id": "FBL-12", "title": "Feedback route", "description": "Test", "app_version": "9.1.4", "context": {}},
        tmp_path,
    )
    assert result["status"] == "synced"
    assert captured["payload"]["application"] == "FieldBook Sync"
    assert "route" not in captured["payload"]
    assert "target_sheet" not in captured["payload"]
    assert "module" not in captured["payload"]


def test_v914_static_ui_contracts():
    desktop = (ROOT / "desktop.py").read_text(encoding="utf-8")
    field_js = (ROOT / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    field_css = (ROOT / "fieldbook_sync/static/styles.css").read_text(encoding="utf-8")
    main_js = (ROOT / "surveysync/static/app.js").read_text(encoding="utf-8")
    apps_script = (ROOT / "tracker_endpoint/Code.gs").read_text(encoding="utf-8")

    assert "def choose_save_file" in desktop
    assert "choose_save_file" in desktop and "window.expose" in desktop
    assert "function saveProjectAs" in field_js
    assert "/api/project/save-as" in field_js
    assert "confirm_install:true" in field_js
    assert "confirm_install:true" in main_js
    assert "review-modal" in field_js
    assert ".modal.review-modal" in field_css
    assert "appendErrorLog_" in apps_script
    assert "FBS_ERROR_LOG_SHEET = 'Error Log'" in apps_script
