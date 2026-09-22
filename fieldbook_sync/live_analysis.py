from __future__ import annotations
from .api_models import (
    SettingsIn as SettingsIn,
    SelectProfileIn as SelectProfileIn,
    ProfileSaveIn as ProfileSaveIn,
    FieldNoteProfileSaveIn as FieldNoteProfileSaveIn,
    FieldNoteProfileSelectIn as FieldNoteProfileSelectIn,
    FieldBookProfileAssignmentIn as FieldBookProfileAssignmentIn,
    FieldNotePageOverrideIn as FieldNotePageOverrideIn,
    FieldNoteProfileDuplicateIn as FieldNoteProfileDuplicateIn,
    FieldNoteTrainingSaveIn as FieldNoteTrainingSaveIn,
    TeachCorrectionIn as TeachCorrectionIn,
    UpdateSourceIn as UpdateSourceIn,
    UpdateInstallIn as UpdateInstallIn,
    FeedbackOpenIn as FeedbackOpenIn,
    FeedbackRetryIn as FeedbackRetryIn,
    ResultEditIn as ResultEditIn,
    ProjectNameIn as ProjectNameIn,
    ProjectSaveAsIn as ProjectSaveAsIn,
    MapCrsIn as MapCrsIn,
    MapAlignmentIn as MapAlignmentIn,
    MapControlPairIn as MapControlPairIn,
    MapAlignmentSolveIn as MapAlignmentSolveIn,
    MapLayerSettingsIn as MapLayerSettingsIn,
    MapLayerOrderIn as MapLayerOrderIn,
    MapBookmarkIn as MapBookmarkIn,
    MapTransformIn as MapTransformIn,
    ManualEdgeIn as ManualEdgeIn,
    ValidationNameIn as ValidationNameIn,
    BatchAddIn as BatchAddIn,
    ArcGISMapsIn as ArcGISMapsIn,
    ArcGISExportIn as ArcGISExportIn,
    ImportJob as ImportJob,
)
from copy import deepcopy
import threading
from .aggregate import aggregate_results
from .ai_reader import ProviderUsage
from .intelligence import infer_network, refresh_result_intelligence
from .models import (
    DipStatus,
    EvidenceBasis,
    OcrCandidate,
    PageEvidence,
    ResultRecord,
    UnmatchedEvidence,
)


def _dedupe_unmatched(items):
    deduped = []
    seen = set()
    for item in items:
        key = (
            item.page_id,
            item.point_id_raw or "",
            round(float(item.confidence or 0), 3),
            item.reason,
            tuple(item.bbox or []),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _live_candidate_key(candidate: OcrCandidate) -> tuple:
    return (candidate.page_id, candidate.point_id, tuple(candidate.bbox or []))


def _live_pending_evidence(candidate: OcrCandidate) -> PageEvidence:
    "Represent an exact OCR hit while semantic interpretation is still pending."
    return PageEvidence(
        matched_point_id=candidate.point_id,
        source_name=candidate.source_name,
        page_number=candidate.page_number,
        page_id=candidate.page_id,
        point_id_raw=candidate.point_id,
        point_id_confidence=candidate.confidence,
        dipped=DipStatus.REVIEW,
        basis=EvidenceBasis.AMBIGUOUS,
        dipped_confidence=0.0,
        evidence="Exact PointID located by PaddleOCR-VL. Qwen interpretation is still pending.",
        bbox=candidate.bbox,
        notes="Live analysis preview; semantic interpretation pending.",
        primary_engine="PaddleOCR-VL 1.6",
        secondary_engine="Qwen pending",
        model_agreement=None,
        ocr_text=candidate.raw_text,
    )


def _sync_live_job_counts_locked() -> None:
    from . import app as context

    context.runtime.job.live_update_seq = context.runtime.live_update_seq
    context.runtime.job.live_candidate_count = len(context.runtime.live_candidates)
    context.runtime.job.live_interpreted_count = len(context.runtime.live_interpreted_ids)
    context.runtime.job.live_network_edge_count = len(context.runtime.live_network_edges)


def _schedule_live_network_rebuild_locked() -> None:
    from . import app as context

    "Coalesce live network updates; caller holds runtime.lock."
    if not context.runtime.live_active or context.runtime.live_network_rebuild_running:
        return
    timer = context.runtime.live_network_timer
    if timer is not None and timer.is_alive():
        return
    timer = threading.Timer(
        context.runtime.live_network_debounce_seconds, _run_live_network_rebuild
    )
    timer.daemon = True
    context.runtime.live_network_timer = timer
    timer.start()


def _run_live_network_rebuild() -> None:
    from . import app as context

    "Compute the expensive network snapshot without holding the global runtime lock."
    with context.runtime.lock:
        context.runtime.live_network_timer = None
        if not context.runtime.live_active:
            return
        context.runtime.live_network_rebuild_running = True
        revision = context.runtime.live_analysis_revision
        dirty_seq = context.runtime.live_network_dirty_seq
        results = deepcopy(context.runtime.live_results)
        max_distance = context.runtime.network_max_distance
        tolerance = context.runtime.network_bearing_tolerance
    try:
        edges = infer_network(
            results,
            max_distance=max_distance,
            max_bearing_error=tolerance,
            reciprocal_tolerance=tolerance,
        )
    except Exception:
        context.logger.exception("Live network rebuild failed; Review/Map analysis will continue.")
        with context.runtime.lock:
            context.runtime.live_network_rebuild_running = False
            if context.runtime.live_active and context.runtime.live_analysis_revision == revision:
                _schedule_live_network_rebuild_locked()
        return
    with context.runtime.lock:
        context.runtime.live_network_rebuild_running = False
        if not context.runtime.live_active or context.runtime.live_analysis_revision != revision:
            return
        if context.runtime.live_network_dirty_seq != dirty_seq:
            _schedule_live_network_rebuild_locked()
            return
        context.runtime.live_results = results
        context.runtime.live_network_edges = edges
        context.runtime.live_update_seq += 1
        _sync_live_job_counts_locked()


def _rebuild_live_analysis_locked() -> None:
    from . import app as context

    "Rebuild live Review/Map state and queue a throttled network refresh.\n\n    The O(N) aggregation/QC pass remains synchronous so Review updates promptly.\n    Network inference is intentionally moved outside ``runtime.lock`` and runs at\n    most about once per debounce interval, preventing large projects from blocking\n    job polling/cancellation after every OCR or interpretation event.\n    "
    if not context.runtime.live_active:
        return
    pending = [
        _live_pending_evidence(c)
        for c in context.runtime.live_candidates
        if _live_candidate_key(c) not in context.runtime.live_interpreted_candidate_keys
    ]
    evidence = list(context.runtime.live_interpreted_evidence) + pending
    context.runtime.live_results = aggregate_results(
        context.runtime.live_survey_points,
        evidence,
        confidence_threshold=context.runtime.confidence_threshold,
        status_rule=context.runtime.status_rule,
    )
    context.runtime.live_unmatched = _dedupe_unmatched(context.runtime.live_unmatched)
    refresh_result_intelligence(
        context.runtime.live_results,
        context.runtime.live_candidates,
        elevation_is_rim=context.runtime.elevation_is_rim,
    )
    context.runtime.live_network_dirty_seq += 1
    context.runtime.live_update_seq += 1
    _sync_live_job_counts_locked()
    _schedule_live_network_rebuild_locked()


def _begin_live_analysis_locked(survey_points: list, analysis_revision: int) -> None:
    from . import app as context

    context.runtime.live_active = True
    context.runtime.live_analysis_revision = analysis_revision
    context.runtime.live_survey_points = deepcopy(survey_points)
    context.runtime.live_candidates = []
    context.runtime.live_interpreted_evidence = []
    context.runtime.live_unmatched = []
    context.runtime.live_results = []
    context.runtime.live_network_edges = []
    context.runtime.live_interpreted_candidate_keys = set()
    context.runtime.live_interpreted_ids = set()
    context.runtime.live_network_dirty_seq = 0
    context.runtime.live_network_rebuild_running = False
    if context.runtime.live_network_timer is not None:
        context.runtime.live_network_timer.cancel()
        context.runtime.live_network_timer = None
    _rebuild_live_analysis_locked()


def _end_live_analysis_locked() -> None:
    from . import app as context

    context.runtime.live_active = False
    context.runtime.live_analysis_revision = -1
    context.runtime.live_survey_points = []
    context.runtime.live_candidates = []
    context.runtime.live_interpreted_evidence = []
    context.runtime.live_unmatched = []
    context.runtime.live_results = []
    context.runtime.live_network_edges = []
    context.runtime.live_interpreted_candidate_keys = set()
    context.runtime.live_interpreted_ids = set()
    context.runtime.live_network_dirty_seq = 0
    context.runtime.live_network_rebuild_running = False
    if context.runtime.live_network_timer is not None:
        context.runtime.live_network_timer.cancel()
        context.runtime.live_network_timer = None


def _publish_live_candidates(candidates: list[OcrCandidate], analysis_revision: int) -> None:
    from . import app as context

    if not candidates:
        return
    with context.runtime.lock:
        if (
            not context.runtime.live_active
            or context.runtime.live_analysis_revision != analysis_revision
        ):
            return
        seen = {_live_candidate_key(c) for c in context.runtime.live_candidates}
        changed = False
        for candidate in candidates:
            key = _live_candidate_key(candidate)
            if key not in seen:
                context.runtime.live_candidates.append(deepcopy(candidate))
                seen.add(key)
                changed = True
        if changed:
            _rebuild_live_analysis_locked()


def _publish_live_interpretation(
    candidate: OcrCandidate | None,
    evidence: list[PageEvidence],
    unmatched: list[UnmatchedEvidence],
    analysis_revision: int,
) -> None:
    from . import app as context

    with context.runtime.lock:
        if (
            not context.runtime.live_active
            or context.runtime.live_analysis_revision != analysis_revision
        ):
            return
        if candidate is not None:
            context.runtime.live_interpreted_candidate_keys.add(_live_candidate_key(candidate))
            context.runtime.live_interpreted_ids.add(candidate.point_id)
        for ev in evidence:
            context.runtime.live_interpreted_evidence.append(deepcopy(ev))
            context.runtime.live_interpreted_ids.add(ev.matched_point_id)
        context.runtime.live_unmatched.extend(deepcopy(unmatched))
        _rebuild_live_analysis_locked()


def _live_point_state_locked(point_id: str) -> str:
    from . import app as context

    if point_id in context.runtime.live_interpreted_ids:
        return "INTERPRETED"
    if any((c.point_id == point_id for c in context.runtime.live_candidates)):
        return "OCR_FOUND"
    return "PENDING_OCR"


def _live_result_dict_locked(result: ResultRecord) -> dict:
    data = result.model_dump(mode="json")
    data["live_state"] = _live_point_state_locked(result.point_id)
    data["live_preview"] = True
    return data


def _record_usage_locked(provider: str, usage: ProviderUsage) -> None:
    from . import app as context

    context.runtime.job.api_requests += usage.requests
    context.runtime.job.input_tokens += usage.input_tokens
    context.runtime.job.output_tokens += usage.output_tokens
    context.runtime.job.total_tokens += usage.total_tokens
    if provider in context.runtime.session_requests:
        context.runtime.session_requests[provider] += usage.requests
