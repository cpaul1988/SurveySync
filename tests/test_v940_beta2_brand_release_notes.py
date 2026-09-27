from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from surveysync import router as survey_router

ROOT = Path(__file__).resolve().parents[1]


def test_beta2_release_notes_have_release_specific_identity():
    app = FastAPI()
    app.include_router(survey_router.router)
    client = TestClient(app)

    response = client.get("/api/v9/release-notes")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "9.4.0"
    assert body["release_id"] == "9.4.0-beta.3"
    assert any("globe" in note.lower() for note in body["notes"])
    assert any("release notes" in note.lower() for note in body["notes"])


def test_beta2_first_launch_notes_use_release_id_and_acknowledge_on_continue():
    js = (ROOT / "surveysync" / "static" / "app.js").read_text(encoding="utf-8")

    assert "surveysync-release-notes-seen-v2" in js
    assert "releaseId=String(d.release_id||d.version||'').trim()" in js
    assert "if(markSeen&&releaseId)markNotesSeen(releaseId)" in js
    assert "function notesWereSeen(id)" in js
    assert "localStorage.setItem(SS_RELEASE_SEEN_KEY,id)" in js
    assert "if(markSeen&&version)" not in js



def test_beta2_all_active_product_marks_use_globe():
    main_html = (ROOT / "surveysync" / "static" / "index.html").read_text(encoding="utf-8")
    main_js = (ROOT / "surveysync" / "static" / "app.js").read_text(encoding="utf-8")
    field_html = (ROOT / "fieldbook_sync" / "static" / "index.html").read_text(encoding="utf-8")

    for content in (main_html, main_js, field_html):
        assert "surveysync_monogram.svg" not in content
        assert "surveysync_globe.svg" in content
