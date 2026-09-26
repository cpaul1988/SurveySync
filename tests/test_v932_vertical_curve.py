from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from surveysync.cogo_extended import solve_vertical_curve


def test_vertical_curve_symmetric_crest_reference():
    result = solve_vertical_curve(
        pvi_station=1000.0,
        pvi_elevation=100.0,
        grade_in_percent=2.0,
        grade_out_percent=-2.0,
        length=200.0,
        sample_interval=50.0,
    )
    assert result["bvc_station"] == pytest.approx(900.0)
    assert result["bvc_elevation"] == pytest.approx(98.0)
    assert result["evc_station"] == pytest.approx(1100.0)
    assert result["evc_elevation"] == pytest.approx(98.0)
    assert result["k_value"] == pytest.approx(50.0)
    assert result["high_low_type"] == "HIGH"
    assert result["high_low_station"] == pytest.approx(1000.0)
    assert result["high_low_elevation"] == pytest.approx(99.0)
    assert result["sample_count"] == 5


def test_vertical_curve_rejects_equal_grades():
    with pytest.raises(ValueError, match="must differ"):
        solve_vertical_curve(
            pvi_station=1000,
            pvi_elevation=100,
            grade_in_percent=2,
            grade_out_percent=2,
            length=200,
        )


def test_vertical_curve_api_is_audited(tmp_path, monkeypatch):
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
            "name": "Vertical Curve API",
            "crs": "EPSG:2278",
            "horizontal_units": "us_survey_feet",
            "vertical_units": "us_survey_feet",
        },
    )
    assert created.status_code == 200, created.text

    response = client.post(
        "/api/v9/cogo/vertical-curve",
        json={
            "pvi_station": 1000,
            "pvi_elevation": 100,
            "grade_in_percent": 2,
            "grade_out_percent": -2,
            "length": 200,
            "sample_interval": 50,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["high_low_type"] == "HIGH"

    actions = [row["action"] for row in survey_router.current_project.db.recent_audit(20)]
    assert "VERTICAL_CURVE" in actions
