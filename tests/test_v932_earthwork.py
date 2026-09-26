from __future__ import annotations

import pytest

from surveysync.earthwork import (
    average_end_area_earthwork,
    cross_section_cut_fill,
    slope_catch_2d,
)


def test_cross_section_flat_cut_reference():
    result = cross_section_cut_fill(
        ground_points=[
            {"offset": -10.0, "elevation": 102.0},
            {"offset": 10.0, "elevation": 102.0},
        ],
        design_points=[
            {"offset": -10.0, "relative_elevation": 0.0},
            {"offset": 10.0, "relative_elevation": 0.0},
        ],
        design_centerline_elevation=100.0,
    )
    assert result["cut_area"] == pytest.approx(40.0)
    assert result["fill_area"] == pytest.approx(0.0)
    assert result["width"] == pytest.approx(20.0)


def test_average_end_area_reference():
    result = average_end_area_earthwork(
        sections=[
            {"station": 1000.0, "cut_area": 40.0, "fill_area": 0.0},
            {"station": 1100.0, "cut_area": 20.0, "fill_area": 10.0},
        ]
    )
    assert result["total_cut_volume"] == pytest.approx(3000.0)
    assert result["total_fill_volume"] == pytest.approx(500.0)
    assert result["net_volume_cut_positive"] == pytest.approx(2500.0)
    assert result["intervals"][0]["mass_haul_ordinate"] == pytest.approx(2500.0)


def test_slope_catch_hits_flat_ground():
    result = slope_catch_2d(
        ground_points=[
            {"offset": 0.0, "elevation": 98.0},
            {"offset": 30.0, "elevation": 98.0},
        ],
        design_points=[
            {"offset": 0.0, "relative_elevation": 0.0},
            {"offset": 10.0, "relative_elevation": -1.0},
        ],
        design_centerline_elevation=100.0,
        side="RIGHT",
    )
    assert result["extrapolated"] is False
    assert result["catch_offset"] == pytest.approx(20.0)
    assert result["catch_elevation"] == pytest.approx(98.0)


def test_cross_section_rejects_nonoverlap():
    with pytest.raises(ValueError, match="do not overlap"):
        cross_section_cut_fill(
            ground_points=[
                {"offset": -20.0, "elevation": 100.0},
                {"offset": -10.0, "elevation": 100.0},
            ],
            design_points=[
                {"offset": 10.0, "relative_elevation": 0.0},
                {"offset": 20.0, "relative_elevation": 0.0},
            ],
            design_centerline_elevation=100.0,
        )
