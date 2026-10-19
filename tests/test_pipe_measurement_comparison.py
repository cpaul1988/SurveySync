from types import SimpleNamespace

import pytest

from fieldbook_sync.measurement_comparison import (
    compare_measurement_records,
    observation_from_text,
    observation_matches_pipe,
)
from fieldbook_sync.models import DipStatus, PageEvidence, PipeMeasurement
from fieldbook_sync.ocr_local import compare_ocr_to_evidence


def evidence(*pipes):
    return PageEvidence(
        matched_point_id="001",
        source_name="synthetic",
        page_number=1,
        page_id="p1",
        dipped="YES",
        basis="MEASUREMENT",
        pipes=list(pipes),
    )


def pipe(dip=4.2, diameter=8, azimuth=90, material="PVC"):
    return PipeMeasurement(dip=dip, diameter_in=diameter, azimuth_deg=azimuth, material=material)


TEXT = "DIP 4.20 8 inch PVC AZ 90; DIP 6.30 12 inch RCP AZ 270"


def test_correct_distinct_records_agree_without_claiming_a_spatial_binding():
    ev = evidence(pipe(), pipe(6.3, 12, 270, "RCP"))
    result = compare_measurement_records(TEXT, ev)
    assert result.numerical_agreement is True
    assert result.pipe_record_agreement is True
    assert result.agreement is True
    assert ev.relationship_status == "unverified"
    assert "spatial review" in result.summary


@pytest.mark.parametrize("field", ["dip", "diameter_in", "azimuth_deg", "material"])
def test_swapping_fields_between_pipes_fails_even_when_every_value_is_present(field):
    left, right = pipe(), pipe(6.3, 12, 270, "RCP")
    old_left, old_right = getattr(left, field), getattr(right, field)
    setattr(left, field, old_right)
    setattr(right, field, old_left)
    ev = evidence(left, right)
    result = compare_measurement_records(TEXT, ev)
    assert result.numerical_agreement is True
    assert result.pipe_record_agreement is False
    assert result.agreement is False
    assert compare_ocr_to_evidence(TEXT, ev)[0] is False


def test_record_order_can_change_without_changing_pipe_relationships():
    assert compare_ocr_to_evidence(TEXT, evidence(pipe(6.3, 12, 270, "RCP"), pipe()))[0] is True


def test_ungrouped_page_values_do_not_prove_pipe_records():
    result = compare_measurement_records(
        TEXT.replace(";", ""), evidence(pipe(), pipe(6.3, 12, 270, "RCP"))
    )
    assert result.numerical_agreement is True
    assert result.pipe_record_agreement is None
    assert result.agreement is None


def test_split_multiline_fields_are_unknown_for_multiple_pipes_not_false_conflicts():
    result = compare_measurement_records(
        "DIP 4.2\n8 inch\nAZ 90\nDIP 6.3\n12 inch\nAZ 270",
        evidence(pipe(), pipe(6.3, 12, 270, "RCP")),
    )
    assert result.numerical_agreement is True
    assert result.pipe_record_agreement is None
    assert result.agreement is None


def test_multiline_single_pipe_keeps_complementary_observations_together():
    result = compare_measurement_records("DIP 4.2\n8 inch PVC\nAZ 90", evidence(pipe()))
    assert result.agreement is True


def test_multiplicity_cannot_reuse_one_pipe_for_two_explicit_records():
    text = "DIP 4.2 8 inch PVC AZ 90; DIP 4.2 8 inch PVC AZ 90"
    result = compare_measurement_records(text, evidence(pipe(), pipe(6.3, 12, 270, "RCP")))
    assert result.pipe_record_agreement is False
    assert compare_measurement_records(text, evidence(pipe(), pipe())).pipe_record_agreement is True


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "4.20 DIP 15 RCP AZ 90",
            {"dip": 4.2, "diameter_in": 15.0, "azimuth_deg": 90.0, "material": "RCP"},
        ),
        ("12 DIP AZ 90", {"diameter_in": 12.0, "azimuth_deg": 90.0, "material": "DIP"}),
        (
            "DIP 4.20 15 RCP AZ 90",
            {"dip": 4.2, "diameter_in": 15.0, "azimuth_deg": 90.0, "material": "RCP"},
        ),
        ("12 DIP 4.20", {"diameter_in": 12.0, "material": "DIP"}),
        ("D:4.20 8 inch PVC", {"dip": 4.2, "diameter_in": 8.0, "material": "PVC"}),
    ],
)
def test_depth_and_ductile_iron_ambiguity_remains_conservative(text, expected):
    assert observation_from_text(text) == expected


def test_circular_azimuth_tolerance_and_complete_fields():
    observation = {"dip": 4.2, "diameter_in": 8, "material": "PVC", "azimuth_deg": 359}
    assert observation_matches_pipe(observation, pipe(azimuth=1), complete=True)
    assert not observation_matches_pipe(observation, pipe(azimuth=4), complete=True)
    assert not observation_matches_pipe({"dip": 4.2}, pipe(), complete=True)
    assert observation_matches_pipe({"dip": 4.2}, pipe(), complete=False)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_values_never_agree(invalid):
    assert not observation_matches_pipe({"dip": 4.2}, SimpleNamespace(dip=invalid))


def test_missing_text_is_unknown_and_explicit_status_is_checked():
    ev = evidence()
    assert compare_ocr_to_evidence("Point 001", ev)[0] is None
    ev.dipped = DipStatus.CNA
    assert compare_ocr_to_evidence("CNA", ev)[0] is True
    assert compare_ocr_to_evidence("CNL", ev)[0] is False


def test_bounded_input_abstains():
    assert compare_measurement_records("DIP 4.2 " * 2000, evidence(pipe())).agreement is None
    assert (
        compare_measurement_records(TEXT, evidence(*[pipe() for _ in range(65)])).agreement is None
    )
