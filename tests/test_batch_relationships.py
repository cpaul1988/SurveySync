"""Batch jobs preserve selected OCR mode, original coordinates, and review evidence."""

from copy import deepcopy
import hashlib
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

import fieldbook_sync
from fieldbook_sync import batch_workers
from fieldbook_sync.models import (
    AppState,
    BatchJob,
    FieldBookPage,
    OcrCandidate,
    PageEvidence,
    PipeMeasurement,
    SurveyPoint,
)
from fieldbook_sync.text_spotting import SpottingCapabilityError


TEXT = '001\nPipe: DIP 4.20 8" PVC AZ 90'
MODEL_HASH = "a" * 64


@pytest.fixture
def batch_case(tmp_path, monkeypatch):
    original, enhanced = tmp_path / "original.png", tmp_path / "enhanced.png"
    Image.new("RGB", (1000, 1000), "white").save(original)
    Image.new("RGB", (1000, 1000), "black").save(enhanced)
    page = FieldBookPage(
        page_id="page-1",
        source_name="synthetic-book",
        page_number=1,
        image_path=str(original),
        enhanced_image_path=str(enhanced),
        mime_type="image/png",
    )
    state = AppState(
        survey_points=[SurveyPoint(point_id="001", code="MH")],
        fieldbook_pages=[page],
        analysis_metadata={"old_run": True},
        spatial_graphs={"old-graph": {"status": "complete"}},
    )
    runtime = SimpleNamespace(
        lock=RLock(),
        storage=SimpleNamespace(lock=RLock(), save=Mock()),
        ocr_mode="spotting",
        spotting_model_dir="selected-local-assets",
        performance_mode="safe",
        ollama_model="fixture-qwen",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_batch_pages=1,
        gemini_model="fixture-gemini",
        gemini_api_key="synthetic-key",
        gemini_batch_pages=1,
        openai_model="fixture-openai",
        openai_api_key="synthetic-key",
        anthropic_model="fixture-anthropic",
        anthropic_api_key="synthetic-key",
        hardware_profile=SimpleNamespace(as_dict=lambda: {}),
    )
    context = SimpleNamespace(
        APP_ROOT=tmp_path,
        runtime=runtime,
        MAX_ACCURACY_OLLAMA_MODEL="unused",
        _field_note_profile_context=lambda *args: "",
        _effective_page_profile_id=lambda *args: "",
        _ollama_model_is_installed=lambda model, installed: model in installed,
    )
    monkeypatch.setattr(fieldbook_sync, "app", context, raising=False)
    monkeypatch.setattr(batch_workers, "ensure_enhanced_pages", lambda *args: None)
    monkeypatch.setattr(batch_workers, "list_ollama_models", lambda **kwargs: ["fixture-qwen"])
    monkeypatch.setattr(
        batch_workers, "paddle_status", lambda *args: SimpleNamespace(installed=True, device="cpu")
    )
    monkeypatch.setattr(batch_workers, "refresh_intelligence", lambda *args, **kwargs: [])
    return SimpleNamespace(
        root=tmp_path,
        page=page,
        state=state,
        runtime=runtime,
        original=original,
        enhanced=enhanced,
    )


def _payload(case, mode):
    return {
        "views": [
            {
                "surveysync_view": {
                    "role": "original",
                    "ocr_mode": mode,
                    "image_sha256": hashlib.sha256(case.original.read_bytes()).hexdigest(),
                    "model_sha256": MODEL_HASH if mode == "spotting" else "",
                },
                "res": {
                    "width": 1000,
                    "height": 1000,
                    "parsing_res_list": [
                        {
                            "block_content": TEXT,
                            "block_bbox": [100, 100, 120, 120],
                            "source": f"paddleocr-vl-1.6-{mode}",
                        }
                    ],
                },
            }
        ]
    }


def _evidence(case):
    return PageEvidence(
        matched_point_id="001",
        page_id=case.page.page_id,
        source_name=case.page.source_name,
        page_number=1,
        point_id_confidence=0.99,
        dipped="YES",
        basis="MEASUREMENT",
        dipped_confidence=0.99,
        evidence=TEXT,
        structure_bbox=[0, 0, 1000, 1000],
        pipes=[
            PipeMeasurement(
                dip=4.2,
                diameter_in=8,
                material="PVC",
                azimuth_deg=90,
                leader_bbox=[0, 0, 1000, 1000],
            )
        ],
    )


def _assert_saved_graph_and_review(case):
    result = case.state.results[0]
    item = result.evidence_records[0]
    assert result.qa_needs_review is True
    assert item.evidence_decision != "AUTO_ACCEPT"
    assert "PIPE_BINDING_REVIEW_REQUIRED" in item.validation_flags
    assert item.spatial_evidence == {}
    assert item.spatial_evidence_key in case.state.spatial_graphs
    graph = case.state.spatial_graphs[item.spatial_evidence_key]
    assert graph["source"]["image_sha256"] == hashlib.sha256(case.original.read_bytes()).hexdigest()
    assert graph["text_regions"] and graph["point_anchors"]
    assert "old-graph" not in case.state.spatial_graphs
    return item


def test_batch_hybrid_freezes_spotting_settings_maps_original_crop_and_saves_receipts(
    batch_case,
    monkeypatch,
):
    case = batch_case
    payload, item = _payload(case, "spotting"), _evidence(case)

    def later_ui_edit(*args):
        case.runtime.ocr_mode = "blocks"
        case.runtime.spotting_model_dir = "different-local-assets"
        case.runtime.ollama_model = "different-qwen"

    def run_paddle(pages, app_root, **kwargs):
        assert kwargs == {
            "ocr_mode": "spotting",
            "spotting_model_dir": "selected-local-assets",
            "performance_mode": "safe",
        }
        return [payload]

    def interpret(**kwargs):
        assert kwargs["model"] == "fixture-qwen"
        with Image.open(kwargs["pages"][0].image_path) as image:
            assert image.size == (475, 388)
            assert image.getpixel((10, 10)) == (255, 255, 255)
        return [item], [], None

    monkeypatch.setattr(batch_workers, "ensure_enhanced_pages", later_ui_edit)
    monkeypatch.setattr(batch_workers, "run_paddle_pages", run_paddle)
    monkeypatch.setattr(batch_workers, "read_pages_ollama", interpret)
    batch_workers._batch_analyze_state(
        BatchJob(job_id="job-1", name="Synthetic", provider="hybrid"),
        case.state,
        case.root / "pages",
    )

    saved = _assert_saved_graph_and_review(case)
    assert saved.structure_bbox == [0, 0, 475, 388]
    assert saved.pipes[0].leader_bbox == [0, 0, 475, 388]
    assert saved.numerical_agreement is True and saved.pipe_record_agreement is True
    metadata = case.state.analysis_metadata
    assert metadata["mode"] == "spotting" and metadata["model"] == "fixture-qwen"
    assert metadata["ocr_provenance"]["observed_model_asset_sha256"] == [MODEL_HASH]
    assert metadata["ocr_provenance"]["observed_view_count"] == 1


@pytest.mark.parametrize("mode", ["blocks", "spotting"])
def test_batch_paddle_only_forwards_mode_and_retains_canonical_graph(batch_case, monkeypatch, mode):
    case = batch_case
    case.runtime.ocr_mode = mode
    paddle = Mock(return_value=[_payload(case, mode)])
    qwen = Mock(side_effect=AssertionError("Paddle-only must not run Qwen"))
    monkeypatch.setattr(batch_workers, "run_paddle_pages", paddle)
    monkeypatch.setattr(batch_workers, "read_pages_ollama", qwen)
    batch_workers._batch_analyze_state(
        BatchJob(job_id="job-1", name="Synthetic", provider="paddle"),
        case.state,
        case.root / "pages",
    )

    assert paddle.call_args.kwargs["ocr_mode"] == mode
    assert paddle.call_args.kwargs["spotting_model_dir"] == "selected-local-assets"
    qwen.assert_not_called()
    item = case.state.results[0].evidence_records[0]
    assert item.evidence_decision != "AUTO_ACCEPT" and not item.pipes
    assert item.spatial_evidence_key in case.state.spatial_graphs
    assert item.spatial_evidence == {}
    assert case.state.analysis_metadata["mode"] == mode
    assert case.state.analysis_metadata["ocr_provenance"]["observed_model_asset_sha256"] == (
        [MODEL_HASH] if mode == "spotting" else []
    )


@pytest.mark.parametrize("provider", ["hybrid", "paddle"])
def test_batch_explicit_spotting_never_falls_back_when_paddle_is_missing(
    batch_case,
    monkeypatch,
    provider,
):
    case = batch_case
    monkeypatch.setattr(
        batch_workers,
        "paddle_status",
        lambda *args: SimpleNamespace(installed=False, message="Missing"),
    )
    paddle, qwen = Mock(), Mock()
    monkeypatch.setattr(batch_workers, "run_paddle_pages", paddle)
    monkeypatch.setattr(batch_workers, "read_pages_ollama", qwen)
    with pytest.raises(SpottingCapabilityError, match="installed PaddleOCR-VL 1.6 runtime"):
        batch_workers._batch_analyze_state(
            BatchJob(job_id="job-1", name="Synthetic", provider=provider),
            case.state,
            case.root / "pages",
        )
    paddle.assert_not_called()
    qwen.assert_not_called()


def test_batch_windows_uses_original_ocr_and_maps_model_pipe_geometry(batch_case, monkeypatch):
    case = batch_case
    candidate = OcrCandidate(
        page_id=case.page.page_id,
        source_name=case.page.source_name,
        page_number=1,
        point_id="001",
        recognized_point_id="001",
        raw_text=TEXT,
        confidence=0.99,
        bbox=[100, 100, 120, 120],
        engine="Windows AI OCR",
        source_view="original",
    )
    payload = {
        "width": 1000,
        "height": 1000,
        "lines": [
            {
                "text": TEXT,
                "polygon": [[100, 100], [120, 100], [120, 120], [100, 120]],
            }
        ],
    }

    def windows(path):
        assert Path(path) == case.original
        return payload

    def interpret(**kwargs):
        with Image.open(kwargs["pages"][0].image_path) as image:
            assert image.size == (475, 388)
            assert image.getpixel((10, 10)) == (255, 255, 255)
        return [_evidence(case)], [], None

    monkeypatch.setattr(batch_workers, "windows_ocr", windows)
    monkeypatch.setattr(
        batch_workers, "_windows_ocr_candidates_from_payload", lambda *args: [candidate]
    )
    monkeypatch.setattr(batch_workers, "read_pages_ollama", interpret)
    batch_workers._batch_analyze_state(
        BatchJob(job_id="job-1", name="Synthetic", provider="windows_ocr_ollama"),
        case.state,
        case.root / "pages",
    )

    saved = _assert_saved_graph_and_review(case)
    assert saved.structure_bbox == [0, 0, 475, 388]
    assert saved.pipes[0].leader_bbox == [0, 0, 475, 388]
    assert saved.numerical_agreement is True and saved.pipe_record_agreement is True
    assert case.state.analysis_metadata["mode"] == "windows_ocr_ollama"


@pytest.mark.parametrize("provider", ["ollama", "gemini", "openai", "anthropic"])
def test_all_direct_batch_paths_apply_pipe_review_gate_without_stale_ocr(
    batch_case,
    monkeypatch,
    provider,
):
    case = batch_case
    item = _evidence(case)
    item.evidence_decision = "AUTO_ACCEPT"
    case.state.ocr_candidates = [
        OcrCandidate(
            page_id=case.page.page_id,
            source_name=case.page.source_name,
            page_number=1,
            point_id="001",
            confidence=1,
            raw_text=TEXT,
            bbox=[100, 100, 120, 120],
        )
    ]
    returned = deepcopy(item)
    for name in (
        "read_pages_ollama",
        "read_pages_gemini",
        "read_page_openai",
        "read_page_anthropic",
    ):
        monkeypatch.setattr(batch_workers, name, lambda **kwargs: ([returned], [], None))
    batch_workers._batch_analyze_state(
        BatchJob(job_id="job-1", name="Synthetic", provider=provider),
        case.state,
        case.root / "pages",
    )

    saved = case.state.results[0].evidence_records[0]
    assert case.state.results[0].qa_needs_review is True
    assert saved.evidence_decision != "AUTO_ACCEPT"
    assert "PIPE_BINDING_REVIEW_REQUIRED" in saved.validation_flags
    assert case.state.ocr_candidates == []
    assert case.state.spatial_graphs == {}
    assert case.state.analysis_metadata["ocr_provenance"]["observed_view_count"] == 0
