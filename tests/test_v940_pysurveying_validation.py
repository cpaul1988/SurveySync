from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from surveysync.network_adjustment import adjust_control_network
from surveysync.pysurveying_reference import (
    reference_adjust_control_network,
    reference_data_snooping,
    validate_native_network,
)

ROOT = Path(__file__).resolve().parents[1]


def _distance_case() -> tuple[list[dict], list[dict]]:
    points = [
        {"point_id": "A", "northing": 0.0, "easting": 0.0, "fixed": True},
        {"point_id": "B", "northing": 0.0, "easting": 100.0, "fixed": True},
        {"point_id": "C", "northing": 100.0, "easting": 0.0, "fixed": True},
        {"point_id": "P", "northing": 31.0, "easting": 39.0, "fixed": False},
    ]
    observations = [
        {
            "kind": "distance",
            "from_id": "A",
            "to_id": "P",
            "value": 50.0,
            "sigma": 0.01,
        },
        {
            "kind": "distance",
            "from_id": "B",
            "to_id": "P",
            "value": math.hypot(30.0, 60.0),
            "sigma": 0.01,
        },
        {
            "kind": "distance",
            "from_id": "C",
            "to_id": "P",
            "value": math.hypot(70.0, 40.0),
            "sigma": 0.01,
        },
    ]
    return points, observations


def _mixed_case() -> tuple[list[dict], list[dict]]:
    true_n, true_e = 30.0, 40.0
    az_c = math.degrees(math.atan2(true_e, true_n - 100.0)) % 360.0
    az_b = math.degrees(math.atan2(true_e - 100.0, true_n)) % 360.0
    angle_a = (
        math.degrees(math.atan2(true_e, true_n))
        - math.degrees(math.atan2(100.0, 0.0))
    ) % 360.0
    points = [
        {"point_id": "A", "northing": 0.0, "easting": 0.0, "fixed": True},
        {"point_id": "B", "northing": 0.0, "easting": 100.0, "fixed": True},
        {"point_id": "C", "northing": 100.0, "easting": 0.0, "fixed": True},
        {"point_id": "P", "northing": 29.5, "easting": 40.5, "fixed": False},
    ]
    observations = [
        {
            "kind": "distance",
            "from_id": "A",
            "to_id": "P",
            "value": math.hypot(true_n, true_e) + 0.01,
            "sigma": 0.02,
        },
        {
            "kind": "distance",
            "from_id": "B",
            "to_id": "P",
            "value": math.hypot(true_n, true_e - 100.0) - 0.01,
            "sigma": 0.02,
        },
        {
            "kind": "azimuth",
            "from_id": "C",
            "to_id": "P",
            "value": az_c + 0.001,
            "sigma": 0.002,
        },
        {
            "kind": "azimuth",
            "from_id": "B",
            "to_id": "P",
            "value": az_b - 0.001,
            "sigma": 0.002,
        },
        {
            "kind": "angle",
            "from_id": "A",
            "to_id": "B",
            "target2_id": "P",
            "value": angle_a + 0.0015,
            "sigma": 0.003,
        },
    ]
    return points, observations


def test_reference_solver_matches_native_distance_network():
    points, observations = _distance_case()
    native = adjust_control_network(points=points, observations=observations)
    validation = validate_native_network(
        points=points,
        observations=observations,
        native_result=native,
    )

    assert validation["status"] == "PASS"
    assert validation["checks"]["coordinate_match"] is True
    assert validation["checks"]["normalized_residual_match"] is True
    assert validation["checks"]["redundancy_match"] is True
    assert validation["checks"]["ellipse_match"] is True
    assert validation["max_coordinate_delta"] < 1e-6


def test_reference_solver_matches_native_mixed_network():
    points, observations = _mixed_case()
    native = adjust_control_network(points=points, observations=observations)
    reference = reference_adjust_control_network(
        points=points,
        observations=observations,
    )
    validation = validate_native_network(
        points=points,
        observations=observations,
        native_result=native,
    )

    native_p = next(row for row in native["points"] if row["point_id"] == "P")
    reference_p = next(row for row in reference["points"] if row["point_id"] == "P")
    assert validation["status"] == "PASS"
    assert reference["degrees_of_freedom"] == native["degrees_of_freedom"] == 3
    assert reference["redundancy_sum"] == pytest.approx(3.0, abs=1e-4)
    assert reference_p["northing"] == pytest.approx(native_p["northing"], abs=1e-4)
    assert reference_p["easting"] == pytest.approx(native_p["easting"], abs=1e-4)


def test_validator_detects_tampered_native_coordinate():
    points, observations = _distance_case()
    native = adjust_control_network(points=points, observations=observations)
    tampered = copy.deepcopy(native)
    point = next(row for row in tampered["points"] if row["point_id"] == "P")
    point["northing"] += 0.01

    validation = validate_native_network(
        points=points,
        observations=observations,
        native_result=tampered,
    )

    assert validation["status"] == "REVIEW"
    assert validation["checks"]["coordinate_match"] is False
    assert validation["max_coordinate_delta"] > 0.009


def test_data_snooping_flags_large_distance_outlier_without_mutating_input():
    true_n, true_e = 30.0, 40.0
    points = [
        {"point_id": "A", "northing": 0.0, "easting": 0.0, "fixed": True},
        {"point_id": "B", "northing": 0.0, "easting": 100.0, "fixed": True},
        {"point_id": "C", "northing": 100.0, "easting": 0.0, "fixed": True},
        {"point_id": "D", "northing": 100.0, "easting": 100.0, "fixed": True},
        {"point_id": "P", "northing": 30.5, "easting": 39.5, "fixed": False},
    ]
    observations = [
        {"kind": "distance", "from_id": "A", "to_id": "P", "value": 50.0, "sigma": 0.01},
        {
            "kind": "distance",
            "from_id": "B",
            "to_id": "P",
            "value": math.hypot(true_n, true_e - 100.0),
            "sigma": 0.01,
        },
        {
            "kind": "distance",
            "from_id": "C",
            "to_id": "P",
            "value": math.hypot(true_n - 100.0, true_e),
            "sigma": 0.01,
        },
        {
            "kind": "distance",
            "from_id": "D",
            "to_id": "P",
            "value": math.hypot(true_n - 100.0, true_e - 100.0),
            "sigma": 0.01,
        },
        {
            "kind": "distance",
            "from_id": "A",
            "to_id": "P",
            "value": 50.25,
            "sigma": 0.01,
        },
    ]
    original = copy.deepcopy(observations)

    result = reference_data_snooping(
        points=points,
        observations=observations,
        threshold=2.0,
        max_removals=1,
    )

    assert observations == original
    assert result["history"]
    assert result["history"][0]["flagged"] is True
    assert result["removed_observation_numbers"]
    assert abs(float(result["history"][0]["standardized_residual"])) >= 2.0


def test_network_api_includes_independent_validation_and_audits_status(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg"))
    from fieldbook_sync import app as field_app
    from surveysync import router as survey_router

    survey_router.config_store = survey_router.ConfigStore(tmp_path / "cfg")
    survey_router.current_project = None
    field_app.runtime = field_app.Runtime(tmp_path / "field_runtime")
    client = TestClient(field_app.app)

    created = client.post(
        "/api/v9/project/create",
        json={
            "parent_folder": str(tmp_path / "projects"),
            "name": "Independent Validator API",
            "crs": "EPSG:2278",
            "horizontal_units": "us_survey_feet",
            "vertical_units": "us_survey_feet",
        },
    )
    assert created.status_code == 200, created.text

    points, observations = _distance_case()
    response = client.post(
        "/api/v9/control/network-adjust",
        json={"points": points, "observations": observations},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["independent_validation"]["status"] == "PASS"
    assert payload["independent_validation"]["engine"] == "pysurveying_reference"

    audits = survey_router.current_project.db.recent_audit(20)
    network_event = next(row for row in audits if row["action"] == "NETWORK_ADJUSTMENT")
    summary = network_event["details"]["result_summary"]
    assert summary["independent_validation"] == "PASS"
    assert summary["max_reference_coordinate_delta"] < 1e-4


def test_pysurveying_attribution_and_validator_documentation_present():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "PYSURVEYING_VALIDATION_ENGINE.md").read_text(
        encoding="utf-8"
    )

    assert "Copyright (c) 2026 Jinghao Hu" in notices
    assert "surveysync/pysurveying_reference.py" in notices
    assert "analytic observation derivatives" in docs
    assert "PASS" in docs and "REVIEW" in docs and "UNAVAILABLE" in docs
