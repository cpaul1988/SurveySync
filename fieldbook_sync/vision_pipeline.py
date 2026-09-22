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
import hashlib
import re
import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import threading
from pathlib import Path
from typing import Any
from .ai_reader import (
    ProviderUsage,
    read_page_openai,
    read_page_anthropic,
    read_pages_gemini,
    read_pages_ollama,
    read_pages_foundry,
)
from .image_processing import crop_normalized_bbox
from .ocr_local import PaddleCancelled, compare_ocr_to_evidence, locate_target_ids, paddle_status
from .models import (
    DipStatus,
    EvidenceBasis,
    FieldBookPage,
    OcrCandidate,
    PageEvidence,
    UnmatchedEvidence,
)
from .performance import build_performance_plan
from .interpret_cache import (
    interpretation_cache_key,
    load_interpretation_cache,
    save_interpretation_cache,
)
from .errors import classify_exception
from .evidence_pipeline import (
    apply_assessment,
    classify_page_text,
    paddle_payload_text,
    windows_payload_text,
    windows_anchor_can_skip_paddle,
)
from surveysync.ai_runtime import DEFAULT_FOUNDRY_VISION_MODEL, get_local_ai_status, windows_ocr


def _direct_vision_analysis(
    *,
    provider: str,
    pages: list[FieldBookPage],
    targets: list[str],
    api_key: str,
    model: str,
    batch_pages: int,
    local_base_url: str,
    analysis_revision: int,
    request_offset: int = 0,
) -> tuple[list[PageEvidence], list[UnmatchedEvidence]]:
    from . import app as context

    "Run direct page analysis for local/cloud vision providers."
    all_evidence: list[PageEvidence] = []
    all_unmatched: list[UnmatchedEvidence] = []
    target_chunks = [targets[i : i + 220] for i in range(0, len(targets), 220)]
    request_index = max(0, int(request_offset or 0))

    def _isolate_failed_pages(
        failed_pages: list[FieldBookPage], exc: Exception, component: str
    ) -> None:
        info = classify_exception(exc, component=component)
        if context.runtime.current_job_id:
            for failed_page in failed_pages:
                context.runtime.job_store.mark_page(
                    context.runtime.current_job_id,
                    failed_page.page_id,
                    status="FAILED",
                    stage=f"{component}_failed",
                    error_code=info.code,
                    error_message=info.user_message,
                )
        with context.runtime.lock:
            context.runtime.job.failed_page_count += len(failed_pages)
            context.runtime.job.warning_count += 1
            context.runtime.job.resumable = True
            context._touch_worker_locked(
                f"{component.title()} failed for {len(failed_pages)} page(s) after retries; continuing with remaining work."
            )

    if provider in {"ollama", "gemini"}:
        page_batches = [pages[i : i + batch_pages] for i in range(0, len(pages), batch_pages)]
        local_requests = len(page_batches) * len(target_chunks)
        total_requests = request_index + local_requests
        with context.runtime.lock:
            context.runtime.job.total_requests = max(
                context.runtime.job.total_requests, total_requests
            )
        for batch_index, batch in enumerate(page_batches, start=1):
            for chunk_index, target_chunk in enumerate(target_chunks, start=1):
                if not context._check_worker_revision(
                    analysis_revision,
                    "Analysis stopped because project data changed. Stale results were not committed.",
                ):
                    return ([], [])
                if not context._analysis_pause_checkpoint(
                    analysis_revision, "between vision requests"
                ):
                    return ([], [])
                request_index += 1
                with context.runtime.lock:
                    context.runtime.job.current_request = request_index
                    context.runtime.job.current_page = min(
                        len(pages), (batch_index - 1) * batch_pages + len(batch)
                    )
                    context.runtime.job.stage = "interpret"
                    engine_label = "Qwen Local" if provider == "ollama" else "Gemini"
                    context.runtime.job.message = (
                        f"{engine_label}: request {request_index}/{total_requests}"
                    )
                    context._touch_worker_locked()
                try:
                    if provider == "ollama":
                        analysis_batch = []
                        for source_page in batch:
                            qpage = deepcopy(source_page)
                            if (
                                source_page.enhanced_image_path
                                and Path(source_page.enhanced_image_path).exists()
                            ):
                                qpage.image_path = source_page.enhanced_image_path
                                qpage.mime_type = "image/jpeg"
                            analysis_batch.append(qpage)
                        evidence, unmatched, usage = context._retry_operation(
                            lambda: read_pages_ollama(
                                pages=analysis_batch,
                                target_point_ids=target_chunk,
                                model=model,
                                base_url=local_base_url,
                                timeout_seconds=900
                                if model == context.MAX_ACCURACY_OLLAMA_MODEL
                                else 300,
                                progress_callback=context._qwen_progress,
                                profile_context=context._field_note_profile_context(),
                            ),
                            component="qwen",
                            attempts=3,
                            page=batch[0] if batch else None,
                        )
                        for ev in evidence:
                            ev.primary_engine = f"Qwen / Ollama ({model})"
                    else:
                        evidence, unmatched, usage = context._retry_operation(
                            lambda: read_pages_gemini(
                                pages=batch,
                                target_point_ids=target_chunk,
                                api_key=api_key,
                                model=model,
                                profile_context=context._field_note_profile_context(),
                            ),
                            component="gemini",
                            attempts=2,
                            page=batch[0] if batch else None,
                        )
                        for ev in evidence:
                            ev.primary_engine = f"Gemini ({model})"
                except Exception as exc:
                    _isolate_failed_pages(batch, exc, "qwen" if provider == "ollama" else "gemini")
                    continue
                all_evidence.extend(evidence)
                all_unmatched.extend(unmatched)
                context._publish_live_interpretation(None, evidence, unmatched, analysis_revision)
                with context.runtime.lock:
                    context._record_usage_locked(provider, usage)
                    context._touch_worker_locked()
                if context.runtime.current_job_id:
                    for completed_page in batch:
                        context.runtime.job_store.mark_page(
                            context.runtime.current_job_id,
                            completed_page.page_id,
                            status="COMPLETE",
                            stage="interpret_complete",
                        )
    else:
        local_requests = len(pages) * len(target_chunks)
        total_requests = request_index + local_requests
        with context.runtime.lock:
            context.runtime.job.total_requests = max(
                context.runtime.job.total_requests, total_requests
            )
        for page_index, page in enumerate(pages, start=1):
            for target_chunk in target_chunks:
                if not context._check_worker_revision(
                    analysis_revision,
                    "Analysis stopped because project data changed. Stale results were not committed.",
                ):
                    return ([], [])
                if not context._analysis_pause_checkpoint(
                    analysis_revision, "between vision requests"
                ):
                    return ([], [])
                request_index += 1
                cloud_name = "Anthropic Claude" if provider == "anthropic" else "OpenAI"
                component = "anthropic" if provider == "anthropic" else "openai"
                with context.runtime.lock:
                    context.runtime.job.current_request = request_index
                    context.runtime.job.current_page = page_index
                    context.runtime.job.stage = "interpret"
                    context.runtime.job.message = (
                        f"{cloud_name}: request {request_index}/{total_requests}"
                    )
                    context._touch_worker_locked()
                try:
                    if provider == "anthropic":
                        evidence, unmatched, usage = context._retry_operation(
                            lambda: read_page_anthropic(
                                image_path=page.image_path,
                                mime_type=page.mime_type,
                                source_name=page.source_name,
                                page_number=page.page_number,
                                page_id=page.page_id,
                                target_point_ids=target_chunk,
                                api_key=api_key,
                                model=model,
                                profile_context=context._field_note_profile_context(),
                                field_note_profile_override=context._effective_page_profile_id(
                                    page
                                ),
                            ),
                            component=component,
                            attempts=2,
                            page=page,
                        )
                    else:
                        evidence, unmatched, usage = context._retry_operation(
                            lambda: read_page_openai(
                                image_path=page.image_path,
                                mime_type=page.mime_type,
                                source_name=page.source_name,
                                page_number=page.page_number,
                                page_id=page.page_id,
                                target_point_ids=target_chunk,
                                api_key=api_key,
                                model=model,
                                profile_context=context._field_note_profile_context(),
                                field_note_profile_override=context._effective_page_profile_id(
                                    page
                                ),
                            ),
                            component=component,
                            attempts=2,
                            page=page,
                        )
                except Exception as exc:
                    _isolate_failed_pages([page], exc, component)
                    continue
                for ev in evidence:
                    ev.primary_engine = f"{cloud_name} ({model})"
                all_evidence.extend(evidence)
                all_unmatched.extend(unmatched)
                context._publish_live_interpretation(None, evidence, unmatched, analysis_revision)
                with context.runtime.lock:
                    context._record_usage_locked(provider, usage)
                    context._touch_worker_locked()
                if context.runtime.current_job_id:
                    context.runtime.job_store.mark_page(
                        context.runtime.current_job_id,
                        page.page_id,
                        status="COMPLETE",
                        stage="interpret_complete",
                    )
    return (all_evidence, all_unmatched)


def _windows_ocr_candidates_from_payload(
    page: FieldBookPage, payload: dict[str, Any], targets: list[str]
) -> list[OcrCandidate]:
    "Convert Windows AI OCR lines into exact PointID candidates only.\n\n    Windows OCR is intentionally used as independent evidence, not as a fuzzy matcher.\n    A target is accepted only when the normalized token read from the page exactly equals\n    a survey PointID.  This prevents the AI target list from manufacturing a found ID.\n"
    target_map = {str(t).strip().casefold(): str(t).strip() for t in targets if str(t).strip()}
    if not target_map:
        return []
    width = max(0, int(payload.get("width") or 0))
    height = max(0, int(payload.get("height") or 0))
    out: list[OcrCandidate] = []
    seen: set[tuple[str, str, int]] = set()
    token_re = re.compile("(?<![A-Za-z0-9])([A-Za-z0-9][A-Za-z0-9._-]*)(?![A-Za-z0-9])")
    for line_index, line in enumerate(payload.get("lines") or []):
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        tokens = [m.group(1) for m in token_re.finditer(text)]
        matches = []
        for token in tokens:
            target = target_map.get(token.casefold())
            if target:
                matches.append(target)
        if not matches:
            continue
        bbox = None
        polygon = line.get("polygon") or []
        if width > 0 and height > 0 and polygon:
            try:
                xs = [float(pt[0]) for pt in polygon]
                ys = [float(pt[1]) for pt in polygon]
                if xs and ys:
                    bbox = [
                        max(0, min(1000, int(round(min(xs) / width * 1000)))),
                        max(0, min(1000, int(round(min(ys) / height * 1000)))),
                        max(0, min(1000, int(round(max(xs) / width * 1000)))),
                        max(0, min(1000, int(round(max(ys) / height * 1000)))),
                    ]
            except Exception:
                bbox = None
        confidence = max(0.0, min(1.0, float(line.get("confidence") or 0.0)))
        for target in dict.fromkeys(matches):
            key = (page.page_id, target, line_index)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                OcrCandidate(
                    page_id=page.page_id,
                    source_name=page.source_name,
                    page_number=page.page_number,
                    point_id=target,
                    raw_text=text,
                    confidence=confidence,
                    bbox=bbox,
                    engine="windows-ai-ocr",
                    exact_match=True,
                )
            )
    return out


def _windows_local_analysis(
    *,
    pages: list[FieldBookPage],
    targets: list[str],
    vision_provider: str,
    model: str,
    local_base_url: str,
    analysis_revision: int,
) -> tuple[list[PageEvidence], list[UnmatchedEvidence], list[OcrCandidate]]:
    from . import app as context

    "Windows AI OCR locator with optional local semantic interpretation.\n\n    PointID authority always comes from exact Windows OCR.  Foundry/Ollama may interpret\n    the crop associated with that exact hit, but can never create a new found PointID.\n    "
    all_evidence: list[PageEvidence] = []
    all_unmatched: list[UnmatchedEvidence] = []
    candidates: list[OcrCandidate] = []
    seen: set[tuple] = set()
    page_by_id = {p.page_id: p for p in pages}
    crop_dir = context.runtime.interpretation_crop_dir / "windows_ai"
    crop_dir.mkdir(parents=True, exist_ok=True)
    with context.runtime.lock:
        context.runtime.job.stage = "ocr"
        context.runtime.job.message = (
            f"Windows AI OCR: locating exact PointIDs on {len(pages)} page(s)…"
        )
        context.runtime.job.current_page = 0
        context.runtime.job.total_pages = len(pages)
    for idx, page in enumerate(pages, start=1):
        if not context._check_worker_revision(
            analysis_revision, "Analysis stopped during Windows OCR because project data changed."
        ):
            return ([], [], [])
        if not context._analysis_pause_checkpoint(analysis_revision, "between Windows OCR pages"):
            return ([], [], [])
        image_path = (
            page.enhanced_image_path
            if page.enhanced_image_path and Path(page.enhanced_image_path).exists()
            else page.image_path
        )
        try:
            payload = windows_ocr(image_path)
        except Exception as exc:
            info = classify_exception(exc, component="windows_ai_ocr")
            if context.runtime.current_job_id:
                context.runtime.job_store.mark_page(
                    context.runtime.current_job_id,
                    page.page_id,
                    status="FAILED",
                    stage="windows_ocr_failed",
                    error_code=info.code,
                    error_message=info.user_message,
                )
            with context.runtime.lock:
                context.runtime.job.failed_page_count += 1
                context.runtime.job.warning_count += 1
                context.runtime.job.resumable = True
                context.runtime.job.current_page = idx
                context.runtime.job.message = (
                    f"Windows AI OCR could not read page {idx}; continuing safely."
                )
                context._touch_worker_locked()
            continue
        classification = classify_page_text(windows_payload_text(payload))
        page.page_type = classification.page_type
        page.page_type_confidence = classification.confidence
        page.page_type_reason = classification.reason
        page_candidates = _windows_ocr_candidates_from_payload(page, payload, targets)
        fresh: list[OcrCandidate] = []
        for cand in page_candidates:
            key = context._live_candidate_key(cand)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(cand)
            fresh.append(cand)
        if fresh:
            context._publish_live_candidates(fresh, analysis_revision)
        if context.runtime.current_job_id:
            context.runtime.job_store.mark_page(
                context.runtime.current_job_id,
                page.page_id,
                status="COMPLETE",
                stage="windows_ocr_complete",
            )
        with context.runtime.lock:
            context.runtime.job.current_page = idx
            context.runtime.job.message = (
                f"Windows AI OCR: page {idx}/{len(pages)} · {len(candidates)} exact PointID hit(s)"
            )
            context._touch_worker_locked()
    total = len(candidates)
    with context.runtime.lock:
        context.runtime.job.total_requests = (
            total if vision_provider in {"foundry", "ollama"} else 0
        )
        context.runtime.job.current_request = 0
        context.runtime.job.stage = "interpret" if total else "aggregate"
    for index, cand in enumerate(candidates, start=1):
        if not context._check_worker_revision(
            analysis_revision,
            "Analysis stopped during local interpretation because project data changed.",
        ):
            return ([], [], [])
        original = page_by_id.get(cand.page_id)
        if original is None:
            continue
        candidate_evidence: list[PageEvidence] = []
        local_unmatched: list[UnmatchedEvidence] = []
        usage = ProviderUsage()
        if vision_provider in {"foundry", "ollama"}:
            src = (
                original.enhanced_image_path
                if original.enhanced_image_path and Path(original.enhanced_image_path).exists()
                else original.image_path
            )
            token = hashlib.sha1(
                json.dumps(
                    {"page": cand.page_id, "point": cand.point_id, "bbox": cand.bbox or []},
                    sort_keys=True,
                ).encode()
            ).hexdigest()[:14]
            crop_path = crop_dir / f"{cand.page_id}_{cand.point_id}_{token}.jpg"
            cropped = (
                crop_path
                if crop_path.exists()
                else crop_normalized_bbox(src, cand.bbox, crop_path, padding=0.3)
                if cand.bbox
                else None
            )
            crop_page = FieldBookPage(
                page_id=original.page_id,
                source_name=original.source_name,
                page_number=original.page_number,
                image_path=str(cropped or src),
                mime_type="image/jpeg" if cropped else original.mime_type,
                page_type=original.page_type,
                page_type_confidence=original.page_type_confidence,
                page_type_reason=original.page_type_reason,
                field_note_profile_override=context._effective_page_profile_id(original),
            )
            try:
                if vision_provider == "foundry":
                    evidence, local_unmatched, usage = read_pages_foundry(
                        pages=[crop_page],
                        target_point_ids=[cand.point_id],
                        model=DEFAULT_FOUNDRY_VISION_MODEL,
                        profile_context=context._field_note_profile_context(),
                    )
                    engine_name = f"Microsoft Foundry Local ({DEFAULT_FOUNDRY_VISION_MODEL})"
                    usage_key = "foundry"
                else:
                    evidence, local_unmatched, usage = read_pages_ollama(
                        pages=[crop_page],
                        target_point_ids=[cand.point_id],
                        model=model,
                        base_url=local_base_url,
                        timeout_seconds=900 if model == context.MAX_ACCURACY_OLLAMA_MODEL else 300,
                        progress_callback=context._qwen_progress,
                        profile_context=context._field_note_profile_context(),
                    )
                    engine_name = f"Qwen / Ollama ({model})"
                    usage_key = "ollama"
                with context.runtime.lock:
                    context._record_usage_locked(usage_key, usage)
                for ev in evidence:
                    if ev.matched_point_id != cand.point_id:
                        local_unmatched.append(
                            UnmatchedEvidence(
                                source_name=ev.source_name,
                                page_number=ev.page_number,
                                page_id=ev.page_id,
                                point_id_raw=ev.point_id_raw or ev.matched_point_id,
                                confidence=ev.point_id_confidence,
                                reason="Local vision returned a PointID that did not match the independent Windows OCR target.",
                                bbox=ev.bbox,
                            )
                        )
                        continue
                    ev.bbox = cand.bbox or ev.bbox
                    ev.ocr_text = cand.raw_text
                    ev.primary_engine = engine_name
                    ev.secondary_engine = "Windows AI TextRecognizer"
                    ev.page_type = original.page_type
                    ev.page_type_confidence = original.page_type_confidence
                    agreement, comparison = compare_ocr_to_evidence(cand.raw_text, ev)
                    ev.model_agreement = agreement
                    if agreement is False:
                        ev.dipped = DipStatus.REVIEW
                        ev.basis = EvidenceBasis.AMBIGUOUS
                        ev.notes = (
                            (ev.notes or "") + " Cross-model disagreement. " + comparison
                        ).strip()
                    apply_assessment(cand, ev, imported_point_ids=targets)
                    candidate_evidence.append(ev)
            except Exception as exc:
                code, message, _ = context._record_job_error(
                    exc, component=vision_provider, page=original, retry_number=1
                )
                with context.runtime.lock:
                    context.runtime.job.warning_count += 1
                    context.runtime.job.resumable = True
                    context.runtime.job.message = f"Local vision could not interpret Point {cand.point_id}; exact OCR hit retained for review."
                    context._touch_worker_locked()
                if context.runtime.current_job_id:
                    context.runtime.job_store.mark_page(
                        context.runtime.current_job_id,
                        cand.page_id,
                        status="FAILED",
                        stage=f"{vision_provider}_failed",
                        error_code=code,
                        error_message=message,
                    )
        if not candidate_evidence:
            candidate_evidence.append(
                PageEvidence(
                    matched_point_id=cand.point_id,
                    source_name=cand.source_name,
                    page_number=cand.page_number,
                    page_id=cand.page_id,
                    point_id_raw=cand.point_id,
                    point_id_confidence=cand.confidence,
                    dipped=DipStatus.REVIEW,
                    basis=EvidenceBasis.AMBIGUOUS,
                    dipped_confidence=0.45 if vision_provider != "manual" else 0.0,
                    evidence="Windows AI OCR found the exact PointID, but local vision did not return a confident structured interpretation."
                    if vision_provider != "manual"
                    else "Windows AI OCR found the exact PointID. Semantic interpretation is left for manual review.",
                    bbox=cand.bbox,
                    notes="Independent exact Windows OCR hit; review pipe/dip details before acceptance.",
                    primary_engine="Windows AI TextRecognizer"
                    if vision_provider == "manual"
                    else "Microsoft Foundry Local"
                    if vision_provider == "foundry"
                    else f"Qwen / Ollama ({model})",
                    secondary_engine="Windows AI TextRecognizer"
                    if vision_provider != "manual"
                    else None,
                    model_agreement=None,
                    ocr_text=cand.raw_text,
                    page_type=original.page_type,
                    page_type_confidence=original.page_type_confidence,
                )
            )
            apply_assessment(cand, candidate_evidence[-1], imported_point_ids=targets)
        all_evidence.extend(candidate_evidence)
        all_unmatched.extend(local_unmatched)
        context._publish_live_interpretation(
            cand, candidate_evidence, local_unmatched, analysis_revision
        )
        with context.runtime.lock:
            if vision_provider in {"foundry", "ollama"}:
                context.runtime.job.current_request = context.index
                context.runtime.job.message = (
                    f"Local interpretation: Point {cand.point_id} ({context.index}/{total})"
                )
            context._touch_worker_locked()
    return (all_evidence, context._dedupe_unmatched(all_unmatched), candidates)


def _hybrid_local_analysis(
    *,
    pages: list[FieldBookPage],
    targets: list[str],
    model: str,
    local_base_url: str,
    batch_pages: int,
    analysis_revision: int,
) -> tuple[list[PageEvidence], list[UnmatchedEvidence], list[OcrCandidate]]:
    from . import app as context

    "Accuracy-first Paddle locator -> targeted Qwen interpretation -> full fallback.\n\n    v8.0.9 adds four speed paths without silently weakening the survey result:\n    * Paddle HPI/GPU is used when the isolated runtime supports it.\n    * Qwen crop interpretations are content-addressed and reused on unchanged pages.\n    * On capable hardware, CPU Paddle may overlap with a single Qwen/Ollama worker.\n    * A one-character Paddle near-match can route Qwen to a likely crop, but is never\n      accepted as a PointID unless Qwen visually confirms the exact target.  If it does\n      not, the original full-page fallback still runs.\n    "
    app_root = context.APP_ROOT
    pstat = paddle_status(app_root)
    if not pstat.installed:
        with context.runtime.lock:
            context.runtime.job.stage = "interpret"
            context.runtime.job.message = (
                "PaddleOCR-VL is not installed; falling back to full-page Qwen Local analysis."
            )
        evidence, unmatched = _direct_vision_analysis(
            provider="ollama",
            pages=pages,
            targets=targets,
            api_key="",
            model=model,
            batch_pages=batch_pages,
            local_base_url=local_base_url,
            analysis_revision=analysis_revision,
        )
        return (evidence, unmatched, [])
    plan = build_performance_plan(
        context.runtime.performance_mode, context.runtime.hardware_profile
    )
    pipeline_overlap = bool(plan.pipeline_overlap and pstat.device == "cpu")
    if not context._check_worker_revision(
        analysis_revision, "Analysis stopped before OCR because project data changed."
    ):
        return ([], [], [])
    with context.runtime.lock:
        context.runtime.job.stage = "ocr"
        context.runtime.job.message = (
            f"PaddleOCR-VL 1.6: locating target PointIDs on {len(pages)} page(s)…"
        )
        context.runtime.job.current_page = 0
        context.runtime.job.paddle_device = pstat.device
        context.runtime.job.ocr_cache_hits = 0
        context.runtime.job.interpretation_cache_hits = 0

    def _ocr_progress(done: int, total: int, message: str) -> None:
        with context.runtime.lock:
            if context.runtime.project_revision == analysis_revision and (
                not context.runtime.cancel_event.is_set()
            ):
                context.runtime.job.current_page = max(0, min(done, total))
                context.runtime.job.total_pages = total
                context.runtime.job.message = message
                m = re.search(
                    "(?:restored\\s+)?(\\d+)(?:/\\d+)?\\s*(?:page\\(s\\)\\s*)?(?:from OCR cache|cached)",
                    message,
                    flags=re.I,
                )
                if m:
                    context.runtime.job.ocr_cache_hits = max(
                        context.runtime.job.ocr_cache_hits, int(m.group(1))
                    )
                context._touch_worker_locked()

    def _ocr_should_stop() -> bool:
        if context.runtime.pause_event.is_set() and (
            not context._analysis_pause_checkpoint(analysis_revision, "between OCR pages")
        ):
            return True
        with context.runtime.lock:
            return (
                context.runtime.cancel_event.is_set()
                or context.runtime.project_revision != analysis_revision
            )

    page_by_id = {p.page_id: p for p in pages}
    candidates: list[OcrCandidate] = []
    candidate_seen: set[tuple] = set()
    confirmed_fuzzy_keys: set[tuple] = set()
    scheduled_keys: set[tuple] = set()
    all_evidence: list[PageEvidence] = []
    all_unmatched: list[UnmatchedEvidence] = []
    collections_lock = threading.RLock()
    counters_lock = threading.RLock()
    interpreted_scheduled = 0
    interpreted_completed = 0
    crop_dir = context.runtime.interpretation_crop_dir
    crop_dir.mkdir(parents=True, exist_ok=True)

    def _candidate_crop(cand: OcrCandidate) -> tuple[FieldBookPage, str]:
        original = page_by_id.get(cand.page_id)
        if not original:
            raise RuntimeError(f"Field-book page {cand.page_id} is no longer available.")
        src = (
            original.enhanced_image_path
            if original.enhanced_image_path and Path(original.enhanced_image_path).exists()
            else original.image_path
        )
        crop_token = hashlib.sha1(
            json.dumps(
                {"page": cand.page_id, "point": cand.point_id, "bbox": cand.bbox or []},
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:14]
        crop_path = crop_dir / f"{cand.page_id}_{cand.point_id}_{crop_token}.jpg"
        cropped = (
            crop_path
            if crop_path.exists()
            else crop_normalized_bbox(src, cand.bbox, crop_path, padding=0.28)
            if cand.bbox
            else None
        )
        image_path = str(cropped or src)
        return (
            FieldBookPage(
                page_id=original.page_id,
                source_name=original.source_name,
                page_number=original.page_number,
                image_path=image_path,
                mime_type="image/jpeg" if cropped else original.mime_type,
                page_type=original.page_type,
                page_type_confidence=original.page_type_confidence,
                page_type_reason=original.page_type_reason,
                field_note_profile_override=context._effective_page_profile_id(original),
            ),
            image_path,
        )

    def _interpret_candidate(cand: OcrCandidate) -> bool:
        """Interpret one Paddle crop. Returns True only if Qwen confirms the target."""
        nonlocal interpreted_completed
        if not context._check_worker_revision(
            analysis_revision,
            "Analysis stopped during local interpretation because project data changed.",
        ):
            return False
        crop_page, image_path = _candidate_crop(cand)
        cache_key = interpretation_cache_key(image_path, point_id=cand.point_id, model=model)
        cached = (
            load_interpretation_cache(context.runtime.interpretation_cache_dir, cache_key)
            if plan.interpretation_cache_enabled
            else None
        )
        cache_hit = cached is not None
        if cached:
            evidence, unmatched, _cached_usage = cached
            usage = ProviderUsage()
            with context.runtime.lock:
                context.runtime.job.interpretation_cache_hits += 1
        else:
            try:
                evidence, unmatched, usage = context._retry_operation(
                    lambda: read_pages_ollama(
                        pages=[crop_page],
                        target_point_ids=[cand.point_id],
                        model=model,
                        base_url=local_base_url,
                        timeout_seconds=900 if model == context.MAX_ACCURACY_OLLAMA_MODEL else 300,
                        progress_callback=context._qwen_progress,
                        profile_context=context._field_note_profile_context(),
                    ),
                    component="qwen",
                    attempts=3,
                    page=page_by_id.get(cand.page_id),
                )
            except Exception as exc:
                code, message, _ = context._record_job_error(
                    exc, component="qwen", page=page_by_id.get(cand.page_id), retry_number=3
                )
                evidence, unmatched, usage = ([], [], ProviderUsage())
                with context.runtime.lock:
                    context.runtime.job.warning_count += 1
                    context.runtime.job.resumable = True
                    context._touch_worker_locked(
                        f"Qwen could not interpret Point {cand.point_id}; marked for review and continuing."
                    )
                if context.runtime.current_job_id and page_by_id.get(cand.page_id):
                    context.runtime.job_store.mark_page(
                        context.runtime.current_job_id,
                        cand.page_id,
                        status="FAILED",
                        stage="qwen_failed",
                        error_code=code,
                        error_message=message,
                    )
            if plan.interpretation_cache_enabled and evidence:
                try:
                    save_interpretation_cache(
                        context.runtime.interpretation_cache_dir,
                        cache_key,
                        evidence,
                        unmatched,
                        usage,
                    )
                except OSError:
                    pass
            with context.runtime.lock:
                context._record_usage_locked("ollama", usage)
        matched = False
        candidate_evidence: list[PageEvidence] = []
        for ev in evidence:
            if ev.matched_point_id != cand.point_id:
                continue
            matched = True
            ev.bbox = cand.bbox or ev.bbox
            ev.ocr_text = cand.raw_text
            ev.primary_engine = f"Qwen / Ollama ({model})" + (" [cache]" if cache_hit else "")
            ev.secondary_engine = cand.engine or "Independent OCR"
            source_page = page_by_id.get(cand.page_id)
            if source_page is not None:
                ev.page_type = source_page.page_type
                ev.page_type_confidence = source_page.page_type_confidence
            agreement, comparison = compare_ocr_to_evidence(cand.raw_text, ev)
            ev.model_agreement = agreement
            if agreement is False:
                ev.dipped = DipStatus.REVIEW
                ev.basis = EvidenceBasis.AMBIGUOUS
                ev.notes = ((ev.notes or "") + " Cross-model disagreement. " + comparison).strip()
            elif agreement is True:
                ev.notes = (
                    (ev.notes or "") + " Independent local extraction agrees. " + comparison
                ).strip()
            assessment = apply_assessment(cand, ev, imported_point_ids=targets)
            if assessment.decision != "AUTO_ACCEPT":
                ev.notes = (
                    (ev.notes or "")
                    + f" Evidence-first decision: {assessment.decision} ({assessment.score:.0%})."
                ).strip()
            candidate_evidence.append(ev)
        local_unmatched = list(unmatched)
        if not matched and cand.exact_match:
            fallback_ev = PageEvidence(
                matched_point_id=cand.point_id,
                source_name=cand.source_name,
                page_number=cand.page_number,
                page_id=cand.page_id,
                point_id_raw=cand.point_id,
                point_id_confidence=cand.confidence,
                dipped=DipStatus.REVIEW,
                basis=EvidenceBasis.AMBIGUOUS,
                dipped_confidence=0.45,
                evidence="PaddleOCR-VL found the exact PointID, but Qwen did not return a confident structured interpretation.",
                bbox=cand.bbox,
                notes="Cross-model disagreement; human review required.",
                primary_engine=f"Qwen / Ollama ({model})",
                secondary_engine=cand.engine or "Independent OCR",
                model_agreement=False,
                ocr_text=cand.raw_text,
                page_type=page_by_id.get(cand.page_id).page_type
                if page_by_id.get(cand.page_id)
                else "unknown",
                page_type_confidence=page_by_id.get(cand.page_id).page_type_confidence
                if page_by_id.get(cand.page_id)
                else 0.0,
            )
            apply_assessment(cand, fallback_ev, imported_point_ids=targets)
            candidate_evidence.append(fallback_ev)
        elif not matched and (not cand.exact_match):
            local_unmatched.append(
                UnmatchedEvidence(
                    source_name=cand.source_name,
                    page_number=cand.page_number,
                    page_id=cand.page_id,
                    point_id_raw=cand.raw_text[:120],
                    confidence=cand.confidence,
                    reason=f"Paddle near-match suggested PointID {cand.point_id}, but Qwen did not visually confirm the exact ID.",
                    bbox=cand.bbox,
                )
            )
        with collections_lock:
            all_evidence.extend(candidate_evidence)
            all_unmatched.extend(local_unmatched)
            if matched and (not cand.exact_match):
                confirmed_fuzzy_keys.add(context._live_candidate_key(cand))
        if matched and (not cand.exact_match):
            context._publish_live_candidates([cand], analysis_revision)
        if candidate_evidence:
            context._publish_live_interpretation(
                cand, candidate_evidence, local_unmatched, analysis_revision
            )
        with counters_lock:
            interpreted_completed += 1
            done = interpreted_completed
            total = interpreted_scheduled
        with context.runtime.lock:
            context.runtime.job.current_request = done
            context.runtime.job.total_requests = max(context.runtime.job.total_requests, total)
            if context.runtime.job.stage == "interpret":
                cache_label = " · cache hit" if cache_hit else ""
                context.runtime.job.message = f"Qwen: interpreted Point {cand.point_id} ({done}/{max(done, total)}){cache_label}"
            context._touch_worker_locked()
        return matched

    executor: ThreadPoolExecutor | None = (
        ThreadPoolExecutor(max_workers=plan.qwen_workers, thread_name_prefix="FBS-Qwen")
        if pipeline_overlap
        else None
    )
    futures: list = []

    def _schedule_candidate(cand: OcrCandidate) -> None:
        nonlocal interpreted_scheduled
        key = context._live_candidate_key(cand)
        with counters_lock:
            if key in scheduled_keys:
                return
            scheduled_keys.add(key)
            interpreted_scheduled += 1
            total = interpreted_scheduled
        with context.runtime.lock:
            context.runtime.job.total_requests = max(context.runtime.job.total_requests, total)
        if executor is not None:
            futures.append(executor.submit(_interpret_candidate, cand))

    trusted_windows_ids: set[str] = set()
    windows_anchor_pairs: set[tuple[str, str]] = set()
    try:
        windows_ready = bool((get_local_ai_status().get("windows_ocr") or {}).get("ready"))
    except Exception:
        windows_ready = False
    if windows_ready:
        with context.runtime.lock:
            context.runtime.job.stage = "fast_ocr"
            context.runtime.job.message = (
                f"Evidence-first fast pass: Windows AI OCR on {len(pages)} page(s)…"
            )
            context._touch_worker_locked()
        for page_index, page in enumerate(pages, start=1):
            if not context._check_worker_revision(
                analysis_revision,
                "Analysis stopped during Windows fast pass because project data changed.",
            ):
                return ([], [], [])
            if not context._analysis_pause_checkpoint(
                analysis_revision, "between Windows fast-pass pages"
            ):
                return ([], [], [])
            image_path = (
                page.enhanced_image_path
                if page.enhanced_image_path and Path(page.enhanced_image_path).exists()
                else page.image_path
            )
            try:
                payload = windows_ocr(image_path)
            except Exception:
                continue
            classification = classify_page_text(windows_payload_text(payload))
            page.page_type = classification.page_type
            page.page_type_confidence = classification.confidence
            page.page_type_reason = classification.reason
            fresh_windows: list[OcrCandidate] = []
            for cand in _windows_ocr_candidates_from_payload(page, payload, targets):
                pair = (cand.page_id, cand.point_id)
                if pair in windows_anchor_pairs:
                    continue
                windows_anchor_pairs.add(pair)
                key = context._live_candidate_key(cand)
                candidate_seen.add(key)
                candidates.append(cand)
                fresh_windows.append(cand)
                if windows_anchor_can_skip_paddle(cand, classification):
                    trusted_windows_ids.add(cand.point_id)
            if fresh_windows:
                context._publish_live_candidates(fresh_windows, analysis_revision)
                if executor is not None:
                    for cand in fresh_windows:
                        _schedule_candidate(cand)
            with context.runtime.lock:
                context.runtime.job.current_page = page_index
                context.runtime.job.message = f"Windows AI fast pass: page {page_index}/{len(pages)} · {len(trusted_windows_ids)} high-confidence PointID anchor(s)"
                context._touch_worker_locked()
    paddle_targets = [target for target in targets if target not in trusted_windows_ids]

    def _ocr_page_result(
        page_number: int, page: FieldBookPage, payload: dict, from_cache: bool
    ) -> None:
        if not context._check_worker_revision(
            analysis_revision, "Analysis stopped during OCR because project data changed."
        ):
            raise PaddleCancelled("Analysis stopped during OCR.")
        if context.runtime.current_job_id:
            context.runtime.job_store.mark_page(
                context.runtime.current_job_id,
                page.page_id,
                status="COMPLETE",
                stage="ocr_complete",
                cache_hit=from_cache,
            )
        with context.runtime.lock:
            context._touch_worker_locked()
        if page.page_type in {"unknown", "blank"} or page.page_type_confidence < 0.6:
            classification = classify_page_text(paddle_payload_text(payload))
            if classification.confidence >= page.page_type_confidence:
                page.page_type = classification.page_type
                page.page_type_confidence = classification.confidence
                page.page_type_reason = classification.reason
        page_candidates = locate_target_ids(
            page, payload, paddle_targets, include_near_matches=plan.near_match_routing
        )
        fresh: list[OcrCandidate] = []
        exact_to_publish: list[OcrCandidate] = []
        for candidate in page_candidates:
            pair = (candidate.page_id, candidate.point_id)
            if candidate.exact_match and pair in windows_anchor_pairs:
                existing = next(
                    (c for c in candidates if (c.page_id, c.point_id) == pair and c.exact_match),
                    None,
                )
                if existing is not None:
                    existing.engine = "Windows AI OCR + PaddleOCR-VL 1.6"
                    existing.confidence = max(existing.confidence, candidate.confidence)
                    if candidate.bbox:
                        existing.bbox = candidate.bbox
                    if candidate.raw_text and candidate.raw_text not in existing.raw_text:
                        existing.raw_text = (existing.raw_text + " | " + candidate.raw_text)[:1200]
                    continue
            key = context._live_candidate_key(candidate)
            if key in candidate_seen:
                continue
            candidate_seen.add(key)
            candidates.append(candidate)
            fresh.append(candidate)
            if candidate.exact_match:
                exact_to_publish.append(candidate)
        if exact_to_publish:
            context._publish_live_candidates(exact_to_publish, analysis_revision)
        if executor is not None:
            for candidate in fresh:
                _schedule_candidate(candidate)

    def _ocr_page_error(
        page_number: int, page: FieldBookPage, error_text: str, attempts: int
    ) -> None:
        exc = RuntimeError(error_text)
        code, message, _recoverable = context._record_job_error(
            exc, component="paddle", page=page, retry_number=max(1, attempts)
        )
        if context.runtime.current_job_id:
            context.runtime.job_store.mark_page(
                context.runtime.current_job_id,
                page.page_id,
                status="FAILED",
                stage="ocr_failed",
                error_code=code,
                error_message=message,
            )
        with context.runtime.lock:
            context.runtime.job.failed_page_count += 1
            context.runtime.job.warning_count += 1
            context.runtime.job.retry_count += max(0, attempts - 1)
            context.runtime.job.resumable = True
            context._touch_worker_locked(
                f"Page {page_number}/{len(pages)} failed OCR after {attempts} attempts; continuing. Hybrid fallback can still recover missing PointIDs."
            )

    if paddle_targets:
        try:
            paddle_payloads = context._run_paddle_supervised(
                pages,
                app_root,
                progress_callback=_ocr_progress,
                cancel_check=_ocr_should_stop,
                page_callback=_ocr_page_result,
                page_error_callback=_ocr_page_error,
                cache_dir=context.runtime.ocr_cache_dir,
                performance_mode=context.runtime.performance_mode,
            )
        except PaddleCancelled:
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)
            context._check_worker_revision(
                analysis_revision, "Analysis stopped during OCR because project data changed."
            )
            return ([], [], [])
        del paddle_payloads
    else:
        with context.runtime.lock:
            context.runtime.job.message = (
                "Windows AI fast pass anchored every target; skipping the heavier Paddle page pass."
            )
            context._touch_worker_locked()
    with context.runtime.lock:
        context.runtime.job.stage = "interpret"
        context.runtime.job.total_requests = max(
            context.runtime.job.total_requests, len(candidates)
        )
        context.runtime.job.current_request = interpreted_completed
        if pipeline_overlap:
            context.runtime.job.message = f"Paddle complete · finishing {max(0, interpreted_scheduled - interpreted_completed)} queued Qwen interpretation(s)…"
        else:
            context.runtime.job.message = (
                f"Paddle complete · interpreting {len(candidates)} located PointID candidate(s)…"
            )
    if executor is None:
        for candidate in candidates:
            _schedule_candidate(candidate)
            _interpret_candidate(candidate)
    else:
        for candidate in candidates:
            _schedule_candidate(candidate)
        try:
            for future in futures:
                future.result()
        finally:
            executor.shutdown(wait=True, cancel_futures=False)
    if not context._check_worker_revision(
        analysis_revision,
        "Analysis stopped during local interpretation because project data changed.",
    ):
        return ([], [], [])
    confirmed_candidates = [
        c
        for c in candidates
        if c.exact_match or context._live_candidate_key(c) in confirmed_fuzzy_keys
    ]
    confirmed_ids = {ev.matched_point_id for ev in all_evidence if ev.matched_point_id}
    remaining = [t for t in targets if t not in confirmed_ids]
    fuzzy_by_target: dict[str, list[OcrCandidate]] = {}
    for cand in candidates:
        if not cand.exact_match and cand.point_id in remaining:
            fuzzy_by_target.setdefault(cand.point_id, []).append(cand)
    for target in list(remaining):
        hints = fuzzy_by_target.get(target) or []
        if not hints:
            continue
        hint_pages: list[FieldBookPage] = []
        seen_page_ids: set[str] = set()
        for hint in hints[:3]:
            page = page_by_id.get(hint.page_id)
            if page and page.page_id not in seen_page_ids:
                seen_page_ids.add(page.page_id)
                hint_pages.append(page)
        if not hint_pages:
            continue
        with context.runtime.lock:
            context.runtime.job.message = f"Accuracy check: verifying likely page(s) for Point {target} before full-book fallback."
        extra_ev, extra_unmatched = _direct_vision_analysis(
            provider="ollama",
            pages=hint_pages,
            targets=[target],
            api_key="",
            model=model,
            batch_pages=1,
            local_base_url=local_base_url,
            analysis_revision=analysis_revision,
            request_offset=context.runtime.job.current_request,
        )
        for ev in extra_ev:
            extra_unmatched.append(
                UnmatchedEvidence(
                    source_name=ev.source_name,
                    page_number=ev.page_number,
                    page_id=ev.page_id,
                    point_id_raw=ev.point_id_raw or ev.matched_point_id,
                    confidence=ev.point_id_confidence,
                    reason=f"AI suggested target PointID {ev.matched_point_id} from a near-match OCR hint; verify the handwritten ID manually.",
                    bbox=ev.bbox,
                )
            )
        all_unmatched.extend(extra_unmatched)
    remaining = [t for t in targets if t not in confirmed_ids]
    if remaining:
        with context.runtime.lock:
            context.runtime.job.message = f"Accuracy-first full-book fallback: searching all pages for {len(remaining)} PointID(s) not yet confirmed."
        extra_ev, extra_unmatched = _direct_vision_analysis(
            provider="ollama",
            pages=pages,
            targets=remaining,
            api_key="",
            model=model,
            batch_pages=batch_pages,
            local_base_url=local_base_url,
            analysis_revision=analysis_revision,
            request_offset=context.runtime.job.current_request,
        )
        for ev in extra_ev:
            extra_unmatched.append(
                UnmatchedEvidence(
                    source_name=ev.source_name,
                    page_number=ev.page_number,
                    page_id=ev.page_id,
                    point_id_raw=ev.point_id_raw or ev.matched_point_id,
                    confidence=ev.point_id_confidence,
                    reason=f"AI-only full-book suggestion for PointID {ev.matched_point_id}; no independent exact OCR confirmation.",
                    bbox=ev.bbox,
                )
            )
        all_unmatched.extend(extra_unmatched)
    return (all_evidence, all_unmatched, confirmed_candidates)
