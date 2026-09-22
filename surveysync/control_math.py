from __future__ import annotations
import math
import re
from datetime import datetime, timezone


def _norm(s: str) -> str:
    return str(s or "").strip().lower().replace(" ", "_").replace("-", "_")


def derive_control_group(point_id: str) -> str:
    """Derive the base control ID from a repeated-shot point label.

    The trailing alphabetic suffix is the observation/shot designator, not part
    of the control ID. Examples: 7A/7B/7C -> 7, 100A/100B/100C -> 100,
    CP-1A -> CP-1. Labels without a trailing alpha suffix after a numeric
    character remain unchanged.
    """
    value = str(point_id or "").strip()
    match = re.match(r"^(.*\d)([A-Za-z]+)$", value)
    return match.group(1) if match else value


def canonical_control_id(control_id: str, point_id: str = "") -> str:
    """Return the canonical base control ID for an observation.

    Prefer a point label only when it clearly contains a trailing shot suffix;
    otherwise normalize the supplied control ID. This makes both TBC-style
    point exports and legacy files whose ``control_id`` column contains 100A,
    100B, 100C group correctly under control 100.
    """
    point = str(point_id or "").strip()
    if point:
        grouped = derive_control_group(point)
        if grouped != point:
            return grouped
    return derive_control_group(str(control_id or "").strip())


def _point_label(control_id: str, point_id: str, shot_id: str) -> str:
    point = str(point_id or "").strip()
    if point:
        return point
    shot = str(shot_id or "").strip()
    if shot:
        return shot if shot.lower().startswith(str(control_id).lower()) else f"{control_id}{shot}"
    return str(control_id)


def _row_point_id(row: dict) -> str:
    control_id = str(row.get("control_id") or "").strip()
    point = str(row.get("point_id") or "").strip()
    if point:
        return point
    shot = str(row.get("shot_id") or "").strip()
    if not shot:
        match = re.search(r"(?:^|\|\s*)Shot\s+([^|]+)", str(row.get("notes") or ""), re.IGNORECASE)
        shot = match.group(1).strip() if match else ""
    if shot:
        return shot if shot.lower().startswith(control_id.lower()) else f"{control_id}{shot}"
    return control_id


def _row_code(row: dict) -> str:
    direct = str(row.get("description") or row.get("code") or "").strip()
    if direct:
        return direct
    match = re.search(r"(?:^|\|\s*)Code\s+([^|]+)", str(row.get("notes") or ""), re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _optional_float(value, *, field: str, row_no: int) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field} on row {row_no}: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"Non-finite {field} on row {row_no}.")
    return number


def _optional_int(value, *, field: str, row_no: int) -> int | None:
    number = _optional_float(value, field=field, row_no=row_no)
    if number is None:
        return None
    rounded = int(round(number))
    if abs(number - rounded) > 1e-9:
        raise ValueError(f"{field} must be a whole number on row {row_no}.")
    return rounded


def _parse_duration_seconds(value, *, units_hint: str = "", row_no: int = 0) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    low = text.lower().strip()
    # Explicit unit suffixes are preferred because exporter conventions vary.
    unit_patterns = (
        (r"^([+-]?[0-9]*\.?[0-9]+)\s*(?:hours?|hrs?|hr|h)$", 3600.0),
        (r"^([+-]?[0-9]*\.?[0-9]+)\s*(?:minutes?|mins?|min|m)$", 60.0),
        (r"^([+-]?[0-9]*\.?[0-9]+)\s*(?:seconds?|secs?|sec|s)$", 1.0),
    )
    for pattern, multiplier in unit_patterns:
        match = re.match(pattern, low)
        if match:
            seconds = float(match.group(1)) * multiplier
            if not math.isfinite(seconds) or seconds < 0:
                raise ValueError(f"Invalid observation duration on row {row_no}: {value!r}")
            return seconds
    # HH:MM:SS or MM:SS. A two-field value is interpreted as minutes:seconds.
    if ":" in low:
        parts = low.split(":")
        try:
            nums = [float(x) for x in parts]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid observation duration on row {row_no}: {value!r}") from exc
        if len(nums) == 3:
            seconds = nums[0] * 3600.0 + nums[1] * 60.0 + nums[2]
        elif len(nums) == 2:
            seconds = nums[0] * 60.0 + nums[1]
        else:
            raise ValueError(f"Invalid observation duration on row {row_no}: {value!r}")
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError(f"Invalid observation duration on row {row_no}: {value!r}")
        return seconds
    try:
        number = float(low)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid observation duration on row {row_no}: {value!r}") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Invalid observation duration on row {row_no}: {value!r}")
    if units_hint == "minutes":
        return number * 60.0
    return number


def _parse_observed_time(value: str) -> dict | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return {"kind": "datetime", "value": dt}
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return {"kind": "datetime", "value": datetime.strptime(text, fmt)}
        except ValueError:
            continue
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
        try:
            t = datetime.strptime(text, fmt).time()
            return {
                "kind": "time",
                "value": t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1_000_000.0,
            }
        except ValueError:
            continue
    return None


def _time_gap_minutes(a: dict | None, b: dict | None) -> float | None:
    if not a or not b or a.get("kind") != b.get("kind"):
        return None
    if a["kind"] == "datetime":
        return abs((a["value"] - b["value"]).total_seconds()) / 60.0
    diff = abs(float(a["value"]) - float(b["value"]))
    # Time-only exports can cross midnight. Use the shortest distance around a 24h clock.
    diff = min(diff, 86400.0 - diff)
    return diff / 60.0


def _field_observation_checks(
    rows: list[dict],
    *,
    min_time_separation_minutes: float = 60.0,
    min_epochs: int = 300,
    min_duration_seconds: float = 300.0,
    min_satellites: int = 5,
    max_pdop: float | None = None,
    max_hdop: float | None = None,
    max_vdop: float | None = None,
) -> dict:
    """Validate field-observation quality without inventing missing metadata.

    Duration/epoch, satellite, time-separation and optional DOP rules are evaluated
    independently. Missing values produce UNVERIFIED; values explicitly outside a
    configured limit produce FAIL.
    """
    per_shot = []
    explicit_failures: list[str] = []
    missing = []
    parsed_times = []
    dop_limits = {"pdop": max_pdop, "hdop": max_hdop, "vdop": max_vdop}
    for row in rows:
        point_id = _row_point_id(row) or str(row.get("observation_id") or "")
        epochs = row.get("epoch_count")
        duration = row.get("duration_seconds")
        satellites = row.get("satellite_count")
        length_known = epochs is not None or duration is not None
        length_pass = (
            (
                (epochs is not None and int(epochs) >= int(min_epochs))
                or (duration is not None and float(duration) >= float(min_duration_seconds))
            )
            if length_known
            else None
        )
        satellite_pass = (
            (int(satellites) >= int(min_satellites)) if satellites is not None else None
        )
        time_provided = bool(row.get("observed_time_provided"))
        parsed = _parse_observed_time(str(row.get("observed_utc") or "")) if time_provided else None
        parsed_times.append((point_id, parsed))
        failures = []
        if length_pass is False:
            failures.append(
                f"observation shorter than {min_epochs} epochs / {min_duration_seconds / 60.0:g} min"
            )
        if satellite_pass is False:
            failures.append(f"fewer than {min_satellites} satellites")
        if not length_known:
            missing.append(f"{point_id}: epochs/duration")
        if satellites is None:
            missing.append(f"{point_id}: satellite count")
        if not time_provided or parsed is None:
            missing.append(f"{point_id}: shot time")
        dop_status = {}
        for key, limit in dop_limits.items():
            value = row.get(key)
            passed = None
            if limit is not None:
                if value is None:
                    missing.append(f"{point_id}: {key.upper()}")
                else:
                    passed = float(value) <= float(limit)
                    if not passed:
                        failures.append(f"{key.upper()} {float(value):g} exceeds {float(limit):g}")
            dop_status[key] = {"value": value, "limit": limit, "pass": passed}
        if failures:
            explicit_failures.extend(f"{point_id}: {x}" for x in failures)
        per_shot.append(
            {
                "point_id": point_id,
                "observed_time": str(row.get("observed_utc") or "") if time_provided else "",
                "epoch_count": epochs,
                "duration_seconds": duration,
                "satellite_count": satellites,
                "pdop": row.get("pdop"),
                "hdop": row.get("hdop"),
                "vdop": row.get("vdop"),
                "fix_type": str(row.get("fix_type") or ""),
                "receiver_model": str(row.get("receiver_model") or ""),
                "receiver_serial": str(row.get("receiver_serial") or ""),
                "antenna_type": str(row.get("antenna_type") or ""),
                "antenna_height": row.get("antenna_height"),
                "length_pass": length_pass,
                "satellite_pass": satellite_pass,
                "dop": dop_status,
                "failures": failures,
            }
        )
    time_verified = all(parsed is not None for _, parsed in parsed_times) and len(parsed_times) >= 2
    time_pairs = []
    time_pass = None
    min_gap = None
    if time_verified:
        kinds = {parsed.get("kind") for _, parsed in parsed_times if parsed}
        if len(kinds) == 1:
            time_pass = True
            for i in range(len(parsed_times)):
                for j in range(i + 1, len(parsed_times)):
                    gap = _time_gap_minutes(parsed_times[i][1], parsed_times[j][1])
                    if gap is None:
                        time_verified = False
                        time_pass = None
                        break
                    time_pairs.append(
                        {"a": parsed_times[i][0], "b": parsed_times[j][0], "minutes": gap}
                    )
                    min_gap = gap if min_gap is None else min(min_gap, gap)
                    if gap + 1e-9 < float(min_time_separation_minutes):
                        time_pass = False
                if not time_verified:
                    break
        else:
            time_verified = False
    if time_verified and time_pass is False:
        explicit_failures.append(
            f"selected shots are less than {float(min_time_separation_minutes):g} minutes apart"
        )
    complete = (not missing) and time_verified
    pass_when_present = not explicit_failures
    return {
        "verified": complete,
        "pass_when_present": pass_when_present,
        "status": "PASS"
        if complete and pass_when_present
        else ("FAIL" if explicit_failures else "UNVERIFIED"),
        "requirements": {
            "min_time_separation_minutes": float(min_time_separation_minutes),
            "min_epochs": int(min_epochs),
            "min_duration_seconds": float(min_duration_seconds),
            "min_satellites": int(min_satellites),
            "max_pdop": max_pdop,
            "max_hdop": max_hdop,
            "max_vdop": max_vdop,
        },
        "per_shot": per_shot,
        "time_separation": {
            "verified": time_verified,
            "pass": time_pass,
            "minimum_gap_minutes": min_gap,
            "pairs": time_pairs,
        },
        "missing_metadata": sorted(set(missing)),
        "failures": explicit_failures,
    }


def _weighted_mean(values: list[float], sigmas: list[float | None]) -> float:
    weights = []
    for s in sigmas:
        if s is None or not math.isfinite(s) or s <= 0:
            weights.append(1.0)
        else:
            weights.append(1.0 / (s * s))
    total = sum(weights)
    return sum(v * w for v, w in zip(values, weights)) / total


def _shot_suffix(point_id: str, base_control_id: str = "") -> str:
    """Return an alphabetic observation suffix such as A/B/C from a shot label."""
    value = str(point_id or "").strip()
    base = str(base_control_id or "").strip()
    if base and value.lower().startswith(base.lower()):
        suffix = value[len(base) :]
        if suffix and suffix.isalpha():
            return suffix.upper()
    match = re.match(r"^(.*\d)([A-Za-z]+)$", value)
    return match.group(2).upper() if match else ""


def _default_spatial_group_tolerance(coordinate_context: dict | None = None) -> float:
    units = str((coordinate_context or {}).get("horizontal_units") or "").lower()
    # Same-control GNSS observations should be very close. Keep the automatic
    # grouping tolerance conservative so nearby but distinct monuments do not
    # get merged merely because their labels look similar.
    return 0.075 if "meter" in units else 0.25


def _three_point_candidate(
    rows: list[dict],
    horizontal_tolerance: float,
    vertical_tolerance: float,
    *,
    min_time_separation_minutes: float = 60.0,
    min_epochs: int = 300,
    min_duration_seconds: float = 300.0,
    min_satellites: int = 5,
    max_pdop: float | None = None,
    max_hdop: float | None = None,
    max_vdop: float | None = None,
    require_field_metadata: bool = False,
) -> dict:
    if len(rows) != 3:
        raise ValueError("Control candidate must contain exactly three observations.")
    ns = [float(r["northing"]) for r in rows]
    es = [float(r["easting"]) for r in rows]
    elevations = [r.get("elevation") for r in rows]
    codes = []
    for row in rows:
        code = _row_code(row)
        if code and code not in codes:
            codes.append(code)
    code = codes[0] if len(codes) == 1 else ";".join(codes)
    n = sum(ns) / 3.0
    e = sum(es) / 3.0
    complete_vertical = all(z is not None and math.isfinite(float(z)) for z in elevations)
    z = (sum(float(v) for v in elevations if v is not None) / 3.0) if complete_vertical else None
    residuals = []
    for row in rows:
        dn = float(row["northing"]) - n
        de = float(row["easting"]) - e
        h = math.hypot(dn, de)
        dz = (
            (float(row["elevation"]) - z)
            if (z is not None and row.get("elevation") is not None)
            else None
        )
        residuals.append(
            {
                "observation_id": row["observation_id"],
                "point_id": _row_point_id(row) or row["observation_id"],
                "analysis_point_id": str(
                    row.get("_effective_point_id") or _row_point_id(row) or row["observation_id"]
                ),
                "dn": dn,
                "de": de,
                "horizontal": h,
                "dz": dz,
                "pass": h <= horizontal_tolerance
                and dz is not None
                and abs(dz) <= vertical_tolerance,
            }
        )
    max_h = max(float(r["horizontal"]) for r in residuals)
    max_v = max(
        (abs(float(r["dz"])) for r in residuals if r["dz"] is not None), default=float("inf")
    )
    rms_h = math.sqrt(sum(float(r["horizontal"]) ** 2 for r in residuals) / 3.0)
    rms_v = (
        math.sqrt(sum(float(r["dz"]) ** 2 for r in residuals) / 3.0) if complete_vertical else None
    )
    coordinate_pass = (
        complete_vertical and max_h <= horizontal_tolerance and max_v <= vertical_tolerance
    )
    field_validation = _field_observation_checks(
        rows,
        min_time_separation_minutes=min_time_separation_minutes,
        min_epochs=min_epochs,
        min_duration_seconds=min_duration_seconds,
        min_satellites=min_satellites,
        max_pdop=max_pdop,
        max_hdop=max_hdop,
        max_vdop=max_vdop,
    )
    field_eligible = bool(field_validation.get("pass_when_present")) and (
        bool(field_validation.get("verified")) or not require_field_metadata
    )
    passed = coordinate_pass and field_eligible
    return {
        "point_ids": [r["point_id"] for r in residuals],
        "analysis_point_ids": [r["analysis_point_id"] for r in residuals],
        "observation_ids": [r["observation_id"] for r in residuals],
        "northing": n,
        "easting": e,
        "elevation": z,
        "code": code,
        "max_horizontal_residual": max_h,
        "max_vertical_residual": None if not complete_vertical else max_v,
        "rms_horizontal_residual": rms_h,
        "rms_vertical_residual": rms_v,
        "vertical_complete": complete_vertical,
        "coordinate_pass": coordinate_pass,
        "field_validation": field_validation,
        "field_metadata_required": bool(require_field_metadata),
        "pass": passed,
        "residuals": residuals,
    }


def _candidate_sort_key(
    candidate: dict, horizontal_tolerance: float, vertical_tolerance: float
) -> tuple:
    h = max(0.0, float(candidate.get("max_horizontal_residual") or 0.0))
    raw_v = candidate.get("max_vertical_residual")
    v = float(raw_v) if raw_v is not None and math.isfinite(float(raw_v)) else float("inf")
    h_ratio = h / max(float(horizontal_tolerance), 1e-12)
    v_ratio = v / max(float(vertical_tolerance), 1e-12)
    exceed = max(h_ratio, v_ratio)
    field = candidate.get("field_validation") or {}
    field_rank = (
        0 if field.get("status") == "PASS" else (1 if field.get("status") == "UNVERIFIED" else 2)
    )
    return (
        0 if candidate.get("pass") else 1,
        field_rank,
        exceed,
        h,
        v,
        float(candidate.get("rms_horizontal_residual") or 0.0),
        float(candidate.get("rms_vertical_residual") or float("inf")),
        tuple(candidate.get("point_ids") or []),
    )


def _letters_to_number(text: str) -> int:
    value = 0
    for char in str(text or "").upper():
        if not ("A" <= char <= "Z"):
            return 0
        value = value * 26 + (ord(char) - 64)
    return value


def _number_to_letters(value: int) -> str:
    out = ""
    n = max(1, int(value))
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def next_reshoot_point_ids(control_id: str, point_ids: list[str], count: int = 3) -> list[str]:
    base = str(control_id or "").strip()
    highest = 0
    for point in point_ids:
        value = str(point or "").strip()
        if value.lower().startswith(base.lower()):
            suffix = value[len(base) :]
            number = _letters_to_number(suffix)
            highest = max(highest, number)
    return [f"{base}{_number_to_letters(highest + i)}" for i in range(1, max(1, int(count)) + 1)]
