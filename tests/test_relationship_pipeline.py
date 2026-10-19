"""Consumer and provenance checks around the measured-geometry pilot."""

from copy import deepcopy
import json

from PIL import Image, ImageDraw
import pytest

from fieldbook_sync.ai_reader import _entry_to_evidence
from fieldbook_sync.evidence_pipeline import apply_assessment
from fieldbook_sync.image_processing import crop_normalized_bbox
from fieldbook_sync.models import (
    AppState, EvidenceBasis, FieldBookPage, OcrCandidate, PageEvidence, PipeMeasurement, ResultRecord,
)
from fieldbook_sync.relationship_evidence import (
    analyze_page_relationships, apply_relationship_evidence, comparison_text_for_point,
    independent_anchors, map_crop_evidence_to_original, merge_text_regions,
    store_page_graphs, windows_text_regions,
)


TEXT = 'DIP 4.62 8" PVC AZ 90'


def candidate(**updates):
    values = dict(page_id="page-1", source_name="book", page_number=1, point_id="001",
                  raw_text="001", recognized_point_id="001", confidence=0.99,
                  bbox=[100, 200, 130, 230], engine="independent_ocr",
                  exact_match=True, source_view="original")
    values.update(updates)
    return OcrCandidate(**values)


def evidence(**updates):
    values = dict(matched_point_id="001", source_name="book", page_number=1,
                  page_id="page-1", point_id_confidence=0.99, dipped="YES",
                  basis=EvidenceBasis.MEASUREMENT, dipped_confidence=0.99,
                  evidence=TEXT, primary_engine="local_vision", model_agreement=True,
                  pipes=[PipeMeasurement(dip=4.62, diameter_in=8, material="PVC", azimuth_deg=90)])
    values.update(updates)
    return PageEvidence(**values)


def graph():
    return {
        "schema_version": 1, "status": "complete", "truncated": False, "review_only": True,
        "source": {"page_id": "page-1", "width": 800, "height": 600,
                   "pixel_sha256": "a" * 64, "coordinate_space": "original_normalized_0_1000"},
        "text_regions": [{"id": "text-1", "text": TEXT, "bbox": [300, 200, 500, 240]}],
        "paths": [{"id": "path-1", "points": [[160, 220], [295, 220]],
                   "endpoints": [[160, 220], [295, 220]], "bbox": [160, 219, 296, 222],
                   "branched": False, "evidence": "original_pixels",
                   "original_resolution_verified": True, "text_ids": ["text-1"],
                   "structure_ids": ["structure-1"]}],
        "structures": [{"id": "structure-1", "point_id": "001", "status": "supported"}],
        "associations": [{"text_id": "text-1", "point_id": "001", "structure_id": "structure-1",
                          "path_ids": ["path-1"], "status": "supported", "reasons": [],
                          "candidates": [{"structure_id": "structure-1", "point_id": "001",
                                          "path_ids": ["path-1"]}]}],
    }


def test_supported_pixel_proposal_is_retained_but_cannot_auto_accept_pipe():
    item, measured = evidence(), graph()
    apply_relationship_evidence(item, measured)
    assert item.relationship_status == "supported"
    assert item.pipes[0].association_path_ids == ["path-1"]
    assert item.pipes[0].association_text_ids == ["text-1"]
    assert item.pipes[0].source_page_id == "page-1"
    assessment = apply_assessment(candidate(), item, imported_point_ids=["001"])
    assert assessment.score >= 0.88
    assert assessment.decision == "REVIEW_DETAILS"
    assert "PIPE_BINDING_REVIEW_REQUIRED" in item.validation_flags


@pytest.mark.parametrize("change", [
    "partial", "truncated", "missing_truncated", "unavailable", "missing_status", "foreign_page",
])
def test_incomplete_or_foreign_graph_cannot_supply_support_or_comparison_text(change):
    measured = graph()
    if change in {"partial", "unavailable"}:
        measured["status"] = change
    elif change == "truncated":
        measured["truncated"] = True
    elif change == "missing_truncated":
        measured.pop("truncated")
    elif change == "missing_status":
        measured.pop("status")
    else:
        measured["source"]["page_id"] = "another-page"
    item = evidence(relationship_status="supported")
    item.pipes[0].association_status = "supported"
    apply_relationship_evidence(item, measured)
    assert item.relationship_status == "unverified"
    assert item.pipes[0].association_status == "unverified"
    assert "INCOMPLETE_OR_STALE_SPATIAL_EVIDENCE" in item.pipes[0].association_flags
    assert comparison_text_for_point(candidate(), measured) == "001"


@pytest.mark.parametrize("change", ["no_path_ids", "missing_path", "model_geometry", "unverified_pixels"])
def test_missing_or_unverified_original_path_is_not_evidence(change):
    measured = graph()
    if change == "no_path_ids":
        measured["associations"][0]["path_ids"] = []
    elif change == "missing_path":
        measured["paths"] = []
    elif change == "model_geometry":
        measured["paths"][0]["evidence"] = "vlm_leader_bbox"
    else:
        measured["paths"][0]["original_resolution_verified"] = False
    item = evidence()
    apply_relationship_evidence(item, measured)
    assert item.relationship_status == "unverified"
    assert item.pipes[0].association_status == "unverified"
    assert "NO_VERIFIED_ORIGINAL_INK_PATH" in item.pipes[0].association_flags
    assert comparison_text_for_point(candidate(), measured) == "001"


def test_measured_path_to_another_point_reports_conflict_and_preserves_alternative():
    measured = graph()
    measured["associations"][0]["point_id"] = "002"
    measured["associations"][0]["candidates"][0]["point_id"] = "002"
    item = evidence()
    apply_relationship_evidence(item, measured)
    assert item.relationship_status == "conflict"
    assert item.pipes[0].association_status == "conflict"
    assert "TEXT_PATH_REACHES_ANOTHER_POINTID" in item.pipes[0].association_flags
    assert item.spatial_evidence["associations"][0]["candidates"][0]["point_id"] == "002"
    assert comparison_text_for_point(candidate(), measured) == "001"
    outcome = apply_assessment(candidate(), item, imported_point_ids=["001", "002"])
    assert outcome.decision != "AUTO_ACCEPT"
    assert "PIPE_RELATIONSHIP_CONFLICT" in outcome.flags


def test_competing_observations_do_not_choose_the_first_matching_pipe():
    measured = graph()
    measured["text_regions"].append(dict(measured["text_regions"][0], id="text-2"))
    measured["associations"].append(dict(measured["associations"][0], text_id="text-2"))
    item = evidence()
    apply_relationship_evidence(item, measured)
    assert item.pipes[0].association_status == "ambiguous"
    assert item.pipes[0].association_text_ids == ["text-1", "text-2"]
    assert "COMPETING_TEXT_RECORDS" in item.pipes[0].association_flags


def test_same_text_record_cannot_prove_two_extracted_pipes():
    item = evidence()
    item.pipes.append(item.pipes[0].model_copy(deep=True))
    apply_relationship_evidence(item, graph())
    assert all(pipe.association_status == "ambiguous" for pipe in item.pipes)


def test_absent_graph_resets_derived_status_without_changing_raw_measurements():
    item = evidence(relationship_status="supported")
    item.pipes[0].association_status = "supported"
    item.pipes[0].association_path_ids = ["stale-path"]
    apply_relationship_evidence(item, None)
    assert item.relationship_status == "unverified"
    assert item.pipes[0].association_path_ids == []
    assert item.pipes[0].dip == 4.62 and item.pipes[0].diameter_in == 8


def test_model_cannot_supply_local_proofs_qc_or_network_metadata():
    source = FieldBookPage(page_id="page-1", source_name="book", page_number=1,
                           image_path="unused.png", mime_type="image/png")
    supplied = {
        "point_id": "001", "dipped": "YES", "basis": "MEASUREMENT",
        "dipped_confidence": 1, "evidence": TEXT,
        "relationship_status": "supported", "spatial_evidence": graph(),
        "spatial_evidence_key": "forged-proof-reference",
        "numerical_agreement": True, "pipe_record_agreement": True,
        "model_agreement": True, "evidence_decision": "AUTO_ACCEPT", "evidence_score": 1,
        "validation_flags": [], "primary_engine": "forged-independent-proof",
        "pipes": [{"dip": 4.62, "dip_raw": "4.62", "diameter_in": 8, "material": "PVC",
                   "azimuth_deg": 90, "leader_bbox": [100, 200, 400, 300],
                   "connected_point_raw": "002", "connected_point_id": "002",
                   "connection_score": 1, "invert_elevation": 123.45, "qc_flags": ["passed"],
                   "source_page_id": "fake", "association_status": "supported",
                   "association_text_ids": ["forged-text"], "association_path_ids": ["forged-path"],
                   "association_flags": ["AUTO_ACCEPT"]}],
    }
    before = deepcopy(supplied)
    item, unmatched = _entry_to_evidence(supplied, page=source, target_set={"001"})
    assert unmatched is None and item is not None
    assert item.spatial_evidence == {} and item.relationship_status == "unverified"
    assert item.spatial_evidence_key == ""
    assert item.model_agreement is None and item.numerical_agreement is None
    assert item.pipe_record_agreement is None and item.evidence_decision == ""
    assert item.primary_engine is None and item.evidence_score == 0
    pipe = item.pipes[0]
    assert pipe.association_status == "unverified" and pipe.association_path_ids == []
    assert pipe.association_text_ids == [] and pipe.association_flags == []
    assert pipe.source_page_id is None and pipe.connected_point_id is None
    assert pipe.connection_score is None and pipe.invert_elevation is None and pipe.qc_flags == []
    assert pipe.connected_point_raw == "002" and pipe.dip_raw == "4.62"
    assert pipe.leader_bbox == [100, 200, 400, 300]  # retained as a model observation only
    assert supplied == before


@pytest.mark.parametrize("basis,pipes", [
    (EvidenceBasis.MEASUREMENT, []),
    (EvidenceBasis.EXPLICIT_YES, [PipeMeasurement(dip=4.62)]),
])
def test_pipe_gate_cannot_be_bypassed_by_empty_records_or_status_basis(basis, pipes):
    item = evidence(basis=basis, pipes=pipes, relationship_status="supported",
                    pipe_record_agreement=True, numerical_agreement=True)
    outcome = apply_assessment(candidate(), item, imported_point_ids=["001"])
    assert outcome.decision != "AUTO_ACCEPT"
    assert "PIPE_BINDING_REVIEW_REQUIRED" in outcome.flags
    if not pipes:
        assert "PIPE_RECORDS_MISSING" in outcome.flags


def test_explicit_nonmeasurement_status_keeps_existing_high_quality_gate():
    item = evidence(basis=EvidenceBasis.EXPLICIT_YES, pipes=[], evidence="Explicitly dipped")
    outcome = apply_assessment(candidate(), item, imported_point_ids=["001"])
    assert outcome.decision == "AUTO_ACCEPT"
    assert "PIPE_BINDING_REVIEW_REQUIRED" not in outcome.flags


def test_original_crop_mapping_uses_actual_padding_and_non_square_dimensions(tmp_path):
    source = tmp_path / "page.png"
    crop = tmp_path / "crop.jpg"
    Image.new("RGB", (1000, 500), "white").save(source)
    before = source.read_bytes()
    region = [200, 200, 600, 600]
    crop_normalized_bbox(source, region, crop, padding=0.08)
    with Image.open(crop) as cropped:
        assert cropped.size == (464, 240)
    item = evidence(bbox=[0, 0, 1000, 1000], structure_bbox=[100, 100, 400, 400])
    item.pipes[0].leader_bbox = [250, 250, 750, 750]
    map_crop_evidence_to_original(item, source, region, cropped=True)
    assert item.bbox == [168, 160, 632, 640]
    assert item.structure_bbox == [214, 208, 354, 352]
    assert item.pipes[0].leader_bbox == [284, 280, 516, 520]
    assert item.pipes[0].association_status == "unverified"
    assert source.read_bytes() == before


def test_exif_oriented_crop_and_remap_share_the_same_page_frame(tmp_path):
    source = tmp_path / "rotated.jpg"
    crop = tmp_path / "crop.jpg"
    image = Image.new("RGB", (400, 800), "white")
    exif = image.getexif()
    exif[274] = 6
    image.save(source, exif=exif)
    before = source.read_bytes()
    region = [200, 200, 600, 600]
    crop_normalized_bbox(source, region, crop, padding=0.08)
    with Image.open(crop) as cropped:
        assert cropped.size == (370, 200)
    item = evidence(bbox=[0, 0, 1000, 1000])
    map_crop_evidence_to_original(item, source, region, cropped=True)
    assert item.bbox == [169, 150, 631, 650]
    assert source.read_bytes() == before


def test_uncropped_evidence_is_not_remapped(tmp_path):
    item = evidence(bbox=[200, 100, 400, 300], structure_bbox=[100, 100, 300, 300])
    before = item.model_dump()
    map_crop_evidence_to_original(item, tmp_path / "not-needed.png", [200, 200, 600, 600], cropped=False)
    assert item.model_dump() == before


def test_duplicate_original_and_cleaned_observations_keep_both_provenances():
    payload = {"width": 800, "height": 600,
               "lines": [{"text": TEXT, "polygon": [[100, 100], [200, 100], [200, 130], [100, 130]]}]}
    original = windows_text_regions(payload, view="original")
    cleaned = windows_text_regions(payload, view="cleaned")
    joined = merge_text_regions(original + cleaned)
    assert len(joined) == 1
    assert {o["source_view"] for o in joined[0]["observations"]} == {"original", "cleaned"}
    assert original[0]["source_view"] == "original"


def test_different_ocr_readings_are_retained_as_competing_observations():
    first = windows_text_regions({"width": 800, "height": 600, "lines": [
        {"text": TEXT, "polygon": [100, 100, 200, 130]}]})
    second = windows_text_regions({"width": 800, "height": 600, "lines": [
        {"text": 'DIP 4.82 8" PVC AZ 90', "polygon": [100, 100, 200, 130]}]}, view="cleaned")
    joined = merge_text_regions(first + second)
    assert len(joined) == 2 and len({r["text"] for r in joined}) == 2


def test_anchor_adapter_does_not_promote_fuzzy_tokens_or_context_boxes():
    good = candidate()
    values = [good, good.model_copy(update={"source_view": "cleaned"}),
              candidate(point_id="002", recognized_point_id="02"),
              candidate(point_id="003", recognized_point_id="003", exact_match=False),
              candidate(point_id="004", recognized_point_id="004", bbox=[0, 0, 700, 700])]
    anchors = independent_anchors(values)
    assert len(anchors) == 1 and anchors[0]["point_id"] == "001"
    assert anchors[0]["raw_text"] == "001"


def test_pipeline_uses_original_pixels_and_keeps_a_supported_proposal_in_review(tmp_path):
    source, cleaned = tmp_path / "original.png", tmp_path / "cleaned.png"
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((80, 140, 160, 220), outline="black", width=3)
    draw.text((107, 175), "001", fill="black")
    draw.text((285, 175), TEXT, fill="black")
    draw.line((159, 180, 281, 180), fill="black", width=3)
    image.save(source)
    Image.new("RGB", image.size, "white").save(cleaned)  # no measured geometry in derivative
    page = FieldBookPage(page_id="page-1", source_name="book", page_number=1,
                         image_path=str(source), enhanced_image_path=str(cleaned), mime_type="image/png")
    anchor = candidate(bbox=[130, 285, 171, 320])
    regions = [{"id": "text-1", "text": TEXT, "bbox": [356, 288, 563, 325], "source": "ocr"}]
    before = source.read_bytes()
    measured = analyze_page_relationships(page, regions, [anchor])
    assert measured["status"] == "complete", measured
    assert measured["associations"][0]["status"] == "supported", measured
    item = evidence()
    apply_relationship_evidence(item, measured)
    assert item.relationship_status == "supported"
    assert comparison_text_for_point(anchor, measured) == TEXT
    assert apply_assessment(anchor, item, imported_point_ids=["001"]).decision != "AUTO_ACCEPT"
    assert source.read_bytes() == before


def test_pipeline_translates_spatial_cancellation_without_reporting_success(monkeypatch):
    from fieldbook_sync import vision_pipeline
    from fieldbook_sync.ocr_local import PaddleCancelled
    from fieldbook_sync.spatial_association import SpatialCancelled

    def cancel(*args, **kwargs):
        raise SpatialCancelled("cancelled")

    monkeypatch.setattr(vision_pipeline, "analyze_page_relationships", cancel)
    page = FieldBookPage(page_id="page-1", source_name="book", page_number=1,
                         image_path="unused.png", mime_type="image/png")
    with pytest.raises(PaddleCancelled):
        vision_pipeline._page_spatial_graph(page, [], [], lambda: True)


def test_canonical_graph_roundtrip_stores_once_and_keeps_all_ambiguous_alternatives():
    from fieldbook_sync.benchmark_export import benchmark_payload

    measured = graph()
    measured["sentinel"] = "one canonical page graph"
    measured["associations"][0]["status"] = "ambiguous"
    measured["associations"][0]["candidates"].append({
        "structure_id": "structure-2", "point_id": "002", "path_ids": ["path-2"]})
    measured["paths"].append(dict(measured["paths"][0], id="path-2"))
    measured["structures"].append({"id": "structure-2", "point_id": "002", "status": "supported"})
    items = [evidence() for _ in range(12)]
    for item in items:
        apply_relationship_evidence(item, measured)
    assert all(item.spatial_evidence is measured for item in items)
    canonical = store_page_graphs(items)
    assert len(canonical) == 1
    key = next(iter(canonical))
    assert all(item.spatial_evidence == {} and item.spatial_evidence_key == key for item in items)
    assert all(item.relationship_status == "ambiguous" for item in items)
    state = AppState(spatial_graphs=canonical,
                     results=[ResultRecord(point_id="001", code="MH", evidence_records=items)])
    encoded = state.model_dump_json()
    assert encoded.count("one canonical page graph") == 1
    restored = AppState.model_validate_json(encoded)
    assert len(restored.spatial_graphs[key]["associations"][0]["candidates"]) == 2
    assert len(restored.spatial_graphs[key]["paths"]) == 2
    assert all(item.spatial_evidence_key == key and item.spatial_evidence == {}
               for item in restored.results[0].evidence_records)
    exported = benchmark_payload(restored)
    assert exported["spatial_graphs"][key] == canonical[key]
    assert exported["results"][0]["evidence_records"][0]["spatial_evidence_key"] == key


def test_identical_graph_content_deduplicates_even_when_instances_differ():
    first, second = evidence(), evidence()
    apply_relationship_evidence(first, graph())
    apply_relationship_evidence(second, graph())
    assert first.spatial_evidence is not second.spatial_evidence
    canonical = store_page_graphs([first, second])
    assert len(canonical) == 1 and first.spatial_evidence_key == second.spatial_evidence_key


def test_serialized_byte_budget_abstains_globally_without_silent_candidate_pruning():
    measured = graph()
    measured["unicode_diagnostic"] = "深" * 1800
    encoded_bytes = len(json.dumps(measured, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8"))
    exact = evidence()
    apply_relationship_evidence(exact, measured)
    complete = store_page_graphs([exact], max_graph_bytes=encoded_bytes)
    assert complete[exact.spatial_evidence_key]["status"] == "complete"
    items = [evidence(), evidence()]
    for item in items:
        apply_relationship_evidence(item, measured)
        assert item.relationship_status == "supported"
    canonical = store_page_graphs(items, max_graph_bytes=encoded_bytes - 1)
    assert len(canonical) == 1
    partial = next(iter(canonical.values()))
    assert partial["status"] == "partial" and partial["truncated"] is True
    assert partial["flags"] == ["serialized_graph_budget"]
    assert not partial["paths"] and not partial["associations"]
    assert all(item.relationship_status == "unverified" and item.pipes[0].association_status == "unverified"
               for item in items)
    assert all("INCOMPLETE_OR_STALE_SPATIAL_EVIDENCE" in item.pipes[0].association_flags for item in items)
    assert all(item.pipes[0].dip == 4.62 for item in items)
    assert measured["status"] == "complete" and measured["associations"]


def two_pipe_graph():
    measured = graph()
    measured["paths"][0].update(points=[[160, 300], [450, 300]],
                                endpoints=[[160, 300], [450, 300]], bbox=[160, 299, 451, 302])
    measured["text_regions"][0]["bbox"] = [450, 290, 620, 320]
    measured["text_regions"].append({"id": "text-2", "text": 'DIP 6.28 12" RCP AZ 180',
                                      "bbox": [450, 590, 620, 620]})
    second_path = deepcopy(measured["paths"][0])
    second_path.update(id="path-2", points=[[160, 600], [450, 600]],
                       endpoints=[[160, 600], [450, 600]], bbox=[160, 599, 451, 602],
                       text_ids=["text-2"])
    measured["paths"].append(second_path)
    measured["associations"].append({
        "text_id": "text-2", "point_id": "001", "structure_id": "structure-1",
        "path_ids": ["path-2"], "status": "supported", "reasons": [], "candidates": []})
    return measured


def test_whole_pipe_tuples_swapped_between_fixed_leader_regions_are_conflicts():
    upper_box, lower_box = [140, 270, 470, 330], [140, 570, 470, 630]
    # All values exist on the page, but each whole tuple was put on the other leader.
    pipes = [PipeMeasurement(dip=6.28, diameter_in=12, material="RCP", azimuth_deg=180,
                             leader_bbox=upper_box),
             PipeMeasurement(dip=4.62, diameter_in=8, material="PVC", azimuth_deg=90,
                             leader_bbox=lower_box)]
    item = evidence(pipes=pipes)
    apply_relationship_evidence(item, two_pipe_graph())
    assert item.relationship_status == "conflict"
    assert all(pipe.association_status == "conflict" for pipe in item.pipes)
    assert item.pipes[0].leader_bbox == upper_box and item.pipes[1].leader_bbox == lower_box
    assert item.pipes[0].dip == 6.28 and item.pipes[1].dip == 4.62
    outcome = apply_assessment(candidate(), item, imported_point_ids=["001"])
    assert outcome.decision != "AUTO_ACCEPT" and "PIPE_RELATIONSHIP_CONFLICT" in outcome.flags


def test_matching_tuple_and_fixed_leader_region_remain_review_proposals():
    pipes = [PipeMeasurement(dip=4.62, diameter_in=8, material="PVC", azimuth_deg=90,
                             leader_bbox=[140, 270, 470, 330]),
             PipeMeasurement(dip=6.28, diameter_in=12, material="RCP", azimuth_deg=180,
                             leader_bbox=[140, 570, 470, 630])]
    item = evidence(pipes=pipes)
    apply_relationship_evidence(item, two_pipe_graph())
    assert item.relationship_status == "supported"
    assert [pipe.association_path_ids for pipe in item.pipes] == [["path-1"], ["path-2"]]
    assert apply_assessment(candidate(), item, imported_point_ids=["001"]).decision != "AUTO_ACCEPT"


def test_context_region_covering_competing_leaders_cannot_choose_by_values():
    item = evidence()
    original_box = [100, 200, 650, 700]
    item.pipes[0].leader_bbox = original_box
    apply_relationship_evidence(item, two_pipe_graph())
    assert item.relationship_status == "ambiguous"
    assert item.pipes[0].association_status == "ambiguous"
    assert item.pipes[0].leader_bbox == original_box


def test_value_matched_path_does_not_fill_a_missing_model_region():
    item = evidence()
    assert item.pipes[0].leader_bbox is None
    apply_relationship_evidence(item, graph())
    assert item.pipes[0].association_status == "supported"
    assert item.pipes[0].leader_bbox is None
