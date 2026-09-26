from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from surveysync.network_adjustment import adjust_control_network


def _distance_reference_case() -> tuple[list[dict], list[dict]]:
    # Adapted as a coordinate-convention-independent numerical reference from
    # pySurveying's MIT-licensed distance-control-network regression fixture.
    points = [
        {"point_id": "A", "northing": 0.0, "easting": 0.0, "fixed": True},
        {"point_id": "B", "northing": 0.0, "easting": 100.0, "fixed": True},
        {"point_id": "C", "northing": 100.0, "easting": 0.0, "fixed": True},
        {"point_id": "P", "northing": 31.0, "easting": 39.0, "fixed": False},
    ]
    observations = [
        {"kind": "distance", "from_id": "A", "to_id": "P", "value": 50.0, "sigma": 0.01},
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


def test_network_adjustment_matches_independent_distance_reference():
    points, observations = _distance_reference_case()
    result = adjust_control_network(points=points, observations=observations)
    adjusted = next(row for row in result["points"] if row["point_id"] == "P")

    assert result["converged"] is True
    assert adjusted["northing"] == pytest.approx(30.0, abs=1e-6)
    assert adjusted["easting"] == pytest.approx(40.0, abs=1e-6)
    assert result["degrees_of_freedom"] == 1
    assert result["redundancy_sum"] == pytest.approx(1.0, abs=1e-5)
    assert adjusted["ellipse95_semi_major"] >= adjusted["ellipse95_semi_minor"] >= 0.0


def test_network_adjustment_mixed_linear_angular_quality_outputs():
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

    result = adjust_control_network(points=points, observations=observations)
    adjusted = next(row for row in result["points"] if row["point_id"] == "P")

    assert result["converged"] is True
    assert result["degrees_of_freedom"] == 3
    assert adjusted["northing"] == pytest.approx(true_n, abs=0.05)
    assert adjusted["easting"] == pytest.approx(true_e, abs=0.05)
    assert result["redundancy_sum"] == pytest.approx(3.0, abs=1e-4)
    assert [row["residual_unit"] for row in result["observations"][:2]] == [
        "project_linear_units",
        "project_linear_units",
    ]
    assert all(
        row["residual_unit"] == "degrees" for row in result["observations"][2:]
    )


def test_network_adjustment_rejects_rank_deficient_geometry():
    points = [
        {"point_id": "A", "northing": 0.0, "easting": 0.0, "fixed": True},
        {"point_id": "P", "northing": 10.0, "easting": 10.0, "fixed": False},
    ]
    observations = [
        {
            "kind": "distance",
            "from_id": "A",
            "to_id": "P",
            "value": math.sqrt(200.0),
            "sigma": 0.01,
        }
    ]
    with pytest.raises(ValueError, match="rank deficient"):
        adjust_control_network(points=points, observations=observations)


def test_network_adjustment_api_is_audited(tmp_path, monkeypatch):
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
            "name": "Network API",
            "crs": "EPSG:2278",
            "horizontal_units": "us_survey_feet",
            "vertical_units": "us_survey_feet",
        },
    )
    assert created.status_code == 200, created.text

    points, observations = _distance_reference_case()
    response = client.post(
        "/api/v9/control/network-adjust",
        json={"points": points, "observations": observations},
    )
    assert response.status_code == 200, response.text
    assert response.json()["converged"] is True

    actions = [row["action"] for row in survey_router.current_project.db.recent_audit(20)]
    assert "NETWORK_ADJUSTMENT" in actions
