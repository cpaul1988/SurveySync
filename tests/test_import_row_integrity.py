"""Never silently remove measured survey rows with missing identifiers."""
from pathlib import Path

import pytest

from surveysync.control import parse_control_csv
from surveysync.leveling import parse_level_csv


def test_level_rejects_populated_row_without_point_id(tmp_path: Path):
    path = tmp_path / "level.csv"
    path.write_text("PointID,BS,FS\nTP1,1.00,0.90\n,1.20,1.10\n")
    with pytest.raises(ValueError, match="row 3.*no PointID"):
        parse_level_csv(path)


def test_control_rejects_coordinate_row_without_point_id(tmp_path: Path):
    path = tmp_path / "control.csv"
    path.write_text("PointID,Northing,Easting,Elevation\n100A,100,200,10\n,101,201,11\n")
    with pytest.raises(ValueError, match="row 3.*no control or PointID"):
        parse_control_csv(path)
