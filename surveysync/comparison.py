from __future__ import annotations

from pathlib import Path
import logging
import sqlite3

from .project import SurveyProject
from .staging import _sniff, detect_mapping, load_mapping_profiles

logger = logging.getLogger(__name__)


def _external_points(project: SurveyProject, path: Path) -> dict[str, dict]:
    headers, rows, _ = _sniff(path)
    mapping = detect_mapping(headers, load_mapping_profiles(project))
    missing = [k for k in ("point_id", "northing", "easting") if not mapping.get(k)]
    if missing:
        raise ValueError("Could not compare file; missing mapped field(s): " + ", ".join(missing))
    out = {}
    for row in rows:
        pid = str(row.get(mapping["point_id"], "")).strip()
        if not pid:
            continue
        try:
            n = float(row.get(mapping["northing"], "")); e = float(row.get(mapping["easting"], ""))
        except Exception:
            continue
        z = None
        if mapping.get("elevation") and str(row.get(mapping["elevation"], "")).strip():
            try: z = float(row.get(mapping["elevation"]))
            except Exception:
                logger.warning("Point %s has an invalid elevation in comparison source %s; elevation comparison will be skipped for that point.", pid, path, exc_info=True)
        desc = str(row.get(mapping.get("description", ""), "") if mapping.get("description") else "")
        out[pid] = {"point_id": pid, "northing": n, "easting": e, "elevation": z, "description": desc}
    return out


def compare_point_file(project: SurveyProject, path: Path, *, horizontal_tolerance: float = 0.001, vertical_tolerance: float = 0.001) -> dict:
    external = _external_points(project, Path(path).expanduser().resolve())
    with project.db.connect() as conn:
        current_rows = [dict(r) for r in conn.execute("SELECT point_id,northing,easting,elevation,description FROM canonical_points ORDER BY point_id").fetchall()]
    current = {str(r["point_id"]): r for r in current_rows}
    added = sorted(set(external) - set(current))
    removed = sorted(set(current) - set(external))
    changed = []
    unchanged = 0
    for pid in sorted(set(current) & set(external)):
        a, b = current[pid], external[pid]
        dn = float(b["northing"]) - float(a["northing"]); de = float(b["easting"]) - float(a["easting"])
        dz = None if a.get("elevation") is None or b.get("elevation") is None else float(b["elevation"]) - float(a["elevation"])
        desc_changed = str(a.get("description") or "") != str(b.get("description") or "")
        if abs(dn) > horizontal_tolerance or abs(de) > horizontal_tolerance or (dz is not None and abs(dz) > vertical_tolerance) or desc_changed:
            changed.append({"point_id": pid, "delta_n": dn, "delta_e": de, "delta_z": dz, "description_changed": desc_changed, "before": a, "after": b})
        else:
            unchanged += 1
    result = {"file_path": str(Path(path).resolve()), "added": added, "removed": removed, "changed": changed, "unchanged_count": unchanged, "summary": {"added": len(added), "removed": len(removed), "changed": len(changed), "unchanged": unchanged}, "tolerances": {"horizontal": horizontal_tolerance, "vertical": vertical_tolerance}}
    project.db.audit("QASync", "POINT_FILE_COMPARED", object_type="comparison", object_id=Path(path).name, details=result["summary"])
    return result


def _project_points_from_folder(path: Path) -> dict[str, dict]:
    root=Path(path).expanduser().resolve()
    manifest=root/"survey_sync_project.json"; db=root/".surveysync"/"survey_sync.db"
    if not manifest.is_file() or not db.is_file():
        raise ValueError("Selected folder is not a SurveySync project.")
    con=sqlite3.connect(str(db)); con.row_factory=sqlite3.Row
    try:
        rows=con.execute("SELECT point_id,northing,easting,elevation,description FROM canonical_points ORDER BY point_id").fetchall()
        return {str(r["point_id"]):dict(r) for r in rows}
    finally:
        con.close()

def _compare_sets(project: SurveyProject, other: dict[str,dict], source_label: str, horizontal_tolerance: float, vertical_tolerance: float) -> dict:
    with project.db.connect() as conn:
        current_rows=[dict(r) for r in conn.execute("SELECT point_id,northing,easting,elevation,description FROM canonical_points ORDER BY point_id").fetchall()]
    current={str(r["point_id"]):r for r in current_rows}
    added=sorted(set(other)-set(current)); removed=sorted(set(current)-set(other)); changed=[]; unchanged=0
    for pid in sorted(set(current)&set(other)):
        a,b=current[pid],other[pid]
        if a.get("northing") is None or a.get("easting") is None or b.get("northing") is None or b.get("easting") is None:
            changed.append({"point_id":pid,"reason":"missing coordinate in one source","before":a,"after":b});continue
        dn=float(b["northing"])-float(a["northing"]);de=float(b["easting"])-float(a["easting"]);dz=None if a.get("elevation") is None or b.get("elevation") is None else float(b["elevation"])-float(a["elevation"]);desc_changed=str(a.get("description") or "")!=str(b.get("description") or "")
        if abs(dn)>horizontal_tolerance or abs(de)>horizontal_tolerance or (dz is not None and abs(dz)>vertical_tolerance) or desc_changed:
            changed.append({"point_id":pid,"delta_n":dn,"delta_e":de,"delta_z":dz,"description_changed":desc_changed,"before":a,"after":b})
        else:unchanged+=1
    result={"source":source_label,"added":added,"removed":removed,"changed":changed,"unchanged_count":unchanged,"summary":{"added":len(added),"removed":len(removed),"changed":len(changed),"unchanged":unchanged},"tolerances":{"horizontal":horizontal_tolerance,"vertical":vertical_tolerance}}
    project.db.audit("QASync","POINT_SOURCE_COMPARED",object_type="comparison",object_id=source_label,details=result["summary"]);return result

def compare_point_source(project: SurveyProject, path: Path, *, horizontal_tolerance: float=0.001, vertical_tolerance: float=0.001) -> dict:
    path=Path(path).expanduser().resolve()
    if path.is_dir():
        return _compare_sets(project,_project_points_from_folder(path),str(path),horizontal_tolerance,vertical_tolerance)
    return compare_point_file(project,path,horizontal_tolerance=horizontal_tolerance,vertical_tolerance=vertical_tolerance)
