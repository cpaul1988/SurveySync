"""Run provenance follows validated OCR receipts, including restarts and stale work."""

from copy import deepcopy
import importlib
import json
from threading import Event, RLock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fieldbook_sync import benchmark_export
from fieldbook_sync.models import (
    AnalysisJob,
    AppState,
    FieldBookPage,
    PageEvidence,
    ResultRecord,
    SurveyPoint,
)


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_FIELD_ROOT", str(tmp_path / "field-storage"))
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "surveysync-config"))
    return importlib.import_module("fieldbook_sync.app")


def _page(tmp_path, page_id):
    return FieldBookPage(
        page_id=page_id,
        source_name="synthetic-book",
        page_number=1,
        image_path=str(tmp_path / f"{page_id}.png"),
        mime_type="image/png",
    )


def _view(role, image_hash, model_hash):
    return {
        "surveysync_view": {
            "role": role,
            "ocr_mode": "spotting",
            "image_sha256": image_hash,
            "model_sha256": model_hash,
        },
        "res": {"private_text": "Synthetic content must not enter the provenance summary"},
    }


def test_supervised_receipts_survive_retry_cache_dedup_and_preserve_assets(
    tmp_path,
    monkeypatch,
    app_module,
):
    pages = [_page(tmp_path, "page-1"), _page(tmp_path, "page-2")]
    first = {
        "views": [_view("original", "1" * 64, "b" * 64), _view("grid_cleaned", "2" * 64, "b" * 64)]
    }
    second = {"views": [_view("original", "3" * 64, "a" * 64)]}
    original_payloads = deepcopy([first, second])
    runtime = SimpleNamespace(lock=RLock(), job=AnalysisJob(running=True))
    monkeypatch.setattr(app_module, "runtime", runtime)
    monkeypatch.setattr(
        app_module, "_record_job_error", lambda *args, **kwargs: ("WORKER-EXIT", "Retry", True)
    )
    monkeypatch.setattr(app_module, "_touch_worker_locked", lambda *args: None)
    monkeypatch.setattr(app_module.time, "sleep", lambda *args: None)
    downstream = Mock()
    attempts = []

    def run_pages(supplied_pages, app_root, **kwargs):
        assert supplied_pages == pages
        assert kwargs["ocr_mode"] == "spotting"
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            kwargs["page_callback"](1, pages[0], first, False)
            raise RuntimeError("Synthetic worker exit after a completed checkpoint")
        kwargs["page_callback"](1, pages[0], deepcopy(first), True)
        kwargs["page_callback"](2, pages[1], second, False)
        return [first, second]

    monkeypatch.setattr(app_module, "run_paddle_pages", run_pages)
    observations = {}
    result = app_module._run_paddle_supervised(
        pages,
        tmp_path,
        ocr_mode="spotting",
        spotting_model_dir="unused-configured-folder",
        ocr_provenance=observations,
        page_callback=downstream,
        max_worker_attempts=2,
    )
    summary = benchmark_export.summarize_ocr_provenance(observations)

    assert attempts == [1, 2] and result == [first, second]
    assert [call.args[3] for call in downstream.call_args_list] == [False, True, False]
    assert runtime.job.retry_count == 1
    assert summary == {
        "observed_modes": ["spotting"],
        "observed_model_asset_sha256": ["a" * 64, "b" * 64],
        "observed_page_count": 2,
        "observed_view_count": 3,
    }
    assert [first, second] == original_payloads
    state = AppState(analysis_metadata={"schema_version": 1, "ocr_provenance": summary})
    exported = benchmark_export.benchmark_payload(state)
    assert exported["benchmark_metadata"]["ocr_provenance"] == summary
    assert "private_text" not in json.dumps(exported)
    assert "unused-configured-folder" not in json.dumps(exported)


def test_configured_spotting_without_receipts_stays_unobserved(tmp_path, monkeypatch, app_module):
    run_pages, downstream = Mock(return_value=[]), Mock()
    monkeypatch.setattr(app_module, "run_paddle_pages", run_pages)
    observations = {}
    app_module._run_paddle_supervised(
        [_page(tmp_path, "page-1")],
        tmp_path,
        ocr_mode="spotting",
        spotting_model_dir="configured-but-never-observed",
        ocr_provenance=observations,
        page_callback=downstream,
    )

    downstream.assert_not_called()
    assert observations == {}
    assert benchmark_export.summarize_ocr_provenance(observations) == {
        "observed_modes": [],
        "observed_model_asset_sha256": [],
        "observed_page_count": 0,
        "observed_view_count": 0,
    }


def test_unavailable_source_hash_is_explicit_and_does_not_preempt_stale_guard(
    tmp_path,
    monkeypatch,
    app_module,
):
    page = _page(tmp_path, "missing-page")
    previous = ResultRecord(point_id="001", code="MH", notes="Previous committed result")
    state = AppState(
        survey_points=[SurveyPoint(point_id="001", code="MH", category="Manhole")],
        fieldbook_pages=[page],
        results=[previous],
        analysis_metadata={"previous": True},
    )
    storage = SimpleNamespace(
        lock=RLock(), state=state, enhanced_dir=tmp_path / "enhanced", save=Mock()
    )
    runtime = SimpleNamespace(
        lock=RLock(),
        storage=storage,
        job=AnalysisJob(running=True),
        project_revision=10,
        cancel_event=Event(),
        pause_event=Event(),
        analysis_heartbeat_stop=Event(),
        hardware_profile=SimpleNamespace(as_dict=lambda: {}),
        ocr_mode="blocks",
        current_job_id=None,
        job_store=SimpleNamespace(record_error=Mock()),
    )
    monkeypatch.setattr(app_module, "runtime", runtime)
    monkeypatch.setattr(app_module, "APP_ROOT", tmp_path)
    monkeypatch.setattr(app_module, "_persist_job_snapshot_locked", lambda **kwargs: None)
    monkeypatch.setattr(app_module, "_end_live_analysis_locked", lambda: None)
    monkeypatch.setattr(app_module, "ensure_enhanced_pages_parallel", lambda *args, **kwargs: None)
    metadata = []
    original_metadata = benchmark_export.analysis_run_metadata

    def capture_metadata(**kwargs):
        value = original_metadata(**kwargs)
        metadata.append(deepcopy(value))
        return value

    def analyze(**kwargs):
        runtime.project_revision += 1
        return [
            PageEvidence(
                matched_point_id="001",
                page_id=page.page_id,
                source_name=page.source_name,
                page_number=1,
                evidence="New synthetic evidence that must be discarded",
            )
        ], []

    monkeypatch.setattr(benchmark_export, "analysis_run_metadata", capture_metadata)
    monkeypatch.setattr(app_module, "_direct_vision_analysis", analyze)
    app_module._analysis_worker(
        "manual",
        "",
        "synthetic",
        0.85,
        analysis_revision=10,
        gemini_batch_pages=1,
    )

    assert len(metadata) == 1
    assert metadata[0]["page_sha256"] == {page.page_id: None}
    assert metadata[0]["provenance_warnings"] == [f"Source image hash unavailable: {page.page_id}"]
    assert page.image_path not in json.dumps(metadata[0])
    assert runtime.job.error_code == "JOB-STALE-001"
    assert runtime.job.running is False and runtime.job.complete is False
    assert state.results == [previous] and state.analysis_metadata == {"previous": True}
    storage.save.assert_not_called()
    runtime.job_store.record_error.assert_not_called()
    assert runtime.analysis_heartbeat_stop.is_set()


def test_manual_reanalysis_does_not_export_previous_model_provenance(
    tmp_path, monkeypatch, app_module
):
    state = AppState(
        survey_points=[SurveyPoint(point_id="001", code="MH", category="Manhole")],
        fieldbook_pages=[_page(tmp_path, "page-1")],
        results=[ResultRecord(point_id="001", code="MH")],
        analysis_metadata={"mode": "spotting", "model": "previous-model"},
        spatial_graphs={"previous": {"status": "complete"}},
    )
    storage = SimpleNamespace(lock=RLock(), state=state, save=Mock())
    runtime = SimpleNamespace(
        lock=RLock(),
        storage=storage,
        job=AnalysisJob(),
        provider="manual",
        project_revision=1,
        confidence_threshold=0.85,
        status_rule="POINT_ID_FOUND",
        elevation_is_rim=False,
        network_max_distance=1500,
        network_bearing_tolerance=25,
        job_store=SimpleNamespace(create_job=Mock(return_value="manual-job"), update_job=Mock()),
    )
    monkeypatch.setattr(app_module, "runtime", runtime)
    monkeypatch.setattr(app_module, "_analysis_preflight_locked", lambda: [])
    monkeypatch.setattr(app_module, "_project_input_signature_locked", lambda: "synthetic")
    result = app_module.api_analyze()
    exported = benchmark_export.benchmark_payload(state)
    assert result["complete"] and result["provider"] == "manual"
    assert exported["benchmark_metadata"]["mode"] == "manual"
    assert "model" not in exported["benchmark_metadata"]
    assert exported["spatial_graphs"] == {} and exported["page_sha256"] == {}
    assert state.results[0].point_id == "001"
    assert state.results[0].evidence_records == []
