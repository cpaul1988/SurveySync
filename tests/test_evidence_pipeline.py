from __future__ import annotations

from fieldbook_sync.evidence_pipeline import (
    PAGE_CONTROL,
    PAGE_LEVEL_LOOP,
    PAGE_UTILITY,
    apply_assessment,
    classify_page_text,
    paddle_payload_text,
    windows_payload_text,
    windows_anchor_can_skip_paddle,
)
from fieldbook_sync.models import EvidenceBasis, OcrCandidate, PageEvidence


def _candidate(engine: str = "Windows AI OCR") -> OcrCandidate:
    return OcrCandidate(
        page_id="p1", source_name="book.pdf", page_number=1,
        point_id="2437", raw_text="MH 2437 DIP 4.62 8 PVC", confidence=0.97,
        bbox=[100, 100, 500, 300], engine=engine, exact_match=True,
    )


def _evidence() -> PageEvidence:
    return PageEvidence(
        matched_point_id="2437", source_name="book.pdf", page_number=1, page_id="p1",
        point_id_raw="2437", point_id_confidence=0.98,
        dipped="YES", basis=EvidenceBasis.MEASUREMENT, dipped_confidence=0.95,
        evidence="DIP 4.62", primary_engine="Qwen3-VL", model_agreement=True,
        page_type=PAGE_UTILITY, page_type_confidence=0.9,
    )


def test_page_classifier_distinguishes_common_survey_pages():
    utility = classify_page_text("MH 2437 DIP 4.62 8 PVC INV storm sewer rim 12.4")
    level = classify_page_text("BM 1 backsight 5.22 HI 105.22 TP1 foresight 4.80 elevation closure")
    control = classify_page_text("GNSS RTK control point northing easting datum occupation")
    assert utility.page_type == PAGE_UTILITY
    assert level.page_type == PAGE_LEVEL_LOOP
    assert control.page_type == PAGE_CONTROL
    assert utility.confidence >= 0.7


def test_payload_flatteners_are_provider_agnostic():
    win = windows_payload_text({"lines": [{"text": "MH 2437"}, {"text": "DIP 4.62"}]})
    paddle = paddle_payload_text({"result": {"parsing_res_list": [{"block_content": "MH 2437"}, {"block_content": "DIP 4.62"}]}})
    assert "2437" in win and "4.62" in win
    assert "2437" in paddle and "4.62" in paddle


def test_high_quality_independent_evidence_can_auto_accept_details():
    ev = _evidence()
    assessment = apply_assessment(_candidate(), ev, imported_point_ids=["2437", "2438"])
    assert assessment.decision == "AUTO_ACCEPT"
    assert assessment.score >= 0.88
    assert ev.evidence_score == assessment.score
    assert "Windows AI OCR" in ev.evidence_sources


def test_model_disagreement_routes_to_review():
    ev = _evidence()
    ev.model_agreement = False
    assessment = apply_assessment(_candidate(), ev, imported_point_ids=["2437"])
    assert assessment.decision != "AUTO_ACCEPT"
    assert "MODEL_DISAGREEMENT" in assessment.flags


def test_ai_without_independent_exact_ocr_stays_manual_review():
    ev = _evidence()
    assessment = apply_assessment(None, ev, imported_point_ids=["2437"])
    assert assessment.decision == "MANUAL_REVIEW"
    assert "NO_INDEPENDENT_EXACT_POINTID" in assessment.flags


def test_windows_fast_anchor_skips_paddle_only_for_strong_utility_context():
    cand = _candidate()
    strong = classify_page_text("MH 2437 DIP 4.62 8 PVC invert storm sewer manhole")
    risky = classify_page_text("BM 2437 backsight 4.62 HI 105.0 foresight TP elevation closure")
    assert windows_anchor_can_skip_paddle(cand, strong) is True
    assert windows_anchor_can_skip_paddle(cand, risky) is False
    weak = cand.model_copy(update={"confidence": 0.80})
    assert windows_anchor_can_skip_paddle(weak, strong) is False
