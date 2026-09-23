from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .audit import utc_now
from .trimble_job import TrimbleJobError, parse_jobxml_points, prepare_jobxml

router = APIRouter(prefix="/api/v9/data-inspector", tags=["Survey Data Inspector"])

MAX_SOURCE_BYTES = 80 * 1024 * 1024
MAX_OUTLIER_SAMPLE = 50000
CACHE_VERSION = 1
DELIMITED_SUFFIXES = {".csv", ".txt", ".tsv", ".pnezd", ".asc"}
TRIMBLE_SUFFIXES = {".job", ".jxl", ".xml"}

ALIASES = {
    "point_id": {
        "point",
        "pointid",
        "pointnumber",
        "pointno",
        "pt",
        "ptno",
        "p",
        "id",
    },
    "northing": {"northing", "north", "n", "y"},
    "easting": {"easting", "east", "e", "x"},
    "elevation": {"elevation", "elev", "height", "z", "el"},
    "description": {"description", "desc", "code", "featurecode", "feature", "d"},
}


class InspectIn(BaseModel):
    file_path: str = Field(min_length=1, max_length=4096)
    force_refresh: bool = False


def _context():
    from . import router as context

    return context


def _cache_root() -> Path:
    root = _context().config_store.root / "data_inspector" / "cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_path(digest: str) -> Path:
    return _cache_root() / f"{digest}.json"


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _infer_mapping(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    normalized = {_normalize_header(header): header for header in headers}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[field] = normalized[alias]
                break
    return mapping


def _safe_float(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _coordinate_outliers(values: list[tuple[str, float, float]]) -> list[str]:
    if len(values) < 8:
        return []
    sample = values[:MAX_OUTLIER_SAMPLE]
    ns = [item[1] for item in sample]
    es = [item[2] for item in sample]
    median_n = statistics.median(ns)
    median_e = statistics.median(es)
    deviations = [
        math.hypot(northing - median_n, easting - median_e)
        for _, northing, easting in sample
    ]
    median_distance = statistics.median(deviations)
    mad = statistics.median([abs(value - median_distance) for value in deviations])
    if mad <= 1e-9:
        positive = [value for value in deviations if value > 0]
        if not positive:
            return []
        threshold = max(statistics.median(positive) * 20.0, 1000.0)
    else:
        threshold = median_distance + 12.0 * mad
    return [
        point_id
        for (point_id, _, _), distance in zip(sample, deviations)
        if distance > threshold
    ][:50]


def _project_context() -> dict[str, Any]:
    context = _context()
    project = context.current_project
    if project is None:
        return {
            "project_open": False,
            "crs": "",
            "horizontal_units": "",
            "vertical_units": "",
        }
    settings = project.coordinate_settings()
    return {
        "project_open": True,
        "project_name": str(project.manifest.get("name") or ""),
        "project_path": str(project.paths.root),
        "crs": str(settings.get("crs") or ""),
        "horizontal_units": str(settings.get("horizontal_units") or ""),
        "vertical_units": str(settings.get("vertical_units") or ""),
    }


def _read_delimited(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("Survey Data Inspector is limited to 80 MiB per source file.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("The survey text file is not valid UTF-8/UTF-8-BOM text.") from exc
    nonblank = [line for line in text.splitlines() if line.strip()]
    if not nonblank:
        raise ValueError("The survey file is empty.")
    sample_text = "\n".join(nonblank[:40])
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    try:
        dialect = csv.Sniffer().sniff(sample_text, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except csv.Error:
        if "\t" in sample_text and "," not in sample_text:
            delimiter = "\t"
    rows = [
        [str(value).strip() for value in row]
        for row in csv.reader(nonblank, delimiter=delimiter)
        if any(str(value).strip() for value in row)
    ]
    if not rows:
        raise ValueError("No survey records were found.")
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    has_header = False
    try:
        has_header = csv.Sniffer().has_header(sample_text)
    except csv.Error:
        has_header = False
    first_normalized = {_normalize_header(value) for value in rows[0]}
    known_aliases = set().union(*ALIASES.values())
    if len(first_normalized & known_aliases) >= 2:
        has_header = True
    headers = (
        [value or f"Column {index + 1}" for index, value in enumerate(rows[0])]
        if has_header
        else [f"Column {index + 1}" for index in range(width)]
    )
    data_rows = rows[1:] if has_header else rows
    if len(set(headers)) != len(headers):
        headers = [f"{value}_{index + 1}" for index, value in enumerate(headers)]
    mapping = _infer_mapping(headers)
    if not has_header and width >= 5:
        mapping = dict(
            zip(
                ("point_id", "northing", "easting", "elevation", "description"),
                headers[:5],
            )
        )
    indexes = {name: headers.index(column) for name, column in mapping.items()}
    point_ids: list[str] = []
    duplicate_ids: set[str] = set()
    seen_ids: set[str] = set()
    numeric_ids: list[int] = []
    coordinate_values: list[tuple[str, float, float]] = []
    missing_elevation = 0
    invalid_coordinates = 0
    codes: set[str] = set()
    for index, row in enumerate(data_rows):
        point_id = (
            row[indexes["point_id"]].strip()
            if "point_id" in indexes and indexes["point_id"] < len(row)
            else str(index + 1)
        )
        point_ids.append(point_id)
        if point_id in seen_ids:
            duplicate_ids.add(point_id)
        seen_ids.add(point_id)
        if re.fullmatch(r"\d+", point_id):
            numeric_ids.append(int(point_id))
        northing = (
            _safe_float(row[indexes["northing"]])
            if "northing" in indexes and indexes["northing"] < len(row)
            else None
        )
        easting = (
            _safe_float(row[indexes["easting"]])
            if "easting" in indexes and indexes["easting"] < len(row)
            else None
        )
        elevation = (
            _safe_float(row[indexes["elevation"]])
            if "elevation" in indexes and indexes["elevation"] < len(row)
            else None
        )
        if "elevation" in indexes and elevation is None:
            missing_elevation += 1
        if "northing" in indexes and "easting" in indexes:
            if northing is None or easting is None:
                invalid_coordinates += 1
            else:
                coordinate_values.append((point_id, northing, easting))
        if "description" in indexes and indexes["description"] < len(row):
            code = row[indexes["description"]].strip()
            if code:
                codes.add(code)
    preview = [
        {header: row[index] if index < len(row) else "" for index, header in enumerate(headers)}
        for row in data_rows[:12]
    ]
    return {
        "format": "delimited",
        "delimiter": "\\t" if delimiter == "\t" else delimiter,
        "has_header": has_header,
        "headers": headers,
        "mapping": mapping,
        "row_count": len(data_rows),
        "preview": preview,
        "numeric_point_id_count": len(numeric_ids),
        "numeric_point_id_min": min(numeric_ids) if numeric_ids else None,
        "numeric_point_id_max": max(numeric_ids) if numeric_ids else None,
        "duplicate_point_ids": sorted(duplicate_ids)[:100],
        "missing_elevation_count": missing_elevation,
        "invalid_coordinate_count": invalid_coordinates,
        "unique_code_count": len(codes),
        "coordinate_outliers_suspected": _coordinate_outliers(coordinate_values),
        "normalized_path": str(path),
    }


def _write_normalized_trimble(
    digest: str, points: list[dict[str, Any]]
) -> Path:
    output = _cache_root() / f"{digest}_trimble_points.csv"
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["PointID", "Northing", "Easting", "Elevation", "Code"])
        for point in points:
            writer.writerow(
                [
                    point.get("point_id", ""),
                    point.get("northing", ""),
                    point.get("easting", ""),
                    point.get("elevation", ""),
                    point.get("code", ""),
                ]
            )
    return output


def _read_trimble(path: Path, digest: str) -> dict[str, Any]:
    work = _cache_root() / "trimble_work"
    jobxml_path, conversion = prepare_jobxml(path, work)
    parsed = parse_jobxml_points(jobxml_path)
    points = list(parsed.get("points") or [])
    metadata = dict(parsed.get("metadata") or {})
    numeric_ids = [
        int(str(point.get("point_id")))
        for point in points
        if re.fullmatch(r"\d+", str(point.get("point_id") or ""))
    ]
    seen: set[str] = set()
    duplicates: set[str] = set()
    coordinates: list[tuple[str, float, float]] = []
    missing_elevation = 0
    codes: set[str] = set()
    for point in points:
        point_id = str(point.get("point_id") or "")
        if point_id in seen:
            duplicates.add(point_id)
        seen.add(point_id)
        northing = _safe_float(point.get("northing"))
        easting = _safe_float(point.get("easting"))
        elevation = _safe_float(point.get("elevation"))
        if elevation is None:
            missing_elevation += 1
        if northing is not None and easting is not None:
            coordinates.append((point_id, northing, easting))
        code = str(point.get("code") or "").strip()
        if code:
            codes.add(code)
    normalized = _write_normalized_trimble(digest, points)
    return {
        "format": "trimble_jobxml",
        "delimiter": ",",
        "has_header": True,
        "headers": ["PointID", "Northing", "Easting", "Elevation", "Code"],
        "mapping": {
            "point_id": "PointID",
            "northing": "Northing",
            "easting": "Easting",
            "elevation": "Elevation",
            "description": "Code",
        },
        "row_count": len(points),
        "preview": [
            {
                "PointID": str(point.get("point_id") or ""),
                "Northing": point.get("northing"),
                "Easting": point.get("easting"),
                "Elevation": point.get("elevation"),
                "Code": str(point.get("code") or ""),
            }
            for point in points[:12]
        ],
        "numeric_point_id_count": len(numeric_ids),
        "numeric_point_id_min": min(numeric_ids) if numeric_ids else None,
        "numeric_point_id_max": max(numeric_ids) if numeric_ids else None,
        "duplicate_point_ids": sorted(
            set(metadata.get("duplicate_point_ids") or []) | duplicates
        )[:100],
        "missing_elevation_count": missing_elevation,
        "invalid_coordinate_count": max(
            0, int(metadata.get("point_count") or len(points)) - len(coordinates)
        ),
        "unique_code_count": len(codes),
        "coordinate_outliers_suspected": _coordinate_outliers(coordinates),
        "normalized_path": str(normalized),
        "trimble_metadata": metadata,
        "conversion": conversion,
    }


def _targets(result: dict[str, Any]) -> list[dict[str, str]]:
    mapping = result.get("mapping") or {}
    targets: list[dict[str, str]] = []
    if {"point_id", "northing", "easting", "elevation", "description"} <= set(mapping):
        targets.append(
            {
                "id": "topo",
                "label": "TopoSync Rod Height QC",
                "reason": "Point ID, N/E/Z and feature code were detected.",
            }
        )
    if {"point_id", "northing", "easting"} <= set(mapping):
        targets.append(
            {
                "id": "control",
                "label": "ControlSync",
                "reason": "Coordinate observations were detected.",
            }
        )
    if "point_id" in mapping:
        targets.append(
            {
                "id": "point_ranges",
                "label": "ReportSync Point Ranges",
                "reason": "Point IDs were detected.",
            }
        )
    return targets


def inspect_path(path_value: str, *, force_refresh: bool = False) -> dict[str, Any]:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Survey file was not found: {path}")
    if path.stat().st_size > MAX_SOURCE_BYTES and path.suffix.lower() not in TRIMBLE_SUFFIXES:
        raise ValueError("Survey Data Inspector is limited to 80 MiB per source file.")
    suffix = path.suffix.lower()
    if suffix not in DELIMITED_SUFFIXES | TRIMBLE_SUFFIXES:
        raise ValueError(
            "Inspector supports CSV, TXT, TSV, PNEZD, ASC, Trimble JOB, JXL and JobXML."
        )
    digest = _sha256(path)
    cache_path = _cache_path(digest)
    if cache_path.is_file() and not force_refresh:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, TypeError):
            cached = None
        if isinstance(cached, dict) and cached.get("cache_version") == CACHE_VERSION:
            cached["cached"] = True
            return cached
    if suffix in DELIMITED_SUFFIXES:
        detail = _read_delimited(path)
    else:
        detail = _read_trimble(path, digest)
    project = _project_context()
    result = {
        "cache_version": CACHE_VERSION,
        "cached": False,
        "inspected_utc": utc_now(),
        "source_path": str(path),
        "source_name": path.name,
        "source_size_bytes": path.stat().st_size,
        "source_sha256": digest,
        "source_suffix": suffix,
        **detail,
        "project_context": project,
        "crs_status": (
            f"Current project CRS: {project['crs']}"
            if project.get("crs")
            else "CRS not verified"
        ),
        "units_status": (
            f"Current project units: {project['horizontal_units']} / {project['vertical_units']}"
            if project.get("horizontal_units")
            else "Units not verified"
        ),
    }
    result["targets"] = _targets(result)
    temp = cache_path.with_suffix(".tmp")
    temp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(cache_path)
    return result


@router.post("/inspect")
def inspect(payload: InspectIn) -> dict[str, Any]:
    try:
        return inspect_path(payload.file_path, force_refresh=payload.force_refresh)
    except (ValueError, OSError, TrimbleJobError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/recent")
def recent(limit: int = 20) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    paths = sorted(
        _cache_root().glob("*.json"),
        key=lambda value: value.stat().st_mtime,
        reverse=True,
    )
    for path in paths[: max(1, min(int(limit), 100))]:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            items.append(
                {
                    "source_name": str(data.get("source_name") or ""),
                    "source_path": str(data.get("source_path") or ""),
                    "normalized_path": str(data.get("normalized_path") or ""),
                    "inspected_utc": str(data.get("inspected_utc") or ""),
                    "row_count": int(data.get("row_count") or 0),
                    "format": str(data.get("format") or ""),
                    "source_sha256": str(data.get("source_sha256") or ""),
                }
            )
    return {"items": items}


@router.post("/cache/clear")
def clear_cache() -> dict[str, Any]:
    removed = 0
    for path in _cache_root().glob("*"):
        if path.is_file():
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    return {"removed": removed}
