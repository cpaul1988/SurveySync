"""Immutable CAD review packages with project-bound provenance and reports."""

from __future__ import annotations
import csv
import hashlib
import io
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED
from .cad_geometry import METERS, digest, closure

MAX_BYTES = 32 * 1024 * 1024


def context(project):
    return {
        k: project.manifest.get(k, "")
        for k in ("project_id", "crs", "horizontal_units", "vertical_units")
    }


def folder(project):
    p = (project.paths.module_root / "BoundarySync" / "CADReview").resolve()
    if not p.is_relative_to(project.paths.root.resolve()):
        raise ValueError("CAD review folder must remain inside project.")
    p.mkdir(parents=True, exist_ok=True)
    return p


def parse_bytes(raw, drawing_units, project_units, gap_search_ft=1.0):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("DXF must contain 1 byte to 32 MiB. No partial import created.")
    if drawing_units not in METERS or project_units not in (
        "meters",
        "international_feet",
        "us_survey_feet",
    ):
        raise ValueError("Explicit supported drawing and project units are required.")
    with tempfile.TemporaryDirectory(prefix="surveysync-cad-") as t:
        root = Path(t)
        src = root / "original.dxf"
        src.write_bytes(raw)
        (root / "request.json").write_text(
            json.dumps(
                {
                    "file": str(src),
                    "drawing_units": drawing_units,
                    "project_units": project_units,
                    "gap_search_ft": gap_search_ft,
                }
            ),
            encoding="utf-8",
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "surveysync.cad_worker",
                    str(root / "request.json"),
                    str(root / "result.json"),
                ],
                cwd=Path(__file__).resolve().parents[1],
                timeout=40,
                capture_output=True,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                "CAD review exceeded 40 seconds; split the drawing. No partial result retained."
            ) from exc
        output = root / "result.json"
        if result.returncode or not output.is_file() or output.stat().st_size > 64 * 1024 * 1024:
            raise ValueError(
                "CAD worker failed or exceeded output limit; no partial result retained."
            )
        data = json.loads(output.read_text(encoding="utf-8"))
        if not data.get("ok"):
            raise ValueError("DXF review failed: " + data.get("error", "unknown parser error"))
        return data["drawing"]


def project_points(project):
    with project.db.connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT point_uuid,point_id,easting,northing,crs,horizontal_units FROM canonical_points ORDER BY rowid LIMIT 20001"
            )
        ]
    if len(rows) > 20000:
        raise ValueError(
            "CAD overlay supports up to 20,000 canonical points; no partial overlay produced."
        )
    valid = []
    excluded = 0
    for p in rows:
        if (
            all(
                isinstance(p[k], (int, float)) and math.isfinite(p[k])
                for k in ("easting", "northing")
            )
            and p["crs"] == project.manifest.get("crs", "")
            and p["horizontal_units"] == project.manifest.get("horizontal_units")
        ):
            valid.append(p)
        else:
            excluded += 1
    return valid, excluded


def retain(project, raw, name, drawing, expected_context):
    if context(project) != expected_context:
        raise ValueError("Project coordinate settings changed during import. Review again.")
    points, excluded = project_points(project)
    drawing = dict(
        drawing,
        review_id=uuid4().hex,
        source_name=Path(name).name,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        project=expected_context,
        points=points,
        excluded_point_count=excluded,
        point_snapshot=digest(points),
    )
    drawing["snapshot"] = digest(drawing)
    destination = folder(project) / drawing["review_id"]
    destination.mkdir()
    try:
        (destination / "original.dxf").write_bytes(raw)
        (destination / "review.json").write_text(
            json.dumps(drawing, allow_nan=False), encoding="utf-8"
        )
        project.db.audit(
            "BoundarySync",
            "CAD_REVIEW_IMPORTED",
            object_type="cad_review",
            object_id=drawing["review_id"],
            details={
                "source_sha256": drawing["source_sha256"],
                "name": drawing["source_name"],
                "snapshot": drawing["snapshot"],
                "drawing_units": drawing["drawing_units"],
                "scale_to_project": drawing["scale_to_project"],
                "issues": len(drawing["qa"]["issues"]),
                "unsupported": len(drawing["unsupported"]),
                "coordinate_alignment_confirmed": True,
            },
        )
    except Exception:
        # Roll back only this newly created immutable package when retention/audit fails.
        shutil.rmtree(destination)
        raise
    return drawing


def read(project, review_id):
    if not re.fullmatch("[0-9a-f]{32}", review_id):
        raise ValueError("Invalid CAD review ID.")
    root = folder(project)
    p = (root / review_id).resolve()
    if not p.is_relative_to(root):
        raise ValueError("Invalid CAD review location.")
    path = p / "review.json"
    if not path.resolve().is_relative_to(root):
        raise ValueError("Invalid CAD review location.")
    if not path.is_file():
        raise ValueError("CAD review not found.")
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("CAD review exceeds size limit.")
    data = json.loads(path.read_text(encoding="utf-8"))
    token = data.pop("snapshot")
    if digest(data) != token:
        raise ValueError("Retained CAD review changed; import again.")
    data["snapshot"] = token
    if data["project"] != context(project):
        raise ValueError("Project coordinate context changed; import again.")
    source = p / "original.dxf"
    if (
        not source.resolve().is_relative_to(root)
        or source.stat().st_size > MAX_BYTES
        or hashlib.sha256(source.read_bytes()).hexdigest() != data["source_sha256"]
    ):
        raise ValueError("Retained DXF changed; import again.")
    points, _ = project_points(project)
    if digest(points) != data["point_snapshot"]:
        raise ValueError("Project points changed; import again to refresh the overlay.")
    return data


def list_reviews(project):
    result = []
    for p in sorted(
        folder(project).glob("*/review.json"), key=lambda x: x.stat().st_mtime, reverse=True
    )[:100]:
        if p.stat().st_size > 64 * 1024 * 1024:
            continue
        # Full integrity/context check occurs when a specific package is opened.
        data = json.loads(p.read_text(encoding="utf-8"))
        result.append({k: data[k] for k in ("review_id", "source_name", "source_sha256")})
    return result


def report(data, selections):
    check = closure(data, selections) if selections else None
    report_data = {k: v for k, v in data.items() if k not in ("entities", "points")}
    report_data["closure"] = check
    stream = io.StringIO(newline="")
    w = csv.writer(stream)
    w.writerow(["Kind", "Entity IDs", "Message", "Value", "Approximate"])
    for issue in data["qa"]["issues"]:
        row = [
            issue["kind"],
            "; ".join(issue["entity_ids"]),
            issue["message"],
            json.dumps(issue["value"]),
            issue["approximate"],
        ]
        w.writerow(
            [
                "'" + str(x) if str(x).startswith(("=", "+", "-", "@", "\t", "\r")) else x
                for x in row
            ]
        )
    out = io.BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as z:
        z.writestr(
            "CAD_Review.json",
            json.dumps(report_data, indent=2, ensure_ascii=False, allow_nan=False),
        )
        z.writestr("CAD_Findings.csv", stream.getvalue())
        z.writestr(
            "README.txt",
            "SurveySync CAD review\n"
            + data["notice"]
            + "\n"
            + data["qa"]["scope"]
            + "\nClosure tolerance: 0.10 project ft; metric projects use 0.03048 m. No source geometry modified.\n",
        )
    return out.getvalue()
