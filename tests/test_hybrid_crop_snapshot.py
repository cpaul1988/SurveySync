"""A supplemental OCR observation must not change an already submitted crop's frame."""

from pathlib import Path
from threading import Event, RLock
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

import fieldbook_sync
from fieldbook_sync import vision_pipeline
from fieldbook_sync.ai_reader import ProviderUsage
from fieldbook_sync.models import FieldBookPage, OcrCandidate, PageEvidence, PipeMeasurement
from fieldbook_sync.text_spotting import SpottingCapabilityError


def test_explicit_spotting_without_paddle_never_falls_back_to_qwen(tmp_path, monkeypatch):
    runtime = SimpleNamespace(
        ocr_mode="spotting", lock=RLock(), job=SimpleNamespace(stage="pending", message="")
    )
    monkeypatch.setattr(
        fieldbook_sync, "app", SimpleNamespace(APP_ROOT=tmp_path, runtime=runtime), raising=False
    )
    monkeypatch.setattr(
        vision_pipeline, "paddle_status", lambda *args: SimpleNamespace(installed=False)
    )
    fallback = Mock(side_effect=AssertionError("Spotting must not invoke another model"))
    monkeypatch.setattr(vision_pipeline, "_direct_vision_analysis", fallback)

    with pytest.raises(SpottingCapabilityError, match="installed PaddleOCR-VL 1.6 runtime"):
        vision_pipeline._hybrid_local_analysis(
            pages=[],
            targets=["001"],
            model="synthetic-qwen",
            local_base_url="http://127.0.0.1",
            batch_pages=1,
            analysis_revision=1,
        )

    fallback.assert_not_called()
    assert runtime.job.stage == "pending"


def test_overlapping_paddle_update_preserves_the_qwen_crop_coordinate_frame(tmp_path, monkeypatch):
    source = tmp_path / "page.png"
    Image.new("RGB", (1000, 1000), "white").save(source)
    page = FieldBookPage(
        page_id="page-1",
        source_name="book",
        page_number=1,
        image_path=str(source),
        mime_type="image/png",
    )
    windows_candidate = OcrCandidate(
        page_id=page.page_id,
        source_name=page.source_name,
        page_number=1,
        point_id="001",
        recognized_point_id="001",
        raw_text="001",
        confidence=0.99,
        bbox=[100, 100, 120, 120],
        engine="Windows AI OCR",
        source_view="original",
    )
    paddle_candidate = windows_candidate.model_copy(deep=True)
    paddle_candidate.bbox = [800, 800, 830, 830]
    paddle_candidate.engine = "PaddleOCR-VL 1.6"
    model_started, paddle_updated = Event(), Event()
    observed_evidence, submitted_images = [], []
    runtime = SimpleNamespace(
        lock=RLock(),
        cancel_event=Event(),
        pause_event=Event(),
        project_revision=1,
        current_job_id=None,
        performance_mode="auto",
        hardware_profile=SimpleNamespace(),
        ocr_mode="blocks",
        interpretation_crop_dir=tmp_path / "crops",
        interpretation_cache_dir=tmp_path / "interpretations",
        ocr_cache_dir=tmp_path / "ocr",
        job=SimpleNamespace(total_requests=0, current_request=0, stage="", warning_count=0),
    )
    context = SimpleNamespace(
        APP_ROOT=tmp_path,
        runtime=runtime,
        MAX_ACCURACY_OLLAMA_MODEL="unused",
        _check_worker_revision=lambda *args: True,
        _analysis_pause_checkpoint=lambda *args: True,
        _touch_worker_locked=lambda *args: None,
        _publish_live_candidates=lambda *args: None,
        _publish_live_interpretation=lambda *args: None,
        _record_usage_locked=lambda *args: None,
        _qwen_progress=lambda *args: None,
        _retry_operation=lambda operation, **kwargs: operation(),
        _effective_page_profile_id=lambda *args: "",
        _field_note_profile_context=lambda: "",
        _dedupe_unmatched=lambda items: items,
        _live_candidate_key=lambda candidate: (
            candidate.page_id,
            candidate.point_id,
            tuple(candidate.bbox or []),
        ),
    )

    def read_crop(**kwargs):
        crop = Path(kwargs["pages"][0].image_path)
        with Image.open(crop) as image:
            submitted_images.append(image.size)
        first_call = not observed_evidence
        item = PageEvidence(
            matched_point_id="001",
            page_id=page.page_id,
            source_name=page.source_name,
            page_number=1,
            point_id_confidence=0.99,
            dipped="YES",
            basis="MEASUREMENT",
            structure_bbox=[0, 0, 1000, 1000],
            pipes=[PipeMeasurement(dip=4.2, leader_bbox=[0, 0, 1000, 1000])],
        )
        observed_evidence.append(item)
        if first_call:
            model_started.set()
            assert paddle_updated.wait(5), "Paddle callback did not complete during inference"
        return [item], [], ProviderUsage()

    def run_paddle(pages, app_root, **kwargs):
        try:
            assert model_started.wait(5), "Windows crop was not scheduled concurrently"
            kwargs["page_callback"](1, page, {"res": {}}, False)
        finally:
            paddle_updated.set()
        return []

    context._run_paddle_supervised = run_paddle
    monkeypatch.setattr(fieldbook_sync, "app", context, raising=False)
    monkeypatch.setattr(
        vision_pipeline,
        "paddle_status",
        lambda *args: SimpleNamespace(installed=True, device="cpu"),
    )
    monkeypatch.setattr(
        vision_pipeline,
        "build_performance_plan",
        lambda *args: SimpleNamespace(
            pipeline_overlap=True,
            qwen_workers=1,
            interpretation_cache_enabled=False,
            near_match_routing=False,
        ),
    )
    monkeypatch.setattr(
        vision_pipeline, "get_local_ai_status", lambda: {"windows_ocr": {"ready": True}}
    )
    monkeypatch.setattr(vision_pipeline, "windows_ocr", lambda *args: {"lines": []})
    monkeypatch.setattr(
        vision_pipeline, "_windows_ocr_candidates_from_payload", lambda *args: [windows_candidate]
    )
    monkeypatch.setattr(vision_pipeline, "windows_anchor_can_skip_paddle", lambda *args: False)
    monkeypatch.setattr(
        vision_pipeline, "locate_target_ids", lambda *args, **kwargs: [paddle_candidate]
    )
    monkeypatch.setattr(vision_pipeline, "_page_spatial_graph", lambda *args: None)
    monkeypatch.setattr(vision_pipeline, "read_pages_ollama", read_crop)

    evidence, unmatched, candidates = vision_pipeline._hybrid_local_analysis(
        pages=[page],
        targets=["001"],
        model="synthetic-qwen",
        local_base_url="http://127.0.0.1",
        batch_pages=1,
        analysis_revision=1,
    )

    assert evidence and not unmatched and candidates
    assert submitted_images[0] == (475, 388)
    assert observed_evidence[0].structure_bbox == [0, 0, 475, 388]
    assert observed_evidence[0].pipes[0].leader_bbox == [0, 0, 475, 388]
