import pytest

from surveysync.topo.calibration import summarize_reviews


def row(run, scatter, unit, decision="confirmed_bust"):
    return {"run_id": run, "candidate_id": "RHB-1", "decision": decision,
            "vertical_units": unit, "candidate": {"offset_std_dev": scatter}}


def test_mixed_units_are_normalized_before_suggesting_feet_tolerance():
    result = summarize_reviews([row("a", .03048, "meters"), row("b", .1, "international_feet")])
    assert result["median_confirmed_scatter"] == pytest.approx(.1)
    assert result["suggested_consistency_ft"] == .2
    assert result["confidence_calibrated"] is False


def test_latest_rejection_supersedes_confirmation_and_bad_units_excluded():
    result = summarize_reviews([
        row("a", .2, "meters", "not_bust"), row("a", .2, "meters"),
        row("b", .2, None), row("c", float("nan"), "meters"),
    ])
    assert result["review_count"] == 3
    assert result["not_bust_count"] == 1
    assert result["excluded_scatter_count"] == 2
    assert result["suggested_consistency_ft"] is None
