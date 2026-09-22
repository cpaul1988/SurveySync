from __future__ import annotations

from collections import defaultdict
from typing import Iterable, List

from .models import DipStatus, EvidenceBasis, PageEvidence, PipeMeasurement, ResultRecord, StatusRule, SurveyPoint


def _pipe_key(pipe: PipeMeasurement) -> tuple:
    return (
        round(pipe.dip, 4) if pipe.dip is not None else None,
        (pipe.dip_raw or "").strip().casefold(),
        round(pipe.diameter_in, 4) if pipe.diameter_in is not None else None,
        (pipe.diameter_raw or "").strip().casefold(),
        (pipe.material or "").strip().casefold(),
        round(pipe.azimuth_deg, 4) if pipe.azimuth_deg is not None else None,
        (pipe.azimuth_raw or "").strip().casefold(),
        round(pipe.leader_direction_deg, 2) if pipe.leader_direction_deg is not None else None,
        (pipe.connected_point_raw or "").strip().casefold(),
    )


def _semantic_dip_status(evidences: list[PageEvidence], confidence_threshold: float) -> tuple[DipStatus, float, list[str]]:
    """Evaluate detailed dip outcomes independently of the primary PointID-found status.

    CNA (Could Not Access) and CNL (Could Not Locate) are first-class field-book
    outcomes. They are decisive only when the model/OCR evidence carries the matching
    explicit basis; conflicting decisive outcomes are routed to REVIEW.
    """
    decisive: dict[DipStatus, list[tuple[float, PageEvidence]]] = {
        DipStatus.YES: [],
        DipStatus.NO: [],
        DipStatus.CNA: [],
        DipStatus.CNL: [],
    }
    review: list[tuple[float, PageEvidence]] = []
    expected_basis = {
        DipStatus.YES: {EvidenceBasis.MEASUREMENT, EvidenceBasis.EXPLICIT_YES},
        DipStatus.NO: {EvidenceBasis.EXPLICIT_NO},
        DipStatus.CNA: {EvidenceBasis.EXPLICIT_CNA},
        DipStatus.CNL: {EvidenceBasis.EXPLICIT_CNL},
    }
    for ev in evidences:
        effective = min(ev.point_id_confidence, ev.dipped_confidence)
        allowed = expected_basis.get(ev.dipped, set())
        if ev.dipped in decisive and ev.basis in allowed and effective >= confidence_threshold:
            decisive[ev.dipped].append((effective, ev))
        else:
            review.append((effective, ev))

    present = [status for status, items in decisive.items() if items]
    notes: list[str] = []
    if len(present) > 1:
        status = DipStatus.REVIEW
        confidence = max([x[0] for items in decisive.values() for x in items] + [x[0] for x in review], default=0.0)
        labels = ", ".join(x.value for x in present)
        notes.append(f"Conflicting high-confidence dip outcomes were found across the field book: {labels}.")
    elif len(present) == 1:
        status = present[0]
        confidence = max(x[0] for x in decisive[status])
        if status == DipStatus.CNA:
            notes.append("Field-book dip status: CNA (Could Not Access).")
        elif status == DipStatus.CNL:
            notes.append("Field-book dip status: CNL (Could Not Locate).")
        if review:
            notes.append("Additional lower-confidence or ambiguous dip evidence is also present.")
    else:
        status = DipStatus.REVIEW
        confidence = max([min(ev.point_id_confidence, ev.dipped_confidence) for ev in evidences], default=0.0)
        notes.append("The PointID was found, but the detailed dipped interpretation needs review.")
    return status, confidence, notes



def apply_status_rule_to_existing(results: Iterable[ResultRecord], status_rule: StatusRule | str) -> None:
    """Re-map primary status without re-running OCR/AI.

    This is used when upgrading older projects or changing the Status Rule setting. Manual
    overrides are preserved. The legacy primary status is copied into dip_status when needed.
    """
    try:
        rule = status_rule if isinstance(status_rule, StatusRule) else StatusRule(str(status_rule))
    except Exception:
        rule = StatusRule.POINT_ID_FOUND
    for r in results:
        if r.manually_overridden:
            continue
        # Projects created before v6.3 stored the semantic dip decision in status.
        if r.dip_status == DipStatus.NOT_FOUND and r.evidence_records and r.status != DipStatus.NOT_FOUND:
            r.dip_status = r.status
        if r.evidence_records:
            r.qa_needs_review = (
                r.dip_status == DipStatus.REVIEW
                or any(e.model_agreement is False for e in r.evidence_records)
                or any((getattr(e, "evidence_decision", "") or "") not in {"", "AUTO_ACCEPT"} for e in r.evidence_records)
            )
            r.status = DipStatus.YES if rule == StatusRule.POINT_ID_FOUND else r.dip_status
        else:
            r.dip_status = DipStatus.NOT_FOUND
            r.qa_needs_review = False
            r.status = DipStatus.NO if rule == StatusRule.POINT_ID_FOUND else DipStatus.NOT_FOUND


def aggregate_results(
    survey_points: Iterable[SurveyPoint],
    evidence_records: Iterable[PageEvidence],
    confidence_threshold: float = 0.85,
    status_rule: StatusRule | str = StatusRule.POINT_ID_FOUND,
) -> List[ResultRecord]:
    """Aggregate field-book evidence into survey results.

    POINT_ID_FOUND (default): exact field-book PointID evidence produces primary Status=YES;
    no exact PointID evidence produces Status=NO. Detailed dip interpretation is retained in
    dip_status/qa_needs_review and can never suppress the basic YES/NO deliverable.

    CONFIRMED_DIP: preserves the advanced behavior where the primary status follows
    the semantic dip evidence and can be YES/NO/CNA/CNL/REVIEW/NOT_FOUND.
    """
    try:
        rule = status_rule if isinstance(status_rule, StatusRule) else StatusRule(str(status_rule))
    except Exception:
        rule = StatusRule.POINT_ID_FOUND

    by_point: dict[str, list[PageEvidence]] = defaultdict(list)
    for ev in evidence_records:
        by_point[ev.matched_point_id].append(ev)

    results: List[ResultRecord] = []
    for point in survey_points:
        evidences = by_point.get(point.point_id, [])
        if not evidences:
            primary = DipStatus.NO if rule == StatusRule.POINT_ID_FOUND else DipStatus.NOT_FOUND
            results.append(ResultRecord(
                point_id=point.point_id, northing=point.northing, easting=point.easting,
                elevation=point.elevation, code=point.code, category=point.category,
                status=primary, dip_status=DipStatus.NOT_FOUND, qa_needs_review=False,
                confidence=0.0, evidence_records=[], pipes=[],
                notes="No exact PointID match was found in the analyzed field-book pages.",
            ))
            continue

        dip_status, semantic_confidence, notes = _semantic_dip_status(evidences, confidence_threshold)
        point_confidence = max((ev.point_id_confidence for ev in evidences), default=0.0)
        model_conflict = any(ev.model_agreement is False for ev in evidences)
        evidence_review = any((getattr(ev, "evidence_decision", "") or "") not in {"", "AUTO_ACCEPT"} for ev in evidences)
        qa_needs_review = dip_status == DipStatus.REVIEW or model_conflict or evidence_review

        if rule == StatusRule.POINT_ID_FOUND:
            # Mission-critical workflow: an exact matched PointID entry means the structure was
            # visited/dipped. Semantic extraction remains advisory QA only.
            status = DipStatus.YES
            confidence = point_confidence
            if qa_needs_review:
                notes.insert(0, "PointID match sets primary Status=YES; detailed dip/pipe interpretation remains in QA review.")
        else:
            status = dip_status
            confidence = semantic_confidence

        # Preserve multiplicity within one evidence record while deduplicating repeat observations
        # across pages. The maximum same-signature multiplicity seen on any one entry wins.
        pipes: List[PipeMeasurement] = []
        max_count_by_key: dict[tuple, int] = {}
        for ev in evidences:
            local_counts: dict[tuple, int] = defaultdict(int)
            local_examples: dict[tuple, list[PipeMeasurement]] = defaultdict(list)
            for pipe in ev.pipes:
                key = _pipe_key(pipe)
                local_counts[key] += 1
                local_examples[key].append(pipe)
            for key, count in local_counts.items():
                previous_max = max_count_by_key.get(key, 0)
                if count <= previous_max:
                    continue
                pipes.extend(local_examples[key][previous_max:count])
                max_count_by_key[key] = count

        results.append(ResultRecord(
            point_id=point.point_id, northing=point.northing, easting=point.easting,
            elevation=point.elevation, code=point.code, category=point.category,
            status=status, dip_status=dip_status, qa_needs_review=qa_needs_review,
            confidence=confidence, evidence_records=evidences, pipes=pipes, notes=" ".join(notes),
        ))

    return results
