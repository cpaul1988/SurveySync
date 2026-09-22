from __future__ import annotations
from .vision_pipeline import _windows_ocr_candidates_from_payload
from .live_analysis import _live_candidate_key, _dedupe_unmatched
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
import math
import hashlib
import shutil
import json
from pathlib import Path
from .aggregate import aggregate_results
from .ai_reader import (
    list_ollama_models,
    read_page_openai,
    read_page_anthropic,
    read_pages_gemini,
    read_pages_ollama,
    read_pages_foundry,
)
from .image_processing import crop_normalized_bbox, ensure_enhanced_pages
from .intelligence import refresh_intelligence
from .ocr_local import compare_ocr_to_evidence, locate_target_ids, paddle_status, run_paddle_pages
from .project_files import create_project_bundle, load_project_bundle
from .models import (
    AppState,
    BatchJob,
    DipStatus,
    EvidenceBasis,
    FieldBookPage,
    OcrCandidate,
    PageEvidence,
    UnmatchedEvidence,
    utc_now_iso,
)
from surveysync.ai_runtime import DEFAULT_FOUNDRY_VISION_MODEL, windows_ocr


def _set_batch_progress(job: BatchJob, done: int, total: int, message: str | None = None) -> None:
    from . import app as context

    with context.runtime.lock, context.runtime.storage.lock:
        job.progress = done / max(total, 1)
        job.updated_at = utc_now_iso()
        if message:
            job.message = message
        context.runtime.storage.save()


def _batch_hybrid_local(
    job: BatchJob, state: AppState, work_pages: Path
) -> tuple[list[PageEvidence], list[UnmatchedEvidence], list[OcrCandidate]]:
    from . import app as context

    "Run the same PaddleOCR -> targeted Qwen strategy for an unattended batch project.\n\n    This is intentionally independent of the interactive runtime job/revision state so one\n    queued project cannot overwrite or be mistaken for the project currently open in the UI.\n    "
    targets = [p.point_id for p in state.survey_points]
    ensure_enhanced_pages(state.fieldbook_pages, work_pages / "enhanced")
    pstat = paddle_status(context.APP_ROOT)
    if not pstat.installed:
        with context.runtime.lock, context.runtime.storage.lock:
            job.message = "PaddleOCR unavailable; using full-page Qwen fallback…"
            context.runtime.storage.save()
        evidence: list[PageEvidence] = []
        unmatched: list[UnmatchedEvidence] = []
        chunks = [targets[i : i + 220] for i in range(0, len(targets), 220)]
        bs = context.runtime.ollama_batch_pages
        total = max(1, math.ceil(len(state.fieldbook_pages) / bs) * len(chunks))
        done = 0
        for i in range(0, len(state.fieldbook_pages), bs):
            pages = state.fieldbook_pages[i : i + bs]
            for chunk in chunks:
                ev, un, _ = read_pages_ollama(
                    pages=pages,
                    target_point_ids=chunk,
                    model=context.runtime.ollama_model,
                    base_url=context.runtime.ollama_base_url,
                    profile_context=context._field_note_profile_context(
                        state.selected_field_note_profile
                    ),
                )
                for item in ev:
                    item.primary_engine = f"Qwen / Ollama ({context.runtime.ollama_model})"
                evidence.extend(ev)
                unmatched.extend(un)
                done += 1
                _set_batch_progress(job, done, total, "Full-page Qwen fallback…")
        return (evidence, unmatched, [])
    payloads = run_paddle_pages(state.fieldbook_pages, context.APP_ROOT)
    candidates: list[OcrCandidate] = []
    for page, payload in zip(state.fieldbook_pages, payloads):
        candidates.extend(locate_target_ids(page, payload, targets))
    unique: list[OcrCandidate] = []
    seen = set()
    for c in candidates:
        key = (c.page_id, c.point_id, tuple(c.bbox or []))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    candidates = unique
    state.ocr_candidates = candidates
    page_by_id = {p.page_id: p for p in state.fieldbook_pages}
    crops_dir = work_pages.parent / "analysis_crops"
    shutil.rmtree(crops_dir, ignore_errors=True)
    crops_dir.mkdir(parents=True, exist_ok=True)
    evidence: list[PageEvidence] = []
    unmatched: list[UnmatchedEvidence] = []
    found_ids = {c.point_id for c in candidates}
    remaining = [t for t in targets if t not in found_ids]
    fallback_chunks = [remaining[i : i + 220] for i in range(0, len(remaining), 220)]
    fallback_calls = (
        math.ceil(len(state.fieldbook_pages) / context.runtime.ollama_batch_pages)
        * len(fallback_chunks)
        if fallback_chunks
        else 0
    )
    total = max(1, len(candidates) + fallback_calls)
    done = 0
    for idx, cand in enumerate(candidates, start=1):
        original = page_by_id.get(cand.page_id)
        if original is None:
            continue
        src = (
            original.enhanced_image_path
            if original.enhanced_image_path and Path(original.enhanced_image_path).exists()
            else original.image_path
        )
        crop_path = crops_dir / f"{cand.page_id}_{cand.point_id}_{idx}.jpg"
        cropped = (
            crop_normalized_bbox(src, cand.bbox, crop_path, padding=0.28) if cand.bbox else None
        )
        qpage = FieldBookPage(
            page_id=original.page_id,
            source_name=original.source_name,
            page_number=original.page_number,
            image_path=str(cropped or src),
            mime_type="image/jpeg" if cropped else original.mime_type,
        )
        evs, uns, _ = read_pages_ollama(
            pages=[qpage],
            target_point_ids=[cand.point_id],
            model=context.runtime.ollama_model,
            base_url=context.runtime.ollama_base_url,
            profile_context=context._field_note_profile_context(state.selected_field_note_profile),
        )
        matched = False
        for ev in evs:
            if ev.matched_point_id != cand.point_id:
                continue
            matched = True
            ev.bbox = cand.bbox or ev.bbox
            ev.ocr_text = cand.raw_text
            ev.primary_engine = f"Qwen / Ollama ({context.runtime.ollama_model})"
            ev.secondary_engine = "PaddleOCR-VL 1.6"
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
            evidence.append(ev)
        unmatched.extend(uns)
        if not matched:
            evidence.append(
                PageEvidence(
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
                    primary_engine=f"Qwen / Ollama ({context.runtime.ollama_model})",
                    secondary_engine="PaddleOCR-VL 1.6",
                    model_agreement=False,
                    ocr_text=cand.raw_text,
                )
            )
        done += 1
        _set_batch_progress(
            job, done, total, f"Hybrid Local: interpreted {idx}/{len(candidates)} indexed entries"
        )
    if remaining:
        bs = context.runtime.ollama_batch_pages
        for i in range(0, len(state.fieldbook_pages), bs):
            pages = state.fieldbook_pages[i : i + bs]
            for chunk in fallback_chunks:
                ev, un, _ = read_pages_ollama(
                    pages=pages,
                    target_point_ids=chunk,
                    model=context.runtime.ollama_model,
                    base_url=context.runtime.ollama_base_url,
                    profile_context=context._field_note_profile_context(
                        state.selected_field_note_profile
                    ),
                )
                for item in ev:
                    item.primary_engine = f"Qwen / Ollama ({context.runtime.ollama_model})"
                evidence.extend(ev)
                unmatched.extend(un)
                done += 1
                _set_batch_progress(
                    job,
                    done,
                    total,
                    f"Qwen fallback: searching {len(remaining)} PointID(s) not indexed by OCR",
                )
    return (evidence, unmatched, candidates)


def _batch_windows_local(
    job: BatchJob, state: AppState, work_pages: Path, *, vision_provider: str
) -> tuple[list[PageEvidence], list[UnmatchedEvidence], list[OcrCandidate]]:
    from . import app as context

    "Batch-safe Windows OCR pipeline.\n\n    Exact PointID authority comes only from Windows TextRecognizer.  A local vision\n    provider may interpret the crop associated with that exact hit, but it cannot\n    introduce a different PointID.  This mirrors the interactive review pipeline\n    without relying on the global interactive AnalysisJob.\n    "
    targets = [p.point_id for p in state.survey_points]
    page_by_id = {p.page_id: p for p in state.fieldbook_pages}
    candidates: list[OcrCandidate] = []
    seen: set[tuple] = set()
    evidence: list[PageEvidence] = []
    unmatched: list[UnmatchedEvidence] = []
    total_pages = max(1, len(state.fieldbook_pages))
    for idx, page in enumerate(state.fieldbook_pages, start=1):
        src = (
            page.enhanced_image_path
            if page.enhanced_image_path and Path(page.enhanced_image_path).exists()
            else page.image_path
        )
        try:
            payload = windows_ocr(src)
        except Exception as exc:
            unmatched.append(
                UnmatchedEvidence(
                    source_name=page.source_name,
                    page_number=page.page_number,
                    page_id=page.page_id,
                    point_id_raw="",
                    confidence=0.0,
                    reason=f"Windows AI OCR could not read this page: {exc}",
                )
            )
            _set_batch_progress(
                job,
                idx,
                total_pages,
                f"Windows AI OCR: page {idx}/{total_pages} could not be read; continuing",
            )
            continue
        for cand in _windows_ocr_candidates_from_payload(page, payload, targets):
            key = _live_candidate_key(cand)
            if key not in seen:
                seen.add(key)
                candidates.append(cand)
        _set_batch_progress(
            job,
            idx,
            total_pages,
            f"Windows AI OCR: page {idx}/{total_pages} · {len(candidates)} exact PointID hit(s)",
        )
    crop_dir = work_pages / "windows_ai_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    total = max(1, len(candidates))
    for idx, cand in enumerate(candidates, start=1):
        original = page_by_id.get(cand.page_id)
        if original is None:
            continue
        accepted: list[PageEvidence] = []
        local_unmatched: list[UnmatchedEvidence] = []
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
            )
            try:
                if vision_provider == "foundry":
                    evs, uns, _usage = read_pages_foundry(
                        pages=[crop_page],
                        target_point_ids=[cand.point_id],
                        model=DEFAULT_FOUNDRY_VISION_MODEL,
                        profile_context=context._field_note_profile_context(
                            state.selected_field_note_profile
                        ),
                    )
                    engine_name = f"Microsoft Foundry Local ({DEFAULT_FOUNDRY_VISION_MODEL})"
                else:
                    evs, uns, _usage = read_pages_ollama(
                        pages=[crop_page],
                        target_point_ids=[cand.point_id],
                        model=context.runtime.ollama_model,
                        base_url=context.runtime.ollama_base_url,
                        timeout_seconds=900
                        if context.runtime.ollama_model == context.MAX_ACCURACY_OLLAMA_MODEL
                        else 300,
                        profile_context=context._field_note_profile_context(
                            state.selected_field_note_profile
                        ),
                    )
                    engine_name = f"Qwen / Ollama ({context.runtime.ollama_model})"
                local_unmatched.extend(uns)
                for ev in evs:
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
                    accepted.append(ev)
            except Exception as exc:
                local_unmatched.append(
                    UnmatchedEvidence(
                        source_name=original.source_name,
                        page_number=original.page_number,
                        page_id=original.page_id,
                        point_id_raw=cand.point_id,
                        confidence=cand.confidence,
                        reason=f"Local interpretation failed; exact Windows OCR hit retained for review: {exc}",
                        bbox=cand.bbox,
                    )
                )
        if not accepted:
            accepted.append(
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
                    else f"Qwen / Ollama ({context.runtime.ollama_model})",
                    secondary_engine="Windows AI TextRecognizer"
                    if vision_provider != "manual"
                    else None,
                    ocr_text=cand.raw_text,
                )
            )
        evidence.extend(accepted)
        unmatched.extend(local_unmatched)
        _set_batch_progress(
            job, idx, total, f"Local review: Point {cand.point_id} ({idx}/{len(candidates)})"
        )
    return (evidence, _dedupe_unmatched(unmatched), candidates)


def _batch_analyze_state(job: BatchJob, state: AppState, work_pages: Path) -> None:
    from . import app as context

    requested_provider = job.provider or "auto"
    provider = requested_provider
    if requested_provider == "auto":
        auto = context._automatic_ai_status(force=True)
        provider = str((auto.get("automatic_plan") or {}).get("provider") or "manual")
        job.message = f"Automatic selected {(auto.get('automatic_plan') or {}).get('label') or provider} for this batch."
    targets = [p.point_id for p in state.survey_points]
    if not targets or not state.fieldbook_pages:
        raise RuntimeError("Batch project needs survey structures and field-book pages.")
    if provider == "manual":
        results = aggregate_results(
            state.survey_points,
            [],
            context.runtime.confidence_threshold,
            status_rule=context.runtime.status_rule,
        )
        for r in results:
            r.status = DipStatus.REVIEW
        state.results = results
        state.network_edges = refresh_intelligence(
            results,
            state.ocr_candidates,
            elevation_is_rim=context.runtime.elevation_is_rim,
            network_max_distance=context.runtime.network_max_distance,
            network_bearing_tolerance=context.runtime.network_bearing_tolerance,
        )
        _set_batch_progress(job, 1, 1, "Manual-review project prepared")
        return
    if provider in {"hybrid", "ollama", "paddle"}:
        installed = (
            list_ollama_models(base_url=context.runtime.ollama_base_url)
            if provider in {"hybrid", "ollama"}
            else []
        )
        if provider in {"hybrid", "ollama"} and (
            not context._ollama_model_is_installed(context.runtime.ollama_model, installed)
        ):
            raise RuntimeError(f"Qwen model '{context.runtime.ollama_model}' is not installed.")
    evidence: list[PageEvidence] = []
    unmatched: list[UnmatchedEvidence] = []
    if provider in {"microsoft_auto", "windows_ocr_ollama", "windows_ocr"}:
        if provider == "microsoft_auto":
            vision_provider = "foundry"
        elif provider == "windows_ocr_ollama":
            vision_provider = "ollama"
            installed = list_ollama_models(base_url=context.runtime.ollama_base_url)
            if not context._ollama_model_is_installed(context.runtime.ollama_model, installed):
                raise RuntimeError(f"Qwen model '{context.runtime.ollama_model}' is not installed.")
        else:
            vision_provider = "manual"
        evidence, unmatched, state.ocr_candidates = _batch_windows_local(
            job, state, work_pages, vision_provider=vision_provider
        )
    elif provider == "hybrid":
        evidence, unmatched, state.ocr_candidates = _batch_hybrid_local(job, state, work_pages)
    elif provider == "paddle":
        ensure_enhanced_pages(state.fieldbook_pages, work_pages / "enhanced")
        pstat = paddle_status(context.APP_ROOT)
        if not pstat.installed:
            raise RuntimeError(pstat.message)
        payloads = run_paddle_pages(state.fieldbook_pages, context.APP_ROOT)
        state.ocr_candidates = []
        for idx, (page, payload) in enumerate(zip(state.fieldbook_pages, payloads), start=1):
            state.ocr_candidates.extend(locate_target_ids(page, payload, targets))
            _set_batch_progress(
                job,
                idx,
                len(state.fieldbook_pages),
                f"PaddleOCR indexed page {idx}/{len(state.fieldbook_pages)}",
            )
        for cand in state.ocr_candidates:
            evidence.append(
                PageEvidence(
                    matched_point_id=cand.point_id,
                    source_name=cand.source_name,
                    page_number=cand.page_number,
                    page_id=cand.page_id,
                    point_id_raw=cand.point_id,
                    point_id_confidence=cand.confidence,
                    dipped=DipStatus.REVIEW,
                    basis=EvidenceBasis.AMBIGUOUS,
                    dipped_confidence=0.4,
                    evidence="PaddleOCR-VL located this exact PointID. Semantic interpretation requires review.",
                    bbox=cand.bbox,
                    primary_engine="PaddleOCR-VL 1.6",
                    ocr_text=cand.raw_text,
                )
            )
    else:
        effective = provider
        chunks = [targets[i : i + 220] for i in range(0, len(targets), 220)]
        total = len(chunks) * (
            math.ceil(
                len(state.fieldbook_pages)
                / (
                    context.runtime.gemini_batch_pages
                    if effective == "gemini"
                    else context.runtime.ollama_batch_pages
                )
            )
            if effective in {"ollama", "gemini"}
            else len(state.fieldbook_pages)
        )
        done = 0
        if effective == "ollama":
            ensure_enhanced_pages(state.fieldbook_pages, work_pages / "enhanced")
            bs = context.runtime.ollama_batch_pages
            for i in range(0, len(state.fieldbook_pages), bs):
                pages = state.fieldbook_pages[i : i + bs]
                for chunk in chunks:
                    ev, un, _ = read_pages_ollama(
                        pages=pages,
                        target_point_ids=chunk,
                        model=context.runtime.ollama_model,
                        base_url=context.runtime.ollama_base_url,
                        profile_context=context._field_note_profile_context(
                            state.selected_field_note_profile
                        ),
                    )
                    evidence.extend(ev)
                    unmatched.extend(un)
                    done += 1
                    _set_batch_progress(job, done, total, "Qwen Local batch analysis…")
        elif effective == "gemini":
            if not context.runtime.gemini_api_key:
                raise RuntimeError("Gemini API key is not available for batch processing.")
            bs = context.runtime.gemini_batch_pages
            for i in range(0, len(state.fieldbook_pages), bs):
                pages = state.fieldbook_pages[i : i + bs]
                for chunk in chunks:
                    ev, un, _ = read_pages_gemini(
                        pages=pages,
                        target_point_ids=chunk,
                        api_key=context.runtime.gemini_api_key,
                        model=context.runtime.gemini_model,
                        profile_context=context._field_note_profile_context(
                            state.selected_field_note_profile
                        ),
                    )
                    evidence.extend(ev)
                    unmatched.extend(un)
                    done += 1
                    _set_batch_progress(job, done, total, "Gemini batch analysis…")
        elif effective == "openai":
            if not context.runtime.openai_api_key:
                raise RuntimeError("OpenAI API key is not available for batch processing.")
            for page in state.fieldbook_pages:
                for chunk in chunks:
                    ev, un, _ = read_page_openai(
                        image_path=page.image_path,
                        mime_type=page.mime_type,
                        source_name=page.source_name,
                        page_number=page.page_number,
                        page_id=page.page_id,
                        target_point_ids=chunk,
                        api_key=context.runtime.openai_api_key,
                        model=context.runtime.openai_model,
                        profile_context=context._field_note_profile_context(
                            state.selected_field_note_profile
                        ),
                        field_note_profile_override=context._effective_page_profile_id(page),
                    )
                    evidence.extend(ev)
                    unmatched.extend(un)
                    done += 1
                    _set_batch_progress(job, done, total, "OpenAI batch analysis…")
        elif effective == "anthropic":
            if not context.runtime.anthropic_api_key:
                raise RuntimeError("Anthropic API key is not available for batch processing.")
            for page in state.fieldbook_pages:
                for chunk in chunks:
                    ev, un, _ = read_page_anthropic(
                        image_path=page.image_path,
                        mime_type=page.mime_type,
                        source_name=page.source_name,
                        page_number=page.page_number,
                        page_id=page.page_id,
                        target_point_ids=chunk,
                        api_key=context.runtime.anthropic_api_key,
                        model=context.runtime.anthropic_model,
                        profile_context=context._field_note_profile_context(
                            state.selected_field_note_profile
                        ),
                        field_note_profile_override=context._effective_page_profile_id(page),
                    )
                    evidence.extend(ev)
                    unmatched.extend(un)
                    done += 1
                    _set_batch_progress(job, done, total, "Anthropic Claude batch analysis…")
        else:
            raise RuntimeError(f"Unsupported batch provider: {provider}")
    state.results = aggregate_results(
        state.survey_points,
        evidence,
        context.runtime.confidence_threshold,
        status_rule=context.runtime.status_rule,
    )
    state.unmatched = _dedupe_unmatched(unmatched)
    state.network_edges = refresh_intelligence(
        state.results,
        state.ocr_candidates,
        elevation_is_rim=context.runtime.elevation_is_rim,
        network_max_distance=context.runtime.network_max_distance,
        network_bearing_tolerance=context.runtime.network_bearing_tolerance,
    )


def _batch_worker() -> None:
    from . import app as context

    while True:
        with context.runtime.lock, context.runtime.storage.lock:
            job = next(
                (j for j in context.runtime.storage.state.batch_jobs if j.status == "QUEUED"), None
            )
            if job is None:
                context.runtime.batch_thread = None
                context.runtime.storage.save()
                return
            job.status = "RUNNING"
            job.updated_at = utc_now_iso()
            job.message = "Opening queued project…"
            job.progress = 0
            context.runtime.storage.save()
            input_path = Path(job.project_file or "")
        job_dir = context.runtime.storage.batch_dir / job.job_id
        work = job_dir / "work"
        shutil.rmtree(work, ignore_errors=True)
        (work / "pages").mkdir(parents=True, exist_ok=True)
        (work / "examples").mkdir(parents=True, exist_ok=True)
        try:
            state, profile = load_project_bundle(input_path, work / "pages", work / "examples")
            with context.runtime.lock, context.runtime.storage.lock:
                job.message = "Analyzing…"
                context.runtime.storage.save()
            _batch_analyze_state(job, state, work / "pages")
            state.project_name = state.project_name or job.name
            output = create_project_bundle(state, work / "pages", job_dir, profile)
            with context.runtime.lock, context.runtime.storage.lock:
                job.status = "COMPLETE"
                job.progress = 1.0
                job.updated_at = utc_now_iso()
                job.message = "Complete"
                job.project_file = str(output)
                context.runtime.storage.save()
        except Exception as exc:
            ref = context._error_reference("BAT")
            context.logger.exception("Batch job %s (%s) failed [%s]", job.job_id, job.name, ref)
            with context.runtime.lock, context.runtime.storage.lock:
                job.status = "ERROR"
                job.updated_at = utc_now_iso()
                job.error = f"{exc} (reference {ref})"
                job.message = "Batch analysis failed; full traceback saved to local log"
                context.runtime.storage.save()
        finally:
            shutil.rmtree(work, ignore_errors=True)
