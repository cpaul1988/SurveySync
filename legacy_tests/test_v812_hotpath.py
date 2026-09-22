from __future__ import annotations

from fieldbook_sync.job_engine import AnalysisJobStore
from fieldbook_sync.models import AppState, FieldBookPage, ResultRecord, SurveyPoint


class Page:
    def __init__(self, page_id: str, n: int):
        self.page_id = page_id
        self.page_number = n
        self.source_name = "book.pdf"


def test_job_store_reuses_one_sqlite_connection(monkeypatch, tmp_path):
    import fieldbook_sync.job_engine as job_engine

    real_connect = job_engine.sqlite3.connect
    calls = []

    def counted_connect(*args, **kwargs):
        calls.append((args, kwargs))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(job_engine.sqlite3, "connect", counted_connect)
    store = AnalysisJobStore(tmp_path / "jobs.sqlite3")
    assert len(calls) == 1

    job_id = store.create_job(
        provider="hybrid", input_signature="sig", project_name="P",
        pages=[Page("p1", 1), Page("p2", 2)],
    )
    store.update_job(job_id, status="RUNNING", stage="ocr", current_page=1)
    store.mark_page(job_id, "p1", status="RUNNING", stage="ocr", increment_attempt=True)
    store.mark_page(job_id, "p1", status="COMPLETE", stage="ocr_complete", cache_hit=False)
    store.record_error(job_id=job_id, component="test", code="T-1", message="test", recoverable=True)
    assert store.get_job(job_id)["pages"][0]["status"] == "COMPLETE"
    assert store.list_errors(job_id)[0]["code"] == "T-1"

    # The hot path must not reconnect/re-run PRAGMAs for each operation.
    assert len(calls) == 1
    store.close()


def test_project_input_signature_is_memoized_until_input_revision_changes(monkeypatch):
    import fieldbook_sync.app as app_mod

    runtime = app_mod.runtime
    state = AppState(
        project_name="Memo Test",
        selected_profile="Profile A",
        survey_points=[SurveyPoint(point_id="100", code="MH", category="structure")],
        fieldbook_pages=[FieldBookPage(
            page_id="page-1", source_name="book.pdf", page_number=1,
            image_path="page_001.jpg", mime_type="image/jpeg",
        )],
    )

    real_sha256 = app_mod.hashlib.sha256
    hash_calls = 0

    def counted_sha256(*args, **kwargs):
        nonlocal hash_calls
        hash_calls += 1
        return real_sha256(*args, **kwargs)

    monkeypatch.setattr(app_mod.hashlib, "sha256", counted_sha256)

    with runtime.lock, runtime.storage.lock:
        old_state = runtime.storage.state
        old_revision = runtime.project_revision
        old_key = runtime.input_signature_cache_key
        old_value = runtime.input_signature_cache_value
        try:
            runtime.storage.state = state
            runtime.project_revision = 500
            runtime.input_signature_cache_key = None
            runtime.input_signature_cache_value = ""

            first = app_mod._project_input_signature_locked()
            second = app_mod._project_input_signature_locked()
            assert first == second
            assert hash_calls == 1

            # Result/review changes are not analysis-input changes and should not
            # force thousands of points/pages to be serialized and hashed again.
            state.results.append(ResultRecord(point_id="100", code="MH"))
            assert app_mod._project_input_signature_locked() == first
            assert hash_calls == 1

            # Input mutations in the app bump project_revision; the next read
            # recomputes once, then returns to O(1) cache hits.
            runtime.project_revision += 1
            third = app_mod._project_input_signature_locked()
            assert third == first  # data stayed identical; generation changed only
            assert hash_calls == 2
            assert app_mod._project_input_signature_locked() == third
            assert hash_calls == 2
        finally:
            runtime.storage.state = old_state
            runtime.project_revision = old_revision
            runtime.input_signature_cache_key = old_key
            runtime.input_signature_cache_value = old_value


def test_diagnostics_modal_uses_running_app_version():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    js = (root / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    assert "state?.app_name" in js
    assert "<strong>8.0.2</strong>" not in js
