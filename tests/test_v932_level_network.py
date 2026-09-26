from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from surveysync.level_network import adjust_level_network


def _reference_level_network() -> tuple[list[dict], list[dict]]:
    points = [
        {"point_id": "BM-A", "elevation": 100.0, "fixed": True},
        {"point_id": "BM-B", "elevation": 101.1, "fixed": False},
        {"point_id": "BM-C", "elevation": 101.9, "fixed": False},
    ]
    observations = [
        {"from_id": "BM-A", "to_id": "BM-B", "delta_elevation": 1.000, "sigma": 0.01},
        {"from_id": "BM-B", "to_id": "BM-C", "delta_elevation": 1.020, "sigma": 0.01},
        {"from_id": "BM-A", "to_id": "BM-C", "delta_elevation": 2.010, "sigma": 0.01},
    ]
    return points, observations


def test_weighted_level_network_reference_loop():
    points, observations = _reference_level_network()
    result = adjust_level_network(points=points, observations=observations)

    adjusted = {row["point_id"]: row for row in result["points"]}
    assert adjusted["BM-A"]["elevation"] == pytest.approx(100.0)
    assert adjusted["BM-B"]["elevation"] == pytest.approx(100.9966666667, abs=1e-8)
    assert adjusted["BM-C"]["elevation"] == pytest.approx(102.0133333333, abs=1e-8)
    assert result["degrees_of_freedom"] == 1
    assert result["redundancy_sum"] == pytest.approx(1.0, abs=1e-8)
    assert result["review_count"] == 0
    assert all(row["sigma_elevation"] >= 0.0 for row in result["points"])


def test_level_network_rejects_unconnected_unknown():
    points = [
        {"point_id": "BM-A", "elevation": 100.0, "fixed": True},
        {"point_id": "BM-B", "elevation": 101.0, "fixed": False},
        {"point_id": "BM-C", "elevation": 102.0, "fixed": False},
    ]
    observations = [
        {"from_id": "BM-A", "to_id": "BM-B", "delta_elevation": 1.0, "sigma": 0.01},
    ]
    with pytest.raises(ValueError, match="rank deficient"):
        adjust_level_network(points=points, observations=observations)


def test_level_network_api_is_audited(tmp_path, monkeypatch):
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
            "name": "Level Network API",
            "crs": "EPSG:2278",
            "horizontal_units": "us_survey_feet",
            "vertical_units": "us_survey_feet",
        },
    )
    assert created.status_code == 200, created.text

    points, observations = _reference_level_network()
    response = client.post(
        "/api/v9/level/network-adjust",
        json={"points": points, "observations": observations},
    )
    assert response.status_code == 200, response.text
    assert response.json()["degrees_of_freedom"] == 1

    actions = [row["action"] for row in survey_router.current_project.db.recent_audit(20)]
    assert "LEVEL_NETWORK_ADJUSTMENT" in actions
