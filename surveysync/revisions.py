from __future__ import annotations

import json
import math
from typing import Any

from .audit import AuditDB, utc_now

_KIND_META = {
    "control": ("control_solutions", "control_id"),
    "level": ("level_solutions", "run_id"),
    "traverse": ("traverse_solutions", "run_id"),
}


def _meta(solution_kind: str) -> tuple[str, str]:
    kind = str(solution_kind or "").strip().lower()
    if kind not in _KIND_META:
        raise ValueError(f"Unsupported solution kind: {solution_kind}")
    return _KIND_META[kind]


def get_active_solution_id(db: AuditDB, solution_kind: str, object_id: str) -> str | None:
    kind = str(solution_kind or "").strip().lower()
    _meta(kind)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT solution_id FROM solution_selections WHERE solution_kind=? AND object_id=?",
            (kind, object_id),
        ).fetchone()
    return str(row["solution_id"]) if row else None


def set_active_solution(
    db: AuditDB,
    solution_kind: str,
    object_id: str,
    solution_id: str,
    *,
    note: str = "",
    audit_action: str | None = None,
) -> dict[str, Any]:
    kind = str(solution_kind or "").strip().lower()
    table, object_column = _meta(kind)
    object_id = str(object_id or "").strip()
    solution_id = str(solution_id or "").strip()
    if not object_id or not solution_id:
        raise ValueError("Object ID and solution ID are required.")
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT solution_id, revision FROM {table} WHERE solution_id=? AND {object_column}=?",
            (solution_id, object_id),
        ).fetchone()
        if not row:
            raise ValueError(f"The selected {kind} solution does not belong to {object_id}.")
        conn.execute(
            """
            INSERT INTO solution_selections(solution_kind,object_id,solution_id,revision,selected_utc,note)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(solution_kind,object_id) DO UPDATE SET
              solution_id=excluded.solution_id,
              revision=excluded.revision,
              selected_utc=excluded.selected_utc,
              note=excluded.note
            """,
            (kind, object_id, solution_id, int(row["revision"]), utc_now(), str(note or "")),
        )
    action = audit_action or f"{kind.upper()}_SOLUTION_ACTIVATED"
    db.audit(
        "ControlSync",
        action,
        object_type=f"{kind}_solution",
        object_id=solution_id,
        revision=int(row["revision"]),
        details={"parent_id": object_id, "note": str(note or "")},
    )
    return {
        "solution_kind": kind,
        "object_id": object_id,
        "solution_id": solution_id,
        "revision": int(row["revision"]),
        "active": True,
        "note": str(note or ""),
    }


def active_or_latest_solution_id(db: AuditDB, solution_kind: str, object_id: str) -> str | None:
    kind = str(solution_kind or "").strip().lower()
    table, object_column = _meta(kind)
    selected = get_active_solution_id(db, kind, object_id)
    if selected:
        return selected
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT solution_id FROM {table} WHERE {object_column}=? ORDER BY revision DESC LIMIT 1",
            (object_id,),
        ).fetchone()
    return str(row["solution_id"]) if row else None


def _json(value: str | None, default):
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _fetch_control_solution(db: AuditDB, control_id: str, solution_id: str) -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM control_solutions WHERE control_id=? AND solution_id=?",
            (control_id, solution_id),
        ).fetchone()
    if not row:
        raise ValueError("Control solution was not found for this control ID.")
    d = dict(row)
    d["settings"] = _json(d.pop("settings_json", "{}"), {})
    d["residuals"] = _json(d.pop("residuals_json", "[]"), [])
    d["pass"] = bool(d["pass"])
    return d


def compare_control_solutions(db: AuditDB, control_id: str, solution_a: str, solution_b: str) -> dict:
    a = _fetch_control_solution(db, control_id, solution_a)
    b = _fetch_control_solution(db, control_id, solution_b)
    dn = float(b["northing"]) - float(a["northing"])
    de = float(b["easting"]) - float(a["easting"])
    za, zb = a.get("elevation"), b.get("elevation")
    dz = (float(zb) - float(za)) if za is not None and zb is not None else None
    return {
        "control_id": control_id,
        "a": a,
        "b": b,
        "delta": {
            "northing": dn,
            "easting": de,
            "horizontal_shift": math.hypot(dn, de),
            "elevation": dz,
            "method_changed": a.get("method") != b.get("method"),
            "pass_changed": bool(a.get("pass")) != bool(b.get("pass")),
            "settings_changed": a.get("settings") != b.get("settings"),
        },
    }


def _fetch_level_solution(db: AuditDB, run_id: str, solution_id: str) -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM level_solutions WHERE run_id=? AND solution_id=?",
            (run_id, solution_id),
        ).fetchone()
    if not row:
        raise ValueError("Level solution was not found for this run.")
    d = dict(row)
    d["settings"] = _json(d.pop("settings_json", "{}"), {})
    d["results"] = _json(d.pop("results_json", "[]"), [])
    d["qc"] = _json(d.pop("qc_json", "{}"), {})
    d["adjusted"] = bool(d["adjusted"])
    return d


def _end_elevation(solution: dict) -> float | None:
    rows = solution.get("results") or []
    if not rows:
        return None
    value = rows[-1].get("adjusted_elevation")
    return float(value) if value is not None else None


def compare_level_solutions(db: AuditDB, run_id: str, solution_a: str, solution_b: str) -> dict:
    a = _fetch_level_solution(db, run_id, solution_a)
    b = _fetch_level_solution(db, run_id, solution_b)
    ca, cb = a.get("closure"), b.get("closure")
    ea, eb = _end_elevation(a), _end_elevation(b)
    return {
        "run_id": run_id,
        "a": a,
        "b": b,
        "delta": {
            "closure": (float(cb) - float(ca)) if ca is not None and cb is not None else None,
            "adjusted_end_elevation": (eb - ea) if ea is not None and eb is not None else None,
            "method_changed": a.get("method") != b.get("method"),
            "adjustment_state_changed": bool(a.get("adjusted")) != bool(b.get("adjusted")),
            "settings_changed": a.get("settings") != b.get("settings"),
            "qc_flags_added": sorted(set((b.get("qc") or {}).get("qc_flags") or []) - set((a.get("qc") or {}).get("qc_flags") or [])),
            "qc_flags_removed": sorted(set((a.get("qc") or {}).get("qc_flags") or []) - set((b.get("qc") or {}).get("qc_flags") or [])),
        },
    }
