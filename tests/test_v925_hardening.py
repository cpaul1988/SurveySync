from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from surveysync.audit import utc_now
from surveysync.coordinate_sanity import inspect_points
from surveysync.project import SurveyProject


def _project(tmp_path: Path) -> SurveyProject:
    return SurveyProject.create(tmp_path, "Coordinate QA", crs="EPSG:2278")


def _insert_point(project: SurveyProject, point_id: str, northing: float, easting: float) -> None:
    now = utc_now()
    with project.db.connect() as conn:
        conn.execute(
            """
            INSERT INTO canonical_points(
                point_uuid,point_id,northing,easting,elevation,description,point_class,
                source_id,derived_from_json,crs,horizontal_units,vertical_units,
                review_state,revision,created_utc,modified_utc
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                uuid4().hex, point_id, northing, easting, 10.0, "QA", "survey",
                None, "[]", "EPSG:2278", "us_survey_feet", "us_survey_feet",
                "REVIEWED", 1, now, now,
            ),
        )


def _flag(result: dict, code: str) -> dict | None:
    return next((item for item in result.get("flags", []) if item.get("code") == code), None)


def test_coordinate_sanity_keeps_northing_easting_and_point_id_row_aligned(tmp_path):
    project = _project(tmp_path)
    cluster = [
        ("P1", 1_000_000.0, 3_000_000.0),
        ("P2", 1_000_002.0, 3_000_001.0),
        ("P3", 999_998.0, 2_999_999.0),
        # This is the regression row: Northing is finite while Easting is not.
        ("BAD", 1_000_004.0, math.inf),
        ("P4", 1_000_001.0, 3_000_003.0),
        ("P5", 999_997.0, 3_000_002.0),
        ("P6", 1_000_003.0, 2_999_997.0),
        ("REMOTE", 8_000_000.0, 9_000_000.0),
    ]
    for row in cluster:
        _insert_point(project, *row)

    result = inspect_points(project)

    assert result["stats"]["count"] == 8
    assert result["stats"]["valid_pair_count"] == 7
    assert result["stats"]["invalid_pair_count"] == 1
    invalid = _flag(result, "INVALID_COORDINATE_ROWS")
    assert invalid is not None
    assert invalid["point_ids"] == ["BAD"]

    remote = _flag(result, "REMOTE_COORDINATE_OUTLIER")
    assert remote is not None
    assert remote["point_ids"] == ["REMOTE"]
    assert "BAD" not in remote["point_ids"]


def test_coordinate_sanity_excludes_nonfinite_pairs_without_corrupting_stats(tmp_path):
    project = _project(tmp_path)
    _insert_point(project, "GOOD", 1_234_567.0, 3_456_789.0)
    _insert_point(project, "BAD_N", math.inf, 3_456_790.0)
    _insert_point(project, "BAD_E", 1_234_569.0, -math.inf)

    result = inspect_points(project)

    assert result["stats"]["valid_pair_count"] == 1
    assert result["stats"]["invalid_pair_count"] == 2
    assert result["stats"]["northing_min"] == 1_234_567.0
    assert result["stats"]["northing_max"] == 1_234_567.0
    assert result["stats"]["easting_min"] == 3_456_789.0
    assert result["stats"]["easting_max"] == 3_456_789.0
    invalid = _flag(result, "INVALID_COORDINATE_ROWS")
    assert invalid is not None
    assert set(invalid["point_ids"]) == {"BAD_N", "BAD_E"}


def test_static_quality_gate_passes_current_tree():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "validate_static_quality.py")],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "static quality gate passed" in completed.stdout.lower()
