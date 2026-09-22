from __future__ import annotations

from pathlib import Path

import fieldbook_sync.feedback as feedback


def test_v922_feedback_envelope_is_accepted_by_legacy_intake(tmp_path, monkeypatch):
    """The production Intake endpoint may still be the pre-routing FieldBook Sync deployment."""
    captured = {}

    class Response:
        status_code = 200
        text = ""
        def json(self):
            payload = captured["payload"]
            # Model the deployed legacy gate that triggered the 9.2.1 production failure.
            if payload.get("schema_version") != 1 or payload.get("application") != "FieldBook Sync":
                return {"ok": False, "error": "Unsupported FieldBook Sync feedback payload."}
            return {"ok": True, "intake_id": "FBR-0013", "row": 14}

    def fake_post(url, *, json, headers, timeout, allow_redirects):
        captured["payload"] = json
        return Response()

    monkeypatch.setattr(feedback.requests, "post", fake_post)
    result = feedback.submit_to_tracker_endpoint(
        "https://script.google.com/macros/s/ABC123/exec",
        {
            "report_id": "FBL-20260919-204138-B2C1CF",
            "created_utc": "2026-09-20T01:41:38Z",
            "report_type": "Feature Request",
            "title": "test",
            "description": "test test",
            "app_version": "9.2.2",
            "context": {},
        },
        tmp_path,
    )
    assert result["status"] == "synced"
    assert result["intake_id"] == "FBR-0013"
    assert captured["payload"]["application"] == "FieldBook Sync"
    assert "route" not in captured["payload"]
    assert "target_sheet" not in captured["payload"]
