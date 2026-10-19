"""Snapshot exports and original-page spatial evidence for FieldBook review."""

from __future__ import annotations

from copy import deepcopy
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

router = APIRouter()


@router.get("/api/export")
def api_export() -> FileResponse:
    # Snapshot under lock, then perform ZIP/GIS generation outside it so UI polling stays responsive.
    from . import app as context

    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_locked()
        if not context.runtime.storage.state.results:
            raise HTTPException(400, "There are no results to export.")
        state_copy = deepcopy(context.runtime.storage.state)
    path = context.create_export_zip(state_copy, context.runtime.storage.export_dir)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/fieldbook-benchmark/export")
def api_fieldbook_benchmark_export() -> StreamingResponse:
    from . import app as context

    from .benchmark_export import benchmark_payload

    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_locked()
        if not context.runtime.storage.state.results:
            raise HTTPException(400, "Analyze a field book before exporting a benchmark run.")
        snapshot = deepcopy(context.runtime.storage.state)
    content = json.dumps(benchmark_payload(snapshot), ensure_ascii=False, indent=2).encode("utf-8")
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="fieldbook-benchmark-run.json"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/fieldbook-spatial/{graph_key}")
def api_fieldbook_spatial(graph_key: str) -> dict:
    from . import app as context

    from .ocr_local import _sha256_file

    with context.runtime.lock, context.runtime.storage.lock:
        graph = deepcopy(context.runtime.storage.state.spatial_graphs.get(graph_key))
        if graph is None:
            raise HTTPException(
                404, "This page has no saved spatial evidence. Re-run its analysis."
            )
        page_id = graph.get("source", {}).get("page_id")
        page = next(
            (
                page
                for page in context.runtime.storage.state.fieldbook_pages
                if page.page_id == page_id
            ),
            None,
        )
        page_path = page.image_path if page else None
    try:
        current_hash = _sha256_file(page_path) if page_path else None
    except OSError:
        current_hash = None
    if not current_hash or current_hash != graph.get("source", {}).get("image_sha256"):
        return {
            "status": "unavailable",
            "truncated": True,
            "source": graph.get("source", {}),
            "flags": ["SOURCE_IMAGE_CHANGED_OR_UNAVAILABLE"],
            "paths": [],
            "structures": [],
            "text_regions": [],
            "point_anchors": [],
            "associations": [],
        }
    return graph


@router.get("/api/export/{fmt}")
def api_direct_export(fmt: str) -> StreamingResponse:
    """Download a lightweight native GIS/CAD format without building the whole QA ZIP."""
    from . import app as context

    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_locked()
        if not context.runtime.storage.state.results:
            raise HTTPException(400, "There are no results to export.")
        state_copy = deepcopy(context.runtime.storage.state)
    try:
        filename, media_type, text = context.direct_export_text(state_copy, fmt)
    except ValueError as exc:
        raise HTTPException(404, "Supported direct exports are GeoJSON, KML, and DXF.") from exc
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    }
    return StreamingResponse(iter([text.encode("utf-8")]), media_type=media_type, headers=headers)
