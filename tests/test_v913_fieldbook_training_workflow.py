from pathlib import Path

from fastapi.testclient import TestClient

from fieldbook_sync.models import FieldBookPage, ImportedFileRecord


def _runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg"))
    from fieldbook_sync import app as field_app
    field_app.runtime = field_app.Runtime(tmp_path / "fieldbook_runtime")
    return field_app, TestClient(field_app.app)


def test_fieldbook_profile_assignment_persists_book_default_and_preserves_page_override(tmp_path, monkeypatch):
    field_app, client = _runtime(tmp_path, monkeypatch)
    img = tmp_path / "p1.png"
    img.write_bytes(b"fixture")
    state = field_app.runtime.storage.state
    state.fieldbook_files = [ImportedFileRecord(name="book.pdf", kind="fieldbook", pages=2)]
    state.fieldbook_pages = [
        FieldBookPage(page_id="p1", source_name="book.pdf", page_number=1, image_path=str(img), mime_type="image/png"),
        FieldBookPage(page_id="p2", source_name="book.pdf", page_number=2, image_path=str(img), mime_type="image/png", field_note_profile_override="GENERIC_SURVEY_NOTES"),
    ]
    field_app.runtime.storage.save()

    res = client.post("/api/fieldbook-profile-assignment", json={"source_name": "book.pdf", "profile_id": "BRT_STANDARD", "mode": "user"})
    assert res.status_code == 200, res.text
    assert state.fieldbook_files[0].field_note_profile == "BRT_STANDARD"
    assert state.fieldbook_files[0].field_note_profile_mode == "user"
    assert all(p.field_note_profile_book == "BRT_STANDARD" for p in state.fieldbook_pages)
    # A page-specific mixed-format override remains independent from the book default.
    assert state.fieldbook_pages[1].field_note_profile_override == "GENERIC_SURVEY_NOTES"
    assert field_app._effective_page_profile_id(state.fieldbook_pages[0]) == "BRT_STANDARD"
    assert field_app._effective_page_profile_id(state.fieldbook_pages[1]) == "GENERIC_SURVEY_NOTES"


def test_fieldbook_profile_assignment_can_return_book_to_auto(tmp_path, monkeypatch):
    field_app, client = _runtime(tmp_path, monkeypatch)
    img = tmp_path / "p.png"; img.write_bytes(b"fixture")
    state = field_app.runtime.storage.state
    state.fieldbook_files = [ImportedFileRecord(name="book.pdf", kind="fieldbook", pages=1, field_note_profile="BRT_STANDARD")]
    state.fieldbook_pages = [FieldBookPage(page_id="p1", source_name="book.pdf", page_number=1, image_path=str(img), mime_type="image/png", field_note_profile_book="BRT_STANDARD")]
    field_app.runtime.storage.save()
    res = client.post("/api/fieldbook-profile-assignment", json={"source_name": "book.pdf", "profile_id": "AUTO"})
    assert res.status_code == 200
    assert state.fieldbook_files[0].field_note_profile == "AUTO"
    assert state.fieldbook_files[0].field_note_profile_mode == "auto"
    assert state.fieldbook_pages[0].field_note_profile_book == ""


def test_training_preview_returns_first_representative_pages_and_saves_ids(tmp_path, monkeypatch):
    field_app, client = _runtime(tmp_path, monkeypatch)
    state = field_app.runtime.storage.state
    state.fieldbook_files = [ImportedFileRecord(name="book.pdf", kind="fieldbook", pages=7)]
    pages = []
    for number in range(1, 8):
        img = tmp_path / f"p{number}.png"; img.write_bytes(b"fixture")
        pages.append(FieldBookPage(page_id=f"p{number}", source_name="book.pdf", page_number=number, image_path=str(img), mime_type="image/png", page_type="cover" if number == 1 else "unknown"))
    state.fieldbook_pages = pages
    field_app.runtime.storage.save()
    res = client.get("/api/fieldbook-training-preview", params={"source_name": "book.pdf", "limit": 5})
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["pages"]) == 5
    # Once a cover is known, useful note pages are prioritized over it.
    assert body["pages"][0]["page_number"] == 2
    assert state.fieldbook_files[0].representative_page_ids == [p["page_id"] for p in body["pages"]]


def test_fieldbook_assignment_api_lists_profile_metadata(tmp_path, monkeypatch):
    field_app, client = _runtime(tmp_path, monkeypatch)
    state = field_app.runtime.storage.state
    state.fieldbook_files = [ImportedFileRecord(name="book.pdf", kind="fieldbook", pages=3, field_note_profile="AUTO")]
    field_app.runtime.storage.save()
    body = client.get("/api/fieldbook-profile-assignments").json()
    assert body["books"][0]["name"] == "book.pdf"
    ids = {p["profile_id"] for p in body["profiles"]}
    assert {"BRT_STANDARD", "GENERIC_SURVEY_NOTES"}.issubset(ids)


def test_fbr_0010_controls_are_in_fieldbook_workflow():
    html = Path("fieldbook_sync/static/index.html").read_text(encoding="utf-8")
    js = Path("fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    assert 'id="fieldbookProfileSelect"' in html
    assert 'id="fieldbookTrainBtn"' in html
    assert 'id="fieldbookPreviewTrainingBtn"' in html
    assert 'id="trainerSourceFilter"' in html
    assert 'id="trainerQuickPreview"' in html
    assert "/api/fieldbook-profile-assignment" in js
    assert "/api/fieldbook-training-preview" in js
    assert "Train this field book" in html
