"""Linked, local survey QA with immutable evidence and explicit copy-only corrections."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import defaultdict
from zipfile import ZipFile, ZIP_DEFLATED

from .topo.storage import list_records

MAX_POINTS = 20000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def snapshot(project, jump=2.0, distance=50.0):
    """Bounded full-project view. Never silently sample, transform or fix coordinates."""
    with project.db.connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM canonical_points ORDER BY rowid LIMIT ?", (MAX_POINTS + 1,)
            )
        ]
        sources = {r["source_id"]: dict(r) for r in conn.execute("SELECT * FROM source_registry")}
    if len(rows) > MAX_POINTS:
        raise ValueError(
            "Visual QA supports up to 20,000 canonical points per project. No partial review was produced."
        )
    for p in rows:
        for key in ("northing", "easting", "elevation"):
            if not finite(p[key]):
                p[key] = None
    m = project.manifest
    metadata = {
        key: m.get(key, "")
        for key in ("project_id", "name", "crs", "horizontal_units", "vertical_units")
    }
    root = project.paths.module_root / "TopoSync" / "RodHeightQC"
    runs = list_records(root, "analysis", limit=50)
    token = digest(
        {
            "points": rows,
            "sources": sources,
            "project": metadata,
            "runs": runs,
            "jump": jump,
            "distance": distance,
        }
    )
    issues = []

    def add(kind, severity, points, explanation, evidence=None):
        uuids = [p["point_uuid"] for p in points]
        item = dict(
            kind=kind,
            severity=severity,
            point_uuids=uuids,
            explanation=explanation,
            evidence=evidence or {},
        )
        item["issue_id"] = digest(item)
        issues.append(item)

    ids = defaultdict(list)
    previous = {}
    known_units = {"us_survey_feet", "international_feet", "meters"}
    for p in rows:
        ids[p["point_id"]].append(p)
        compatible = all(p[k] == metadata[k] for k in ("crs", "horizontal_units", "vertical_units"))
        p["mappable"] = (
            p["northing"] is not None
            and p["easting"] is not None
            and p["crs"] == metadata["crs"]
            and p["horizontal_units"] == metadata["horizontal_units"]
        )
        if p["northing"] is None or p["easting"] is None:
            add(
                "missing_xy",
                "ERROR",
                [p],
                "Northing or easting is missing or nonfinite; this record cannot be plotted.",
            )
        if p["elevation"] is None:
            add(
                "missing_z",
                "WARN",
                [p],
                "Elevation is missing or nonfinite. No elevation is inferred.",
            )
        if not compatible:
            add(
                "coordinate_context",
                "ERROR",
                [p],
                "Point CRS or units differ from the project. No automatic transformation is applied.",
                {k: p[k] for k in ("crs", "horizontal_units", "vertical_units")},
            )
        key = (p["source_id"], p["description"])
        before = previous.get(key)
        previous[key] = p if compatible and p["mappable"] and p["elevation"] is not None else None
        if (
            before
            and previous[key]
            and p["source_id"]
            and p["description"]
            and metadata["horizontal_units"] in known_units
            and metadata["vertical_units"] in known_units
        ):
            gap = math.hypot(p["easting"] - before["easting"], p["northing"] - before["northing"])
            dz = p["elevation"] - before["elevation"]
            if gap <= distance and abs(dz) >= jump:
                add(
                    "elevation_jump",
                    "WARN",
                    [before, p],
                    "Elevation difference between consecutive retained records with the same source and exact description. This is a screening flag, not proof of a bust or acquisition order.",
                    {
                        "horizontal_distance": gap,
                        "elevation_change": dz,
                        "vertical_threshold": jump,
                        "horizontal_limit": distance,
                    },
                )
    for point_id, group in ids.items():
        if len(group) > 1:
            add(
                "duplicate_id",
                "ERROR",
                group,
                f"{len(group)} separate records share PointID {point_id}. Select by record UUID; none are overwritten.",
            )

    # Match saved rod evidence by exact source bytes AND coordinates, never IDs alone.
    for run in runs:
        settings = run.get("result", {}).get("settings", {})
        if any(settings.get(k) != metadata[k] for k in ("horizontal_units", "vertical_units")):
            continue
        originals = defaultdict(list)
        for p in run.get("points", []):
            originals[p.get("point_id")].append(p)
        matched = defaultdict(list)
        for p in rows:
            src = sources.get(p["source_id"], {})
            if src.get("sha256") != run.get("source_sha256") or not p["mappable"]:
                continue
            if any(
                all(p[k] == o.get(k) for k in ("northing", "easting", "elevation"))
                for o in originals[p["point_id"]]
            ):
                matched[p["point_id"]].append(p)
        for c in run.get("result", {}).get("candidates", []):
            if c.get("status") != "PROBABLE":
                continue
            affected = [p for pid in c.get("affected_point_ids", []) for p in matched[pid]]
            if affected:
                add(
                    "rod_candidate",
                    "WARN",
                    affected,
                    "Saved TopoSync probable rod-height range. Evidence score is heuristic, not a probability. Only unchanged records from the same source are linked.",
                    {"run_id": run["record_id"], "candidate": c, "linked_records": len(affected)},
                )
    reviews = {}
    with project.db.connect() as conn:
        for r in conn.execute(
            "SELECT details_json,ts_utc FROM audit_events WHERE action='VISUAL_QA_REVIEW' ORDER BY rowid"
        ):
            value = json.loads(r["details_json"])
            if value.get("snapshot") == token:
                reviews[value["issue_id"]] = {**value, "ts_utc": r["ts_utc"]}
    for item in issues:
        item["review"] = reviews.get(item["issue_id"])
    return {
        "snapshot": token,
        "project": metadata,
        "points": rows,
        "sources": sources,
        "issues": issues,
        "settings": {"jump": jump, "distance": distance},
        "rod_runs_checked": len(runs),
        "notice": "Local project-coordinate plan view; no basemap or coordinate conversion. Jump screening uses consecutive same-description records within each source, not spatial nearest neighbors. Up to 50 recent saved TopoSync runs are checked.",
    }


def verify_correction_sources(project, data, changes):
    from .project import sha256_file

    ids = {c.point_uuid for c in changes}
    sources = {p["source_id"] for p in data["points"] if p["point_uuid"] in ids and p["source_id"]}
    for source_id in sources:
        source = data["sources"].get(source_id)
        if source is None:
            raise ValueError("Correction source is no longer registered.")
        path = (project.paths.root / source["stored_path"]).resolve()
        if (
            not path.is_relative_to(project.paths.root.resolve())
            or not path.is_file()
            or sha256_file(path) != source["sha256"]
        ):
            raise ValueError(
                "Correction source is missing or its hash changed. Restore verified evidence first."
            )


def corrected_archive(data, changes, reason):
    """Return a separate reviewed copy and exact JSON evidence, never mutate points."""
    lookup = {p["point_uuid"]: p for p in data["points"]}
    if len({c.point_uuid for c in changes}) != len(changes):
        raise ValueError("Each record can be corrected only once per export.")
    altered = {}
    evidence = []
    for c in changes:
        p = lookup.get(c.point_uuid)
        if p is None or p["elevation"] is None:
            raise ValueError("Correction needs an existing record with a finite elevation.")
        if p["vertical_units"] not in {"us_survey_feet", "international_feet", "meters"}:
            raise ValueError("Confirm recognized elevation units before correcting a record.")
        value = p["elevation"] + c.offset
        if not math.isfinite(value):
            raise ValueError("Corrected elevation must be finite.")
        altered[c.point_uuid] = value
        evidence.append({"original": p, "offset": c.offset, "corrected_elevation": value})
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    keys = [
        "point_uuid",
        "point_id",
        "northing",
        "easting",
        "elevation",
        "description",
        "crs",
        "horizontal_units",
        "vertical_units",
        "source_id",
    ]
    writer.writerow(keys)
    exact = []
    for p in data["points"]:
        record = {k: p[k] for k in keys}
        record["elevation"] = altered.get(p["point_uuid"], p["elevation"])
        exact.append(record)
        writer.writerow(
            [
                (
                    "'" + v
                    if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@"))
                    else v
                )
                for v in record.values()
            ]
        )
    payload = {
        "project": data["project"],
        "snapshot": data["snapshot"],
        "reason": reason,
        "changes": evidence,
        "corrected_points": exact,
        "sources": data["sources"],
        "csv_note": "Potential spreadsheet formulas in text cells are prefixed with an apostrophe in CSV only. JSON retains exact identifiers and text.",
    }
    result = io.BytesIO()
    with ZipFile(result, "w", ZIP_DEFLATED) as archive:
        archive.writestr("reviewed_points.csv", output.getvalue())
        archive.writestr("review_evidence.json", json.dumps(payload, indent=2, allow_nan=False))
    return result.getvalue(), evidence


def source_observations(project, point_uuid):
    """Read verified retained CSV/TXT observations without guessing duplicate identity."""
    from .project import sha256_file
    from .point_import import parse_canonical_points

    with project.db.connect() as conn:
        row = conn.execute(
            "SELECT point_id,source_id FROM canonical_points WHERE point_uuid=?", (point_uuid,)
        ).fetchone()
        if row is None:
            raise ValueError("Point record no longer exists.")
        source = conn.execute(
            "SELECT * FROM source_registry WHERE source_id=?", (row["source_id"],)
        ).fetchone()
    if source is None:
        raise ValueError("This record has no retained source file.")
    path = (project.paths.root / source["stored_path"]).resolve()
    if not path.is_relative_to(project.paths.root.resolve()) or not path.is_file():
        raise ValueError("Retained source is missing or outside this project.")
    if path.stat().st_size > 30 * 1024 * 1024:
        raise ValueError("Source observation preview is limited to 30 MiB.")
    if sha256_file(path) != source["sha256"]:
        raise ValueError(
            "Retained source hash changed. Restore verified evidence before reviewing corrections."
        )
    if path.suffix.lower() not in {".csv", ".txt", ".tsv", ".pnezd", ".asc"}:
        return {
            "source": dict(source),
            "observations": [],
            "notice": "Source hash verified. Observation preview supports canonical delimited point files only; inspect this source in its original application.",
        }
    points = parse_canonical_points(path)
    matches = [p for p in points if p["point_id"] == row["point_id"]]
    return {
        "source": dict(source),
        "observations": matches,
        "notice": "All original rows with this exact PointID are shown. Duplicate rows are not automatically paired to edited records.",
    }
