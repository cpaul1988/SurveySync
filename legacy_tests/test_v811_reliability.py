from __future__ import annotations

import json
import zipfile
from pathlib import Path

from fieldbook_sync.diagnostics import build_diagnostic_bundle
from fieldbook_sync.job_engine import AnalysisJobStore
from fieldbook_sync.models import DipStatus, ResultRecord, ReviewState, SurveyPoint
from fieldbook_sync.validation import compare_to_baseline, save_baseline, load_baseline


class Page:
    def __init__(self, page_id: str, n: int):
        self.page_id = page_id
        self.page_number = n
        self.source_name = "book.pdf"


def test_job_store_recovers_orphaned_running_jobs(tmp_path):
    store = AnalysisJobStore(tmp_path / "jobs.sqlite3")
    job_id = store.create_job(
        provider="hybrid", input_signature="abc", project_name="Test",
        pages=[Page("p1", 1), Page("p2", 2)],
    )
    store.update_job(job_id, status="RUNNING", stage="ocr", current_page=1)
    assert store.recover_interrupted_jobs() == 1
    job = store.get_job(job_id)
    assert job["status"] == "INTERRUPTED"
    assert store.latest_resumable("abc")["job_id"] == job_id



def test_job_store_recovers_corrupt_database_file(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    path.write_bytes(b"not a sqlite database")
    store = AnalysisJobStore(path)
    assert store.list_jobs() == []
    assert list(tmp_path.glob("jobs.corrupt_*.sqlite3"))

def test_job_store_page_checkpoint_and_error_ledger(tmp_path):
    store = AnalysisJobStore(tmp_path / "jobs.sqlite3")
    job_id = store.create_job(provider="paddle", input_signature="x", project_name="T", pages=[Page("p1", 1)])
    store.mark_page(job_id, "p1", status="FAILED", stage="ocr_failed", error_code="OCR-001", error_message="bad page")
    store.record_error(job_id=job_id, page_id="p1", component="paddle", code="OCR-001", message="bad page", recoverable=True)
    job = store.get_job(job_id)
    assert job["pages"][0]["status"] == "FAILED"
    assert store.list_errors(job_id)[0]["code"] == "OCR-001"


def test_validation_baseline_round_trip_and_metrics(tmp_path):
    baseline_path = tmp_path / "baseline.json"
    results = [
        ResultRecord(point_id="100", code="MH", status=DipStatus.YES, dip_status=DipStatus.YES, review_state=ReviewState.ACCEPTED),
        ResultRecord(point_id="200", code="MH", status=DipStatus.NOT_FOUND, dip_status=DipStatus.NOT_FOUND, review_state=ReviewState.ACCEPTED),
    ]
    save_baseline(baseline_path, name="Truth", project_name="P", results=results, app_version="8.0.11")
    baseline = load_baseline(baseline_path)
    metrics = compare_to_baseline(results, baseline)
    assert metrics["point_id_coverage"] == 1.0
    assert metrics["status_accuracy"] == 1.0
    assert metrics["found_recall"] == 1.0


def test_diagnostic_bundle_is_privacy_first(tmp_path):
    root = tmp_path / "data"
    (root / "logs").mkdir(parents=True)
    (root / "logs" / "app.log").write_text("trace", encoding="utf-8")
    # Deliberately place sensitive-looking project/image content under storage root;
    # diagnostics must not recursively sweep it into the bundle.
    (root / "pages").mkdir()
    (root / "pages" / "secret.jpg").write_bytes(b"secret-image")
    store = AnalysisJobStore(root / "analysis_jobs.sqlite3")
    out = build_diagnostic_bundle(
        output_dir=tmp_path / "out", app_version="8.0.11", storage_root=root,
        hardware={"logical_cores": 8}, settings={"api_key": "secret"}, job_store=store,
    )
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert "PRIVACY.txt" in names
        assert "logs/app.log" in names
        assert not any(name.endswith("secret.jpg") for name in names)
        settings = json.loads(zf.read("settings_redacted.json"))
        assert settings["api_key"] == "<redacted>"


def test_v811_ui_exposes_recovery_and_validation_controls():
    root = Path(__file__).resolve().parents[1]
    html = (root / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
    js = (root / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    app = (root / "fieldbook_sync/app.py").read_text(encoding="utf-8")
    for item in ["resumeJobBtn", "diagnosticBundleBtn", "validationBaselineBtn", "validationCompareBtn", "reliabilityStatus"]:
        assert f'id="{item}"' in html
    for route in ["/api/resume-analysis", "/api/job-history", "/api/error-history", "/api/diagnostics/export", "/api/validation/compare"]:
        assert route in app or route in js


def test_v811_paddle_bridge_isolates_page_failures_and_retries():
    root = Path(__file__).resolve().parents[1]
    bridge = (root / "paddle_bridge.py").read_text(encoding="utf-8")
    ocr = (root / "fieldbook_sync/ocr_local.py").read_text(encoding="utf-8")
    assert "page_retry" in bridge
    assert "page_failed" in bridge
    assert "--page-retries" in bridge and '"2"' in ocr
    assert "page_error_callback" in ocr


def test_v811_app_uses_persistent_sqlite_job_store_and_watchdog():
    root = Path(__file__).resolve().parents[1]
    app = (root / "fieldbook_sync/app.py").read_text(encoding="utf-8")
    assert "AnalysisJobStore" in app
    assert "analysis_jobs.sqlite3" in app
    assert "_start_worker_watchdog" in app
    assert "_run_paddle_supervised" in app
    assert "recover_interrupted_jobs" in app
    assert "_analysis_preflight_locked" in app
