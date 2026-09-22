from __future__ import annotations
from .api_models import (
    FieldNoteProfileSaveIn,
    FieldNoteProfileSelectIn,
    FieldBookProfileAssignmentIn,
    FieldNoteProfileDuplicateIn,
    FieldNoteTrainingSaveIn,
    TeachCorrectionIn,
)
import json
from pathlib import Path
from uuid import uuid4
from fastapi import File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from .models import FieldNoteProfile, FieldNoteTrainingAnnotation, FieldNoteTrainingExample
from .field_note_profiles import (
    AUTO_PROFILE_ID,
    delete_field_note_profile,
    delete_training_example,
    duplicate_field_note_profile,
    export_profile_bundle,
    get_field_note_profile,
    import_profile_bundle,
    list_field_note_profiles,
    list_training_examples,
    safe_profile_id as safe_field_note_profile_id,
    save_field_note_profile,
    save_training_example,
)
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/field-note-profiles")
def api_field_note_profiles() -> dict:
    from . import app as context

    profiles = list_field_note_profiles(context.runtime.storage.field_note_profile_dir)
    examples = list_training_examples(context.runtime.storage.field_note_training_dir)
    counts: dict[str, int] = {}
    for ex in examples:
        counts[ex.profile_id] = counts.get(ex.profile_id, 0) + 1
    return {
        "selected": context.runtime.storage.state.selected_field_note_profile or AUTO_PROFILE_ID,
        "profiles": [
            {**p.model_dump(mode="json"), "example_count": counts.get(p.profile_id, 0)}
            for p in profiles
        ],
        "total_examples": len(examples),
    }


@router.post("/api/field-note-profiles")
def api_save_field_note_profile(payload: FieldNoteProfileSaveIn) -> dict:
    from . import app as context

    profile = FieldNoteProfile(**payload.model_dump(exclude={"original_profile_id"}))
    original = payload.original_profile_id or profile.profile_id or profile.name
    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_locked()
        try:
            save_field_note_profile(
                context.runtime.storage.field_note_profile_dir,
                profile,
                original_profile_id=original,
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc
        if (
            context.runtime.storage.state.selected_field_note_profile == original
            and profile.profile_id != original
        ):
            context.runtime.storage.state.selected_field_note_profile = profile.profile_id
        context.runtime.storage.save()
    return {"ok": True, "profile": profile.model_dump(mode="json")}


@router.post("/api/field-note-profiles/{profile_id}/duplicate")
def api_duplicate_field_note_profile(profile_id: str, payload: FieldNoteProfileDuplicateIn) -> dict:
    from . import app as context

    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_locked()
        try:
            clone = duplicate_field_note_profile(
                context.runtime.storage.field_note_profile_dir, profile_id, payload.new_name
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "profile": clone.model_dump(mode="json")}


@router.delete("/api/field-note-profiles/{profile_id}")
def api_delete_field_note_profile(profile_id: str) -> dict:
    from . import app as context

    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_locked()
        try:
            delete_field_note_profile(context.runtime.storage.field_note_profile_dir, profile_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        if context.runtime.storage.state.selected_field_note_profile == profile_id:
            context.runtime.storage.state.selected_field_note_profile = AUTO_PROFILE_ID
            context.runtime.storage.save()
    return {"ok": True}


@router.post("/api/select-field-note-profile")
def api_select_field_note_profile(payload: FieldNoteProfileSelectIn) -> dict:
    from . import app as context

    selected = (payload.profile_id or AUTO_PROFILE_ID).strip().upper()
    if selected != AUTO_PROFILE_ID:
        try:
            get_field_note_profile(context.runtime.storage.field_note_profile_dir, selected)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_locked()
        context.runtime.storage.state.selected_field_note_profile = selected
        context.runtime.storage.save()
    return {"ok": True, "selected": selected}


@router.get("/api/fieldbook-profile-assignments")
def api_fieldbook_profile_assignments() -> dict:
    from . import app as context

    profiles = list_field_note_profiles(context.runtime.storage.field_note_profile_dir)
    with context.runtime.storage.lock:
        books = []
        for book in context.runtime.storage.state.fieldbook_files:
            if book.kind != "fieldbook":
                continue
            books.append(
                {
                    **book.model_dump(mode="json"),
                    "field_note_profile": book.field_note_profile or AUTO_PROFILE_ID,
                    "representative_page_ids": list(book.representative_page_ids or []),
                }
            )
    return {"profiles": [p.model_dump(mode="json") for p in profiles], "books": books}


@router.post("/api/fieldbook-profile-assignment")
def api_fieldbook_profile_assignment(payload: FieldBookProfileAssignmentIn) -> dict:
    from . import app as context

    source_name = str(payload.source_name or "").strip()
    selected = str(payload.profile_id or AUTO_PROFILE_ID).strip().upper()
    mode = str(payload.mode or "user").strip().lower()
    if not source_name:
        raise HTTPException(400, "Field-book source name is required.")
    profile = None
    if selected != AUTO_PROFILE_ID:
        try:
            profile = get_field_note_profile(
                context.runtime.storage.field_note_profile_dir, selected
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_locked()
        book = next(
            (
                x
                for x in context.runtime.storage.state.fieldbook_files
                if x.kind == "fieldbook" and x.name == source_name
            ),
            None,
        )
        if book is None:
            raise HTTPException(404, "Imported field book not found.")
        book.field_note_profile = selected
        book.field_note_profile_version = int(profile.version) if profile else 0
        book.field_note_profile_mode = (
            "auto" if selected == AUTO_PROFILE_ID else "trained" if mode == "trained" else "user"
        )
        book.field_note_profile_confidence = 0.0
        book.field_note_profile_reason = (
            "Auto-detect during analysis using installed field-note profiles."
            if selected == AUTO_PROFILE_ID
            else f"{profile.name} selected for this field book."
        )
        for page in context.runtime.storage.state.fieldbook_pages:
            if page.source_name == source_name:
                page.field_note_profile_book = "" if selected == AUTO_PROFILE_ID else selected
        context._bump_project_revision_locked()
        context.runtime.storage.save()
    return {
        "ok": True,
        "source_name": source_name,
        "profile_id": selected,
        "mode": book.field_note_profile_mode,
    }


@router.get("/api/fieldbook-training-preview")
def api_fieldbook_training_preview(source_name: str, limit: int = 5) -> dict:
    from . import app as context

    source_name = str(source_name or "").strip()
    limit = max(1, min(int(limit or 5), 12))
    with context.runtime.storage.lock:
        book = next(
            (
                x
                for x in context.runtime.storage.state.fieldbook_files
                if x.kind == "fieldbook" and x.name == source_name
            ),
            None,
        )
        if book is None:
            raise HTTPException(404, "Imported field book not found.")
        pages = [
            p for p in context.runtime.storage.state.fieldbook_pages if p.source_name == source_name
        ]
        ranked = sorted(
            pages,
            key=lambda p: (
                1 if str(p.page_type or "").lower() in {"cover", "index", "blank"} else 0,
                p.page_number,
            ),
        )[:limit]
        if ranked:
            book.representative_page_ids = [p.page_id for p in ranked]
            context.runtime.storage.save()
        return {
            "source_name": source_name,
            "profile_id": book.field_note_profile or AUTO_PROFILE_ID,
            "profile_mode": book.field_note_profile_mode or "auto",
            "pages": [
                {
                    "page_id": p.page_id,
                    "page_number": p.page_number,
                    "url": f"/api/page/{p.page_id}?enhanced=1"
                    if p.enhanced_image_path
                    else f"/api/page/{p.page_id}",
                    "page_type": p.page_type,
                    "page_profile_override": p.field_note_profile_override or AUTO_PROFILE_ID,
                    "book_profile": p.field_note_profile_book or AUTO_PROFILE_ID,
                }
                for p in ranked
            ],
        }


@router.get("/api/field-note-training/examples")
def api_field_note_training_examples(profile_id: str = "") -> list[dict]:
    from . import app as context

    items = list_training_examples(
        context.runtime.storage.field_note_training_dir, profile_id or None
    )
    return [x.model_dump(mode="json") for x in items]


@router.post("/api/field-note-training/examples")
def api_save_field_note_training_example(payload: FieldNoteTrainingSaveIn) -> dict:
    from . import app as context

    try:
        profile = get_field_note_profile(
            context.runtime.storage.field_note_profile_dir, payload.profile_id
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    with context.runtime.storage.lock:
        page = next(
            (
                p
                for p in context.runtime.storage.state.fieldbook_pages
                if p.page_id == payload.page_id
            ),
            None,
        )
        if page is None:
            raise HTTPException(404, "Field-book page not found.")
        source = Path(
            page.enhanced_image_path
            if page.enhanced_image_path and Path(page.enhanced_image_path).exists()
            else page.image_path
        )
        if not source.exists():
            raise HTTPException(404, "The local page image is missing.")
        annotations = []
        for raw in payload.annotations:
            ann = raw.model_copy(deep=True)
            if not ann.annotation_id:
                ann.annotation_id = uuid4().hex
            if ann.bbox is not None:
                if len(ann.bbox) != 4 or any((v < 0 or v > 1000 for v in ann.bbox)):
                    raise HTTPException(
                        400,
                        "Training annotation boxes must use normalized coordinates from 0 to 1000.",
                    )
                x1, y1, x2, y2 = ann.bbox
                if x2 <= x1 or y2 <= y1:
                    raise HTTPException(400, "Training annotation box has invalid bounds.")
            annotations.append(ann)
        example = FieldNoteTrainingExample(
            example_id=uuid4().hex,
            profile_id=profile.profile_id,
            page_id=page.page_id,
            source_name=page.source_name,
            page_number=page.page_number,
            annotations=annotations,
            origin="trainer",
            notes=payload.notes,
        )
        example = save_training_example(
            context.runtime.storage.field_note_training_dir, example, source_image=source
        )
    return {"ok": True, "example": example.model_dump(mode="json")}


@router.delete("/api/field-note-training/examples/{profile_id}/{example_id}")
def api_delete_field_note_training_example(profile_id: str, example_id: str) -> dict:
    from . import app as context

    try:
        delete_training_example(
            context.runtime.storage.field_note_training_dir, profile_id, example_id
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@router.get("/api/field-note-training/examples/{profile_id}/{example_id}/image")
def api_field_note_training_example_image(profile_id: str, example_id: str) -> FileResponse:
    from . import app as context

    item = next(
        (
            x
            for x in list_training_examples(
                context.runtime.storage.field_note_training_dir, profile_id
            )
            if x.example_id == example_id
        ),
        None,
    )
    if item is None or not item.image_path:
        raise HTTPException(404, "Training image not found.")
    path = Path(item.image_path)
    if not path.exists():
        raise HTTPException(404, "Training image is missing from the local workspace.")
    return FileResponse(path, headers={"Cache-Control": "no-store"})


@router.post("/api/results/{point_id}/teach-profile")
def api_teach_result_to_profile(point_id: str, payload: TeachCorrectionIn) -> dict:
    from . import app as context

    try:
        profile = get_field_note_profile(
            context.runtime.storage.field_note_profile_dir, payload.profile_id
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_locked()
        result = next(
            (r for r in context.runtime.storage.state.results if r.point_id == point_id), None
        )
        if result is None:
            raise HTTPException(404, "Result not found.")
        ev = result.evidence_records[0] if result.evidence_records else None
        if ev is None:
            raise HTTPException(400, "This result has no linked field-book evidence to teach from.")
        page = next(
            (p for p in context.runtime.storage.state.fieldbook_pages if p.page_id == ev.page_id),
            None,
        )
        if page is None:
            raise HTTPException(404, "The linked field-book page is missing.")
        source = Path(
            page.enhanced_image_path
            if page.enhanced_image_path and Path(page.enhanced_image_path).exists()
            else page.image_path
        )
        annotations: list[FieldNoteTrainingAnnotation] = []
        if ev.structure_bbox:
            annotations.append(
                FieldNoteTrainingAnnotation(
                    annotation_id=uuid4().hex,
                    label="structure",
                    bbox=ev.structure_bbox,
                    value=result.point_id,
                )
            )
        if ev.bbox:
            annotations.append(
                FieldNoteTrainingAnnotation(
                    annotation_id=uuid4().hex,
                    label="structure_point_id",
                    bbox=ev.bbox,
                    text=ev.point_id_raw or result.point_id,
                    value=result.point_id,
                )
            )
        for index, pipe in enumerate(result.pipes):
            if pipe.leader_bbox:
                annotations.append(
                    FieldNoteTrainingAnnotation(
                        annotation_id=uuid4().hex,
                        label="pipe_leader",
                        bbox=pipe.leader_bbox,
                        pipe_index=context.index,
                        text=pipe.connected_point_raw or pipe.notes or "",
                        value=json.dumps(pipe.model_dump(mode="json"), separators=(",", ":")),
                    )
                )
        example = FieldNoteTrainingExample(
            example_id=uuid4().hex,
            profile_id=profile.profile_id,
            page_id=page.page_id,
            source_name=page.source_name,
            page_number=page.page_number,
            annotations=annotations,
            accepted_result=result.model_dump(mode="json"),
            origin="teach_from_correction",
            notes=payload.notes or f"Reviewer taught corrected Point {point_id} to {profile.name}.",
        )
        example = save_training_example(
            context.runtime.storage.field_note_training_dir, example, source_image=source
        )
        context._record_history_locked(
            "Teach field-note profile",
            point_id,
            None,
            result.model_dump(mode="json"),
            f"Saved corrected example to field-note profile {profile.profile_id}.",
        )
        context.runtime.storage.save()
    return {"ok": True, "example": example.model_dump(mode="json")}


@router.get("/api/field-note-profiles/{profile_id}/export")
def api_export_field_note_profile(profile_id: str) -> FileResponse:
    from . import app as context

    try:
        profile = get_field_note_profile(context.runtime.storage.field_note_profile_dir, profile_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    output = (
        context.runtime.storage.export_dir / f"{safe_field_note_profile_id(profile.profile_id)}.fnp"
    )
    export_profile_bundle(
        context.runtime.storage.field_note_profile_dir,
        context.runtime.storage.field_note_training_dir,
        profile.profile_id,
        output,
    )
    return FileResponse(output, media_type="application/zip", filename=output.name)


@router.post("/api/field-note-profiles/import")
async def api_import_field_note_profile(file: UploadFile = File(...)) -> dict:
    from . import app as context

    context._ensure_analysis_idle()
    if not (file.filename or "").lower().endswith(".fnp"):
        raise HTTPException(400, "Choose a SurveySync Field Note Profile (.fnp) file.")
    tmp = context.runtime.storage.root / f"field_note_profile_{uuid4().hex}.fnp"
    try:
        await context._stream_upload_to_path(file, tmp, max_bytes=100 * 1024 * 1024)
        try:
            profile = import_profile_bundle(
                context.runtime.storage.field_note_profile_dir,
                context.runtime.storage.field_note_training_dir,
                tmp,
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(400, f"Could not import field-note profile: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)
    return {"ok": True, "profile": profile.model_dump(mode="json")}
