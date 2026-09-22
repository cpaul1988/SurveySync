from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

from .audit import utc_now

CONTROL_ALIASES: dict[str, tuple[str, ...]] = {
    "control_id": ("control_id","control","control_number","control_no","group_id","control_group","base_control_id","base_control"),
    "point_id": ("point_id","point","point_number","point_no","pt","ptno","pnt","pn","p","name","station","station_id","station_label","shot_name"),
    "northing": ("northing","north","n","y","y_coord","y_coordinate","y_value","grid_northing","north_coord"),
    "easting": ("easting","east","e","x","x_coord","x_coordinate","x_value","grid_easting","east_coord"),
    "elevation": ("elevation","elev","elev_ft","height","z","z_value","rl","orthometric_height","grid_elevation"),
    "description": ("description","desc","code","feature","feature_code","point_code","d"),
    "h_sigma": ("h_sigma","hsigma","horizontal_sigma","horizontal_accuracy","h_accuracy","hacc","hrms"),
    "v_sigma": ("v_sigma","vsigma","vertical_sigma","vertical_accuracy","v_accuracy","vacc","vrms"),
    "method": ("method","survey_method","solution","type","observation_type"),
    "observed_utc": ("observed_utc","observed","timestamp","time","shot_time","observation_time","occupation_time","date_time","datetime","start_time","observation_start","occupation_start","start_datetime"),
    "observed_date": ("observed_date","observation_date","occupation_date","shot_date","date"),
    "epoch_count": ("epoch_count","epochs","epoch","num_epochs","number_of_epochs","observation_epochs","epochs_used"),
    "duration_seconds": ("duration_seconds","duration_sec","duration_secs","seconds","observation_seconds","occupation_seconds","obs_seconds"),
    "duration_minutes": ("duration_minutes","duration_min","minutes","observation_minutes","occupation_minutes","obs_minutes"),
    "duration": ("duration","observation_duration","occupation_duration","obs_duration","occupation_length"),
    "satellite_count": ("satellite_count","satellites","satellite_number","satellites_used","sats","sats_used","number_sats","sat_count","num_satellites","number_of_satellites","sv","svs","sv_used"),
    "pdop": ("pdop","position_dop","position_dilution_of_precision"),
    "hdop": ("hdop","horizontal_dop","horizontal_dilution_of_precision"),
    "vdop": ("vdop","vertical_dop","vertical_dilution_of_precision"),
    "fix_type": ("fix_type","solution_type","position_type","gnss_quality","rtk_status","fix_status"),
    "receiver_model": ("receiver_model","receiver_type","rover_model","gnss_receiver","receiver"),
    "receiver_serial": ("receiver_serial","receiver_serial_number","serial_number","receiver_sn","receiver_serial_no"),
    "antenna_type": ("antenna_type","antenna_model","antenna_name"),
    "antenna_height": ("antenna_height","height_of_antenna","instrument_height","measured_height","ant_height"),
    "shot_id": ("shot_id","shot","observation_id","obs_id","occupation","occupation_id"),
    "session_id": ("session_id","session","survey_session","job","job_id"),
}

CONTROL_FIELD_LABELS: dict[str, str] = {
    "point_id": "Point / Shot ID",
    "control_id": "Control Group ID",
    "northing": "Northing",
    "easting": "Easting",
    "elevation": "Elevation",
    "description": "Code / Description",
    "observed_date": "Shot Date",
    "observed_utc": "Shot Time / Timestamp",
    "epoch_count": "Epoch Count",
    "duration": "Observation Duration",
    "duration_seconds": "Duration (seconds)",
    "duration_minutes": "Duration (minutes)",
    "satellite_count": "Satellite Count",
    "pdop": "PDOP",
    "hdop": "HDOP",
    "vdop": "VDOP",
    "fix_type": "Fix / Solution Type",
    "receiver_model": "Receiver Model",
    "receiver_serial": "Receiver Serial",
    "antenna_type": "Antenna Type",
    "antenna_height": "Antenna Height",
    "h_sigma": "Horizontal Sigma / Accuracy",
    "v_sigma": "Vertical Sigma / Accuracy",
    "method": "Survey Method",
    "shot_id": "Shot Suffix / ID",
    "session_id": "Session ID",
}

_REQUIRED_ANY_ID = ("point_id", "control_id")
_REQUIRED_COORDS = ("northing", "easting")
_UNIT_TOKENS = {"ft","feet","foot","us","survey","international","intl","usft","us_survey_ft","ussurveyft","us_survey_feet","survey_feet","survey_ft","m","meter","meters","metre","metres"}


def normalize_control_header(value: str) -> str:
    value = str(value or "").strip().lower()
    value = value.replace("#", " number ").replace("&", " and ")
    value = re.sub(r"[\[\](){}]", " ", value)
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_")


def _header_candidates(value: str) -> list[str]:
    base = normalize_control_header(value)
    candidates = [base]
    parts = [p for p in base.split("_") if p]
    trimmed = [p for p in parts if p not in _UNIT_TOKENS]
    if trimmed and trimmed != parts:
        candidates.append("_".join(trimmed))
    # Common labels include an appended unit such as Northing_US_Ft or Elev_m.
    if len(parts) > 1 and parts[-1] in _UNIT_TOKENS:
        candidates.append("_".join(parts[:-1]))
    return list(dict.fromkeys(candidates))


def control_header_signature(headers: list[str]) -> str:
    normalized = sorted(normalize_control_header(h) for h in headers if str(h or "").strip())
    return hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()[:20]


def _alias_target_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for target, aliases in CONTROL_ALIASES.items():
        for alias in aliases:
            out[normalize_control_header(alias)] = target
    return out


_ALIAS_TO_TARGET = _alias_target_map()


def _numeric(value: Any) -> bool:
    try:
        float(str(value).strip())
        return True
    except (TypeError, ValueError):
        return False


def _looks_like_header(first: list[str], second: list[str] | None) -> bool:
    alias_hits = 0
    for value in first:
        if any(candidate in _ALIAS_TO_TARGET for candidate in _header_candidates(value)):
            alias_hits += 1
    if alias_hits >= 2:
        return True
    if second:
        # Unknown company-specific headings still look like text while their data row
        # contains multiple numeric coordinate values.
        first_numeric = sum(_numeric(v) for v in first)
        second_numeric = sum(_numeric(v) for v in second)
        if first_numeric <= 1 and second_numeric >= 2:
            return True
    return False


def read_control_delimited(path: Path, max_rows: int = 50000) -> dict:
    path = Path(path).expanduser().resolve()
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    raw_reader = csv.reader(io.StringIO(text), dialect=dialect)
    raw_rows: list[list[str]] = []
    for raw in raw_reader:
        cleaned = [str(v or "").strip() for v in raw]
        if not cleaned or all(not v for v in cleaned):
            continue
        raw_rows.append(cleaned)
        if len(raw_rows) >= max_rows + 1:
            break
    if not raw_rows:
        raise ValueError("The control file is empty.")
    width = max(len(r) for r in raw_rows)
    first = raw_rows[0]
    second = raw_rows[1] if len(raw_rows) > 1 else None
    has_header = _looks_like_header(first, second)
    if has_header:
        headers = [(v or f"Column {i+1}").strip() for i, v in enumerate(first)]
        source_rows = raw_rows[1:]
    else:
        headers = [f"Column {i+1}" for i in range(width)]
        source_rows = raw_rows
    rows = [
        {headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers))}
        for r in source_rows[:max_rows]
    ]
    return {
        "headers": headers,
        "rows": rows,
        "delimiter": getattr(dialect, "delimiter", ","),
        "has_header": has_header,
    }


def _learned_mapping_path(project) -> Path:
    return project.paths.db.parent / "control_column_mappings.json"


def load_control_mapping_profiles(project) -> dict:
    path = _learned_mapping_path(project)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def learn_control_mapping(project, headers: list[str], mapping: dict[str, str], label: str = "") -> dict:
    clean = {str(k): str(v) for k, v in (mapping or {}).items() if k in CONTROL_ALIASES and v in headers}
    sig = control_header_signature(headers)
    profiles = load_control_mapping_profiles(project)
    profiles[sig] = {"headers": headers, "mapping": clean, "label": str(label or ""), "updated_utc": utc_now()}
    path = _learned_mapping_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(profiles, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    project.db.audit("ControlSync", "CONTROL_COLUMN_MAPPING_LEARNED", object_type="mapping", object_id=sig, details={"label": label, "mapping": clean})
    return {"signature": sig, **profiles[sig]}


def detect_control_mapping(headers: list[str], rows: list[dict] | None = None, learned: dict | None = None) -> dict:
    sig = control_header_signature(headers)
    if learned and sig in learned:
        stored = learned[sig].get("mapping") if isinstance(learned[sig], dict) else None
        if isinstance(stored, dict) and all(v in headers for v in stored.values() if v):
            return {"mapping": dict(stored), "confidence": {k: 1.0 for k in stored}, "learned": True}

    mapping: dict[str, str] = {}
    confidence: dict[str, float] = {}
    for header in headers:
        for candidate in _header_candidates(header):
            target = _ALIAS_TO_TARGET.get(candidate)
            if target and target not in mapping:
                mapping[target] = header
                confidence[target] = 0.98
                break

    # Headerless common survey files: P,N,E,Z,D or P,N,E,Z.
    if headers and all(re.fullmatch(r"Column \d+", h) for h in headers):
        if len(headers) >= 3:
            mapping.setdefault("point_id", headers[0]); confidence.setdefault("point_id", 0.75)
            mapping.setdefault("northing", headers[1]); confidence.setdefault("northing", 0.72)
            mapping.setdefault("easting", headers[2]); confidence.setdefault("easting", 0.72)
        if len(headers) >= 4:
            mapping.setdefault("elevation", headers[3]); confidence.setdefault("elevation", 0.68)
        if len(headers) >= 5:
            mapping.setdefault("description", headers[4]); confidence.setdefault("description", 0.65)

    # Conservative data-assisted inference for custom headings. Never guess N/E if
    # there are not at least two strongly numeric columns; the UI will ask instead.
    rows = list(rows or [])[:50]
    if rows:
        stats = {}
        for header in headers:
            values = [str(r.get(header, "")).strip() for r in rows if str(r.get(header, "")).strip()]
            numeric_ratio = (sum(_numeric(v) for v in values) / len(values)) if values else 0.0
            stats[header] = {"numeric_ratio": numeric_ratio, "values": values}
        unmapped_numeric = [h for h in headers if h not in mapping.values() and stats[h]["numeric_ratio"] >= 0.9]
        unmapped_text = [h for h in headers if h not in mapping.values() and stats[h]["numeric_ratio"] <= 0.2 and stats[h]["values"]]
        if "point_id" not in mapping and "control_id" not in mapping and unmapped_text:
            # Prefer an ID-like column whose values are mostly unique and compact.
            ranked = sorted(unmapped_text, key=lambda h: (-(len(set(stats[h]["values"])) / max(1, len(stats[h]["values"]))), sum(len(v) for v in stats[h]["values"]) / max(1, len(stats[h]["values"]))))
            mapping["point_id"] = ranked[0]; confidence["point_id"] = 0.55
        # If coordinate names were not recognized, leave them unmapped unless the
        # conventional first numeric columns are unmistakable. This prevents N/E swaps.
        if "northing" not in mapping and "easting" not in mapping and len(unmapped_numeric) >= 2:
            # Only infer conventional P,N,E order when the ID column precedes them.
            id_header = mapping.get("point_id") or mapping.get("control_id")
            if id_header in headers:
                idx = headers.index(id_header)
                after = [h for h in headers[idx+1:] if h in unmapped_numeric]
                if len(after) >= 2:
                    mapping["northing"] = after[0]; confidence["northing"] = 0.50
                    mapping["easting"] = after[1]; confidence["easting"] = 0.50
                    if "elevation" not in mapping and len(after) >= 3:
                        mapping["elevation"] = after[2]; confidence["elevation"] = 0.45

    return {"mapping": mapping, "confidence": confidence, "learned": False}


def validate_control_mapping(mapping: dict[str, str], headers: list[str]) -> list[str]:
    clean = {k: v for k, v in (mapping or {}).items() if k in CONTROL_ALIASES and v in headers}
    missing: list[str] = []
    if not any(clean.get(k) for k in _REQUIRED_ANY_ID):
        missing.append("Point / Shot ID or Control Group ID")
    for key in _REQUIRED_COORDS:
        if not clean.get(key):
            missing.append(CONTROL_FIELD_LABELS[key])
    return missing


def preview_control_delimited(project, path: Path, mapping: dict | None = None, preview_rows: int = 12) -> dict:
    scan = read_control_delimited(path)
    # Headerless files use synthetic Column N names. Reusing a learned mapping
    # solely from those generic names could silently mis-map a different layout
    # with the same number of columns, so require review each time.
    learned = load_control_mapping_profiles(project) if scan["has_header"] else {}
    detected = detect_control_mapping(scan["headers"], scan["rows"], learned)
    effective = dict(detected["mapping"])
    for k, v in (mapping or {}).items():
        if k in CONTROL_ALIASES:
            if v in scan["headers"]:
                effective[k] = v
            elif not v:
                effective.pop(k, None)
    missing = validate_control_mapping(effective, scan["headers"])
    confidence = dict(detected.get("confidence") or {})
    for k, v in (mapping or {}).items():
        if k in CONTROL_ALIASES and v in scan["headers"]:
            confidence[k] = 1.0
    low_confidence = sorted(k for k, score in confidence.items() if score < 0.70 and effective.get(k))
    return {
        "format": "delimited",
        "source_path": str(Path(path).expanduser().resolve()),
        "delimiter": scan["delimiter"],
        "has_header": scan["has_header"],
        "headers": scan["headers"],
        "mapping": effective,
        "confidence": confidence,
        "mapping_signature": control_header_signature(scan["headers"]),
        "learned_mapping_used": bool(detected.get("learned")),
        "required_missing": missing,
        "low_confidence_fields": low_confidence,
        "ready": not missing,
        "row_count": len(scan["rows"]),
        "preview": scan["rows"][:max(1, min(int(preview_rows), 30))],
        "fields": [{"key": k, "label": CONTROL_FIELD_LABELS.get(k, k), "required": k in {"northing", "easting"}} for k in CONTROL_FIELD_LABELS],
    }
