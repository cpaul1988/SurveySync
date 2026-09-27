"""Optional point-cloud support for SurveySync.

LAS metadata inspection is available with the Python standard library only.
LAZ/COPC and point sampling use optional laspy or PDAL capabilities when present.
No point-cloud dependency is required for SurveySync startup.
"""

from __future__ import annotations

import importlib.util
import json
import math
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any

from .project import SurveyProject

_POINT_EXTENSIONS = {".las", ".laz"}


class PointCloudError(RuntimeError):
    pass


def runtime_status() -> dict[str, Any]:
    pdal = shutil.which("pdal")
    laspy_ready = importlib.util.find_spec("laspy") is not None
    return {
        "native_las_metadata": True,
        "laspy_ready": bool(laspy_ready),
        "pdal_ready": bool(pdal),
        "pdal_path": str(pdal or ""),
        "las_supported": True,
        "laz_supported": bool(laspy_ready or pdal),
        "sampling_supported": bool(laspy_ready),
        "note": (
            "LAS metadata works without optional software. "
            "Install laspy with a LAZ backend or PDAL for compressed LAZ/COPC support."
        ),
    }


def _u16(data: bytes, offset: int) -> int:
    return int(struct.unpack_from("<H", data, offset)[0])


def _u32(data: bytes, offset: int) -> int:
    return int(struct.unpack_from("<I", data, offset)[0])


def _u64(data: bytes, offset: int) -> int:
    return int(struct.unpack_from("<Q", data, offset)[0])


def _f64(data: bytes, offset: int) -> float:
    return float(struct.unpack_from("<d", data, offset)[0])


def _native_las_header(path: Path) -> dict[str, Any]:
    """Read stable LAS 1.0-1.4 header fields without loading point records."""
    with path.open("rb") as fh:
        data = fh.read(375)
    if len(data) < 227 or data[:4] != b"LASF":
        raise PointCloudError("File does not contain a valid LAS header.")

    version_major = data[24]
    version_minor = data[25]
    header_size = _u16(data, 94)
    offset_to_points = _u32(data, 96)
    vlr_count = _u32(data, 100)
    raw_point_format = data[104]
    point_format = int(raw_point_format & 0x3F)
    compressed_flag = bool(raw_point_format & 0x80)
    point_record_length = _u16(data, 105)
    legacy_point_count = _u32(data, 107)
    extended_point_count = 0
    if version_major == 1 and version_minor >= 4 and len(data) >= 255:
        extended_point_count = _u64(data, 247)
    point_count = extended_point_count or legacy_point_count

    scale_x = _f64(data, 131)
    scale_y = _f64(data, 139)
    scale_z = _f64(data, 147)
    offset_x = _f64(data, 155)
    offset_y = _f64(data, 163)
    offset_z = _f64(data, 171)
    max_x = _f64(data, 179)
    min_x = _f64(data, 187)
    max_y = _f64(data, 195)
    min_y = _f64(data, 203)
    max_z = _f64(data, 211)
    min_z = _f64(data, 219)

    numeric = (
        scale_x,
        scale_y,
        scale_z,
        offset_x,
        offset_y,
        offset_z,
        min_x,
        min_y,
        min_z,
        max_x,
        max_y,
        max_z,
    )
    if not all(math.isfinite(value) for value in numeric):
        raise PointCloudError("LAS header contains non-finite scale/offset/bounds values.")
    if any(value <= 0 for value in (scale_x, scale_y, scale_z)):
        raise PointCloudError("LAS header contains a non-positive coordinate scale.")

    return {
        "reader": "native_las_header",
        "version": f"{version_major}.{version_minor}",
        "header_size": header_size,
        "offset_to_point_data": offset_to_points,
        "vlr_count": vlr_count,
        "point_format": point_format,
        "point_record_length": point_record_length,
        "point_count": int(point_count),
        "legacy_point_count": int(legacy_point_count),
        "extended_point_count": int(extended_point_count),
        "compressed_flag": compressed_flag,
        "scale": {"x": scale_x, "y": scale_y, "z": scale_z},
        "offset": {"x": offset_x, "y": offset_y, "z": offset_z},
        "bounds": {
            "min_x": min_x,
            "min_y": min_y,
            "min_z": min_z,
            "max_x": max_x,
            "max_y": max_y,
            "max_z": max_z,
        },
    }


def _inspect_with_laspy(path: Path) -> dict[str, Any]:
    try:
        import laspy
    except ImportError as exc:
        raise PointCloudError("laspy is not installed.") from exc

    try:
        with laspy.open(path) as reader:
            header = reader.header
            mins = [float(value) for value in header.mins]
            maxs = [float(value) for value in header.maxs]
            scales = [float(value) for value in header.scales]
            offsets = [float(value) for value in header.offsets]
            point_format = int(header.point_format.id)
            version = str(header.version)
            point_count = int(header.point_count)
    except (OSError, ValueError, laspy.errors.LaspyException) as exc:
        raise PointCloudError(f"laspy could not read point-cloud metadata: {exc}") from exc

    return {
        "reader": "laspy",
        "version": version,
        "point_format": point_format,
        "point_count": point_count,
        "scale": {"x": scales[0], "y": scales[1], "z": scales[2]},
        "offset": {"x": offsets[0], "y": offsets[1], "z": offsets[2]},
        "bounds": {
            "min_x": mins[0],
            "min_y": mins[1],
            "min_z": mins[2],
            "max_x": maxs[0],
            "max_y": maxs[1],
            "max_z": maxs[2],
        },
    }


def _inspect_with_pdal(path: Path) -> dict[str, Any]:
    pdal = shutil.which("pdal")
    if not pdal:
        raise PointCloudError("PDAL CLI is not installed.")
    command = [pdal, "info", "--summary", "--metadata", str(path)]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PointCloudError(f"PDAL metadata inspection failed: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-1500:]
        raise PointCloudError(
            f"PDAL could not inspect the point cloud (exit {completed.returncode})."
            + (f" {detail}" if detail else "")
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PointCloudError("PDAL returned invalid JSON metadata.") from exc
    return {"reader": "pdal", "pdal": payload}


def inspect_point_cloud(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise PointCloudError(f"Point-cloud file was not found: {source}")
    suffix = source.suffix.lower()
    if suffix not in _POINT_EXTENSIONS:
        raise PointCloudError("Point-cloud inspection currently supports LAS and LAZ files.")

    if suffix == ".las":
        metadata = _native_las_header(source)
        # An LAS header may still indicate compressed point data. Prefer an optional
        # capable reader in that unusual case.
        if metadata.get("compressed_flag"):
            status = runtime_status()
            if status["laspy_ready"]:
                metadata = _inspect_with_laspy(source)
            elif status["pdal_ready"]:
                metadata = _inspect_with_pdal(source)
            else:
                raise PointCloudError(
                    "LAS header indicates compressed point data; install laspy/LAZ support or PDAL."
                )
    else:
        status = runtime_status()
        if status["laspy_ready"]:
            try:
                metadata = _inspect_with_laspy(source)
            except PointCloudError:
                if status["pdal_ready"]:
                    metadata = _inspect_with_pdal(source)
                else:
                    raise
        elif status["pdal_ready"]:
            metadata = _inspect_with_pdal(source)
        else:
            raise PointCloudError(
                "LAZ/COPC requires optional laspy with a LAZ backend or the PDAL CLI."
            )

    return {
        "path": str(source),
        "filename": source.name,
        "extension": suffix,
        "size_bytes": source.stat().st_size,
        "metadata": metadata,
        "runtime": runtime_status(),
    }


def sample_points(path: str | Path, *, max_points: int = 1000) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    limit = max(1, min(int(max_points), 10000))
    if importlib.util.find_spec("laspy") is None:
        raise PointCloudError(
            "Point sampling requires optional laspy. Metadata-only LAS inspection remains available."
        )
    try:
        import laspy  # type: ignore

        with laspy.open(source) as reader:
            points = reader.read_points(limit)
            rows = []
            classifications = getattr(points, "classification", None)
            for index in range(len(points)):
                row = {
                    "x": float(points.x[index]),
                    "y": float(points.y[index]),
                    "z": float(points.z[index]),
                }
                if classifications is not None:
                    row["classification"] = int(classifications[index])
                rows.append(row)
    except (OSError, ValueError, laspy.errors.LaspyException) as exc:
        raise PointCloudError(f"laspy could not sample point records: {exc}") from exc

    return {
        "path": str(source),
        "sample_count": len(rows),
        "max_points": limit,
        "points": rows,
        "note": "Sample contains the first point records only and is intended for QA preview, not statistical sampling.",
    }


def import_point_cloud(
    project: SurveyProject,
    path: str | Path,
    *,
    notes: str = "",
) -> dict[str, Any]:
    inspection = inspect_point_cloud(path)
    source = project.import_source(
        Path(path),
        "TopoSync",
        notes or "Original LAS/LAZ point-cloud source retained immutably by SurveySync.",
    )
    project.db.audit(
        "TopoSync",
        "POINT_CLOUD_IMPORTED",
        object_type="source",
        object_id=str(source.get("source_id") or ""),
        details={
            "filename": inspection["filename"],
            "extension": inspection["extension"],
            "size_bytes": inspection["size_bytes"],
            "reader": inspection["metadata"].get("reader"),
            "point_count": inspection["metadata"].get("point_count"),
            "bounds": inspection["metadata"].get("bounds"),
        },
    )
    return {**inspection, "source": source}


def point_cloud_sources(project: SurveyProject) -> list[dict[str, Any]]:
    return [
        row
        for row in project.sources()
        if str(row.get("module") or "") == "TopoSync"
        and Path(str(row.get("original_name") or "")).suffix.lower() in _POINT_EXTENSIONS
    ]
