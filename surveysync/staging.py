from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4

from .audit import utc_now
from .coordinate_sanity import inspect_points
from .project import SurveyProject, sha256_file

ALIASES = {
    "point_id": ("point_id", "point", "pt", "ptno", "pnt", "pn", "pointnumber", "point_number", "name"),
    "northing": ("northing", "north", "n", "y", "y_coord", "ycoord"),
    "easting": ("easting", "east", "e", "x", "x_coord", "xcoord"),
    "elevation": ("elevation", "elev", "z", "height", "rl"),
    "description": ("description", "desc", "code", "feature", "feature_code", "d"),
}


def _norm(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip().lower().replace("-", "_").replace(" ", "_") if ch.isalnum() or ch == "_")


def _mapping_path(project: SurveyProject) -> Path:
    return project.paths.db.parent / "column_mappings.json"


def load_mapping_profiles(project: SurveyProject) -> dict:
    path = _mapping_path(project)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save_mapping_profiles(project: SurveyProject, data: dict) -> None:
    path = _mapping_path(project); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def header_signature(headers: list[str]) -> str:
    normalized = sorted(_norm(h) for h in headers if str(h or "").strip())
    return hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()[:20]


def detect_mapping(headers: list[str], learned: dict | None = None) -> dict:
    normalized = {_norm(h): h for h in headers}
    sig = header_signature(headers)
    if learned and sig in learned:
        stored = learned[sig].get("mapping") if isinstance(learned[sig], dict) else None
        if isinstance(stored, dict) and all(v in headers for v in stored.values() if v):
            return dict(stored)
    mapping: dict[str, str] = {}
    for target, aliases in ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[target] = normalized[alias]
                break
    return mapping


def learn_mapping(project: SurveyProject, headers: list[str], mapping: dict, label: str = "") -> dict:
    valid_targets = set(ALIASES)
    clean = {str(k): str(v) for k, v in (mapping or {}).items() if k in valid_targets and v in headers}
    sig = header_signature(headers)
    profiles = load_mapping_profiles(project)
    profiles[sig] = {"headers": headers, "mapping": clean, "label": str(label or ""), "updated_utc": utc_now()}
    _save_mapping_profiles(project, profiles)
    project.db.audit("Core", "COLUMN_MAPPING_LEARNED", object_type="mapping", object_id=sig, details={"label": label, "mapping": clean})
    return {"signature": sig, **profiles[sig]}


def _sniff(path: Path) -> tuple[list[str], list[dict], str]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except Exception:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [str(h or "").strip() for h in (reader.fieldnames or [])]
    if not headers:
        # Common survey PNEZD files are headerless. Detect five-column rows and
        # expose synthetic headers rather than modifying the source file.
        rows = []
        raw_reader = csv.reader(io.StringIO(text), dialect=dialect)
        for raw in raw_reader:
            if not raw or all(not str(v).strip() for v in raw):
                continue
            rows.append(raw)
            if len(rows) >= 5000:
                break
        if rows and min(len(r) for r in rows) >= 4:
            headers = ["Point", "Northing", "Easting", "Elevation", "Description"][:max(4, min(5, max(len(r) for r in rows)))]
            converted = []
            for r in rows:
                converted.append({headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers))})
            return headers, converted, getattr(dialect, "delimiter", ",")
        raise ValueError("The selected file does not contain a recognizable header or PNEZD-style rows.")
    rows = []
    for row in reader:
        rows.append({h: row.get(h, "") for h in headers})
        if len(rows) >= 50000:
            break
    return headers, rows, getattr(dialect, "delimiter", ",")


def _row_analysis(rows: list[dict], mapping: dict) -> dict:
    issues = []
    required = ["point_id", "northing", "easting"]
    missing = [k for k in required if not mapping.get(k)]
    if missing:
        issues.append({"severity": "BLOCKING", "code": "MISSING_REQUIRED_MAPPING", "message": "Missing mapping for: " + ", ".join(missing)})
        return {"valid_rows": 0, "invalid_rows": len(rows), "duplicate_ids": [], "missing_elevations": 0, "issues": issues}
    valid = invalid = missing_z = 0
    ids: list[str] = []
    for row in rows:
        pid = str(row.get(mapping["point_id"], "")).strip()
        if not pid:
            invalid += 1; continue
        try:
            float(row.get(mapping["northing"], "")); float(row.get(mapping["easting"], ""))
        except Exception:
            invalid += 1; continue
        valid += 1; ids.append(pid)
        zfield = mapping.get("elevation")
        if zfield and not str(row.get(zfield, "")).strip():
            missing_z += 1
    seen = set(); dup = set()
    for pid in ids:
        if pid in seen: dup.add(pid)
        seen.add(pid)
    if dup:
        issues.append({"severity": "REVIEW", "code": "DUPLICATE_POINT_IDS_IN_FILE", "message": f"{len(dup)} duplicate PointID(s) occur inside the staged file.", "point_ids": sorted(dup)[:50]})
    if invalid:
        issues.append({"severity": "REVIEW", "code": "INVALID_ROWS", "message": f"{invalid} row(s) do not contain usable PointID/Northing/Easting values."})
    return {"valid_rows": valid, "invalid_rows": invalid, "duplicate_ids": sorted(dup), "missing_elevations": missing_z, "issues": issues}


def stage_import(project: SurveyProject, path: Path, *, kind: str = "points", mapping: dict | None = None, preview_rows: int = 12) -> dict:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if kind != "points":
        raise ValueError("v9.2.1 staging currently supports canonical point imports.")
    headers, rows, delimiter = _sniff(path)
    learned = load_mapping_profiles(project)
    detected = detect_mapping(headers, learned)
    if mapping:
        detected.update({k: v for k, v in mapping.items() if k in ALIASES and v in headers})
    analysis = _row_analysis(rows, detected)
    stage_id = uuid4().hex
    preview = rows[:max(1, min(int(preview_rows), 50))]
    with project.db.connect() as conn:
        conn.execute(
            "INSERT INTO import_staging(stage_id,ts_utc,source_path,source_sha256,kind,headers_json,mapping_json,status,row_count,analysis_json,preview_json,committed_source_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (stage_id, utc_now(), str(path), sha256_file(path), kind, json.dumps(headers), json.dumps(detected), "READY" if not any(x.get("severity") == "BLOCKING" for x in analysis["issues"]) else "BLOCKED", len(rows), json.dumps(analysis), json.dumps(preview), ""),
        )
    project.db.audit("Core", "IMPORT_STAGED", object_type="import_stage", object_id=stage_id, details={"path": str(path), "kind": kind, "row_count": len(rows), "mapping": detected, "issues": analysis["issues"]})
    return {"stage_id": stage_id, "source_path": str(path), "source_sha256": sha256_file(path), "kind": kind, "headers": headers, "mapping": detected, "delimiter": delimiter, "status": "READY" if not any(x.get("severity") == "BLOCKING" for x in analysis["issues"]) else "BLOCKED", "row_count": len(rows), "analysis": analysis, "preview": preview, "mapping_signature": header_signature(headers), "learned_mapping_used": header_signature(headers) in learned}


def list_stages(project: SurveyProject, limit: int = 50) -> list[dict]:
    with project.db.connect() as conn:
        rows = conn.execute("SELECT * FROM import_staging ORDER BY ts_utc DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for src, dst, fallback in (("headers_json", "headers", "[]"), ("mapping_json", "mapping", "{}"), ("analysis_json", "analysis", "{}"), ("preview_json", "preview", "[]")):
            d[dst] = json.loads(d.pop(src) or fallback)
        out.append(d)
    return out


def _get_stage(project: SurveyProject, stage_id: str) -> dict:
    with project.db.connect() as conn:
        row = conn.execute("SELECT * FROM import_staging WHERE stage_id=?", (stage_id,)).fetchone()
    if not row:
        raise ValueError("Staged import was not found.")
    d = dict(row)
    d["headers"] = json.loads(d.pop("headers_json") or "[]")
    d["mapping"] = json.loads(d.pop("mapping_json") or "{}")
    d["analysis"] = json.loads(d.pop("analysis_json") or "{}")
    d["preview"] = json.loads(d.pop("preview_json") or "[]")
    return d


def commit_stage(project: SurveyProject, stage_id: str, *, learn: bool = True) -> dict:
    stage = _get_stage(project, stage_id)
    if stage["status"] == "BLOCKED":
        raise ValueError("This staged import has blocking mapping errors and cannot be committed.")
    path = Path(stage["source_path"])
    if not path.is_file() or sha256_file(path) != stage["source_sha256"]:
        raise ValueError("The staged source file has moved or changed. Stage it again before import.")
    headers, rows, _ = _sniff(path)
    mapping = stage["mapping"]
    source = project.import_source(path, "Core", "Committed from v9.2.1 import staging")
    now = utc_now(); inserted = 0; conflicts = []; skipped = 0
    with project.db.connect() as conn:
        existing = {str(r[0]) for r in conn.execute("SELECT point_id FROM canonical_points").fetchall()}
        for row in rows:
            pid = str(row.get(mapping.get("point_id", ""), "")).strip()
            if not pid:
                skipped += 1; continue
            try:
                n = float(row.get(mapping.get("northing", ""), "")); e = float(row.get(mapping.get("easting", ""), ""))
            except Exception:
                skipped += 1; continue
            if pid in existing:
                conflicts.append(pid); continue
            z = None
            zf = mapping.get("elevation")
            if zf and str(row.get(zf, "")).strip():
                try: z = float(row.get(zf))
                except Exception: z = None
            desc = str(row.get(mapping.get("description", ""), "") if mapping.get("description") else "")
            conn.execute(
                "INSERT INTO canonical_points(point_uuid,point_id,northing,easting,elevation,description,point_class,source_id,derived_from_json,crs,horizontal_units,vertical_units,review_state,revision,created_utc,modified_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uuid4().hex, pid, n, e, z, desc, "survey", source["source_id"], "[]", project.manifest.get("crs", ""), project.manifest.get("horizontal_units", ""), project.manifest.get("vertical_units", ""), "UNREVIEWED", 1, now, now),
            )
            existing.add(pid); inserted += 1
        status = "COMMITTED_WITH_REVIEW" if conflicts or skipped else "COMMITTED"
        conn.execute("UPDATE import_staging SET status=?, committed_source_id=? WHERE stage_id=?", (status, source["source_id"], stage_id))
    if learn:
        learn_mapping(project, headers, mapping, label=path.suffix.lower().lstrip(".") or "points")
    project.db.audit("Core", "STAGED_IMPORT_COMMITTED", object_type="import_stage", object_id=stage_id, details={"inserted": inserted, "conflicts": sorted(set(conflicts))[:100], "skipped": skipped, "source_id": source["source_id"]})
    return {"stage_id": stage_id, "status": status, "inserted": inserted, "conflicts": sorted(set(conflicts)), "skipped": skipped, "source_id": source["source_id"]}
