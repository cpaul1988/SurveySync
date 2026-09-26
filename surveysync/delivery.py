from __future__ import annotations

import csv
import hashlib
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .audit import utc_now
from .project import SurveyProject, safe_name, sha256_file
from .reporting import register_deliverable

logger = logging.getLogger(__name__)

DEFAULT_EXPORT_PROFILES = {
    "survey_points": {
        "id": "survey_points", "name": "Survey Points", "formats": ["csv", "pnezd", "geojson"],
        "precision": 4, "include_reports": False, "include_existing_exports": False,
    },
    "field_crew": {
        "id": "field_crew", "name": "Field Crew", "formats": ["pnezd", "csv"],
        "precision": 4, "include_reports": False, "include_existing_exports": False,
    },
    "client_deliverable": {
        "id": "client_deliverable", "name": "Client Deliverable Package", "formats": ["csv", "geojson"],
        "precision": 4, "include_reports": True, "include_existing_exports": True,
    },
}


def _profile_path(project: SurveyProject) -> Path:
    return project.paths.db.parent / "export_profiles.json"


def load_profiles(project: SurveyProject) -> list[dict]:
    profiles = {k: dict(v) for k, v in DEFAULT_EXPORT_PROFILES.items()}
    path = _profile_path(project)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if isinstance(value, dict): profiles[key] = value
        except Exception:
            logger.warning("Could not load export profile overrides from %s; defaults will be used.", path, exc_info=True)
    return [profiles[k] for k in sorted(profiles)]


def save_profile(project: SurveyProject, profile: dict) -> dict:
    pid = safe_name(str(profile.get("id") or profile.get("name") or "profile")).lower().replace(" ", "_")
    if not pid: raise ValueError("Export profile requires an id or name.")
    formats = [str(x).lower() for x in profile.get("formats", []) if str(x).lower() in {"csv", "pnezd", "geojson"}]
    if not formats: raise ValueError("Choose at least one export format: CSV, PNEZD, or GeoJSON.")
    item = {
        "id": pid,
        "name": str(profile.get("name") or pid),
        "formats": formats,
        "precision": max(0, min(10, int(profile.get("precision", 4)))),
        "include_reports": bool(profile.get("include_reports", False)),
        "include_existing_exports": bool(profile.get("include_existing_exports", False)),
    }
    path = _profile_path(project)
    raw = {}
    if path.exists():
        try: raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception: raw = {}
    raw[pid] = item
    tmp = path.with_suffix(".tmp"); tmp.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8"); tmp.replace(path)
    project.db.audit("ReportSync", "EXPORT_PROFILE_SAVED", object_type="export_profile", object_id=pid, details=item)
    return item


def _points(project: SurveyProject) -> list[dict]:
    with project.db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT point_id,northing,easting,elevation,description,review_state FROM canonical_points ORDER BY point_id").fetchall()]


def export_points(project: SurveyProject, profile_id: str) -> dict:
    profiles = {x["id"]: x for x in load_profiles(project)}
    if profile_id not in profiles: raise ValueError("Export profile was not found.")
    profile = profiles[profile_id]; points = _points(project)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    folder = project.paths.exports / "Profiles" / f"{safe_name(profile['name'])}_{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    precision = int(profile.get("precision", 4)); files = []
    if "csv" in profile["formats"]:
        path = folder / "points.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh); w.writerow(["PointID", "Northing", "Easting", "Elevation", "Description", "ReviewState"])
            for p in points: w.writerow([p["point_id"], f"{p['northing']:.{precision}f}" if p["northing"] is not None else "", f"{p['easting']:.{precision}f}" if p["easting"] is not None else "", f"{p['elevation']:.{precision}f}" if p["elevation"] is not None else "", p.get("description", ""), p.get("review_state", "")])
        files.append(path)
    if "pnezd" in profile["formats"]:
        path = folder / "points.pnezd"
        with path.open("w", encoding="utf-8") as fh:
            for p in points:
                n = "" if p["northing"] is None else f"{p['northing']:.{precision}f}"; e = "" if p["easting"] is None else f"{p['easting']:.{precision}f}"; z = "" if p["elevation"] is None else f"{p['elevation']:.{precision}f}"
                fh.write(f"{p['point_id']},{n},{e},{z},{p.get('description','')}\n")
        files.append(path)
    if "geojson" in profile["formats"]:
        path = folder / "points.geojson"
        fc = {"type": "FeatureCollection", "name": project.manifest.get("name", "SurveySync Points"), "crs": {"type": "name", "properties": {"name": project.manifest.get("crs", "")}}, "features": []}
        for p in points:
            if p["northing"] is None or p["easting"] is None: continue
            fc["features"].append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["easting"], p["northing"]]}, "properties": {"PointID": p["point_id"], "Elevation": p["elevation"], "Description": p.get("description", ""), "ReviewState": p.get("review_state", "")}})
        path.write_text(json.dumps(fc, indent=2), encoding="utf-8"); files.append(path)
    project.db.audit("ReportSync", "EXPORT_PROFILE_RUN", object_type="export_profile", object_id=profile_id, details={"files": [str(x) for x in files], "point_count": len(points)})
    return {"profile": profile, "folder": str(folder), "files": [str(x) for x in files], "point_count": len(points)}


def build_deliverable_package(project: SurveyProject, *, profile_id: str = "client_deliverable", label: str = "") -> dict:
    run = export_points(project, profile_id)
    profile = run["profile"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    package_name = f"{safe_name(project.manifest.get('name','Project'))}_{stamp}_Deliverables.zip"
    package_path = project.paths.exports / package_name
    candidates = [Path(x) for x in run["files"]]
    if profile.get("include_reports") and project.paths.reports.exists():
        candidates.extend(p for p in project.paths.reports.iterdir() if p.is_file())
    if profile.get("include_existing_exports") and project.paths.exports.exists():
        candidates.extend(p for p in project.paths.exports.iterdir() if p.is_file() and p != package_path and p.suffix.lower() != ".zip")
    unique = []
    seen = set()
    for p in candidates:
        try: key = str(p.resolve())
        except Exception: continue
        if p.is_file() and key not in seen:
            seen.add(key); unique.append(p)
    audit_integrity = project.db.verify_audit_chain()
    manifest = {
        "product": "SurveySync", "project_id": project.manifest.get("project_id", ""), "project_name": project.manifest.get("name", ""),
        "created_utc": utc_now(), "profile": profile, "label": label, "crs": project.manifest.get("crs", ""),
        "horizontal_units": project.manifest.get("horizontal_units", ""), "vertical_units": project.manifest.get("vertical_units", ""), "files": [],
        "audit_chain": {
            "verified": bool(audit_integrity.get("ok")),
            "hash_version": audit_integrity.get("hash_version"),
            "chain_id": audit_integrity.get("chain_id", ""),
            "event_count": audit_integrity.get("event_count", 0),
            "head_hash": audit_integrity.get("head_hash", ""),
            "scope": "Project audit state immediately before deliverable package creation",
        },
    }
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in unique:
            digest = sha256_file(p)
            arc = f"Files/{p.name}"
            zf.write(p, arc)
            manifest["files"].append({"name": p.name, "archive_path": arc, "sha256": digest, "size_bytes": p.stat().st_size})
        zf.writestr("SurveySync_Manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    result = register_deliverable(project, package_path, module="ReportSync", kind="deliverable_package_zip", metadata={"profile_id": profile_id, "file_count": len(unique), "label": label})
    return {**result, "manifest": manifest}
