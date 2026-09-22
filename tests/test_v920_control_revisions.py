from __future__ import annotations

import json

import pytest

from surveysync.control import import_observations, list_solutions, solve
from surveysync.leveling import import_run, solution_history, solve_saved_run
from surveysync.project import SurveyProject
from surveysync.revisions import compare_control_solutions, compare_level_solutions, set_active_solution


def make_project(tmp_path):
    return SurveyProject.create(tmp_path, "Revision Test")


def test_control_revision_activation_compare_and_restore(tmp_path):
    p = make_project(tmp_path)
    import_observations(
        p.db,
        [
            {"control_id": "CP1", "northing": 100.0, "easting": 200.0, "elevation": 10.0},
            {"control_id": "CP1", "northing": 100.03, "easting": 200.0, "elevation": 10.02},
            {"control_id": "CP1", "northing": 100.00, "easting": 200.03, "elevation": 10.01},
        ],
    )
    r1 = solve(p.db, "CP1", "arithmetic", 0.10, 0.10)

    # A changed included observation creates a genuinely different immutable revision.
    with p.db.connect() as conn:
        oid = conn.execute(
            "SELECT observation_id FROM control_observations WHERE control_id='CP1' ORDER BY observation_id LIMIT 1"
        ).fetchone()[0]
        conn.execute("UPDATE control_observations SET northing=northing+0.03 WHERE observation_id=?", (oid,))
    r2 = solve(p.db, "CP1", "arithmetic", 0.10, 0.10)

    hist = list_solutions(p.db, "CP1")
    assert [x["revision"] for x in hist] == [2, 1]
    assert hist[0]["active"] is True
    assert hist[1]["active"] is False

    diff = compare_control_solutions(p.db, "CP1", r1["solution_id"], r2["solution_id"])
    assert diff["delta"]["horizontal_shift"] > 0
    assert diff["delta"]["northing"] != 0

    restored = set_active_solution(
        p.db,
        "control",
        "CP1",
        r1["solution_id"],
        note="unit-test restore",
        audit_action="CONTROL_SOLUTION_RESTORED",
    )
    assert restored["revision"] == 1
    hist = list_solutions(p.db, "CP1")
    assert next(x for x in hist if x["revision"] == 1)["active"] is True
    assert next(x for x in hist if x["revision"] == 2)["active"] is False
    with p.db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM control_solutions WHERE control_id='CP1'").fetchone()[0]
    assert count == 2, "Restoring must not delete or clone immutable solution history."


def test_level_revision_activation_compare_and_restore(tmp_path):
    p = make_project(tmp_path)
    run_id = import_run(
        p.db,
        "Loop 1",
        [
            {
                "point_id": "TP1",
                "bs_upper": 5.31,
                "bs_middle": 5.20,
                "bs_lower": 5.10,
                "fs_upper": 4.50,
                "fs_middle": 4.39,
                "fs_lower": 4.30,
            }
        ],
        start_elevation=100.0,
        known_end_elevation=100.81,
        adjustment_method="none",
    )
    r1 = solve_saved_run(p.db, run_id, adjustment_method="none", calculation_profile="ron_workbook")
    r2 = solve_saved_run(p.db, run_id, adjustment_method="setups", calculation_profile="ron_workbook")

    hist = solution_history(p.db, run_id)
    assert [x["revision"] for x in hist] == [2, 1]
    assert hist[0]["active"] is True

    diff = compare_level_solutions(p.db, run_id, r1["solution_id"], r2["solution_id"])
    assert diff["delta"]["method_changed"] is True
    assert diff["delta"]["adjustment_state_changed"] is True

    set_active_solution(
        p.db,
        "level",
        run_id,
        r1["solution_id"],
        note="unit-test restore",
        audit_action="LEVEL_SOLUTION_RESTORED",
    )
    hist = solution_history(p.db, run_id)
    assert next(x for x in hist if x["revision"] == 1)["active"] is True
    assert next(x for x in hist if x["revision"] == 2)["active"] is False


def test_revision_selection_rejects_solution_from_other_object(tmp_path):
    p = make_project(tmp_path)
    import_observations(p.db, [{"control_id": "CP1", "northing": 1, "easting": 2, "elevation": 3}])
    import_observations(p.db, [{"control_id": "CP2", "northing": 4, "easting": 5, "elevation": 6}])
    s1 = solve(p.db, "CP1")
    solve(p.db, "CP2")
    with pytest.raises(ValueError, match="does not belong"):
        set_active_solution(p.db, "control", "CP2", s1["solution_id"])


def test_control_report_uses_restored_active_revision(tmp_path):
    import fitz

    from surveysync.reporting import control_report

    p = make_project(tmp_path)
    import_observations(
        p.db,
        [
            {"control_id": "CPR", "northing": 100.0, "easting": 200.0, "elevation": 10.0},
            {"control_id": "CPR", "northing": 100.03, "easting": 200.0, "elevation": 10.02},
            {"control_id": "CPR", "northing": 100.00, "easting": 200.03, "elevation": 10.01},
        ],
    )
    r1 = solve(p.db, "CPR", "arithmetic", 0.10, 0.10)
    with p.db.connect() as conn:
        oid = conn.execute(
            "SELECT observation_id FROM control_observations WHERE control_id='CPR' ORDER BY observation_id LIMIT 1"
        ).fetchone()[0]
        conn.execute("UPDATE control_observations SET northing=northing+0.06 WHERE observation_id=?", (oid,))
    solve(p.db, "CPR", "arithmetic", 0.10, 0.10)
    set_active_solution(
        p.db,
        "control",
        "CPR",
        r1["solution_id"],
        note="report regression restore",
        audit_action="CONTROL_SOLUTION_RESTORED",
    )

    out = tmp_path / "control_revision_report.pdf"
    control_report(p, out, prepared_by="QA")
    doc = fitz.open(out)
    try:
        text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    assert "CPR  Active Rev 1" in text
    assert "CPR  Active Rev 2" not in text
