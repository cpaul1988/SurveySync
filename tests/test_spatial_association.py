"""Synthetic geometry checks, not accuracy claims for handwritten field books."""

from dataclasses import replace
import hashlib
import json

from PIL import Image, ImageDraw
import pytest

from fieldbook_sync.spatial_association import (
    SpatialCancelled, SpatialLimits, associate_page_geometry,
)


SIZE = (800, 600)


def bbox(box):
    return [box[0] * 1000 / SIZE[0], box[1] * 1000 / SIZE[1],
            box[2] * 1000 / SIZE[0], box[3] * 1000 / SIZE[1]]


def page():
    return Image.new("RGB", SIZE, "white")


def circle(image, center, point_id="001", ident="a1", radius=40):
    x, y = center
    draw = ImageDraw.Draw(image)
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline="black", width=3)
    draw.text((x - 13, y - 5), point_id, fill="black")
    return {"id": ident, "point_id": point_id, "raw_text": point_id,
            "bbox": bbox((x - 16, y - 9, x + 17, y + 12)),
            "source": "independent_ocr", "exact_match": True, "independent": True}


def note(image, position, ident="t1", text="150 PVC"):
    x, y = position
    ImageDraw.Draw(image).text((x, y), text, fill="black")
    return {"id": ident, "text": text, "bbox": bbox((x, y - 2, x + 55, y + 14)),
            "source": "ocr"}


def analyze(image, texts, anchors, **kwargs):
    return associate_page_geometry(image, page_id="page-1", text_regions=texts,
                                   point_anchors=anchors,
                                   limits=kwargs.pop("limits", SpatialLimits(max_seconds=30)),
                                   **kwargs)


def simple_scene():
    image = page()
    anchor = circle(image, (120, 180))
    text = note(image, (285, 175))
    ImageDraw.Draw(image).line((159, 180, 281, 180), fill="black", width=3)
    return image, text, anchor


def test_original_line_supports_exact_id_without_mutating_pixels():
    image, text, anchor = simple_scene()
    before = image.tobytes()
    output = analyze(image, [text], [anchor])
    assert output["status"] == "complete"
    assert output["review_only"] is True
    match = output["associations"][0]
    assert match["status"] == "supported", output
    assert match["point_id"] == "001"
    assert len(match["path_ids"]) == 1
    path = output["paths"][0]
    assert path["evidence"] == "original_pixels" and path["points"]
    assert len(path["endpoints"]) == 2 and not path["branched"]
    assert path["points"][0] in path["endpoints"]
    assert path["points"][-1] in path["endpoints"]
    assert all(0 <= value <= 1000 for point in path["points"] for value in point)
    expected = hashlib.sha256(f"RGB:{SIZE[0]}x{SIZE[1]}:".encode() + before).hexdigest()
    assert output["source"]["pixel_sha256"] == expected
    assert image.tobytes() == before
    json.dumps(output, allow_nan=False)


def test_visible_path_beats_nearer_unconnected_structure():
    image = page()
    target = circle(image, (120, 300), "001", "a1")
    nearer = circle(image, (420, 245), "002", "a2")
    text = note(image, (420, 295))
    ImageDraw.Draw(image).line((159, 300, 416, 300), fill="black", width=3)
    output = analyze(image, [text], [target, nearer])
    assert output["associations"][0]["point_id"] == "001", output
    assert output["associations"][0]["status"] == "supported"


def test_adjacent_separate_leaders_retain_distinct_ids():
    image = page()
    anchors = [circle(image, (120, 150), "001", "a1"),
               circle(image, (120, 250), "002", "a2")]
    texts = [note(image, (350, 145), "t1"), note(image, (350, 245), "t2")]
    draw = ImageDraw.Draw(image)
    draw.line((159, 150, 346, 150), fill="black", width=3)
    draw.line((159, 250, 346, 250), fill="black", width=3)
    output = analyze(image, texts, anchors)
    assert [(a["status"], a["point_id"]) for a in output["associations"]] == [
        ("supported", "001"), ("supported", "002")], output


def test_crossing_leaders_abstain_even_with_exact_ids():
    image = page()
    anchors = [circle(image, (120, 150), "001", "a1"),
               circle(image, (120, 350), "002", "a2")]
    texts = [note(image, (410, 145), "t1"), note(image, (410, 345), "t2")]
    draw = ImageDraw.Draw(image)
    draw.line([(159, 150), (405, 350)], fill="black", width=3)
    draw.line([(159, 350), (405, 150)], fill="black", width=3)
    output = analyze(image, texts, anchors)
    assert output["paths"], output
    assert all(a["status"] == "ambiguous" and a["point_id"] is None
               for a in output["associations"]), output
    assert any(p["branched"] for p in output["paths"])
    assert all("crossing_or_branched_ink" in a["reasons"] for a in output["associations"])


def test_broken_leader_does_not_get_a_nearest_only_binding():
    image, text, anchor = simple_scene()
    ImageDraw.Draw(image).rectangle((216, 175, 223, 185), fill="white")
    output = analyze(image, [text], [anchor])
    assert output["associations"][0]["status"] == "unresolved", output
    assert output["associations"][0]["point_id"] is None


def test_note_beside_structure_end_is_not_linked_through_wrong_terminal():
    image = page()
    anchor = circle(image, (120, 180))
    text = note(image, (164, 161))
    ImageDraw.Draw(image).line((159, 180, 281, 180), fill="black", width=3)
    output = analyze(image, [text], [anchor])
    assert output["associations"][0]["status"] != "supported", output
    assert "no_opposite_terminal_evidence" in output["associations"][0]["reasons"]


def test_native_resolution_verification_supports_intact_downsampled_page():
    image, text, anchor = simple_scene()
    image = image.resize((2400, 1800), Image.Resampling.NEAREST)
    output = analyze(image, [text], [anchor])
    assert output["associations"][0]["status"] == "supported", output
    assert output["paths"][0]["original_resolution_verified"] is True


def test_native_resolution_check_rejects_gap_lost_by_downsampling():
    image, text, anchor = simple_scene()
    image = image.resize((2400, 1800), Image.Resampling.NEAREST)
    ImageDraw.Draw(image).line((660, 525, 660, 555), fill="white", width=1)
    output = analyze(image, [text], [anchor])
    assert output["associations"][0]["status"] != "supported", output
    assert output["associations"][0]["point_id"] is None


def test_disconnected_stroke_next_to_circle_does_not_become_contact():
    image = page()
    anchor = circle(image, (120, 180))
    text = note(image, (285, 175))
    # A small real white gap between circle and leader must remain a gap.
    ImageDraw.Draw(image).line((163, 180, 281, 180), fill="black", width=3)
    output = analyze(image, [text], [anchor])
    assert output["associations"][0]["status"] == "unresolved", output


def test_multiple_exact_ids_in_one_structure_remain_ambiguous():
    image, text, first = simple_scene()
    second = dict(first, id="a2", point_id="002", raw_text="002")
    output = analyze(image, [text], [first, second])
    assert output["structures"][0]["candidate_point_ids"] == ["001", "002"]
    assert output["associations"][0]["status"] == "ambiguous"
    assert output["associations"][0]["point_id"] is None


def test_same_id_in_separate_structures_does_not_become_unique():
    image = page()
    anchors = [circle(image, (120, 150), "001", "a1"),
               circle(image, (120, 300), "001", "a2")]
    text = note(image, (350, 145))
    ImageDraw.Draw(image).line((159, 150, 346, 150), fill="black", width=3)
    output = analyze(image, [text], anchors)
    assert output["associations"][0]["status"] == "ambiguous", output
    assert all(s["status"] == "ambiguous" for s in output["structures"])


@pytest.mark.parametrize("change", [
    {"independent": False}, {"exact_match": False}, {"raw_text": "1"},
    {"raw_text": "point 001"}, {"source": ""},
])
def test_anchor_requires_independent_exact_token_and_keeps_leading_zeros(change):
    image, text, anchor = simple_scene()
    anchor.update(change)
    output = analyze(image, [text], [anchor])
    assert output["associations"][0]["status"] != "supported", output
    assert output["associations"][0]["point_id"] is None


def test_duplicate_independent_readings_inside_same_loop_are_allowed():
    image, text, anchor = simple_scene()
    duplicate = dict(anchor, id="a2", source="second_independent_ocr")
    output = analyze(image, [text], [anchor, duplicate])
    assert output["associations"][0]["point_id"] == "001", output


def test_competing_text_regions_at_same_endpoint_are_ambiguous():
    image, text, anchor = simple_scene()
    output = analyze(image, [text, dict(text, id="t2", text="other note")], [anchor])
    assert all(a["status"] == "ambiguous" for a in output["associations"]), output
    assert all("competing_text_regions" in a["reasons"] for a in output["associations"])


def test_vlm_context_boxes_cannot_supply_missing_geometry():
    image = page()
    text = note(image, (285, 175))
    anchor = {"id": "a1", "point_id": "001", "raw_text": "001",
              "bbox": bbox((100, 160, 130, 180)), "source": "independent_ocr",
              "exact_match": True, "independent": True}
    hints = [{"id": "vlm-context", "bbox": [0, 0, 900, 900],
              "leader_bbox": [0, 0, 900, 900], "source": "vlm"}]
    output = analyze(image, [text], [anchor], structure_hints=hints)
    assert not output["structures"] and not output["paths"]
    assert output["associations"][0]["status"] == "unresolved"


def test_context_sized_text_box_is_not_a_local_note():
    image, text, anchor = simple_scene()
    text["bbox"] = [0, 0, 900, 900]
    output = analyze(image, [text], [anchor])
    assert output["associations"][0]["status"] == "unresolved"
    assert output["associations"][0]["reasons"] == ["nonlocal_context_box"]


@pytest.mark.parametrize("bad_box", [
    [-1, 10, 20, 30], [0, 0, 1001, 20], [10, 20, 10, 30], [20, 20, 10, 30],
    [0, 0, float("nan"), 30], [0, 0, float("inf"), 30], [True, 0, 10, 10], [0, 0, 10],
])
def test_invalid_coordinates_fail_explicitly(bad_box):
    image, text, anchor = simple_scene()
    text["bbox"] = bad_box
    with pytest.raises(ValueError):
        analyze(image, [text], [anchor])


def test_budget_exhaustion_demotes_all_partial_results():
    image = page()
    anchors = [circle(image, (120, 150), "001", "a1"),
               circle(image, (120, 300), "002", "a2")]
    texts = [note(image, (350, 145), "t1"), note(image, (350, 295), "t2")]
    draw = ImageDraw.Draw(image)
    draw.line((159, 150, 346, 150), fill="black", width=3)
    draw.line((159, 300, 346, 300), fill="black", width=3)
    output = analyze(image, texts, anchors,
                     limits=replace(SpatialLimits(max_seconds=30), max_paths=1))
    assert output["status"] == "partial" and output["truncated"] is True
    assert "path_count_budget" in output["flags"]
    assert all(a["status"] == "unresolved" and a["point_id"] is None
               for a in output["associations"])
    assert all(s["status"] == "unresolved" for s in output["structures"])


@pytest.mark.parametrize("changes,flag", [
    ({"max_original_pixels": 100}, "original_pixel_budget"),
    ({"max_runs": 10}, "component_run_budget"),
    ({"max_text_regions": 1}, "input_record_budget"),
])
def test_hard_input_and_work_bounds(changes, flag):
    image, text, anchor = simple_scene()
    texts = [text, dict(text, id="t2")]
    output = analyze(image, texts, [anchor],
                     limits=replace(SpatialLimits(max_seconds=30), **changes))
    assert output["status"] == "partial" and flag in output["flags"]
    assert not any(a["status"] == "supported" for a in output["associations"])


def test_cancellation_is_checked_during_processing_without_mutation():
    image, text, anchor = simple_scene()
    before = image.tobytes()
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls >= 12

    with pytest.raises(SpatialCancelled):
        analyze(image, [text], [anchor], cancelled=cancelled)
    assert calls == 12
    assert image.tobytes() == before


def test_time_budget_cannot_return_supported(monkeypatch):
    from fieldbook_sync import spatial_association
    now = 0.0

    def clock():
        nonlocal now
        now += 0.1
        return now

    monkeypatch.setattr(spatial_association.time, "monotonic", clock)
    image, text, anchor = simple_scene()
    output = analyze(image, [text], [anchor], limits=SpatialLimits(max_seconds=0.3))
    assert output["status"] == "partial" and "time_budget" in output["flags"]
    assert not any(a["status"] == "supported" for a in output["associations"])
