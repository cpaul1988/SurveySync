from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from uuid import uuid4

from .audit import AuditDB, utc_now

ALIASES = {
    "from_point": ("from_point", "from", "start_point", "station_from"),
    "to_point": ("to_point", "to", "end_point", "station_to", "point"),
    "azimuth_deg": ("azimuth_deg", "azimuth", "az", "bearing_decimal", "direction"),
    "distance": ("distance", "dist", "length"),
    "notes": ("notes", "note", "remarks", "description"),
}


def _norm(s: str) -> str:
    return str(s or "").strip().lower().replace(" ", "_").replace("-", "_")


def _mapping(fields: list[str]) -> dict[str, str]:
    normalized = {_norm(f): f for f in fields}
    out: dict[str, str] = {}
    for target, aliases in ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                out[target] = normalized[alias]
                break
    if "azimuth_deg" not in out or "distance" not in out:
        raise ValueError("Traverse file needs Azimuth and Distance columns.")
    return out


def parse_traverse_csv(path: Path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;")
    except Exception:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("Traverse file does not contain a header row.")
    fm = _mapping(list(reader.fieldnames))
    out: list[dict] = []
    for row_no, row in enumerate(reader, start=2):
        raw_dist = str(row.get(fm["distance"], "") or "").strip()
        raw_az = str(row.get(fm["azimuth_deg"], "") or "").strip()
        if not raw_dist and not raw_az:
            continue
        try:
            distance = float(raw_dist)
            azimuth = float(raw_az) % 360.0
        except Exception as exc:
            raise ValueError(f"Invalid traverse course on row {row_no}: {exc}") from exc
        if distance <= 0:
            raise ValueError(f"Traverse distance on row {row_no} must be greater than zero.")
        out.append({
            "from_point": str(row.get(fm.get("from_point", ""), "") or "").strip(),
            "to_point": str(row.get(fm.get("to_point", ""), "") or "").strip(),
            "azimuth_deg": azimuth,
            "distance": distance,
            "notes": str(row.get(fm.get("notes", ""), "") or ""),
            "source_row": row_no,
        })
    if not out:
        raise ValueError("No traverse courses were found.")
    return out


def _delta(azimuth_deg: float, distance: float) -> tuple[float, float]:
    rad = math.radians(float(azimuth_deg))
    # Survey azimuth clockwise from north: dN=cos, dE=sin.
    return float(distance) * math.cos(rad), float(distance) * math.sin(rad)


def solve_traverse(
    courses: list[dict],
    *,
    start_n: float,
    start_e: float,
    known_end_n: float | None = None,
    known_end_e: float | None = None,
    adjustment_method: str = "bowditch",
) -> dict:
    if not courses:
        raise ValueError("No traverse courses were supplied.")
    method = str(adjustment_method or "bowditch").strip().lower()
    if method not in {"none", "bowditch", "transit"}:
        raise ValueError("Traverse adjustment method must be none, bowditch, or transit.")

    raw_courses = []
    sum_dn = sum_de = total_length = 0.0
    for idx, course in enumerate(courses, start=1):
        dn, de = _delta(course["azimuth_deg"], course["distance"])
        sum_dn += dn; sum_de += de; total_length += float(course["distance"])
        raw_courses.append({**course, "sequence_no": idx, "raw_dn": dn, "raw_de": de})

    raw_end_n = float(start_n) + sum_dn
    raw_end_e = float(start_e) + sum_de
    if known_end_n is None and known_end_e is None:
        # Closed traverse defaults to the start coordinate.
        known_end_n = float(start_n)
        known_end_e = float(start_e)
    elif known_end_n is None or known_end_e is None:
        raise ValueError("Provide both known end northing and easting, or neither for a closed traverse.")
    target_dn = float(known_end_n) - float(start_n)
    target_de = float(known_end_e) - float(start_e)
    closure_n = sum_dn - target_dn
    closure_e = sum_de - target_de
    linear_closure = math.hypot(closure_n, closure_e)
    precision_ratio = (total_length / linear_closure) if linear_closure > 0 else math.inf

    abs_dn_sum = sum(abs(c["raw_dn"]) for c in raw_courses)
    abs_de_sum = sum(abs(c["raw_de"]) for c in raw_courses)
    n = float(start_n); e = float(start_e)
    results = []
    for course in raw_courses:
        corr_n = corr_e = 0.0
        if method == "bowditch" and total_length > 0:
            fraction = float(course["distance"]) / total_length
            corr_n = -closure_n * fraction
            corr_e = -closure_e * fraction
        elif method == "transit":
            corr_n = -closure_n * (abs(course["raw_dn"]) / abs_dn_sum) if abs_dn_sum > 0 else 0.0
            corr_e = -closure_e * (abs(course["raw_de"]) / abs_de_sum) if abs_de_sum > 0 else 0.0
        adj_dn = course["raw_dn"] + corr_n
        adj_de = course["raw_de"] + corr_e
        start_course_n, start_course_e = n, e
        n += adj_dn; e += adj_de
        results.append({
            **course,
            "start_n": start_course_n,
            "start_e": start_course_e,
            "correction_n": corr_n,
            "correction_e": corr_e,
            "adjusted_dn": adj_dn,
            "adjusted_de": adj_de,
            "end_n": n,
            "end_e": e,
        })

    return {
        "start_n": float(start_n), "start_e": float(start_e),
        "known_end_n": float(known_end_n), "known_end_e": float(known_end_e),
        "raw_end_n": raw_end_n, "raw_end_e": raw_end_e,
        "adjusted_end_n": n, "adjusted_end_e": e,
        "closure_n": closure_n, "closure_e": closure_e,
        "linear_closure": linear_closure,
        "total_length": total_length,
        "precision_ratio": precision_ratio,
        "adjusted": method != "none",
        "adjustment_method": method,
        "courses": results,
        "formula_status": "DETERMINISTIC_GENERIC",
    }


def import_run(db: AuditDB, name: str, courses: list[dict], *, start_n: float, start_e: float, end_n: float | None = None, end_e: float | None = None, source_id: str | None = None, adjustment_method: str = "bowditch") -> str:
    run_id = uuid4().hex
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO traverse_runs(run_id,name,created_utc,source_id,start_n,start_e,end_n,end_e,adjustment_method,status,notes) VALUES(?,?,?,?,?,?,?,?,?,'IMPORTED','')",
            (run_id, name, utc_now(), source_id, float(start_n), float(start_e), end_n, end_e, adjustment_method),
        )
        for idx, course in enumerate(courses, start=1):
            conn.execute(
                "INSERT INTO traverse_courses(course_id,run_id,sequence_no,from_point,to_point,azimuth_deg,distance,notes) VALUES(?,?,?,?,?,?,?,?)",
                (uuid4().hex, run_id, idx, course.get("from_point", ""), course.get("to_point", ""), course["azimuth_deg"], course["distance"], course.get("notes", "")),
            )
    db.audit("ControlSync", "TRAVERSE_IMPORTED", object_type="traverse_run", object_id=run_id, details={"name": name, "course_count": len(courses)})
    return run_id


def solve_saved_run(db: AuditDB, run_id: str, *, adjustment_method: str | None = None) -> dict:
    with db.connect() as conn:
        run = conn.execute("SELECT * FROM traverse_runs WHERE run_id=?", (run_id,)).fetchone()
        if not run:
            raise ValueError("Traverse run was not found.")
        courses = [dict(r) for r in conn.execute("SELECT * FROM traverse_courses WHERE run_id=? ORDER BY sequence_no", (run_id,)).fetchall()]
    rd = dict(run)
    result = solve_traverse(
        courses, start_n=rd["start_n"], start_e=rd["start_e"], known_end_n=rd["end_n"], known_end_e=rd["end_e"], adjustment_method=adjustment_method or rd["adjustment_method"]
    )
    with db.connect() as conn:
        revision = int(conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM traverse_solutions WHERE run_id=?", (run_id,)).fetchone()[0])
        solution_id = uuid4().hex
        conn.execute(
            "INSERT INTO traverse_solutions(solution_id,run_id,ts_utc,revision,closure_n,closure_e,linear_closure,precision_ratio,adjusted,method,results_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (solution_id, run_id, utc_now(), revision, result["closure_n"], result["closure_e"], result["linear_closure"], result["precision_ratio"] if math.isfinite(result["precision_ratio"]) else None, 1 if result["adjusted"] else 0, result["adjustment_method"], json.dumps(result["courses"], sort_keys=True)),
        )
        conn.execute("UPDATE traverse_runs SET status='SOLVED',adjustment_method=? WHERE run_id=?", (result["adjustment_method"], run_id))
        conn.execute("INSERT INTO derived_result_state(result_kind,object_id,state,reason,changed_utc) VALUES(?,?,?,?,?) ON CONFLICT(result_kind,object_id) DO UPDATE SET state='CURRENT',reason=excluded.reason,changed_utc=excluded.changed_utc", ("traverse", run_id, "CURRENT", "Traverse solution recalculated", utc_now()))
    db.audit("ControlSync", "TRAVERSE_SOLUTION_CREATED", object_type="traverse_solution", object_id=solution_id, revision=revision, details={"run_id": run_id, "linear_closure": result["linear_closure"], "method": result["adjustment_method"]})
    return {**result, "run_id": run_id, "solution_id": solution_id, "revision": revision}


def list_runs(db: AuditDB) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT r.*, (SELECT COUNT(*) FROM traverse_courses c WHERE c.run_id=r.run_id) AS course_count, (SELECT MAX(revision) FROM traverse_solutions s WHERE s.run_id=r.run_id) AS latest_revision FROM traverse_runs r ORDER BY created_utc DESC").fetchall()
    return [dict(r) for r in rows]
