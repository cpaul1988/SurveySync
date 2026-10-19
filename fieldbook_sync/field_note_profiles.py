from __future__ import annotations
import logging

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Iterable, List
from uuid import uuid4

from .models import (
    FieldNoteProfile,
    FieldNoteTrainingAnnotation as FieldNoteTrainingAnnotation,
    FieldNoteTrainingExample,
    utc_now_iso,
)

AUTO_PROFILE_ID = "AUTO"
BRT_PROFILE_ID = "BRT_STANDARD"
BRT_PROFILE_VERSION = 2
GENERIC_PROFILE_ID = "GENERIC_SURVEY_NOTES"
MAX_BUNDLE_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
MAX_BUNDLE_MEMBER_BYTES = 50 * 1024 * 1024
MAX_PROFILE_JSON_BYTES = 2 * 1024 * 1024
MAX_EXAMPLE_JSON_BYTES = 5 * 1024 * 1024


def _clip(value: str, limit: int = 800) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def safe_profile_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("_")
    return (text or f"PROFILE_{uuid4().hex[:8]}").upper()


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def default_brt_profile() -> FieldNoteProfile:
    return FieldNoteProfile(
        profile_id=BRT_PROFILE_ID,
        name="BRT Utility / Structure Notes",
        client="BRT",
        job_type="Utility / structure inventory",
        scope="built_in",
        locked=True,
        version=BRT_PROFILE_VERSION,
        description=(
            "BRT field-note interpretation conventions: a circular structure/manhole, a sketch-north mark, "
            "an exact structure PointID, and separate pipe/connection leaders. A reference mockup illustrates "
            "these relationships without requiring its note boxes, colors, layout, or number of attachments. "
            "Undefined labels remain raw notes pending a confirmed glossary."
        ),
        detection_cues=[
            "Circular structure/manhole sketch",
            "Internal north arrow or N orientation mark, distinct from connector arrowheads",
            "Structure PointID written near the structure",
            "Separate pipe/feature leaders with any visible number of attachments",
            "Leader annotations may include Dip, pipe diameter/material, Az, raw BOS/TOD/TOW/TOP labels, or an explicit destination PointID",
        ],
        vocabulary=[
            "Dip", "Az", "BOS", "TOD", "TOW", "TOP", "ID#", "PVC", "VCP", "RCP", "Trapped", "Filled w/debris", "to Point"
        ],
        expected_fields=[
            "structure_point_id", "north_orientation", "structure_notes", "pipe_leaders", "dip", "diameter",
            "material", "azimuth", "destination_point_id", "condition", "notes"
        ],
        extraction_instructions=[
            "Identify the exact structure PointID from visible evidence. Repeated copies of its own ID# beside connection notes identify ownership; preserve them as raw notes, never as a destination or self-connection.",
            "Keep every visible attachment/leader as a separate connection record, including more than two attachments. Associate handwriting with its own visible leader and preserve competing associations for review; repeated owner IDs do not merge separate connections.",
            "An internal arrow or N orientation mark indicates sketch north when its role is clear. Use the visible mark and context, not ink color, a fixed position, or the paper's top edge. Keep this north mark distinct from connector flow arrowheads.",
            "Keep sketch north orientation, written azimuth, visual leader bearing, and flow as separate observations. Do not copy one into another. Leave the written azimuth field unknown unless explicitly recorded; a visual leader bearing remains a separate estimate. Retain raw directional text and uncertainty.",
            "For a connector with a clearly visible arrowhead, record flow toward the circle as inflow and away from the circle as outflow in that connection's notes. Without a distinct arrowhead, keep flow unknown. A leader line, north mark, or written azimuth alone does not establish flow; these observations require human review and are not automated arrow-detector evidence.",
            "Rectangular note boxes in the reference mockup were only an Excel illustration. Actual handwritten notes need no box, fixed row order, or fixed annotation position. Use visible text/leader relationships and retain uncertainty instead of forcing the illustrated layout.",
            "BOS, TOD and TOW have no confirmed glossary definitions or structure/pipe field scope. Preserve each exact written label and any visible value in notes, with observed placement when useful. Do not expand abbreviations, invent units, or assign field scope. Keep TOP distinct from TOD; preserve other undefined labels the same way.",
            "Reference labels with no sample value supply no measurement. On the current page, an unfilled or illegible label remains raw notes with an unknown value, never zero. Do not fill blank values from another attachment, a template, or a training example.",
            "Preserve explicit references such as 'to 3394' or 'Az = to 3394' as destination PointID text only when they clearly name another structure. A destination reference is not a numeric azimuth. Repeated own ID# denotes ownership; retain ambiguous references raw for review.",
            "Assign defined structure-wide observations or individual pipe notes only when visible evidence supports that relationship. Undefined abbreviations retain raw text and location without inferred field scope. Incomplete grammar, uncertain handwriting, or unresolved associations require review.",
        ],
        symbols=[
            {"label": "structure", "meaning": "Surveyed structure/manhole", "visual_cue": "circle", "relationship": "center of connection sketch"},
            {"label": "north_arrow", "meaning": "Sketch north/orientation, separate from flow", "visual_cue": "internal orientation arrow or N, independent of color", "relationship": "identified by visible structure context, not paper-up"},
            {"label": "structure_point_id", "meaning": "Surveyed structure PointID", "visual_cue": "handwritten integer/text", "relationship": "near structure circle"},
            {"label": "pipe_leader", "meaning": "Individual pipe/connection", "visual_cue": "line/arrow", "relationship": "touches/radiates from structure"},
            {"label": "flow_observation", "meaning": "Advisory connector inflow/outflow observation retained in notes", "visual_cue": "visible connector arrowhead toward/away from the circle", "relationship": "separate from north, written azimuth, and leader bearing; review required"},
            {"label": "destination_point", "meaning": "Explicit reference to another surveyed PointID", "visual_cue": "to #### / Az = to ####", "relationship": "belongs to one connection; repeated own ID# identifies ownership"},
        ],
    )


def default_generic_profile() -> FieldNoteProfile:
    return FieldNoteProfile(
        profile_id=GENERIC_PROFILE_ID,
        name="Generic Survey Field Notes",
        client="",
        job_type="General survey notes",
        scope="built_in",
        locked=True,
        description=(
            "Conservative fallback profile for pages that do not match a named field-note grammar. "
            "It extracts only visible evidence and keeps uncertain relationships in review."
        ),
        detection_cues=["No known named profile has a strong visual/layout match"],
        vocabulary=[],
        expected_fields=["point_id", "visible_measurements", "notes"],
        extraction_instructions=[
            "Do not infer semantic relationships from proximity alone when the layout grammar is unknown.",
            "Extract visible text/measurements conservatively and route ambiguous associations to review.",
        ],
        symbols=[],
    )


def ensure_default_field_note_profiles(profile_dir: Path) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    for profile in (default_brt_profile(), default_generic_profile()):
        path = profile_dir / f"{profile.profile_id}.json"
        if not path.exists():
            _atomic_write_json(path, profile.model_dump(mode="json"))


def list_field_note_profiles(profile_dir: Path) -> List[FieldNoteProfile]:
    ensure_default_field_note_profiles(profile_dir)
    result: List[FieldNoteProfile] = []
    for path in sorted(profile_dir.glob("*.json")):
        try:
            profile = FieldNoteProfile.model_validate_json(path.read_text(encoding="utf-8"))
            if (profile.profile_id == BRT_PROFILE_ID and profile.scope == "built_in"
                    and profile.locked and profile.version < BRT_PROFILE_VERSION):
                # Installed locked grammar is code-owned. Refresh it in memory so old
                # default files reach current prompts without rewriting user storage,
                # custom profiles, timestamps, or separately stored labeled examples.
                current = default_brt_profile()
                profile = profile.model_copy(update={
                    name: getattr(current, name) for name in (
                        "version", "description", "detection_cues", "vocabulary",
                        "expected_fields", "extraction_instructions", "symbols",
                    )
                })
            result.append(profile)
        except Exception:
            continue
    result.sort(key=lambda p: (0 if p.profile_id == BRT_PROFILE_ID else 1 if p.scope == "built_in" else 2, p.name.casefold()))
    return result


def get_field_note_profile(profile_dir: Path, profile_id: str) -> FieldNoteProfile:
    wanted = str(profile_id or "").strip().upper()
    for profile in list_field_note_profiles(profile_dir):
        if profile.profile_id.upper() == wanted:
            return profile
    raise KeyError(f"Field-note profile not found: {profile_id}")


def save_field_note_profile(profile_dir: Path, profile: FieldNoteProfile, *, original_profile_id: str | None = None) -> Path:
    ensure_default_field_note_profiles(profile_dir)
    profile.profile_id = safe_profile_id(profile.profile_id or profile.name)
    profile.name = profile.name.strip()
    if not profile.name:
        raise ValueError("Field-note profile name is required.")
    original = safe_profile_id(original_profile_id or profile.profile_id)
    target = profile_dir / f"{profile.profile_id}.json"

    existing = {p.profile_id: p for p in list_field_note_profiles(profile_dir)}
    prior = existing.get(original)
    if prior and prior.locked and original != profile.profile_id:
        raise ValueError("Built-in field-note profiles cannot be renamed. Duplicate it into a custom profile instead.")
    if profile.profile_id in existing and profile.profile_id != original and existing[profile.profile_id].profile_id != original:
        raise ValueError(f"A field-note profile with ID '{profile.profile_id}' already exists.")
    if prior and prior.locked:
        # Built-in profiles can be enriched with local examples, but the canonical rules are immutable.
        raise ValueError("Built-in field-note profile rules are locked. Create a custom profile to change the grammar.")

    profile.scope = "custom" if profile.scope == "built_in" else (profile.scope or "custom")
    profile.locked = False
    profile.updated_at = utc_now_iso()
    if not profile.created_at:
        profile.created_at = profile.updated_at
    _atomic_write_json(target, profile.model_dump(mode="json"))
    if original != profile.profile_id:
        old = profile_dir / f"{original}.json"
        if old.exists():
            old.unlink()
    return target


def duplicate_field_note_profile(profile_dir: Path, source_profile_id: str, new_name: str) -> FieldNoteProfile:
    source = get_field_note_profile(profile_dir, source_profile_id)
    clone = source.model_copy(deep=True)
    clone.profile_id = safe_profile_id(new_name)
    clone.name = new_name.strip()
    clone.scope = "custom"
    clone.locked = False
    clone.version = 1
    clone.created_at = utc_now_iso()
    clone.updated_at = clone.created_at
    save_field_note_profile(profile_dir, clone)
    return clone


def delete_field_note_profile(profile_dir: Path, profile_id: str) -> None:
    profile = get_field_note_profile(profile_dir, profile_id)
    if profile.locked:
        raise ValueError("Built-in field-note profiles cannot be deleted.")
    path = profile_dir / f"{profile.profile_id}.json"
    if not path.exists():
        raise KeyError(f"Field-note profile not found: {profile_id}")
    path.unlink()


def example_dir(training_root: Path, profile_id: str) -> Path:
    path = training_root / safe_profile_id(profile_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_training_examples(training_root: Path, profile_id: str | None = None) -> List[FieldNoteTrainingExample]:
    roots: Iterable[Path]
    if profile_id:
        roots = [example_dir(training_root, profile_id)]
    else:
        training_root.mkdir(parents=True, exist_ok=True)
        roots = [p for p in training_root.iterdir() if p.is_dir()]
    items: List[FieldNoteTrainingExample] = []
    for root in roots:
        for meta in sorted(root.glob("*.json")):
            try:
                items.append(FieldNoteTrainingExample.model_validate_json(meta.read_text(encoding="utf-8")))
            except Exception:
                continue
    items.sort(key=lambda x: x.created_at, reverse=True)
    return items


def save_training_example(training_root: Path, example: FieldNoteTrainingExample, source_image: Path | None = None) -> FieldNoteTrainingExample:
    root = example_dir(training_root, example.profile_id)
    if not example.example_id:
        example.example_id = uuid4().hex
    if source_image is not None:
        suffix = source_image.suffix.lower() if source_image.suffix else ".jpg"
        dst = root / f"{example.example_id}{suffix}"
        shutil.copy2(source_image, dst)
        example.image_path = str(dst)
    meta = root / f"{example.example_id}.json"
    _atomic_write_json(meta, example.model_dump(mode="json"))
    return example


def delete_training_example(training_root: Path, profile_id: str, example_id: str) -> None:
    root = example_dir(training_root, profile_id)
    meta = root / f"{example_id}.json"
    if not meta.exists():
        raise KeyError(f"Training example not found: {example_id}")
    try:
        ex = FieldNoteTrainingExample.model_validate_json(meta.read_text(encoding="utf-8"))
        if ex.image_path:
            img = Path(ex.image_path)
            if img.exists() and img.parent.resolve() == root.resolve():
                img.unlink(missing_ok=True)
    except Exception:
        logging.getLogger(__name__).warning("Recovery fallback in field_note_profiles; operation did not complete.", exc_info=True)
    meta.unlink(missing_ok=True)


def _training_grammar_summary(training_root: Path | None, profile_id: str) -> str:
    """Return privacy-preserving structural hints learned from labeled examples.

    Raw handwritten values, source names, PointIDs and accepted results are intentionally
    excluded so a profile can be used with an opt-in cloud provider without leaking data
    from another project. The summary contains only annotation types, counts and coarse
    normalized layout centers.
    """
    if training_root is None:
        return ""
    try:
        examples = list_training_examples(training_root, profile_id)[:24]
    except Exception:
        return ""
    if not examples:
        return ""
    labels: dict[str, int] = {}
    centers: dict[str, list[tuple[float, float]]] = {}
    pipe_linked: dict[str, int] = {}
    for ex in examples:
        for ann in ex.annotations:
            label = str(ann.label or "other").strip().lower()[:80]
            labels[label] = labels.get(label, 0) + 1
            if ann.pipe_index is not None:
                pipe_linked[label] = pipe_linked.get(label, 0) + 1
            if ann.bbox and len(ann.bbox) == 4:
                x1, y1, x2, y2 = ann.bbox
                centers.setdefault(label, []).append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
    label_text = ", ".join(f"{k}×{v}" for k, v in sorted(labels.items(), key=lambda kv: (-kv[1], kv[0]))[:16])
    layout_bits = []
    for label, pts in sorted(centers.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:8]:
        if len(pts) < 2:
            continue
        x = round(sum(p[0] for p in pts) / len(pts))
        y = round(sum(p[1] for p in pts) / len(pts))
        layout_bits.append(f"{label} center≈({x},{y})/1000")
    pipe_text = ", ".join(f"{k}×{v}" for k, v in sorted(pipe_linked.items(), key=lambda kv: (-kv[1], kv[0]))[:10])
    parts = [f"Learned from {len(examples)} locally labeled example(s): annotation types {label_text or 'none'}." ]
    if layout_bits:
        parts.append("Coarse layout tendencies: " + "; ".join(layout_bits) + ".")
    if pipe_text:
        parts.append("Pipe-associated annotation types: " + pipe_text + ".")
    parts.append("These are advisory tendencies only; visible evidence on the current page always wins.")
    return " ".join(parts)


def build_profile_prompt(profile_dir: Path, selected_profile_id: str = AUTO_PROFILE_ID, training_root: Path | None = None) -> str:
    profiles = list_field_note_profiles(profile_dir)
    selected = str(selected_profile_id or AUTO_PROFILE_ID).strip().upper()
    if selected != AUTO_PROFILE_ID:
        try:
            profiles = [get_field_note_profile(profile_dir, selected)]
            mode = f"The operator selected field-note profile {profiles[0].profile_id}. Apply it only where the visible page is consistent with its grammar; otherwise mark the relationship ambiguous."
        except KeyError:
            profiles = list_field_note_profiles(profile_dir)
            mode = "The configured field-note profile was unavailable. Auto-detect conservatively from the available profile catalog."
    else:
        mode = (
            "Auto-detect the best matching field-note profile for each page. Use a named profile only when the visual/layout cues fit; "
            "otherwise use GENERIC_SURVEY_NOTES or UNKNOWN and route uncertain semantic associations to review."
        )

    lines = ["\nFIELD-NOTE PROFILE CONTEXT:", mode]
    for profile in profiles[:12]:
        lines.append(f"PROFILE {profile.profile_id}: {_clip(profile.name, 160)} — {_clip(profile.description, 1000)}")
        if profile.detection_cues:
            lines.append(" Detection cues: " + "; ".join(_clip(x, 400) for x in profile.detection_cues[:8]))
        if profile.vocabulary:
            lines.append(" Common vocabulary: " + ", ".join(_clip(x, 100) for x in profile.vocabulary[:30]))
        if profile.extraction_instructions:
            lines.append(" Rules: " + " ".join(_clip(x, 500) for x in profile.extraction_instructions[:10]))
        learned = _training_grammar_summary(training_root, profile.profile_id)
        if learned:
            lines.append(" Learned grammar: " + learned)
    lines.append(
        "Return field_note_profile as one profile ID from this catalog when confident, GENERIC_SURVEY_NOTES for a conservative generic read, or UNKNOWN. "
        "field_note_profile_confidence is 0..1 and is advisory only."
    )
    return "\n".join(lines)


def export_profile_bundle(profile_dir: Path, training_root: Path, profile_id: str, output_path: Path) -> Path:
    profile = get_field_note_profile(profile_dir, profile_id)
    examples = list_training_examples(training_root, profile.profile_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.json", profile.model_dump_json(indent=2))
        for ex in examples:
            zf.writestr(f"examples/{ex.example_id}.json", ex.model_dump_json(indent=2))
            if ex.image_path:
                image = Path(ex.image_path)
                if image.exists() and image.is_file():
                    zf.write(image, f"images/{ex.example_id}{image.suffix.lower() or '.jpg'}")
    return output_path


def import_profile_bundle(profile_dir: Path, training_root: Path, bundle_path: Path, *, overwrite: bool = False) -> FieldNoteProfile:
    with zipfile.ZipFile(bundle_path, "r") as zf:
        infos = zf.infolist()
        names = {info.filename for info in infos}
        total_uncompressed = sum(max(0, int(info.file_size)) for info in infos)
        if total_uncompressed > MAX_BUNDLE_UNCOMPRESSED_BYTES:
            raise ValueError("The .fnp bundle is too large after decompression.")
        for info in infos:
            path = Path(info.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("The .fnp bundle contains an unsafe path.")
            if info.file_size > MAX_BUNDLE_MEMBER_BYTES:
                raise ValueError(f"The .fnp bundle member '{info.filename}' is too large.")
        if "profile.json" not in names:
            raise ValueError("The .fnp bundle does not contain profile.json.")
        profile_info = next(info for info in infos if info.filename == "profile.json")
        if profile_info.file_size > MAX_PROFILE_JSON_BYTES:
            raise ValueError("profile.json is too large.")
        profile = FieldNoteProfile.model_validate_json(zf.read("profile.json").decode("utf-8"))
        profile.profile_id = safe_profile_id(profile.profile_id or profile.name)
        profile.locked = False
        profile.scope = "custom"
        existing_ids = {p.profile_id for p in list_field_note_profiles(profile_dir)}
        if profile.profile_id in {BRT_PROFILE_ID, GENERIC_PROFILE_ID}:
            base = safe_profile_id(f"{profile.profile_id}_CUSTOM")
            candidate = base
            n = 2
            while candidate in existing_ids:
                candidate = f"{base}_{n}"
                n += 1
            profile.profile_id = candidate
            profile.name = f"{profile.name} (Custom)"
        elif profile.profile_id in existing_ids and not overwrite:
            raise ValueError(f"Field-note profile '{profile.profile_id}' already exists.")
        profile.updated_at = utc_now_iso()
        _atomic_write_json(profile_dir / f"{profile.profile_id}.json", profile.model_dump(mode="json"))

        root = example_dir(training_root, profile.profile_id)
        info_by_name = {info.filename: info for info in infos}
        for name in sorted(names):
            if not name.startswith("examples/") or not name.endswith(".json"):
                continue
            info = info_by_name[name]
            if info.file_size > MAX_EXAMPLE_JSON_BYTES:
                continue
            try:
                ex = FieldNoteTrainingExample.model_validate_json(zf.read(name).decode("utf-8"))
            except Exception:
                continue
            ex.profile_id = profile.profile_id
            image_members = [n for n in names if n.startswith(f"images/{ex.example_id}.") and "/" not in n[len("images/"):]]
            if image_members:
                member = image_members[0]
                suffix = Path(member).suffix.lower() or ".jpg"
                if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                    suffix = ".jpg"
                dst = root / f"{ex.example_id}{suffix}"
                with zf.open(member) as src, dst.open("wb") as out:
                    shutil.copyfileobj(src, out, length=1024 * 1024)
                ex.image_path = str(dst)
            _atomic_write_json(root / f"{ex.example_id}.json", ex.model_dump(mode="json"))
    return profile

