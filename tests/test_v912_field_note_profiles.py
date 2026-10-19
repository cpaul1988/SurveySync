from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from fieldbook_sync import field_note_profiles
from fieldbook_sync.ai_reader import EXTRACTION_SCHEMA, system_prompt
from fieldbook_sync.field_note_profiles import (
    AUTO_PROFILE_ID,
    BRT_PROFILE_ID,
    BRT_PROFILE_VERSION,
    GENERIC_PROFILE_ID,
    build_profile_prompt,
    default_brt_profile,
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
from fieldbook_sync.interpret_cache import interpretation_cache_key
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


@pytest.mark.parametrize("selection", [BRT_PROFILE_ID, AUTO_PROFILE_ID])
def test_installed_brt_upgrade_reaches_prompt_and_preserves_local_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selection: str
):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    legacy = FieldNoteProfile(
        profile_id=BRT_PROFILE_ID,
        name="BRT Utility / Structure Notes",
        scope="built_in",
        locked=True,
        version=1,
        description="Previously installed BRT grammar",
        extraction_instructions=["Previous built-in grammar marker."],
        created_at="2026-01-01T12:00:00Z",
        updated_at="2026-01-02T12:00:00Z",
    )
    legacy_path = profiles / f"{BRT_PROFILE_ID}.json"
    legacy_path.write_text(legacy.model_dump_json(indent=2), encoding="utf-8")
    custom = FieldNoteProfile(
        profile_id="CLIENT_BRT_RULES",
        name="Client BRT rules",
        extraction_instructions=["Keep this client-defined convention unchanged."],
    )
    save_field_note_profile(profiles, custom)
    training = tmp_path / "training"
    image = tmp_path / "page.png"
    image.write_bytes(b"synthetic-storage-fixture")
    example = save_training_example(
        training,
        FieldNoteTrainingExample(
            profile_id=BRT_PROFILE_ID,
            source_name="PRIVATE EXAMPLE SOURCE",
            annotations=[
                FieldNoteTrainingAnnotation(
                    label="pipe_leader", bbox=[100, 200, 300, 400],
                    pipe_index=0, text="PRIVATE HANDWRITTEN VALUE",
                ),
            ],
            accepted_result={"notes": "PRIVATE ACCEPTED VALUE"},
        ),
        source_image=image,
    )
    stored = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    # Reproduce the previous installed grammar before its version upgrade. The
    # actual context, including local training hints, is part of the cache key.
    with monkeypatch.context() as previous_version:
        previous_version.setattr(field_note_profiles, "BRT_PROFILE_VERSION", 1)
        previous_context = build_profile_prompt(profiles, selection, training)
    context = build_profile_prompt(profiles, selection, training)
    composed_prompt = system_prompt(context)
    effective = get_field_note_profile(profiles, BRT_PROFILE_ID)
    current = default_brt_profile()

    assert effective.version == BRT_PROFILE_VERSION > legacy.version
    assert effective.created_at == legacy.created_at
    assert effective.updated_at == legacy.updated_at
    assert effective.symbols == current.symbols
    # This checks delivery through the real prompt budget/composition, so adding
    # an eleventh rule or truncating a long rule cannot silently drop a safeguard.
    for rule in current.extraction_instructions:
        assert rule in composed_prompt
    assert "Previous built-in grammar marker." not in composed_prompt
    assert "Learned from 1 locally labeled example" in composed_prompt
    for private_text in ("PRIVATE EXAMPLE SOURCE", "PRIVATE HANDWRITTEN VALUE", "PRIVATE ACCEPTED VALUE"):
        assert private_text not in composed_prompt
    assert interpretation_cache_key(
        image, point_id="42", model="local-test-model", profile_context=previous_context,
    ) != interpretation_cache_key(
        image, point_id="42", model="local-test-model", profile_context=context,
    )
    assert build_profile_prompt(profiles, selection, training) == context
    assert get_field_note_profile(profiles, custom.profile_id) == custom
    assert list_training_examples(training, BRT_PROFILE_ID) == [example]
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == stored


@pytest.mark.parametrize(
    ("scope", "locked", "version"),
    [
        ("custom", False, 1),
        ("custom", True, 1),
        ("built_in", False, 1),
        ("built_in", True, BRT_PROFILE_VERSION + 1),
    ],
)
def test_brt_upgrade_does_not_replace_custom_unlocked_or_future_grammar(
    tmp_path: Path, scope: str, locked: bool, version: int
):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    profile = FieldNoteProfile(
        profile_id=BRT_PROFILE_ID,
        name="Stored profile",
        scope=scope,
        locked=locked,
        version=version,
        extraction_instructions=["Preserve this independently owned or newer grammar."],
    )
    path = profiles / f"{BRT_PROFILE_ID}.json"
    path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    stored = path.read_bytes()

    assert get_field_note_profile(profiles, BRT_PROFILE_ID) == profile
    assert profile.extraction_instructions[0] in build_profile_prompt(profiles, BRT_PROFILE_ID)
    assert path.read_bytes() == stored


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
