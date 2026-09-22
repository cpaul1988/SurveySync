from __future__ import annotations
import logging
from .api_models import (
    MapCrsIn,
    MapAlignmentIn,
    MapAlignmentSolveIn,
    MapLayerSettingsIn,
    MapLayerOrderIn,
    MapBookmarkIn,
    MapTransformIn,
    ManualEdgeIn,
)
import asyncio
import math
import tempfile
from pathlib import Path
from typing import Any, List
from fastapi import File, Form, HTTPException, UploadFile
from .models import MapBookmark, CustomCoordinateSystem, MapAlignmentSettings, ManualNetworkEdge
from .global_mapper import convert_vector_to_geojson, find_global_mapper
from .map_gis import (
    crs_unit_label,
    import_map_files,
    normalize_crs,
    xy_to_wgs84,
    wgs84_to_xy,
    crs_details,
    search_coordinate_systems,
    parse_custom_crs_text,
    apply_similarity_alignment,
    invert_similarity_alignment,
    solve_similarity_alignment,
    crs_area_warning,
)
from fastapi import APIRouter

router = APIRouter()


def _aligned_project_xy_locked(easting: float, northing: float) -> tuple[float, float]:
    from . import app as context

    a = context.runtime.storage.state.map_alignment
    if not a.enabled:
        return (float(easting), float(northing))
    return apply_similarity_alignment(
        float(easting),
        float(northing),
        scale_factor=a.scale_factor,
        rotation_deg=a.rotation_deg,
        offset_x=a.offset_x,
        offset_y=a.offset_y,
        origin_x=a.origin_x,
        origin_y=a.origin_y,
    )


def _inverse_aligned_project_xy_locked(easting: float, northing: float) -> tuple[float, float]:
    from . import app as context

    a = context.runtime.storage.state.map_alignment
    if not a.enabled:
        return (float(easting), float(northing))
    return invert_similarity_alignment(
        float(easting),
        float(northing),
        scale_factor=a.scale_factor,
        rotation_deg=a.rotation_deg,
        offset_x=a.offset_x,
        offset_y=a.offset_y,
        origin_x=a.origin_x,
        origin_y=a.origin_y,
    )


def _project_xy_to_lonlat_locked(
    easting: float | None, northing: float | None
) -> tuple[float | None, float | None]:
    from . import app as context

    if easting is None or northing is None:
        return (None, None)
    crs = (context.runtime.storage.state.map_project_crs or "").strip()
    if not crs:
        return (None, None)
    try:
        gx, gy = _aligned_project_xy_locked(float(easting), float(northing))
        lon, lat = xy_to_wgs84(gx, gy, crs)
        if not (math.isfinite(lon) and math.isfinite(lat)):
            return (None, None)
        return (lon, lat)
    except Exception:
        return (None, None)


def _manual_network_edges_locked() -> list[dict]:
    from . import app as context

    by_id = {p.point_id: p for p in context.runtime.storage.state.survey_points}
    out: list[dict] = []
    for e in context.runtime.storage.state.manual_network_edges:
        a, b = (by_id.get(e.from_point), by_id.get(e.to_point))
        if (
            not a
            or not b
            or a.easting is None
            or (a.northing is None)
            or (b.easting is None)
            or (b.northing is None)
        ):
            continue
        distance = math.hypot(
            float(b.easting) - float(a.easting), float(b.northing) - float(a.northing)
        )
        out.append(
            {
                "from_point": e.from_point,
                "to_point": e.to_point,
                "from_pipe_index": -1,
                "to_pipe_index": None,
                "distance": distance,
                "azimuth_from": None,
                "azimuth_to_expected": None,
                "reciprocal_error_deg": None,
                "bearing_error_deg": None,
                "score": 100.0,
                "status": "MANUAL",
                "notes": e.notes or "Manual connection",
                "manual": True,
                "locked": e.locked,
            }
        )
    return out


def _structure_map_record(point_id: str, easting: float, northing: float, **extra) -> dict:
    lon, lat = _project_xy_to_lonlat_locked(easting, northing)
    return {
        "point_id": point_id,
        "easting": easting,
        "northing": northing,
        "lon": lon,
        "lat": lat,
        **extra,
    }


@router.get("/api/network")
def api_network() -> dict:
    from . import app as context

    with context.runtime.lock:
        if context.runtime.job.running and context.runtime.live_active:
            structures = []
            for r in context.runtime.live_results:
                if r.easting is None or r.northing is None:
                    continue
                live_state = context._live_point_state_locked(r.point_id)
                display_status = (
                    r.status.value
                    if live_state == "INTERPRETED"
                    else "OCR_FOUND"
                    if live_state == "OCR_FOUND"
                    else "PENDING"
                )
                structures.append(
                    _structure_map_record(
                        r.point_id,
                        r.easting,
                        r.northing,
                        status=display_status,
                        committed_status=r.status.value,
                        live_state=live_state,
                        code=r.code,
                        category=r.category,
                        smart_confidence=r.smart_confidence,
                        pipe_count=len(r.pipes),
                        qc_flags=r.qc_flags,
                        elevation=r.elevation,
                        pipes=[p.model_dump(mode="json") for p in r.pipes],
                    )
                )
            inferred = [e.model_dump(mode="json") for e in context.runtime.live_network_edges]
            manual = _manual_network_edges_locked()
            return {
                "live_preview": True,
                "update_seq": context.runtime.live_update_seq,
                "candidate_count": len(context.runtime.live_candidates),
                "interpreted_count": len(context.runtime.live_interpreted_ids),
                "edges": inferred + manual,
                "structures": structures,
                "project_crs": context.runtime.storage.state.map_project_crs,
                "project_crs_name": context.runtime.storage.state.map_project_crs_name,
                "geographic_ready": bool(context.runtime.storage.state.map_project_crs),
            }
    with context.runtime.storage.lock:
        manual = _manual_network_edges_locked()
        if not context.runtime.storage.state.results:
            return {
                "live_preview": False,
                "edges": manual,
                "structures": [
                    _structure_map_record(
                        p.point_id,
                        p.easting,
                        p.northing,
                        status="PENDING",
                        code=p.code,
                        category=p.category,
                        smart_confidence=0.0,
                        pipe_count=0,
                        qc_flags=[],
                        elevation=p.elevation,
                        pipes=[],
                    )
                    for p in context.runtime.storage.state.survey_points
                    if p.easting is not None and p.northing is not None
                ],
                "project_crs": context.runtime.storage.state.map_project_crs,
                "project_crs_name": context.runtime.storage.state.map_project_crs_name,
                "geographic_ready": bool(context.runtime.storage.state.map_project_crs),
            }
        return {
            "live_preview": False,
            "edges": [
                e.model_dump(mode="json") for e in context.runtime.storage.state.network_edges
            ]
            + manual,
            "structures": [
                _structure_map_record(
                    r.point_id,
                    r.easting,
                    r.northing,
                    status=r.status.value,
                    code=r.code,
                    category=r.category,
                    smart_confidence=r.smart_confidence,
                    pipe_count=len(r.pipes),
                    qc_flags=r.qc_flags,
                    elevation=r.elevation,
                    pipes=[p.model_dump(mode="json") for p in r.pipes],
                )
                for r in context.runtime.storage.state.results
                if r.easting is not None and r.northing is not None
            ],
            "project_crs": context.runtime.storage.state.map_project_crs,
            "project_crs_name": context.runtime.storage.state.map_project_crs_name,
            "geographic_ready": bool(context.runtime.storage.state.map_project_crs),
        }


@router.get("/api/map/state")
def api_map_state() -> dict:
    from . import app as context

    with context.runtime.storage.lock:
        st = context.runtime.storage.state
        return {
            "project_crs": st.map_project_crs,
            "project_crs_name": st.map_project_crs_name,
            "project_units": crs_unit_label(st.map_project_crs),
            "crs_warning": st.map_crs_warning,
            "alignment": st.map_alignment.model_dump(mode="json"),
            "custom_coordinate_systems": [
                c.model_dump(mode="json") for c in st.custom_coordinate_systems
            ],
            "layers": [layer.model_dump(mode="json") for layer in st.map_layers],
            "bookmarks": [bookmark.model_dump(mode="json") for bookmark in st.map_bookmarks],
            "manual_edges": [edge.model_dump(mode="json") for edge in st.manual_network_edges],
        }


@router.get("/api/map/crs/search")
def api_map_crs_search(q: str = "") -> dict:
    try:
        return {"results": search_coordinate_systems(q, limit=50)}
    except Exception as exc:
        raise HTTPException(400, f"Coordinate-system search failed: {exc}")


@router.post("/api/map/crs/import")
async def api_map_crs_import(file: UploadFile = File(...)) -> dict:
    from . import app as context

    name = Path(file.filename or "custom.prj").name
    raw = await file.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(413, "Custom coordinate-system files are limited to 2 MB.")
    try:
        text = raw.decode("utf-8-sig")
    except Exception:
        text = raw.decode("cp1252", errors="replace")
    try:
        info = parse_custom_crs_text(text, name)
    except Exception as exc:
        raise HTTPException(400, f"Custom coordinate system could not be read: {exc}")
    item = CustomCoordinateSystem(
        name=info["name"],
        definition=info["definition"],
        authority=info.get("id", ""),
        units=info.get("units", ""),
        source_name=name,
    )
    with context.runtime.storage.lock:
        context.runtime.storage.state.custom_coordinate_systems = [
            c
            for c in context.runtime.storage.state.custom_coordinate_systems
            if c.name != item.name
        ]
        context.runtime.storage.state.custom_coordinate_systems.append(item)
        context.runtime.storage.save()
    return {"coordinate_system": item.model_dump(mode="json"), "details": info}


@router.post("/api/map/crs")
def api_map_crs(payload: MapCrsIn) -> dict:
    from . import app as context

    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_or_paused_locked()
        raw = (payload.crs or "").strip()
        warning = ""
        details: dict[str, Any] | None = None
        if not raw:
            context.runtime.storage.state.map_project_crs = ""
            context.runtime.storage.state.map_project_crs_name = ""
            context.runtime.storage.state.map_crs_warning = ""
        else:
            try:
                canonical, name = normalize_crs(raw)
                details = crs_details(canonical)
            except Exception as exc:
                raise HTTPException(400, f"Coordinate system could not be recognized: {exc}")
            context.runtime.storage.state.map_project_crs = canonical
            context.runtime.storage.state.map_project_crs_name = name
            samples = [
                p
                for p in context.runtime.storage.state.survey_points
                if p.easting is not None and p.northing is not None
            ][:25]
            if samples:
                lons = []
                lats = []
                for p in samples:
                    try:
                        gx, gy = _aligned_project_xy_locked(float(p.easting), float(p.northing))
                        lon, lat = xy_to_wgs84(gx, gy, canonical)
                        if math.isfinite(lon) and math.isfinite(lat):
                            lons.append(lon)
                            lats.append(lat)
                    except Exception:
                        logging.getLogger(__name__).warning(
                            "Recovery fallback in map_routes; operation did not complete.",
                            exc_info=True,
                        )
                if lons:
                    warning = crs_area_warning(
                        canonical, sum(lons) / len(lons), sum(lats) / len(lats)
                    )
            context.runtime.storage.state.map_crs_warning = warning
        context.runtime.storage.save()
        return {
            "project_crs": context.runtime.storage.state.map_project_crs,
            "project_crs_name": context.runtime.storage.state.map_project_crs_name,
            "project_units": crs_unit_label(context.runtime.storage.state.map_project_crs),
            "warning": warning,
            "details": details,
        }


@router.post("/api/map/alignment")
def api_map_alignment(payload: MapAlignmentIn) -> dict:
    from . import app as context

    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_or_paused_locked()
        if not math.isfinite(payload.scale_factor) or payload.scale_factor == 0:
            raise HTTPException(400, "Combined scale factor must be a finite non-zero number.")
        context.runtime.storage.state.map_alignment = MapAlignmentSettings(
            enabled=payload.enabled,
            scale_factor=payload.scale_factor,
            rotation_deg=payload.rotation_deg,
            offset_x=payload.offset_x,
            offset_y=payload.offset_y,
            origin_x=payload.origin_x,
            origin_y=payload.origin_y,
            label=payload.label or "Survey alignment",
        )
        context.runtime.storage.state.map_crs_warning = ""
        context.runtime.storage.save()
        return {"alignment": context.runtime.storage.state.map_alignment.model_dump(mode="json")}


@router.post("/api/map/alignment/solve")
def api_map_alignment_solve(payload: MapAlignmentSolveIn) -> dict:
    try:
        solved = solve_similarity_alignment([p.model_dump(mode="json") for p in payload.pairs])
        return {"solution": solved}
    except Exception as exc:
        raise HTTPException(400, f"Control-point calibration could not be solved: {exc}")


@router.post("/api/map/transform")
def api_map_transform(payload: MapTransformIn) -> dict:
    from . import app as context

    with context.runtime.storage.lock:
        crs = context.runtime.storage.state.map_project_crs
    if not crs:
        raise HTTPException(409, "Set the project coordinate system first.")
    try:
        if payload.direction == "from_wgs84":
            if payload.lon is None or payload.lat is None:
                raise ValueError("Longitude and latitude are required.")
            gx, gy = wgs84_to_xy(payload.lon, payload.lat, crs)
            with context.runtime.storage.lock:
                x, y = _inverse_aligned_project_xy_locked(gx, gy)
            return {"x": x, "y": y, "grid_x": gx, "grid_y": gy, "crs": crs}
        if payload.x is None or payload.y is None:
            raise ValueError("Easting/X and Northing/Y are required.")
        with context.runtime.storage.lock:
            gx, gy = _aligned_project_xy_locked(payload.x, payload.y)
        lon, lat = xy_to_wgs84(gx, gy, crs)
        return {"lon": lon, "lat": lat, "grid_x": gx, "grid_y": gy, "crs": crs}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(400, f"Coordinate conversion failed: {exc}")


@router.post("/api/map/import")
async def api_map_import(files: List[UploadFile] = File(...), assume_crs: str = Form("")) -> dict:
    from . import app as context

    if not files:
        raise HTTPException(400, "Choose at least one GIS file.")
    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_or_paused_locked()
        project_crs = (assume_crs or context.runtime.storage.state.map_project_crs or "").strip()
    with tempfile.TemporaryDirectory(prefix="fbs_map_import_") as td:
        root = Path(td)
        paths: list[Path] = []
        for upload in files:
            name = Path(upload.filename or "layer").name
            target = root / name
            await context._stream_upload_to_path(upload, target)
            paths.append(target)
        try:
            layers = await asyncio.to_thread(
                import_map_files, paths, context.APP_ROOT, project_crs or None
            )
        except (ValueError, RuntimeError) as native_exc:
            if not find_global_mapper():
                raise HTTPException(400, str(native_exc)) from native_exc
            sidecar_exts = {".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix"}
            candidates = [p for p in paths if p.suffix.lower() not in sidecar_exts]
            if not candidates:
                raise HTTPException(400, str(native_exc)) from native_exc
            converted: list[Path] = []
            conversion_errors: list[str] = []
            for index, source in enumerate(candidates, start=1):
                target = root / f"gm_converted_{context.index}.geojson"
                try:
                    await asyncio.to_thread(convert_vector_to_geojson, source, target)
                    converted.append(target)
                except Exception as gm_exc:
                    conversion_errors.append(f"{source.name}: {gm_exc}")
            if not converted:
                detail = "; ".join(conversion_errors[:3]) or "no primary dataset could be converted"
                raise HTTPException(
                    400,
                    f"Native import failed ({native_exc}). Global Mapper also could not convert the dataset to a vector map layer: {detail}",
                ) from native_exc
            try:
                layers = await asyncio.to_thread(
                    import_map_files, converted, context.APP_ROOT, project_crs or None
                )
                for layer in layers:
                    if layer.source_name.startswith("gm_converted_"):
                        layer.warning = (
                            "Imported through the installed Global Mapper conversion bridge."
                        )
            except Exception as gm_exc:
                raise HTTPException(
                    400,
                    f"Native import failed ({native_exc}). Global Mapper converted the source, but FieldBook Sync could not load the converted GeoJSON: {gm_exc}",
                ) from gm_exc
        except Exception as exc:
            ref = context._error_reference("GIS")
            context.logger.exception("GIS import failed [%s]", ref)
            raise HTTPException(500, f"GIS import failed. Reference {ref}: {exc}")
    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_or_paused_locked()
        context.runtime.storage.state.map_layers.extend(layers)
        context.runtime.storage.save()
        return {
            "imported": len(layers),
            "layers": [layer.model_dump(mode="json") for layer in layers],
        }


@router.post("/api/map/layers/{layer_id}")
def api_map_layer_settings(layer_id: str, payload: MapLayerSettingsIn) -> dict:
    from . import app as context

    with context.runtime.storage.lock:
        layer = next(
            (x for x in context.runtime.storage.state.map_layers if x.layer_id == layer_id), None
        )
        if layer is None:
            raise HTTPException(404, "Map layer not found.")
        if payload.visible is not None:
            layer.visible = bool(payload.visible)
        if payload.opacity is not None:
            layer.opacity = float(payload.opacity)
        if payload.name is not None and payload.name.strip():
            layer.name = payload.name.strip()[:120]
        context.runtime.storage.save()
        return layer.model_dump(mode="json")


@router.post("/api/map/layer-order")
def api_map_layer_order(payload: MapLayerOrderIn) -> dict:
    from . import app as context

    with context.runtime.storage.lock:
        existing = {x.layer_id: x for x in context.runtime.storage.state.map_layers}
        ordered = [existing[x] for x in payload.layer_ids if x in existing]
        seen = {x.layer_id for x in ordered}
        ordered.extend(
            (x for x in context.runtime.storage.state.map_layers if x.layer_id not in seen)
        )
        context.runtime.storage.state.map_layers = ordered
        context.runtime.storage.save()
        return {"layer_ids": [x.layer_id for x in ordered]}


@router.delete("/api/map/layers/{layer_id}")
def api_map_layer_delete(layer_id: str) -> dict:
    from . import app as context

    with context.runtime.storage.lock:
        before = len(context.runtime.storage.state.map_layers)
        context.runtime.storage.state.map_layers = [
            x for x in context.runtime.storage.state.map_layers if x.layer_id != layer_id
        ]
        if len(context.runtime.storage.state.map_layers) == before:
            raise HTTPException(404, "Map layer not found.")
        context.runtime.storage.save()
        return {"deleted": True}


@router.post("/api/map/bookmarks")
def api_map_bookmark_add(payload: MapBookmarkIn) -> dict:
    from . import app as context

    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Bookmark name is required.")
    bookmark = MapBookmark(**{**payload.model_dump(), "name": name[:80]})
    with context.runtime.storage.lock:
        context.runtime.storage.state.map_bookmarks.append(bookmark)
        context.runtime.storage.save()
    return bookmark.model_dump(mode="json")


@router.delete("/api/map/bookmarks/{bookmark_id}")
def api_map_bookmark_delete(bookmark_id: str) -> dict:
    from . import app as context

    with context.runtime.storage.lock:
        before = len(context.runtime.storage.state.map_bookmarks)
        context.runtime.storage.state.map_bookmarks = [
            b for b in context.runtime.storage.state.map_bookmarks if b.bookmark_id != bookmark_id
        ]
        if len(context.runtime.storage.state.map_bookmarks) == before:
            raise HTTPException(404, "Bookmark not found.")
        context.runtime.storage.save()
    return {"deleted": True}


@router.post("/api/network/manual")
def api_network_manual_add(payload: ManualEdgeIn) -> dict:
    from . import app as context

    a, b = (payload.from_point.strip(), payload.to_point.strip())
    if not a or not b or a == b:
        raise HTTPException(400, "Choose two different structures.")
    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_locked()
        ids = {p.point_id for p in context.runtime.storage.state.survey_points}
        if a not in ids or b not in ids:
            raise HTTPException(404, "One or both structures were not found.")
        exists = any(
            (
                {e.from_point, e.to_point} == {a, b}
                for e in context.runtime.storage.state.manual_network_edges
            )
        )
        if not exists:
            context.runtime.storage.state.manual_network_edges.append(
                ManualNetworkEdge(
                    from_point=a, to_point=b, notes=payload.notes or "Manual connection"
                )
            )
            context.runtime.storage.save()
    return {"created": not exists, "from_point": a, "to_point": b}


@router.delete("/api/network/manual/{from_point}/{to_point}")
def api_network_manual_delete(from_point: str, to_point: str) -> dict:
    from . import app as context

    with context.runtime.lock, context.runtime.storage.lock:
        context._assert_analysis_idle_locked()
        before = len(context.runtime.storage.state.manual_network_edges)
        context.runtime.storage.state.manual_network_edges = [
            e
            for e in context.runtime.storage.state.manual_network_edges
            if {e.from_point, e.to_point} != {from_point, to_point}
        ]
        if len(context.runtime.storage.state.manual_network_edges) == before:
            raise HTTPException(404, "Manual connection not found.")
        context.runtime.storage.save()
    return {"deleted": True}
