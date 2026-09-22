from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from fieldbook_sync.app import (
    _begin_live_analysis_locked,
    _end_live_analysis_locked,
    _publish_live_candidates,
    _publish_live_interpretation,
    api_network,
    api_results,
    runtime,
)
from fieldbook_sync.models import (
    AnalysisJob,
    DipStatus,
    EvidenceBasis,
    OcrCandidate,
    PageEvidence,
    SurveyPoint,
)

ROOT = Path(__file__).resolve().parents[1]
APPJS = (ROOT / "fieldbook_sync" / "static" / "app.js").read_text(encoding="utf-8")
OCR = (ROOT / "fieldbook_sync" / "ocr_local.py").read_text(encoding="utf-8")


def _survey() -> list[SurveyPoint]:
    return [
        SurveyPoint(point_id="100", northing=1000.0, easting=2000.0, elevation=100.0, code="STM MH", category="Storm Manhole"),
        SurveyPoint(point_id="101", northing=1010.0, easting=2010.0, elevation=99.5, code="GI", category="Grate Inlet"),
    ]


def _snapshot_runtime():
    with runtime.lock:
        return {
            "job": deepcopy(runtime.job),
            "active": runtime.live_active,
            "revision": runtime.live_analysis_revision,
            "seq": runtime.live_update_seq,
            "survey": deepcopy(runtime.live_survey_points),
            "candidates": deepcopy(runtime.live_candidates),
            "evidence": deepcopy(runtime.live_interpreted_evidence),
            "unmatched": deepcopy(runtime.live_unmatched),
            "results": deepcopy(runtime.live_results),
            "edges": deepcopy(runtime.live_network_edges),
            "keys": set(runtime.live_interpreted_candidate_keys),
            "ids": set(runtime.live_interpreted_ids),
        }


def _restore_runtime(s):
    with runtime.lock:
        runtime.job = s["job"]
        runtime.live_active = s["active"]
        runtime.live_analysis_revision = s["revision"]
        runtime.live_update_seq = s["seq"]
        runtime.live_survey_points = s["survey"]
        runtime.live_candidates = s["candidates"]
        runtime.live_interpreted_evidence = s["evidence"]
        runtime.live_unmatched = s["unmatched"]
        runtime.live_results = s["results"]
        runtime.live_network_edges = s["edges"]
        runtime.live_interpreted_candidate_keys = s["keys"]
        runtime.live_interpreted_ids = s["ids"]


def test_v808_live_analysis_starts_with_all_survey_points_visible_as_pending():
    saved = _snapshot_runtime()
    try:
        with runtime.lock:
            runtime.job = AnalysisJob(running=True, provider="hybrid")
            _begin_live_analysis_locked(_survey(), 7)
        network = api_network()
        assert network["live_preview"] is True
        assert len(network["structures"]) == 2
        assert {p["status"] for p in network["structures"]} == {"PENDING"}
        rows = api_results()
        assert len(rows) == 2
        assert {r["live_state"] for r in rows} == {"PENDING_OCR"}
    finally:
        _restore_runtime(saved)


def test_v808_ocr_candidate_is_published_before_final_commit():
    saved = _snapshot_runtime()
    try:
        with runtime.lock:
            runtime.job = AnalysisJob(running=True, provider="hybrid")
            _begin_live_analysis_locked(_survey(), 8)
        cand = OcrCandidate(page_id="p1", source_name="book.pdf", page_number=1, point_id="100", raw_text="100 STM MH", confidence=.98, bbox=[10, 20, 30, 40])
        before = runtime.job.live_update_seq
        _publish_live_candidates([cand], 8)
        rows = {r["point_id"]: r for r in api_results()}
        assert rows["100"]["live_state"] == "OCR_FOUND"
        assert rows["101"]["live_state"] == "PENDING_OCR"
        assert runtime.job.live_candidate_count == 1
        assert runtime.job.live_update_seq > before
    finally:
        _restore_runtime(saved)


def test_v808_interpretation_replaces_pending_state_live():
    saved = _snapshot_runtime()
    try:
        with runtime.lock:
            runtime.job = AnalysisJob(running=True, provider="hybrid")
            _begin_live_analysis_locked(_survey(), 9)
        cand = OcrCandidate(page_id="p1", source_name="book.pdf", page_number=1, point_id="100", raw_text="100 DIP 4.2", confidence=.98, bbox=[10, 20, 30, 40])
        _publish_live_candidates([cand], 9)
        ev = PageEvidence(
            matched_point_id="100", source_name="book.pdf", page_number=1, page_id="p1",
            point_id_raw="100", point_id_confidence=.98, dipped=DipStatus.YES,
            basis=EvidenceBasis.MEASUREMENT, dipped_confidence=.95, evidence="DIP 4.2",
            bbox=[10, 20, 30, 40], primary_engine="Qwen3.8", secondary_engine="PaddleOCR-VL 1.6",
        )
        _publish_live_interpretation(cand, [ev], [], 9)
        rows = {r["point_id"]: r for r in api_results()}
        assert rows["100"]["live_state"] == "INTERPRETED"
        assert runtime.job.live_interpreted_count == 1
    finally:
        _restore_runtime(saved)


def test_v808_paddle_stream_has_per_page_callback_for_cache_and_new_pages():
    assert "page_callback:" in OCR
    assert "page_callback(original_index + 1" in OCR
    assert "page_callback(original_idx + 1" in OCR


def test_v808_browser_refreshes_live_tabs_only_when_snapshot_changes():
    assert "refreshLiveViews" in APPJS
    assert "live_update_seq" in APPJS
    assert "seq!==liveSeqSeen" in APPJS
    assert "renderCandidates();renderNetwork();renderMetrics()" in APPJS


def test_v808_review_and_map_have_explicit_live_states():
    assert "PENDING OCR" in APPJS
    assert "OCR FOUND" in APPJS
    assert "INTERPRETATION PENDING" in APPJS
    assert "LIVE ANALYSIS PREVIEW" in APPJS
    assert "network.candidate_count" in APPJS
