from fieldbook_sync.ai_reader import _parse_status_basis, ENTRY_PROPERTIES, SYSTEM_PROMPT
from fieldbook_sync.aggregate import aggregate_results
from fieldbook_sync.intelligence import calculate_smart_confidence
from fieldbook_sync.models import DipStatus, EvidenceBasis, PageEvidence, StatusRule, SurveyPoint
from fieldbook_sync.ocr_local import compare_ocr_to_evidence
from fieldbook_sync.interpret_cache import INTERPRETATION_CACHE_SCHEMA


def _ev(status: DipStatus, basis: EvidenceBasis, evidence: str) -> PageEvidence:
    return PageEvidence(
        matched_point_id="1001",
        source_name="book.pdf",
        page_number=1,
        page_id="p1",
        point_id_raw="1001",
        point_id_confidence=0.99,
        dipped=status,
        dipped_confidence=0.98,
        basis=basis,
        evidence=evidence,
        pipes=[],
    )


def test_schema_and_prompt_explicitly_support_cna_cnl():
    assert "CNA" in ENTRY_PROPERTIES["dipped"]["enum"]
    assert "CNL" in ENTRY_PROPERTIES["dipped"]["enum"]
    assert "EXPLICIT_CNA" in ENTRY_PROPERTIES["basis"]["enum"]
    assert "EXPLICIT_CNL" in ENTRY_PROPERTIES["basis"]["enum"]
    assert "COULD NOT ACCESS" in SYSTEM_PROMPT
    assert "COULD NOT LOCATE" in SYSTEM_PROMPT
    assert "dip-status" in INTERPRETATION_CACHE_SCHEMA


def test_provider_cannot_emit_cna_cnl_without_matching_explicit_basis():
    assert _parse_status_basis({"dipped":"CNA", "basis":"AMBIGUOUS"})[0] == DipStatus.REVIEW
    assert _parse_status_basis({"dipped":"CNL", "basis":"EXPLICIT_NO"})[0] == DipStatus.REVIEW
    assert _parse_status_basis({"dipped":"CNA", "basis":"EXPLICIT_CNA"}) == (DipStatus.CNA, EvidenceBasis.EXPLICIT_CNA)
    assert _parse_status_basis({"dipped":"CNL", "basis":"EXPLICIT_CNL"}) == (DipStatus.CNL, EvidenceBasis.EXPLICIT_CNL)


def test_cna_is_preserved_as_dip_detail_but_point_id_found_primary_stays_yes():
    point = SurveyPoint(point_id="1001", code="MH")
    result = aggregate_results([point], [_ev(DipStatus.CNA, EvidenceBasis.EXPLICIT_CNA, "CNA")], .85, StatusRule.POINT_ID_FOUND)[0]
    assert result.status == DipStatus.YES
    assert result.dip_status == DipStatus.CNA
    assert result.qa_needs_review is False
    assert result.pipes == []
    assert "Could Not Access" in result.notes


def test_cnl_becomes_primary_when_confirmed_dip_rule_is_selected():
    point = SurveyPoint(point_id="1001", code="MH")
    result = aggregate_results([point], [_ev(DipStatus.CNL, EvidenceBasis.EXPLICIT_CNL, "CNL")], .85, StatusRule.CONFIRMED_DIP)[0]
    assert result.status == DipStatus.CNL
    assert result.dip_status == DipStatus.CNL
    assert result.qa_needs_review is False
    assert "Could Not Locate" in result.notes


def test_conflicting_cna_and_cnl_require_review():
    point = SurveyPoint(point_id="1001", code="MH")
    evidence = [
        _ev(DipStatus.CNA, EvidenceBasis.EXPLICIT_CNA, "CNA"),
        _ev(DipStatus.CNL, EvidenceBasis.EXPLICIT_CNL, "CNL"),
    ]
    result = aggregate_results([point], evidence, .85, StatusRule.POINT_ID_FOUND)[0]
    assert result.status == DipStatus.YES
    assert result.dip_status == DipStatus.REVIEW
    assert result.qa_needs_review is True


def test_paddle_text_can_independently_verify_cna_and_cnl():
    cna = _ev(DipStatus.CNA, EvidenceBasis.EXPLICIT_CNA, "CNA")
    cnl = _ev(DipStatus.CNL, EvidenceBasis.EXPLICIT_CNL, "CNL")
    assert compare_ocr_to_evidence("1001 CNA", cna)[0] is True
    assert compare_ocr_to_evidence("1001 could not access", cna)[0] is True
    assert compare_ocr_to_evidence("1001 CNL", cnl)[0] is True
    assert compare_ocr_to_evidence("1001 could not locate", cnl)[0] is True
    assert compare_ocr_to_evidence("1001 CNA", cnl)[0] is False


def test_cna_cnl_receive_explicit_evidence_confidence_credit():
    cna_result = aggregate_results(
        [SurveyPoint(point_id="1001", code="MH")],
        [_ev(DipStatus.CNA, EvidenceBasis.EXPLICIT_CNA, "CNA")],
        .85,
        StatusRule.POINT_ID_FOUND,
    )[0]
    score, factors = calculate_smart_confidence(cna_result)
    assert score > 0
    assert any("Could Not Access" in factor for factor in factors)
