from __future__ import annotations

import math

import pytest

from surveysync.horizontal_alignment import (
    alignment_station_offset,
    build_horizontal_alignment,
    point_at_station,
    station_offset_point,
)
from surveysync.landxml_io import export_landxml, import_landxml


def _alignment_definition() -> dict:
    return {
        "start_northing": 0.0,
        "start_easting": 0.0,
        "start_azimuth_deg": 0.0,
        "start_station": 1000.0,
        "elements": [
            {"kind": "tangent", "length": 100.0},
            {"kind": "curve", "radius": 50.0, "delta_deg": 90.0, "direction": "RIGHT"},
            {"kind": "tangent", "length": 25.0},
        ],
    }


def test_horizontal_alignment_continuity_reference():
    alignment = build_horizontal_alignment(**_alignment_definition())

    assert alignment["element_count"] == 3
    assert alignment["length"] == pytest.approx(100.0 + math.pi * 25.0 + 25.0)
    assert alignment["end_northing"] == pytest.approx(150.0)
    assert alignment["end_easting"] == pytest.approx(75.0)
    assert alignment["end_azimuth_deg"] == pytest.approx(90.0)

    curve_mid_station = 1100.0 + math.pi * 12.5
    point = point_at_station(alignment, curve_mid_station)
    assert point["northing"] == pytest.approx(100.0 + 50.0 / math.sqrt(2.0), abs=1e-8)
    assert point["easting"] == pytest.approx(50.0 - 50.0 / math.sqrt(2.0), abs=1e-8)
    assert point["tangent_azimuth_deg"] == pytest.approx(45.0)


def test_alignment_left_positive_station_offset_round_trip():
    alignment = build_horizontal_alignment(**_alignment_definition())

    tangent_stake = station_offset_point(alignment=alignment, station=1050.0, offset=10.0)
    assert tangent_stake["northing"] == pytest.approx(50.0)
    assert tangent_stake["easting"] == pytest.approx(-10.0)

    tangent_inverse = alignment_station_offset(
        alignment=alignment,
        point_northing=tangent_stake["northing"],
        point_easting=tangent_stake["easting"],
    )
    assert tangent_inverse["station"] == pytest.approx(1050.0)
    assert tangent_inverse["offset"] == pytest.approx(10.0)
    assert tangent_inverse["side"] == "LEFT"

    curve_station = 1100.0 + math.pi * 12.5
    curve_stake = station_offset_point(alignment=alignment, station=curve_station, offset=7.0)
    curve_inverse = alignment_station_offset(
        alignment=alignment,
        point_northing=curve_stake["northing"],
        point_easting=curve_stake["easting"],
    )
    assert curve_inverse["station"] == pytest.approx(curve_station, abs=1e-7)
    assert curve_inverse["offset"] == pytest.approx(7.0, abs=1e-7)
    assert curve_inverse["side"] == "LEFT"


def test_landxml_points_parcel_alignment_round_trip(tmp_path):
    output = tmp_path / "survey.xml"
    definition = _alignment_definition()
    written = export_landxml(
        output_path=output,
        points=[
            {
                "point_id": "101",
                "northing": 1000.0,
                "easting": 2000.0,
                "elevation": 25.5,
                "description": "CONTROL",
            },
            {
                "point_id": "102",
                "northing": 1010.0,
                "easting": 2010.0,
                "elevation": None,
                "description": "",
            },
        ],
        parcels=[
            {
                "name": "LOT 1",
                "vertices": [
                    {"northing": 0.0, "easting": 0.0},
                    {"northing": 0.0, "easting": 100.0},
                    {"northing": 100.0, "easting": 100.0},
                    {"northing": 100.0, "easting": 0.0},
                ],
            }
        ],
        alignments=[{"name": "CL-1", "alignment": definition}],
    )
    assert written["point_count"] == 2
    assert output.exists()

    loaded = import_landxml(output)
    assert loaded["landxml_version"] == "1.2"
    assert loaded["point_count"] == 2
    assert loaded["parcel_count"] == 1
    assert loaded["alignment_count"] == 1
    assert loaded["points"][0]["point_id"] == "101"
    assert loaded["points"][0]["elevation"] == pytest.approx(25.5)
    assert loaded["parcels"][0]["name"] == "LOT 1"

    imported_alignment = loaded["alignments"][0]
    assert imported_alignment["name"] == "CL-1"
    assert imported_alignment["derived"]["element_count"] == 3
    assert imported_alignment["derived"]["end_northing"] == pytest.approx(150.0, abs=1e-5)
    assert imported_alignment["derived"]["end_easting"] == pytest.approx(75.0, abs=1e-5)


def test_alignment_rejects_invalid_curve_direction():
    definition = _alignment_definition()
    definition["elements"] = [
        {"kind": "curve", "radius": 100.0, "delta_deg": 30.0, "direction": "SIDEWAYS"}
    ]
    with pytest.raises(ValueError, match="LEFT or RIGHT"):
        build_horizontal_alignment(**definition)


def test_alignment_landxml_api_preserves_source(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "cfg"))
    from fastapi.testclient import TestClient

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
            "name": "LandXML API",
            "crs": "EPSG:2278",
            "horizontal_units": "us_survey_feet",
            "vertical_units": "us_survey_feet",
        },
    )
    assert created.status_code == 200, created.text

    definition = _alignment_definition()
    built = client.post("/api/v9/cogo/alignment/build", json=definition)
    assert built.status_code == 200, built.text
    assert built.json()["element_count"] == 3

    stake = client.post(
        "/api/v9/cogo/alignment/stake-point",
        json={"alignment": definition, "station": 1050.0, "offset": 10.0},
    )
    assert stake.status_code == 200, stake.text
    assert stake.json()["easting"] == pytest.approx(-10.0)

    output = tmp_path / "api_landxml.xml"
    exported = client.post(
        "/api/v9/landxml/export",
        json={
            "output_path": str(output),
            "points": [
                {
                    "point_id": "101",
                    "northing": 1000.0,
                    "easting": 2000.0,
                    "elevation": 25.5,
                    "description": "CONTROL",
                }
            ],
            "parcels": [],
            "alignments": [{"name": "CL-API", "alignment": definition}],
        },
    )
    assert exported.status_code == 200, exported.text
    assert output.exists()

    imported = client.post("/api/v9/landxml/import", json={"file_path": str(output)})
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["point_count"] == 1
    assert body["alignment_count"] == 1
    assert body["source"]["sha256"]

    actions = [row["action"] for row in survey_router.current_project.db.recent_audit(30)]
    assert "ALIGNMENT_BUILD" in actions
    assert "ALIGNMENT_STAKE_POINT" in actions
    assert "LANDXML_EXPORTED" in actions
    assert "SOURCE_IMPORTED" in actions
    assert "LANDXML_IMPORTED" in actions
