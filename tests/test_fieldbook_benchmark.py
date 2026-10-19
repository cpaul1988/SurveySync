"""Synthetic contracts for scoring saved evidence, not OCR performance tests."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

from scripts import benchmark_fieldbook as benchmark


def gold_page():
    return {
        "schema_version": 1,
        "page_id": "synthetic-page",
        "source_sha256": None,
        "structures_complete": True,
        "dip_unit": "ft",
        "structures": [
            {
                "structure_id": "structure-a",
                "point_id": "0001",
                "pipes_complete": True,
                "dip_status": "YES",
                "pipes": [
                    {
                        "pipe_id": "east-pipe",
                        "leader_bbox": [100, 100, 200, 130],
                        "fields": {
                            "dip": 4.2,
                            "diameter_in": 8,
                            "material": "PVC",
                            "azimuth_deg": 90,
                            "connected_point_raw": None,
                        },
                    },
                    {
                        "pipe_id": "west-pipe",
                        "leader_bbox": [300, 100, 400, 130],
                        "fields": {
                            "dip": 6.3,
                            "diameter_in": 12,
                            "material": "RCP",
                            "azimuth_deg": 270,
                            "connected_point_raw": "0002",
                        },
                    },
                ],
            }
        ],
    }


def evidence(page=None):
    page = page or gold_page()
    structure = page["structures"][0]
    return {
        "page_id": page["page_id"],
        "matched_point_id": structure["point_id"],
        "dipped": structure.get("dip_status"),
        "evidence_decision": "AUTO_ACCEPT",
        "pipes": [
            {"leader_bbox": pipe["leader_bbox"], **pipe["fields"]}
            for pipe in deepcopy(structure["pipes"])
        ],
    }


def project_export(record=None, **overrides):
    record = record or evidence()
    return {
        "results": [
            {
                "point_id": record["matched_point_id"],
                "review_state": "UNREVIEWED",
                "manually_overridden": False,
                "evidence_records": [record],
            }
        ],
        **overrides,
    }


def score(page=None, records=None, **kwargs):
    pages = page if isinstance(page, list) else [page or gold_page()]
    gold = benchmark.parse_gold("\n".join(json.dumps(p) for p in pages))
    predictions, _, _ = benchmark.parse_predictions(
        "\n".join(json.dumps(p) for p in (records if records is not None else [evidence()])),
        jsonl=True,
    )
    return benchmark.score(gold, predictions, **kwargs)


def test_perfect_records_match_by_geometry_even_if_prediction_order_changes():
    record = evidence()
    record["pipes"].reverse()
    record["pipes"][1]["material"] = "pvc"
    result = score(records=[record])
    for metric in (
        "exact_point_id_precision",
        "exact_point_id_recall",
        "labelled_pipe_binding_accuracy",
        "complete_pipe_record_accuracy",
        "complete_structure_record_accuracy",
    ):
        assert result[metric]["value"] == 1
    assert result["false_auto_accept_rate"] == {"numerator": 0, "denominator": 1, "value": 0}


@pytest.mark.parametrize("field", ["dip", "diameter_in", "azimuth_deg", "material"])
def test_same_page_value_bag_does_not_hide_swapped_pipe_values(field):
    record = evidence()
    before = [p[field] for p in record["pipes"]]
    record["pipes"][0][field], record["pipes"][1][field] = reversed(before)
    assert sorted(before) == sorted(p[field] for p in record["pipes"])
    result = score(records=[record])
    assert result["exact_point_id_recall"]["value"] == 1
    assert result["pipe_spatial_match_recall"]["value"] == 1
    assert result["labelled_pipe_binding_accuracy"]["value"] == 0
    assert result["complete_pipe_record_accuracy"]["value"] == 0
    assert result["complete_structure_record_accuracy"]["value"] == 0
    assert result["field_accuracy"][field]["value"] == 0
    assert result["false_auto_accept_rate"]["value"] == 1


def test_missing_prediction_geometry_fails_eligible_binding_denominator():
    record = evidence()
    for pipe in record["pipes"]:
        pipe.pop("leader_bbox")
    result = score(records=[record])
    assert result["pipe_spatial_match_recall"] == {"numerator": 0, "denominator": 2, "value": 0}
    assert result["labelled_pipe_binding_accuracy"]["value"] == 0
    assert result["false_auto_accept_rate"]["value"] == 1


def test_many_predictions_for_one_gold_pipe_abstain_from_ambiguous_pair():
    record = evidence()
    record["pipes"].append(deepcopy(record["pipes"][0]))
    result = score(records=[record])
    assert result["labelled_pipe_binding_accuracy"]["value"] == 0.5
    assert result["complete_structure_record_accuracy"]["value"] == 0


def test_one_prediction_cannot_match_two_gold_pipes():
    record = evidence()
    record["pipes"] = [record["pipes"][0]]
    record["pipes"][0]["leader_bbox"] = [90, 90, 410, 140]
    result = score(records=[record], min_iou=0.1)
    assert result["pipe_spatial_match_recall"]["value"] == 0
    assert result["labelled_pipe_binding_accuracy"]["denominator"] == 2


def test_exact_point_ids_preserve_leading_zeros_and_missing_predictions():
    record = evidence()
    record["matched_point_id"] = "1"
    result = score(records=[record])
    assert result["exact_point_id_precision"]["value"] == 0
    assert result["exact_point_id_recall"]["value"] == 0
    assert result["counts"]["point_fp"] == 1
    assert result["labelled_pipe_binding_accuracy"]["value"] == 0
    empty = score(records=[])
    assert empty["exact_point_id_precision"]["value"] is None
    assert empty["exact_point_id_recall"]["value"] == 0
    assert empty["review_rate"]["value"] is None


def test_unlabelled_fields_are_not_zero_denominators_or_assumed_correct():
    page = gold_page()
    structure = page["structures"][0]
    structure.pop("dip_status")
    structure["pipes_complete"] = False
    for pipe in structure["pipes"]:
        pipe["fields"] = {"dip": pipe["fields"]["dip"]}
    result = score(page=page)
    assert result["field_accuracy"]["dip"]["denominator"] == 2
    assert result["field_accuracy"]["diameter_in"]["value"] is None
    assert result["complete_pipe_record_accuracy"]["value"] is None
    assert result["complete_structure_record_accuracy"]["value"] is None
    assert result["false_auto_accept_rate"]["value"] is None
    assert result["counts"]["auto_accept_unassessed"] == 1


def test_verified_absence_is_not_an_unknown_field():
    record = evidence()
    record["pipes"][0].pop("connected_point_raw")
    result = score(records=[record])
    assert result["field_accuracy"]["connected_point_raw"]["value"] == 0.5
    assert result["complete_pipe_record_accuracy"]["value"] == 0.5
    assert result["false_auto_accept_rate"]["value"] == 1


def test_unlabelled_geometry_excluded_and_unknown_point_labels_stay_unassessed():
    page = gold_page()
    page["structures"][0]["pipes"][0]["leader_bbox"] = None
    result = score(page=page)
    assert result["labelled_pipe_binding_accuracy"]["denominator"] == 1
    assert result["counts"]["unlabelled_pipe_geometry"] == 1
    assert result["false_auto_accept_rate"]["value"] is None
    page["structures"][0]["point_id"] = None
    result = score(page=page)
    assert result["exact_point_id_precision"]["value"] is None
    assert result["exact_point_id_recall"]["value"] is None
    assert result["counts"]["point_predictions_unassessed"] == 1
    assert result["counts"]["unknown_point_labels"] == 1


def test_complete_and_partial_negative_pages_have_different_false_positive_scope():
    page = gold_page()
    page["structures"] = []
    result = score(page=page)
    assert result["counts"]["point_fp"] == 1
    assert result["false_auto_accept_rate"]["value"] == 1
    page["structures_complete"] = False
    result = score(page=page)
    assert result["counts"]["point_fp"] == 0
    assert result["counts"]["point_predictions_unassessed"] == 1
    assert result["false_auto_accept_rate"]["value"] is None


def test_review_and_manual_edits_do_not_change_raw_prediction_accuracy():
    record = evidence()
    record["pipes"][0]["dip"] = 999
    data = project_export(record)
    data["results"][0].update(
        review_state="EDITED", manually_overridden=True, pipes=evidence()["pipes"]
    )
    predictions, _, _ = benchmark.parse_predictions(json.dumps(data))
    gold = benchmark.parse_gold(json.dumps(gold_page()))
    result = benchmark.score(gold, predictions)
    assert result["complete_pipe_record_accuracy"]["value"] == 0.5
    assert result["false_auto_accept_rate"]["value"] == 1
    assert result["counts"]["manual_EDITED"] == 1
    assert result["counts"]["manually_overridden"] == 1
    record["evidence_decision"] = "REVIEW_DETAILS"
    result = score(records=[record])
    assert result["review_rate"]["value"] == 1
    assert result["false_auto_accept_rate"]["value"] is None


def test_actual_engine_export_keeps_raw_scoring_and_supplied_review_timing():
    from fieldbook_sync.benchmark_export import benchmark_payload
    from fieldbook_sync.models import AppState, PageEvidence, ResultRecord

    record = PageEvidence(**evidence(), source_name="synthetic", page_number=1)
    state = AppState(
        analysis_metadata={
            "schema_version": 1,
            "mode": "blocks",
            "source_commit": None,
            "implementation_sha256": "a" * 64,
            "page_sha256": {"synthetic-page": "b" * 64},
            "measurements": {"wall_seconds": 10},
            "ocr_provenance": {
                "observed_modes": ["spotting"],
                "observed_model_asset_sha256": ["c" * 64],
                "observed_page_count": 1,
                "observed_view_count": 2,
            },
        },
        results=[
            ResultRecord(
                point_id="0001",
                code="MH",
                evidence_records=[record],
                pipes=[],
                review_elapsed_seconds=3.5,
                review_action_count=1,
            )
        ],
    )
    predictions, supplied, hashes = benchmark.parse_predictions(
        json.dumps(benchmark_payload(state))
    )
    metadata = benchmark._metadata(supplied, "blocks")
    assert metadata["measurements"]["correction_seconds"] == 3.5
    assert metadata["measurements"]["reviewed_structures"] == 1
    assert "idle time" in metadata["review_timing_basis"]
    assert metadata["source_commit"] is None
    assert metadata["ocr_provenance"] == state.analysis_metadata["ocr_provenance"]
    assert hashes == {"synthetic-page": "b" * 64}
    result = benchmark.score(benchmark.parse_gold(json.dumps(gold_page())), predictions)
    assert result["complete_pipe_record_accuracy"]["value"] == 1


def test_predictions_outside_labelled_pages_do_not_inflate_scores():
    record = evidence()
    record["page_id"] = "unlabelled-page"
    result = score(records=[record])
    assert result["counts"]["predictions_outside_labelled_pages"] == 1
    assert result["exact_point_id_recall"]["value"] == 0
    assert result["review_rate"]["value"] is None


def test_page_hashes_verified_missing_or_rejected_without_reading_image_path():
    page = gold_page()
    page["source_sha256"] = "a" * 64
    page["image_path"] = "this-file-deliberately-does-not-exist.png"
    result = score(page=page, page_hashes={page["page_id"]: "A" * 64})
    assert result["counts"]["verified_page_hashes"] == 1
    assert score(page=page)["counts"]["unverified_page_hashes"] == 1
    with pytest.raises(benchmark.BenchmarkError, match="hashes differ"):
        score(page=page, page_hashes={page["page_id"]: "b" * 64})


@pytest.mark.parametrize("bad", [True, "4.2", float("nan"), float("inf"), [4.2], {}])
def test_invalid_numeric_gold_and_predictions_are_rejected(bad):
    page = gold_page()
    page["structures"][0]["pipes"][0]["fields"]["dip"] = bad
    with pytest.raises(benchmark.BenchmarkError):
        benchmark.parse_gold(json.dumps(page))
    record = evidence()
    record["pipes"][0]["dip"] = bad
    with pytest.raises(benchmark.BenchmarkError):
        benchmark.parse_predictions(json.dumps(record), jsonl=True)


def test_numbers_outside_supported_float_range_fail_before_geometry_arithmetic():
    for value in ("1e9999", "1e-9999"):
        record = json.dumps(evidence()).replace('"dip": 4.2', '"dip": ' + value)
        with pytest.raises(benchmark.BenchmarkError):
            benchmark.parse_predictions(record, jsonl=True)


@pytest.mark.parametrize("box", [[0, 0, 0, 100], [0, 0, 1001, 100], [0, -1, 100, 100], [1, 2, 3]])
def test_invalid_boxes_rejected(box):
    page = gold_page()
    page["structures"][0]["pipes"][0]["leader_bbox"] = box
    with pytest.raises(benchmark.BenchmarkError):
        benchmark.parse_gold(json.dumps(page))


@pytest.mark.parametrize(
    "field,value", [("diameter_in", 0), ("azimuth_deg", 360), ("azimuth_deg", -1)]
)
def test_out_of_range_fields_rejected(field, value):
    page = gold_page()
    page["structures"][0]["pipes"][0]["fields"][field] = value
    with pytest.raises(benchmark.BenchmarkError):
        benchmark.parse_gold(json.dumps(page))


def test_duplicate_gold_labels_and_unknown_field_keys_fail():
    page = gold_page()
    with pytest.raises(benchmark.BenchmarkError, match="duplicate page"):
        benchmark.parse_gold(json.dumps(page) + "\n" + json.dumps(page))
    page["structures"].append(deepcopy(page["structures"][0]))
    with pytest.raises(benchmark.BenchmarkError, match="duplicate structure"):
        benchmark.parse_gold(json.dumps(page))
    page = gold_page()
    page["structures"][0]["pipes"][1]["pipe_id"] = "east-pipe"
    with pytest.raises(benchmark.BenchmarkError, match="duplicate pipe label"):
        benchmark.parse_gold(json.dumps(page))
    page = gold_page()
    page["structures"][0]["pipes"][1]["leader_bbox"] = [100, 100, 200, 130]
    with pytest.raises(benchmark.BenchmarkError, match="duplicate pipe bounding box"):
        benchmark.parse_gold(json.dumps(page))
    page = gold_page()
    page["structures"][0]["pipes"][0]["fields"]["diameter"] = 8
    with pytest.raises(benchmark.BenchmarkError, match="unknown key"):
        benchmark.parse_gold(json.dumps(page))
    with pytest.raises(benchmark.BenchmarkError, match="invalid JSON"):
        benchmark.parse_gold('{"schema_version": 1, "schema_version": 1}')


@pytest.mark.parametrize("key", ["dipped", "review_state", "evidence_decision"])
def test_malformed_enums_do_not_escape_validation_as_type_errors(key):
    record = evidence()
    record[key] = ["private-invalid-enum"]
    with pytest.raises(benchmark.BenchmarkError):
        benchmark.parse_predictions(json.dumps(record), jsonl=True)
    page = gold_page()
    page["structures"][0]["dip_status"] = []
    with pytest.raises(benchmark.BenchmarkError):
        benchmark.parse_gold(json.dumps(page))


def test_agreeing_raw_views_count_one_identity_and_preserve_every_raw_decision():
    data = project_export()
    second = evidence()
    second["pipes"].reverse()
    second["pipes"][1]["material"] = "pvc"
    second["pipes"][1]["diameter_in"] = 8.0
    second["evidence_decision"] = "MANUAL_REVIEW"
    data["results"][0]["evidence_records"].append(second)
    predictions, _, _ = benchmark.parse_predictions(json.dumps(data))
    snapshot = deepcopy(predictions)
    result = benchmark.score(benchmark.parse_gold(json.dumps(gold_page())), predictions)
    assert predictions == snapshot, "Scoring must not change or discard raw observations"
    assert len(predictions) == 2
    assert result["exact_point_id_recall"] == {"numerator": 1, "denominator": 1, "value": 1}
    assert result["complete_pipe_record_accuracy"]["value"] == 1
    assert result["complete_structure_record_accuracy"]["value"] == 1
    assert result["counts"]["duplicate_prediction_groups"] == 1
    assert result["counts"]["agreeing_duplicate_groups"] == 1
    assert result["counts"]["conflicting_duplicate_groups"] == 0
    assert result["counts"]["raw_prediction_observations"] == 2
    assert result["counts"]["unique_prediction_groups"] == 1
    assert result["counts"]["duplicate_observations"] == 1
    assert result["counts"]["scoped_predictions"] == 2
    assert result["review_rate"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert result["false_auto_accept_rate"]["denominator"] == 1


def test_conflicting_pipe_values_never_select_the_favorable_view_in_either_order():
    first, second = evidence(), evidence()
    second["pipes"][0]["dip"], second["pipes"][1]["dip"] = 6.3, 4.2
    second["evidence_decision"] = "MANUAL_REVIEW"
    second["review_state"] = "EDITED"
    second["manually_overridden"] = True
    forward = score(records=[first, second])
    assert score(records=[second, first]) == forward
    assert forward["exact_point_id_recall"]["value"] == 1
    assert forward["pipe_spatial_match_recall"]["value"] == 1
    assert forward["labelled_pipe_binding_accuracy"]["value"] == 0
    assert forward["complete_pipe_record_accuracy"]["value"] == 0
    assert forward["complete_structure_record_accuracy"]["value"] == 0
    assert all(metric["value"] == 0 for metric in forward["field_accuracy"].values())
    assert forward["counts"]["conflicting_duplicate_groups"] == 1
    assert forward["counts"]["agreeing_duplicate_groups"] == 0
    assert forward["false_auto_accept_rate"] == {"numerator": 1, "denominator": 1, "value": 1}
    assert forward["counts"]["manual_EDITED"] == 1
    assert forward["counts"]["manually_overridden"] == 1


def test_duplicate_box_drift_keeps_only_geometry_shared_by_every_view():
    first, second = evidence(), evidence()
    second["pipes"][0]["leader_bbox"] = [101, 100, 201, 130]
    result = score(records=[first, second])
    assert score(records=[second, first]) == result
    assert result["pipe_spatial_match_recall"]["value"] == 0.5
    assert result["complete_pipe_record_accuracy"]["value"] == 0
    assert result["false_auto_accept_rate"] == {"numerator": 2, "denominator": 2, "value": 1}


def test_duplicate_status_conflict_is_not_repaired_using_gold():
    first, second = evidence(), evidence()
    second["dipped"] = "NO"
    result = score(records=[first, second])
    assert result["dip_status_accuracy"]["value"] == 0
    assert result["complete_structure_record_accuracy"]["value"] == 0
    assert result["counts"]["conflicting_duplicate_groups"] == 1


def test_duplicate_conflict_does_not_fabricate_missing_gold_denominators():
    page = gold_page()
    page["structures"][0].pop("dip_status")
    page["structures"][0]["pipes_complete"] = False
    for pipe in page["structures"][0]["pipes"]:
        pipe["fields"] = {}
    first, second = evidence(), evidence()
    second["pipes"][0]["dip"] = 4.3
    result = score(page=page, records=[first, second])
    assert result["labelled_pipe_binding_accuracy"]["denominator"] == 0
    assert result["false_auto_accept_rate"]["denominator"] == 0
    assert result["counts"]["auto_accept_unassessed"] == 2
    assert result["counts"]["conflicting_duplicate_groups"] == 1


def test_conflicting_extra_pipe_cannot_disappear_into_a_correct_empty_record():
    page = gold_page()
    page["structures"][0]["pipes"] = []
    first, second = evidence(page), evidence(page)
    second["pipes"] = evidence()["pipes"][:1]
    result = score(page=page, records=[first, second])
    assert result["complete_structure_record_accuracy"]["value"] == 0
    assert result["false_auto_accept_rate"]["value"] == 1


def test_duplicate_unexpected_identity_is_one_false_id_but_two_raw_auto_decisions():
    wrong = evidence()
    wrong["matched_point_id"] = "0002"
    result = score(records=[evidence(), wrong, deepcopy(wrong)])
    assert result["exact_point_id_precision"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert result["exact_point_id_recall"]["value"] == 1
    assert result["false_auto_accept_rate"]["numerator"] == 2
    assert result["false_auto_accept_rate"]["denominator"] == 3


def test_aggregated_pipes_and_duplicate_result_labels_still_fail():
    data = project_export()
    data["results"][0].pop("evidence_records")
    data["results"][0]["pipes"] = evidence()["pipes"]
    with pytest.raises(benchmark.BenchmarkError, match="aggregated pipes"):
        benchmark.parse_predictions(json.dumps(data))
    data = project_export()
    data["results"].append(deepcopy(data["results"][0]))
    with pytest.raises(benchmark.BenchmarkError, match="duplicate ResultRecord"):
        benchmark.parse_predictions(json.dumps(data))


def test_native_export_null_page_hash_is_unverified_not_invalid():
    data = project_export(page_sha256={"synthetic-page": None})
    predictions, _, hashes = benchmark.parse_predictions(json.dumps(data))
    page = gold_page()
    page["source_sha256"] = "a" * 64
    result = benchmark.score(
        benchmark.parse_gold(json.dumps(page)), predictions, page_hashes=hashes
    )
    assert hashes == {"synthetic-page": None}
    assert result["counts"]["unverified_page_hashes"] == 1
    assert result["counts"]["verified_page_hashes"] == 0


def test_native_zip_uses_hashed_snapshot_and_never_extracts_members(tmp_path):
    archive_path = tmp_path / "export.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("audit.json", json.dumps(project_export()))
        archive.writestr("../must-not-exist.png", b"synthetic")
    predictions, metadata, hashes, digest = benchmark.load_predictions(archive_path)
    assert len(predictions) == 1
    assert metadata == hashes == {}
    assert digest == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert not (tmp_path.parent / "must-not-exist.png").exists()
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(archive_path, "a") as archive:
            archive.writestr("audit.json", "{}")
    with pytest.raises(benchmark.BenchmarkError, match="one bounded audit"):
        benchmark.load_predictions(archive_path)


def test_saved_timing_and_hardware_are_optional_supplied_metadata():
    raw = {
        "schema_version": 1,
        "mode": "spotting",
        "source_commit": "a" * 40,
        "source_dirty": True,
        "implementation_sha256": "b" * 64,
        "review_timing_basis": "Dialog elapsed time including idle time.",
        "model": "synthetic-test-fixture",
        "hardware": {"gpu": "synthetic GPU", "vram_gib": 4},
        "measurements": {
            "page_seconds": [4, 1, 3, 2],
            "correction_seconds": 8,
            "corrected_structures": 1,
        },
        "private_project_path": "must-not-be-copied",
    }
    metadata = benchmark._metadata(raw, "spotting")
    assert metadata["measurements"]["page_seconds"] == {"count": 4, "p50": 2, "p95": 4}
    assert metadata["measurements"]["correction_seconds"] == 8
    assert "wall_seconds" not in metadata["measurements"]
    assert "private_project_path" not in metadata
    assert metadata["implementation_sha256"] == "b" * 64
    assert "idle time" in metadata["review_timing_basis"]
    assert "supplied" in metadata["provenance"]
    assert benchmark._metadata({}, "blocks")["source_commit"] is None
    assert benchmark._metadata({}, "blocks")["measurements"] == {}
    with pytest.raises(benchmark.BenchmarkError, match="mode differs"):
        benchmark._metadata(raw, "blocks")
    raw["measurements"]["wall_seconds"] = benchmark.Decimal("1e9999")
    with pytest.raises(benchmark.BenchmarkError):
        benchmark._metadata(raw, "spotting")


def ocr_provenance():
    return {
        "observed_modes": ["spotting", "blocks"],
        "observed_model_asset_sha256": ["b" * 64, "A" * 64],
        "observed_page_count": 2,
        "observed_view_count": 3,
    }


def test_actual_worker_provenance_and_warnings_are_preserved_without_inference():
    metadata = benchmark._metadata(
        {
            "ocr_provenance": ocr_provenance(),
            "provenance_warnings": ["Source image hash unavailable: synthetic-page"],
        },
        "spotting",
    )
    assert metadata["ocr_provenance"] == {
        "observed_modes": ["blocks", "spotting"],
        "observed_model_asset_sha256": ["a" * 64, "b" * 64],
        "observed_page_count": 2,
        "observed_view_count": 3,
    }
    assert metadata["provenance_warnings"] == ["Source image hash unavailable: synthetic-page"]
    absent = benchmark._metadata({}, "spotting")
    assert "ocr_provenance" not in absent
    assert "provenance_warnings" not in absent
    empty = {
        "observed_modes": [],
        "observed_model_asset_sha256": [],
        "observed_page_count": 0,
        "observed_view_count": 0,
    }
    assert benchmark._metadata({"ocr_provenance": empty}, "blocks")["ocr_provenance"] == empty


@pytest.mark.parametrize(
    "key,bad",
    [
        ("observed_modes", "spotting"),
        ("observed_modes", ["block"]),
        ("observed_modes", ["spotting", "spotting"]),
        ("observed_modes", [{}]),
        ("observed_model_asset_sha256", ["local-model-directory"]),
        ("observed_model_asset_sha256", [None]),
        ("observed_model_asset_sha256", ["a" * 64, "A" * 64]),
        ("observed_model_asset_sha256", "a" * 64),
        ("observed_page_count", True),
        ("observed_page_count", -1),
        ("observed_view_count", 2.0),
        ("observed_view_count", "2"),
    ],
)
def test_invalid_worker_provenance_is_rejected(key, bad):
    raw = ocr_provenance()
    raw[key] = bad
    with pytest.raises(benchmark.BenchmarkError, match="OCR provenance"):
        benchmark._metadata({"ocr_provenance": raw}, "spotting")


def test_worker_provenance_requires_the_documented_schema():
    for raw in (None, {}, {**ocr_provenance(), "selected_model_path": "must-not-copy"}):
        with pytest.raises(benchmark.BenchmarkError, match="OCR provenance"):
            benchmark._metadata({"ocr_provenance": raw}, "spotting")
    for bad in ("warning", [None], [""], ["private\nmultiline"]):
        with pytest.raises(benchmark.BenchmarkError):
            benchmark._metadata({"provenance_warnings": bad}, "spotting")


@pytest.mark.parametrize(
    "path",
    [
        "https://example.invalid/input",
        "s3://private/key",
        "//server/share",
        "\\\\server\\share",
        "data:text/plain,abc",
    ],
)
def test_network_paths_are_rejected(path):
    with pytest.raises(benchmark.BenchmarkError):
        benchmark.load_predictions(path)


def test_private_output_cannot_escape_git_worktree_rule_when_git_is_missing(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(benchmark, "_git", lambda *args: None)
    with pytest.raises(benchmark.BenchmarkError, match="reports must be below"):
        benchmark.write_private_report(tmp_path / "report.json", {})
    with pytest.raises(benchmark.BenchmarkError, match="must be gitignored"):
        benchmark.write_private_report(tmp_path / benchmark.PRIVATE_DIR / "report.json", {})


def test_output_symlink_and_overwrite_protections(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "_worktree_root", lambda _path: None)
    target = tmp_path / "report.json"
    benchmark.write_private_report(target, {"test": 1})
    with pytest.raises(benchmark.BenchmarkError, match="report exists"):
        benchmark.write_private_report(target, {"test": 2})
    benchmark.write_private_report(target, {"test": 2}, overwrite=True)
    assert json.loads(target.read_text())["test"] == 2
    link = tmp_path / "linked.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")
    with pytest.raises(benchmark.BenchmarkError, match="symlink or junction"):
        benchmark.write_private_report(link, {}, overwrite=True)


def test_cli_compares_runs_privately_and_preserves_inputs(tmp_path, capsys):
    if shutil.which("git") is None:
        pytest.skip("Git required to verify ignored output contract")
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(benchmark.PRIVATE_DIR + "/\n", encoding="utf-8")
    private = tmp_path / benchmark.PRIVATE_DIR
    private.mkdir()
    gold = private / "gold.jsonl"
    good = private / "correct.json"
    bad = private / "swapped.json"
    report_path = private / "report.json"
    gold.write_text(json.dumps(gold_page()) + "\n", encoding="utf-8")
    good.write_text(json.dumps(project_export()), encoding="utf-8")
    swapped = evidence()
    swapped["pipes"][0]["dip"], swapped["pipes"][1]["dip"] = 6.3, 4.2
    bad.write_text(json.dumps(project_export(swapped)), encoding="utf-8")
    args = ["--gold", str(gold), "--run", f"block={bad}", "--run", f"spotting={good}"]
    assert benchmark.main([*args, "--output", str(report_path)]) == 0
    report = json.loads(report_path.read_text())
    assert report["runs"]["block"]["metrics"]["labelled_pipe_binding_accuracy"]["value"] == 0
    assert report["runs"]["spotting"]["metrics"]["labelled_pipe_binding_accuracy"]["value"] == 1
    assert report["gold_sha256"] == hashlib.sha256(gold.read_bytes()).hexdigest()
    assert report["policy"]["release_or_security_clearance"] is False
    assert report["runs"]["spotting"]["metadata"]["source_commit"] is None
    serialized = report_path.read_text()
    assert "0001" not in serialized
    assert "synthetic-page" not in serialized
    assert str(tmp_path) not in serialized
    assert "0001" not in capsys.readouterr().out
    original = gold.read_bytes()
    assert benchmark.main([*args, "--output", str(gold), "--overwrite"]) == 2
    assert gold.read_bytes() == original
    assert benchmark.main([*args, "--output", str(tmp_path / "public.json")]) == 2
    assert not (tmp_path / "public.json").exists()


def test_repository_synthetic_fixtures_are_usable_and_not_performance_claims():
    directory = Path(__file__).parent / "data" / "fieldbook_benchmark"
    report = benchmark.build_report(
        directory / "gold.jsonl",
        [
            ("correct", str(directory / "correct.json")),
            ("swapped", str(directory / "swapped.json")),
        ],
    )
    assert report["runs"]["correct"]["metrics"]["complete_pipe_record_accuracy"]["value"] == 1
    assert report["runs"]["swapped"]["metrics"]["complete_pipe_record_accuracy"]["value"] == 0
    assert report["runs"]["correct"]["metadata"]["measurements"] == {}
