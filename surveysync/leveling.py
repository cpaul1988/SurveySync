from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from uuid import uuid4

from .audit import AuditDB, utc_now
from .survey_validation import finite_number, normalize_header
from .revisions import get_active_solution_id, set_active_solution

ALIASES = {
    "point_id": ("point_id", "point", "pt", "station", "tp", "turning_point"),
    "backsight": ("backsight", "bs", "back_sight"),
    "foresight": ("foresight", "fs", "fore_sight"),
    "bs_upper": ("bs_upper", "bs_top", "bs_u", "bsupper"),
    "bs_middle": ("bs_middle", "bs_mid", "bs_m", "bsmiddle"),
    "bs_lower": ("bs_lower", "bs_bottom", "bs_l", "bslower"),
    "fs_upper": ("fs_upper", "fs_top", "fs_u", "fsupper"),
    "fs_middle": ("fs_middle", "fs_mid", "fs_m", "fsmiddle"),
    "fs_lower": ("fs_lower", "fs_bottom", "fs_l", "fslower"),
    "distance_bs": ("distance_bs", "bs_distance", "dist_bs", "bs_dist"),
    "distance_fs": ("distance_fs", "fs_distance", "dist_fs", "fs_dist"),
    "notes": ("notes", "note", "remarks", "description"),
}


def _norm(value: str) -> str:
    return normalize_header(value)


def _maybe_float(value) -> float | None:
    raw = "" if value is None else str(value).strip()
    if not raw:
        return None
    return finite_number(raw)


def _mapping(fieldnames: list[str]) -> dict[str, str]:
    normed = {_norm(name): name for name in fieldnames}
    out: dict[str, str] = {}
    for target, aliases in ALIASES.items():
        for alias in aliases:
            if _norm(alias) in normed:
                out[target] = normed[_norm(alias)]
                break
    if "point_id" not in out:
        raise ValueError("Level file needs a Point/PointID/Station column.")
    has_single = "backsight" in out or "foresight" in out
    has_three_wire = all(k in out for k in ("bs_upper", "bs_middle", "bs_lower")) or all(k in out for k in ("fs_upper", "fs_middle", "fs_lower"))
    if not has_single and not has_three_wire:
        raise ValueError("Level file needs BS/FS columns or three-wire BS/FS upper-middle-lower columns.")
    return out


def parse_level_csv(path: Path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;")
    except Exception:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("Level file does not contain a header row.")
    fm = _mapping(list(reader.fieldnames))
    out: list[dict] = []
    for line_no, row in enumerate(reader, start=2):
        point_id = str(row.get(fm["point_id"], "") or "").strip()
        if not point_id:
            if any(str(value or "").strip() for value in row.values() if isinstance(value, str)):
                raise ValueError(f"Level row {line_no} has data but no PointID.")
            continue
        try:
            item = {"point_id": point_id, "source_row": line_no}
            for key in (
                "backsight", "foresight", "bs_upper", "bs_middle", "bs_lower",
                "fs_upper", "fs_middle", "fs_lower", "distance_bs", "distance_fs",
            ):
                item[key] = _maybe_float(row.get(fm[key])) if key in fm else None
            item["notes"] = str(row.get(fm.get("notes", ""), "") or "")
        except Exception as exc:
            raise ValueError(f"Invalid level value on row {line_no}: {exc}") from exc
        out.append(item)
    if not out:
        raise ValueError("No level observations were found.")
    return out


def three_wire_mean(upper: float | None, middle: float | None, lower: float | None, *, profile: str = "middle_wire") -> tuple[float | None, float | None, float | None]:
    """Return (reading, middle_check, stadia_intercept).

    ``middle_wire`` preserves the generic SurveySync behavior: use the observed
    middle wire as the level reading when present. ``ron_workbook`` reproduces
    the authoritative "3 Wire Level Loop Template.xlsx" formulas: the reported
    BS/FS reading is the arithmetic average of all three wire readings, and the
    stadia intercept is upper-lower (multiplied by 100 by the caller).
    """
    mode=str(profile or "middle_wire").strip().lower()
    vals=[v for v in (upper,middle,lower) if v is not None]
    if mode == "ron_workbook":
        reading=(sum(float(v) for v in vals)/len(vals)) if len(vals)==3 else None
    elif middle is not None:
        reading=float(middle)
    elif upper is not None and lower is not None:
        reading=(float(upper)+float(lower))/2.0
    else:
        reading=None
    check=None
    intercept=None
    if upper is not None and lower is not None:
        intercept=float(upper)-float(lower)
        if middle is not None:
            check=abs(float(middle)-((float(upper)+float(lower))/2.0))
    return reading,check,intercept

def normalize_observation(obs: dict, *, stadia_multiplier: float = 100.0, calculation_profile: str = "middle_wire") -> dict:
    obs = dict(obs)
    for key in ("backsight", "foresight", "bs_upper", "bs_middle", "bs_lower",
                "fs_upper", "fs_middle", "fs_lower", "distance_bs", "distance_fs"):
        if obs.get(key) is not None:
            obs[key] = finite_number(obs[key], key)
    for prefix, reading in (("bs", "backsight"), ("fs", "foresight")):
        count = sum(obs.get(prefix + "_" + wire) is not None for wire in ("upper", "middle", "lower"))
        if calculation_profile == "ron_workbook" and obs.get(reading) is None and count in (1, 2):
            raise ValueError("Ron workbook reduction requires all three wires or an explicit reduced reading.")
    bs = obs.get("backsight")
    fs = obs.get("foresight")
    bs_check = fs_check = None
    bs_intercept = fs_intercept = None
    if bs is None:
        bs, bs_check, bs_intercept = three_wire_mean(obs.get("bs_upper"), obs.get("bs_middle"), obs.get("bs_lower"), profile=calculation_profile)
    else:
        _, bs_check, bs_intercept = three_wire_mean(obs.get("bs_upper"), obs.get("bs_middle"), obs.get("bs_lower"), profile=calculation_profile)
    if fs is None:
        fs, fs_check, fs_intercept = three_wire_mean(obs.get("fs_upper"), obs.get("fs_middle"), obs.get("fs_lower"), profile=calculation_profile)
    else:
        _, fs_check, fs_intercept = three_wire_mean(obs.get("fs_upper"), obs.get("fs_middle"), obs.get("fs_lower"), profile=calculation_profile)
    dist_bs = obs.get("distance_bs")
    dist_fs = obs.get("distance_fs")
    if dist_bs is None and bs_intercept is not None:
        dist_bs = bs_intercept * stadia_multiplier
    if dist_fs is None and fs_intercept is not None:
        dist_fs = fs_intercept * stadia_multiplier
    return {
        **obs,
        "backsight": bs,
        "foresight": fs,
        "bs_middle_check": bs_check,
        "fs_middle_check": fs_check,
        "distance_bs": dist_bs,
        "distance_fs": dist_fs,
        "bs_stadia_intercept": bs_intercept,
        "fs_stadia_intercept": fs_intercept,
        "calculation_profile": str(calculation_profile or "middle_wire"),
    }


def resolve_row_layout(rows, requested):
    sides = [(r.get("backsight") is not None, r.get("foresight") is not None) for r in rows]
    paired = all(bs and fs for bs, fs in sides)
    separate = len(sides) % 2 == 0 and all(side == ((True, False) if i % 2 == 0 else (False, True)) for i, side in enumerate(sides))
    stations = len(sides) >= 2 and sides[0] == (True, False) and sides[-1] == (False, True) and all(bs and fs for bs, fs in sides[1:-1])
    if requested == "auto":
        if paired:
            return "differential_setups"
        if separate:
            return "separate_sights"
        raise ValueError("Ambiguous level-book layout. Select station_rows explicitly for BS on starting benchmark and FS/BS on turning points.")
    valid = {"differential_setups": paired, "separate_sights": separate, "station_rows": stations}
    if not valid.get(requested, False):
        raise ValueError(f"Readings do not match selected level row layout {requested!r}.")
    return requested


def solve_level_run(
    observations: list[dict],
    *,
    start_elevation: float,
    known_end_elevation: float | None = None,
    adjustment_method: str = "none",
    middle_wire_tolerance: float = 0.005,
    max_distance_imbalance: float | None = None,
    closure_tolerance: float | None = None,
    stadia_multiplier: float = 100.0,
    calculation_profile: str = "ron_workbook",
    row_layout: str = "auto",
) -> dict:
    if not observations:
        raise ValueError("No level observations were supplied.")
    start_elevation = finite_number(start_elevation, "Start elevation")
    if known_end_elevation is not None:
        known_end_elevation = finite_number(known_end_elevation, "Known end elevation")
    middle_wire_tolerance = finite_number(middle_wire_tolerance, "Middle-wire tolerance")
    stadia_multiplier = finite_number(stadia_multiplier, "Stadia multiplier")
    for value in (middle_wire_tolerance, stadia_multiplier, max_distance_imbalance, closure_tolerance):
        if value is not None and finite_number(value, "Tolerance/multiplier") < 0:
            raise ValueError("Tolerances and stadia multiplier must not be negative.")
    method = str(adjustment_method or "none").strip().lower()
    if method not in {"none", "setups", "distance"}:
        raise ValueError("Level adjustment method must be none, setups, or distance.")
    calc_profile=str(calculation_profile or "ron_workbook").strip().lower()
    if calc_profile not in {"ron_workbook","middle_wire"}:
        raise ValueError("Level calculation profile must be ron_workbook or middle_wire.")
    rows = [normalize_observation(o, stadia_multiplier=stadia_multiplier, calculation_profile=calc_profile) for o in observations]
    layout = resolve_row_layout(rows, row_layout)
    current = float(start_elevation)
    height_of_instrument = None
    results: list[dict] = []
    total_bs = total_fs = 0.0
    total_bs_distance = total_fs_distance = 0.0
    setup_count = 0
    wire_flags: list[str] = []
    cumulative_distance = 0.0

    for idx, row in enumerate(rows, start=1):
        bs = row.get("backsight")
        fs = row.get("foresight")
        if bs is None and fs is None:
            raise ValueError(f"Level row {row.get('source_row', idx)} has neither a backsight nor foresight reading.")
        if bs is not None:
            total_bs += float(bs)
        if fs is not None:
            total_fs += float(fs)
        role = "POINT"
        if layout == "differential_setups":
            height_of_instrument = finite_number(current + bs, "Height of instrument")
            current = finite_number(height_of_instrument - fs, "Point elevation")
            setup_count += 1
            displayed = current
        elif layout == "station_rows":
            if fs is not None:
                current = finite_number(height_of_instrument - fs, "Point elevation")
                setup_count += 1
            displayed = current
            if bs is not None:
                height_of_instrument = finite_number(current + bs, "Height of instrument")
        elif bs is not None:
            height_of_instrument = finite_number(current + bs, "Height of instrument")
            displayed = height_of_instrument
            role = "HEIGHT_OF_INSTRUMENT"
        else:
            current = finite_number(height_of_instrument - fs, "Point elevation")
            displayed = current
            setup_count += 1
        db = float(row.get("distance_bs") or 0.0)
        df = float(row.get("distance_fs") or 0.0)
        total_bs_distance += db
        total_fs_distance += df
        cumulative_distance += max(db, df, 0.0)
        for label, check in (("BS", row.get("bs_middle_check")), ("FS", row.get("fs_middle_check"))):
            if check is not None and check > middle_wire_tolerance:
                wire_flags.append(f"Row {row.get('source_row', idx)} {label} middle-wire check {check:.4f} exceeds {middle_wire_tolerance:.4f}.")
        for label, intercept in (("BS", row.get("bs_stadia_intercept")), ("FS", row.get("fs_stadia_intercept"))):
            if intercept is not None and float(intercept) < 0:
                wire_flags.append(f"Row {row.get('source_row', idx)} {label} upper/lower wires appear reversed (stadia intercept {float(intercept):+.4f}).")
        results.append({
            "sequence_no": idx,
            "point_id": row.get("point_id") or "",
            "raw_elevation": displayed,
            "adjusted_elevation": displayed,
            "row_role": role,
            "point_elevation": current if role == "POINT" else None,
            "height_of_instrument": height_of_instrument,
            "cumulative_setups": setup_count,
            "backsight": bs,
            "foresight": fs,
            "distance_bs": row.get("distance_bs"),
            "distance_fs": row.get("distance_fs"),
            "stadia_difference": (float(row.get("distance_bs") or 0.0) - float(row.get("distance_fs") or 0.0)),
            "cumulative_distance": cumulative_distance,
            "bs_middle_check": row.get("bs_middle_check"),
            "fs_middle_check": row.get("fs_middle_check"),
            "correction": 0.0,
        })

    raw_end = current
    closure = None if known_end_elevation is None else raw_end - float(known_end_elevation)
    adjusted = False
    if closure is not None and method != "none" and results:
        if method == "distance" and cumulative_distance > 0:
            denom = cumulative_distance
            for r in results:
                fraction = 0.0 if r["cumulative_setups"] == 0 else float(r["cumulative_distance"]) / denom
                correction = -closure * fraction
                r["correction"] = correction
                r["adjusted_elevation"] = r["raw_elevation"] + correction
        else:
            # Setup-count distribution is deterministic and remains available when
            # field books do not include stadia distances.
            denom = max(1, setup_count)
            for i, r in enumerate(results, start=1):
                fraction = r["cumulative_setups"] / denom
                correction = -closure * fraction
                r["correction"] = correction
                r["adjusted_elevation"] = r["raw_elevation"] + correction
        adjusted = True

    for row in results:
        row["adjusted_elevation"] = finite_number(row["adjusted_elevation"], "Adjusted elevation")
        row["adjusted_point_elevation"] = row["adjusted_elevation"] if row["row_role"] == "POINT" else None
    for value in (total_bs, total_fs, total_bs_distance, total_fs_distance, cumulative_distance):
        finite_number(value, "Level total")
    if closure is not None:
        finite_number(closure, "Level closure")
    distance_imbalance = total_bs_distance - total_fs_distance
    qc_flags = list(wire_flags)
    if max_distance_imbalance is not None and abs(distance_imbalance) > float(max_distance_imbalance):
        qc_flags.append(f"BS/FS distance imbalance {distance_imbalance:.3f} exceeds {float(max_distance_imbalance):.3f}.")
    closure_pass = None
    if closure is not None and closure_tolerance is not None:
        closure_pass = abs(closure) <= float(closure_tolerance)
        if not closure_pass:
            qc_flags.append(f"Level closure {closure:+.4f} exceeds tolerance ±{float(closure_tolerance):.4f}.")

    return {
        "start_elevation": float(start_elevation),
        "known_end_elevation": known_end_elevation,
        "raw_end_elevation": raw_end,
        "adjusted_end_elevation": results[-1]["adjusted_elevation"] if results else raw_end,
        "sum_bs": total_bs,
        "sum_fs": total_fs,
        "delta_elevation": total_bs - total_fs,
        "closure": closure,
        "closure_tolerance": closure_tolerance,
        "closure_pass": closure_pass,
        "adjusted": adjusted,
        "adjustment_method": method,
        "setup_count": setup_count,
        "row_layout": layout,
        "total_bs_distance": total_bs_distance,
        "total_fs_distance": total_fs_distance,
        "distance_imbalance": distance_imbalance,
        "middle_wire_tolerance": middle_wire_tolerance,
        "qc_flags": qc_flags,
        "results": results,
        "calculation_profile": calc_profile,
        "formula_status": "VALIDATED_RON_WORKBOOK" if calc_profile == "ron_workbook" else "DETERMINISTIC_GENERIC",
        "formula_profile": ({
            "source_workbook":"3 Wire Level Loop Template.xlsx",
            "three_wire_reading":"AVERAGE(upper,middle,lower)",
            "stadia_distance":"(upper-lower)*100",
            "height_of_instrument":"starting elevation + averaged backsight",
            "turn_point_elevation":"height of instrument - averaged foresight",
            "setup_stadia_balance":"stadia backsight - stadia foresight",
            "close":"computed ending elevation - starting/known benchmark elevation",
            "adjustment_note":"The supplied workbook defines reduction and closure, but no closure-adjustment formula; SurveySync adjustment remains an explicit deterministic method (none/setups/distance).",
        } if calc_profile == "ron_workbook" else None),
    }


def import_run(
    db: AuditDB,
    name: str,
    observations: list[dict],
    *,
    source_id: str | None = None,
    start_elevation: float | None = None,
    known_end_elevation: float | None = None,
    start_point: str = "",
    end_point: str = "",
    adjustment_method: str = "none",
) -> str:
    for obs in observations:
        normalize_observation(obs, calculation_profile="middle_wire")
    for value in (start_elevation, known_end_elevation):
        if value is not None:
            finite_number(value, "Benchmark elevation")
    run_id = uuid4().hex
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO level_runs(run_id,name,created_utc,source_id,start_point,end_point,start_elevation,known_end_elevation,adjustment_method,status,notes) VALUES(?,?,?,?,?,?,?,?,?,'IMPORTED','')",
            (run_id, name, utc_now(), source_id, start_point, end_point, start_elevation, known_end_elevation, adjustment_method),
        )
        for idx, obs in enumerate(observations, start=1):
            conn.execute(
                "INSERT INTO level_observations(observation_id,run_id,sequence_no,point_id,backsight,foresight,bs_upper,bs_middle,bs_lower,fs_upper,fs_middle,fs_lower,distance_bs,distance_fs,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uuid4().hex, run_id, idx, obs.get("point_id", ""), obs.get("backsight"), obs.get("foresight"),
                    obs.get("bs_upper"), obs.get("bs_middle"), obs.get("bs_lower"), obs.get("fs_upper"), obs.get("fs_middle"), obs.get("fs_lower"),
                    obs.get("distance_bs"), obs.get("distance_fs"), obs.get("notes", ""),
                ),
            )
    db.audit("ControlSync", "LEVEL_RUN_IMPORTED", object_type="level_run", object_id=run_id, details={"name": name, "observation_count": len(observations)})
    return run_id


def _load_observations(db: AuditDB, run_id: str) -> tuple[dict, list[dict]]:
    with db.connect() as conn:
        run = conn.execute("SELECT * FROM level_runs WHERE run_id=?", (run_id,)).fetchone()
        if not run:
            raise ValueError("Level run was not found.")
        rows = conn.execute("SELECT * FROM level_observations WHERE run_id=? ORDER BY sequence_no", (run_id,)).fetchall()
        sights = conn.execute("SELECT sequence_no,side,readings_json FROM level_recheck_sights WHERE run_id=? AND active=1", (run_id,)).fetchall()
    observations = [dict(r) for r in rows]
    by_sequence = {row["sequence_no"]: row for row in observations}
    for sight in sights:
        if sight["sequence_no"] not in by_sequence:
            raise ValueError("An approved level recheck refers to a missing original observation.")
        apply_recheck_sight(by_sequence[sight["sequence_no"]], sight["side"], json.loads(sight["readings_json"]))
    return dict(run), observations


def apply_recheck_sight(row: dict, side: str, readings: dict) -> None:
    """Replace one approved sight while preserving the other side of a turning-point row."""
    prefix = "bs" if side == "BS" else "fs"
    if side not in {"BS", "FS"}:
        raise ValueError("Level recheck side must be BS or FS.")
    for key in ("upper", "middle", "lower"):
        row[f"{prefix}_{key}"] = finite_number(readings[key], f"{side} {key}")
    row["backsight" if side == "BS" else "foresight"] = None
    row["distance_bs" if side == "BS" else "distance_fs"] = readings.get("distance")


def solve_saved_run(
    db: AuditDB,
    run_id: str,
    *,
    start_elevation: float | None = None,
    known_end_elevation: float | None = None,
    adjustment_method: str | None = None,
    middle_wire_tolerance: float = 0.005,
    max_distance_imbalance: float | None = None,
    closure_tolerance: float | None = None,
    stadia_multiplier: float = 100.0,
    calculation_profile: str = "ron_workbook",
    row_layout: str = "auto",
) -> dict:
    run, observations = _load_observations(db, run_id)
    start = start_elevation if start_elevation is not None else run.get("start_elevation")
    if start is None:
        raise ValueError("A starting elevation is required before solving the level run.")
    known_end = known_end_elevation if known_end_elevation is not None else run.get("known_end_elevation")
    method = adjustment_method or run.get("adjustment_method") or "setups"
    result = solve_level_run(
        observations,
        start_elevation=float(start),
        known_end_elevation=known_end,
        adjustment_method=method,
        middle_wire_tolerance=middle_wire_tolerance,
        max_distance_imbalance=max_distance_imbalance,
        closure_tolerance=closure_tolerance,
        stadia_multiplier=stadia_multiplier,
        calculation_profile=calculation_profile,
        row_layout=row_layout,
    )
    with db.connect() as conn:
        recheck_ids = [r[0] for r in conn.execute("SELECT sight_id FROM level_recheck_sights WHERE run_id=? AND active=1 ORDER BY sequence_no,side", (run_id,))]
        revision = int(conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM level_solutions WHERE run_id=?", (run_id,)).fetchone()[0])
        solution_id = uuid4().hex
        conn.execute(
            "INSERT INTO level_solutions(solution_id,run_id,ts_utc,revision,closure,adjusted,method,settings_json,results_json,qc_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                solution_id, run_id, utc_now(), revision, result.get("closure"), 1 if result.get("adjusted") else 0, result["adjustment_method"],
                json.dumps({"middle_wire_tolerance": middle_wire_tolerance, "max_distance_imbalance": max_distance_imbalance, "closure_tolerance": closure_tolerance, "stadia_multiplier": stadia_multiplier, "calculation_profile": calculation_profile, "row_layout": result["row_layout"], "recheck_sight_ids": recheck_ids}, sort_keys=True),
                json.dumps(result["results"], sort_keys=True),
                json.dumps({k: result[k] for k in ("sum_bs", "sum_fs", "delta_elevation", "distance_imbalance", "qc_flags", "closure_pass")}, sort_keys=True),
            ),
        )
        conn.execute("UPDATE level_runs SET status='SOLVED',start_elevation=?,known_end_elevation=?,adjustment_method=? WHERE run_id=?", (start, known_end, method, run_id))
        conn.execute("INSERT INTO derived_result_state(result_kind,object_id,state,reason,changed_utc) VALUES(?,?,?,?,?) ON CONFLICT(result_kind,object_id) DO UPDATE SET state='CURRENT',reason=excluded.reason,changed_utc=excluded.changed_utc", ("level", run_id, "CURRENT", "Level solution recalculated", utc_now()))
    db.audit("ControlSync", "LEVEL_SOLUTION_CREATED", object_type="level_solution", object_id=solution_id, revision=revision, details={"run_id": run_id, "closure": result.get("closure"), "adjusted": result.get("adjusted")})
    set_active_solution(db, "level", run_id, solution_id, note="Newest calculated revision", audit_action="LEVEL_SOLUTION_ACTIVATED")
    return {**result, "run_id": run_id, "solution_id": solution_id, "revision": revision, "active": True}


def list_runs(db: AuditDB) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT r.*, (SELECT COUNT(*) FROM level_observations o WHERE o.run_id=r.run_id) AS observation_count, (SELECT MAX(revision) FROM level_solutions s WHERE s.run_id=r.run_id) AS latest_revision FROM level_runs r ORDER BY created_utc DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def solution_history(db: AuditDB, run_id: str) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM level_solutions WHERE run_id=? ORDER BY revision DESC", (run_id,)).fetchall()
    selected = get_active_solution_id(db, "level", run_id)
    out = []
    for idx, row in enumerate(rows):
        d = dict(row)
        d["settings"] = json.loads(d.pop("settings_json") or "{}")
        d["results"] = json.loads(d.pop("results_json") or "[]")
        d["qc"] = json.loads(d.pop("qc_json") or "{}")
        d["adjusted"] = bool(d["adjusted"])
        d["active"] = (d["solution_id"] == selected) if selected else idx == 0
        out.append(d)
    return out
