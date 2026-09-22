from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from fieldbook_sync.ai_reader import EXTRACTION_SCHEMA
from fieldbook_sync.field_note_profiles import (
    AUTO_PROFILE_ID,
    BRT_PROFILE_ID,
    GENERIC_PROFILE_ID,
    build_profile_prompt,
    duplicate_field_note_profile,
    ensure_default_field_note_profiles,
    export_profile_bundle,
    get_field_note_profile,
    import_profile_bundle,
    list_field_note_profiles,
    list_training_examples,
    save_field_note_profile,
    save_training_example,
)
from fieldbook_sync.models import (
    FieldNoteProfile,
    FieldNoteTrainingAnnotation,
    FieldNoteTrainingExample,
    PageEvidence,
)


def test_default_profiles_capture_brt_grammar(tmp_path: Path):
    profiles = tmp_path / "profiles"
    ensure_default_field_note_profiles(profiles)
    brt = get_field_note_profile(profiles, BRT_PROFILE_ID)
    generic = get_field_note_profile(profiles, GENERIC_PROFILE_ID)
    assert brt.locked is True
    assert generic.locked is True
    rules = " ".join(brt.extraction_instructions).lower()
    cues = " ".join(brt.detection_cues).lower()
    assert "leader" in rules and "destination pointid" in rules
    assert "circular" in cues and "north" in cues
    assert {p.profile_id for p in list_field_note_profiles(profiles)} >= {BRT_PROFILE_ID, GENERIC_PROFILE_ID}


def test_custom_profile_crud_and_builtin_lock(tmp_path: Path):
    profiles = tmp_path / "profiles"
    ensure_default_field_note_profiles(profiles)
    with pytest.raises(ValueError):
        save_field_note_profile(profiles, get_field_note_profile(profiles, BRT_PROFILE_ID))
    clone = duplicate_field_note_profile(profiles, BRT_PROFILE_ID, "Client X Sewer Sketch")
    assert clone.profile_id == "CLIENT_X_SEWER_SKETCH"
    assert clone.locked is False
    clone.description = "Square structure, north tick, tabular pipe notes."
    save_field_note_profile(profiles, clone, original_profile_id=clone.profile_id)
    assert "Square structure" in get_field_note_profile(profiles, clone.profile_id).description


def test_labeled_examples_change_prompt_without_leaking_raw_project_values(tmp_path: Path):
    profiles = tmp_path / "profiles"
    training = tmp_path / "training"
    ensure_default_field_note_profiles(profiles)
    clone = duplicate_field_note_profile(profiles, BRT_PROFILE_ID, "Client Y Utility")
    image = tmp_path / "page.jpg"
    image.write_bytes(b"not-a-real-image-needed-for-storage-test")
    ex = FieldNoteTrainingExample(
        profile_id=clone.profile_id,
        source_name="SECRET PROJECT 123",
        page_number=4,
        annotations=[
            FieldNoteTrainingAnnotation(label="structure", bbox=[400, 400, 600, 600], value="8899"),
            FieldNoteTrainingAnnotation(label="pipe_leader", bbox=[100, 450, 400, 520], pipe_index=0, text="to 9001"),
            FieldNoteTrainingAnnotation(label="dip", bbox=[120, 520, 250, 580], pipe_index=0, value="3.65"),
        ],
        accepted_result={"point_id": "8899", "notes": "SECRET CLIENT VALUE"},
    )
    save_training_example(training, ex, source_image=image)
    prompt = build_profile_prompt(profiles, clone.profile_id, training)
    assert "Learned from 1 locally labeled example" in prompt
    assert "pipe_leader" in prompt and "dip" in prompt
    # Profile learning must not leak previous project identifiers/values into future AI prompts.
    assert "SECRET PROJECT 123" not in prompt
    assert "SECRET CLIENT VALUE" not in prompt
    assert "8899" not in prompt and "9001" not in prompt and "3.65" not in prompt


def test_fnp_round_trip_preserves_profile_and_examples(tmp_path: Path):
    profiles = tmp_path / "profiles"
    training = tmp_path / "training"
    ensure_default_field_note_profiles(profiles)
    profile = FieldNoteProfile(
        profile_id="STORM_DRAIN_CUSTOM",
        name="Storm Drain Custom",
        client="Example",
        job_type="Storm drain",
        description="Boxes with pipe callout tables",
        detection_cues=["square structure"],
        expected_fields=["structure_point_id", "dip"],
        extraction_instructions=["Associate table row with its leader."],
    )
    save_field_note_profile(profiles, profile)
    image = tmp_path / "example.png"
    image.write_bytes(b"image-bytes")
    saved = save_training_example(
        training,
        FieldNoteTrainingExample(
            profile_id=profile.profile_id,
            source_name="book.pdf",
            page_number=2,
            annotations=[FieldNoteTrainingAnnotation(label="structure", bbox=[100, 100, 300, 300])],
        ),
        source_image=image,
    )
    bundle = export_profile_bundle(profiles, training, profile.profile_id, tmp_path / "storm.fnp")

    imported_profiles = tmp_path / "profiles_imported"
    imported_training = tmp_path / "training_imported"
    imported = import_profile_bundle(imported_profiles, imported_training, bundle)
    assert imported.profile_id == profile.profile_id
    examples = list_training_examples(imported_training, imported.profile_id)
    assert len(examples) == 1
    assert examples[0].example_id == saved.example_id
    assert Path(examples[0].image_path).exists()


def test_importing_builtin_bundle_creates_non_destructive_custom_id(tmp_path: Path):
    profiles = tmp_path / "profiles"
    training = tmp_path / "training"
    ensure_default_field_note_profiles(profiles)
    bundle = export_profile_bundle(profiles, training, BRT_PROFILE_ID, tmp_path / "brt.fnp")
    imported = import_profile_bundle(profiles, training, bundle)
    assert imported.profile_id.startswith("BRT_STANDARD_CUSTOM")
    assert imported.profile_id != BRT_PROFILE_ID
    assert get_field_note_profile(profiles, BRT_PROFILE_ID).locked is True


def test_fnp_import_rejects_unsafe_member_path(tmp_path: Path):
    profiles = tmp_path / "profiles"
    training = tmp_path / "training"
    bad = tmp_path / "bad.fnp"
    profile = FieldNoteProfile(profile_id="BAD", name="Bad")
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("profile.json", profile.model_dump_json())
        zf.writestr("../escape.txt", "no")
    with pytest.raises(ValueError, match="unsafe path"):
        import_profile_bundle(profiles, training, bad)


def test_profile_aware_evidence_and_schema_fields():
    ev = PageEvidence(
        page_id="p1", source_name="book.pdf", page_number=1,
        point_id="1", matched_point_id="1", point_id_raw="1", status="REVIEW", dip_status="REVIEW",
        confidence=0.5, evidence="visible sketch", field_note_profile="CLIENT_CUSTOM",
        field_note_profile_confidence=0.82,
    )
    assert ev.field_note_profile == "CLIENT_CUSTOM"
    props = EXTRACTION_SCHEMA["properties"]["entries"]["items"]["properties"]
    assert "field_note_profile" in props
    assert "field_note_profile_confidence" in props


def test_fieldbook_ui_exposes_profile_trainer():
    html = Path("fieldbook_sync/static/index.html").read_text(encoding="utf-8")
    js = Path("fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    assert "Field Note Trainer" in html
    assert 'id="fieldNoteActiveProfile"' in html
    assert 'id="trainerOverlay"' in html
    assert 'id="saveTrainingExampleBtn"' in html
    assert "Teach this profile" in js
    assert "/api/field-note-profiles/import" in js
    assert "/teach-profile" in js
