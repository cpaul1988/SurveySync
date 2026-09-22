from __future__ import annotations

"""Evidence-first analysis helpers for SurveySync FieldBookSync.

The functions in this module are deliberately deterministic and dependency-light. AI/OCR
providers are allowed to *observe* the page; this layer decides how much trust to place in
those observations and whether a human needs to review them.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .models import EvidenceBasis, OcrCandidate, PageEvidence


PAGE_UNKNOWN = "unknown"
PAGE_UTILITY = "utility_structure"
PAGE_LEVEL_LOOP = "level_loop"
PAGE_CONTROL = "control"
PAGE_TOPO = "topo"
PAGE_INDEX = "index"
PAGE_SKETCH = "sketch"
PAGE_BLANK = "blank"


@dataclass(frozen=True)
class PageClassification:
    page_type: str = PAGE_UNKNOWN
    confidence: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class EvidenceAssessment:
    score: float
    decision: str
    sources: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    factors: list[str] = field(default_factory=list)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def windows_payload_text(payload: dict[str, Any]) -> str:
    """Flatten Windows TextRecognizer output into classifier text."""
    parts: list[str] = []
    for line in payload.get("lines") or []:
        if isinstance(line, dict):
            text = _clean_text(line.get("text") or "")
            if text:
                parts.append(text)
    return "\n".join(parts)


def paddle_payload_text(payload: Any) -> str:
    """Flatten PaddleOCR-VL parsing blocks without depending on private OCR helpers."""
    parts: list[str] = []
    seen: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            content = obj.get("block_content")
            if isinstance(content, str):
                text = _clean_text(content)
                if text and text not in seen:
                    seen.add(text)
                    parts.append(text)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(payload)
    return "\n".join(parts)


def classify_page_text(text: str) -> PageClassification:
    """Conservatively classify a field-book page from OCR text.

    Classification is advisory only: UNKNOWN pages are always analyzed normally. BLANK is
    returned only when there is effectively no readable text; it is not used as an
    authoritative reason to discard source material.
    """
    clean = _clean_text(text)
    if len(re.sub(r"[^A-Za-z0-9]", "", clean)) < 3:
        return PageClassification(PAGE_BLANK, 0.96, "No meaningful OCR text was detected.")

    low = clean.casefold()
    token_count = max(1, len(re.findall(r"[a-z0-9]+", low)))
    scores = {
        PAGE_UTILITY: 0,
        PAGE_LEVEL_LOOP: 0,
        PAGE_CONTROL: 0,
        PAGE_TOPO: 0,
        PAGE_INDEX: 0,
        PAGE_SKETCH: 0,
    }

    weighted_terms = {
        PAGE_UTILITY: {
            "dip": 4, "dipped": 4, "invert": 4, "inv": 2, "pipe": 3, "mh": 3,
            "manhole": 4, "storm": 2, "sanitary": 2, "sewer": 3, "pvc": 2,
            "rcp": 2, "cmp": 2, "hdpe": 2, "diameter": 2, "rim": 2,
        },
        PAGE_LEVEL_LOOP: {
            "backsight": 5, "back sight": 5, "foresight": 5, "fore sight": 5,
            "b.s.": 4, "f.s.": 4, "bs": 2, "fs": 2, "turning point": 5,
            "tp": 2, "height of instrument": 5, "hi": 2, "benchmark": 4,
            "bm": 2, "elevation": 2, "level loop": 6, "closure": 3,
        },
        PAGE_CONTROL: {
            "control": 4, "gnss": 5, "gps": 4, "rtk": 5, "occupation": 3,
            "baseline": 2, "datum": 3, "benchmark": 2, "northing": 3,
            "easting": 3, "coordinate": 3,
        },
        PAGE_TOPO: {
            "topo": 5, "topographic": 5, "shot": 3, "shots": 3, "feature": 2,
            "edge of pavement": 3, "eop": 2, "flowline": 3, "ground": 2,
        },
        PAGE_INDEX: {
            "index": 7, "contents": 5, "page": 1, "pages": 1, "book no": 3,
        },
        PAGE_SKETCH: {
            "sketch": 6, "not to scale": 5, "nts": 3, "detail": 2,
        },
    }
    for page_type, terms in weighted_terms.items():
        for term, weight in terms.items():
            if term in low:
                scores[page_type] += weight

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_type, best_score = ranked[0]
    second_score = ranked[1][1]
    if best_score < 3:
        return PageClassification(PAGE_UNKNOWN, 0.35, "OCR text did not strongly match a known survey page type.")

    # The confidence is intentionally conservative; page-type classification is routing
    # context, never evidence that overrides what is visibly on the page.
    margin = max(0, best_score - second_score)
    confidence = min(0.97, 0.58 + min(0.25, best_score / max(10.0, token_count / 4.0) * 0.08) + min(0.14, margin * 0.025))
    return PageClassification(
        best_type,
        round(confidence, 3),
        f"Matched {best_type.replace('_', ' ')} terminology (score {best_score}, margin {margin}).",
    )


def specialized_prompt_note(page_type: str) -> str:
    notes = {
        PAGE_UTILITY: (
            "This looks like a utility/structure page. Focus on the exact PointID association, "
            "dip/depth/invert measurements, pipe diameter, material, azimuth/bearing, CNA/CNL, and explicit notes. "
            "If the page uses the BRT-style circle + north arrow + pipe leaders, keep each leader and its nearby annotations as one pipe record."
        ),
        PAGE_LEVEL_LOOP: (
            "This looks like a level-loop page. Do not reinterpret BS/FS/HI/TP/elevation observations as sewer dips or pipes. "
            "Only return a structure entry if an exact target PointID and structure-specific dip evidence are visibly present."
        ),
        PAGE_CONTROL: (
            "This looks like control/GNSS notes. Do not reinterpret coordinates, antenna heights, occupations, or control elevations "
            "as sewer dip measurements. Only return structure evidence when it is explicitly visible."
        ),
        PAGE_TOPO: (
            "This looks like topographic notes. Do not turn generic shots/features into structure dip evidence unless the exact target "
            "PointID is visibly tied to a structure entry."
        ),
        PAGE_INDEX: "This looks like an index/contents page. Treat listed PointIDs as references, not structure/dip evidence.",
        PAGE_SKETCH: "This looks primarily like a sketch/detail page. Use geometry to associate each visible leader with its own annotations and, when a north arrow is clear, to estimate leader direction; never infer dip/diameter/material values from geometry alone.",
        PAGE_BLANK: "Very little OCR text was detected. Be conservative and return no entry unless the target and supporting evidence are clearly visible.",
        PAGE_UNKNOWN: "Page type is uncertain. Apply the normal conservative field-book extraction rules.",
    }
    return notes.get(page_type or PAGE_UNKNOWN, notes[PAGE_UNKNOWN])



def windows_anchor_can_skip_paddle(candidate: OcrCandidate, classification: PageClassification) -> bool:
    """Return True only for a very strong Windows anchor where redundant Paddle search is safe.

    This is intentionally narrow: exact imported-ID matching is already enforced before this
    helper is called; we additionally require strong Windows confidence and a confidently
    classified utility/structure page. Unknown, level-loop, control, index, topo, and sketch
    contexts continue through PaddleOCR-VL for accuracy.
    """
    return bool(
        candidate.exact_match
        and candidate.confidence >= 0.94
        and classification.page_type == PAGE_UTILITY
        and classification.confidence >= 0.75
    )

def assess_evidence(
    candidate: OcrCandidate | None,
    evidence: PageEvidence,
    *,
    imported_point_ids: Iterable[str],
) -> EvidenceAssessment:
    """Score an extraction using independent evidence, not model self-confidence alone."""
    imported = {str(x).strip() for x in imported_point_ids if str(x).strip()}
    score = 0.0
    sources: list[str] = []
    flags: list[str] = []
    factors: list[str] = []

    exact_ocr = bool(candidate and candidate.exact_match and candidate.point_id == evidence.matched_point_id)
    if exact_ocr:
        score += 0.42
        sources.append(candidate.engine or "independent OCR")
        factors.append("Independent OCR exactly matched the imported PointID.")
    else:
        flags.append("NO_INDEPENDENT_EXACT_POINTID")

    if evidence.matched_point_id in imported:
        score += 0.18
        factors.append("PointID exists in the imported survey targets.")
    else:
        flags.append("POINTID_NOT_IN_SURVEY")

    if evidence.primary_engine:
        score += 0.12
        sources.append(evidence.primary_engine)
        factors.append("A vision/document model supplied structured interpretation.")

    if evidence.model_agreement is True:
        score += 0.14
        factors.append("Independent OCR and model interpretation agree.")
    elif evidence.model_agreement is False:
        score -= 0.24
        flags.append("MODEL_DISAGREEMENT")
        factors.append("Independent engines disagree; human review required.")

    semantic_conf = max(0.0, min(1.0, float(evidence.dipped_confidence or 0.0)))
    score += 0.08 * semantic_conf
    if evidence.basis != EvidenceBasis.AMBIGUOUS:
        score += 0.04
    else:
        flags.append("AMBIGUOUS_SEMANTICS")

    if evidence.page_type in {PAGE_LEVEL_LOOP, PAGE_CONTROL, PAGE_INDEX}:
        # These page types are more prone to numbers that resemble PointIDs/dips. Exact OCR
        # keeps the point association authoritative, but semantic data needs extra caution.
        score -= 0.05
        flags.append("NON_STRUCTURE_PAGE_CONTEXT")

    score = round(max(0.0, min(1.0, score)), 3)
    if exact_ocr and score >= 0.88 and evidence.model_agreement is not False and "AMBIGUOUS_SEMANTICS" not in flags:
        decision = "AUTO_ACCEPT"
    elif exact_ocr and score >= 0.58:
        decision = "REVIEW_DETAILS"
    else:
        decision = "MANUAL_REVIEW"

    # Stable ordering and no duplicate provider labels.
    deduped_sources = list(dict.fromkeys(x for x in sources if x))
    return EvidenceAssessment(score, decision, deduped_sources, flags, factors)


def apply_assessment(candidate: OcrCandidate | None, evidence: PageEvidence, *, imported_point_ids: Iterable[str]) -> EvidenceAssessment:
    assessment = assess_evidence(candidate, evidence, imported_point_ids=imported_point_ids)
    evidence.evidence_score = assessment.score
    evidence.evidence_decision = assessment.decision
    evidence.evidence_sources = assessment.sources
    evidence.validation_flags = assessment.flags
    return assessment
