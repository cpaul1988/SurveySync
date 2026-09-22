from __future__ import annotations
from .api_models import (
    TrimbleJobImportIn,
    LevelImportIn,
    LevelSolveIn,
    LevelRevisionSelectIn,
    TraverseImportIn,
    TraverseSolveIn,
    ScaleFitIn,
    ProjectionSamplesIn,
    SpatialImportIn,
    FieldToFinishIn,
    UtilitySyncIn,
    UtilityAnalyzeIn,
    UtilityInvertIn,
    UtilityKmlIn,
    AttachmentIn,
    AutoPhotoIn,
    SurveyReportIn,
    NotificationPolicyIn,
    EmailNotificationIn,
    TrimbleProjectsIn,
    CloudImportIn,
    AnnotatedFieldbookIn,
)
import json
import shutil
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from .audit import utc_now
from .project import safe_name
from .leveling import (
    parse_level_csv,
    import_run as import_level_run,
    solve_saved_run as solve_level_saved,
    list_runs as list_level_runs,
    solution_history as level_solution_history,
)
from .revisions import set_active_solution, compare_level_solutions
from .traverse import (
    parse_traverse_csv,
    import_run as import_traverse_run,
    solve_saved_run as solve_traverse_saved,
    list_runs as list_traverse_runs,
)
from .scale_factor import (
    ScaleSample,
    fit_project_factor,
    projection_scale_samples,
    save_solution as save_scale_solution,
    list_solutions as list_scale_solutions,
)
from .spatial import import_spatial, list_layers as list_spatial_layers
from .field_to_finish import parse_coded_points, build_linework, to_geojson
from .utility import (
    sync_fieldbook_results,
    score_supplemental_gis,
    pipe_grades,
    completion_status,
    export_completion_kmz,
)
from .attachments import attach_file, list_attachments, auto_attach_photos
from .reporting import project_report, control_report, list_deliverables, register_deliverable
from .notifications import (
    send_deliverable_notification,
    list_notifications,
    load_policy as load_notification_policy,
    save_policy as save_notification_policy,
)
from .field_cloud import trimble_list_projects, import_cloud_file, list_sync_log
from .trimble_job import (
    prepare_jobxml,
    parse_jobxml_points,
    trimble_runtime_status,
    TrimbleJobError,
)

router = APIRouter()


@router.post("/api/v9/level/extract-fieldbook")
def level_extract_fieldbook():
    from . import router as context

    p = context.require_project()
    field_app = context._fieldbook_app_module()
    try:
        from fieldbook_sync.levelbook_extract import extract_level_book_candidate

        state = field_app.runtime.storage.state
        result = extract_level_book_candidate(
            state,
            Path(__file__).resolve().parents[1],
            model=field_app.runtime.ollama_model,
            base_url=field_app.runtime.ollama_base_url,
        )
        out = p.paths.derived / "ControlSync" / "level_book_extraction_candidate.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        p.db.audit(
            "ControlSync",
            "LEVEL_BOOK_AI_EXTRACTION_CANDIDATE",
            object_type="level_candidate",
            object_id=out.name,
            details={
                "row_count": len(result.get("rows") or []),
                "page_count": result.get("page_count"),
                "review_required": True,
            },
        )
        return {**result, "candidate_path": str(out)}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/level/import")
def level_import(payload: LevelImportIn):
    from . import router as context

    p = context.require_project()
    path = Path(payload.file_path).expanduser().resolve()
    try:
        src = p.import_source(path, "ControlSync", "Level book/level loop observations")
        obs = parse_level_csv(path)
        run_id = import_level_run(
            p.db,
            payload.name,
            obs,
            source_id=src["source_id"],
            start_elevation=payload.start_elevation,
            known_end_elevation=payload.known_end_elevation,
            start_point=payload.start_point,
            end_point=payload.end_point,
            adjustment_method=payload.adjustment_method,
        )
        return {"run_id": run_id, "observation_count": len(obs), "source_id": src["source_id"]}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/level/runs")
def level_runs():
    from . import router as context

    return {"runs": list_level_runs(context.require_project().db)}


@router.post("/api/v9/level/solve")
def level_solve(payload: LevelSolveIn):
    from . import router as context

    try:
        return solve_level_saved(
            context.require_project().db,
            payload.run_id,
            start_elevation=payload.start_elevation,
            known_end_elevation=payload.known_end_elevation,
            adjustment_method=payload.adjustment_method,
            middle_wire_tolerance=payload.middle_wire_tolerance,
            max_distance_imbalance=payload.max_distance_imbalance,
            closure_tolerance=payload.closure_tolerance,
            stadia_multiplier=payload.stadia_multiplier,
            calculation_profile=payload.calculation_profile,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/level/history")
def level_history(run_id: str):
    from . import router as context

    try:
        return {"solutions": level_solution_history(context.require_project().db, run_id)}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/level/activate")
def level_activate_revision(payload: LevelRevisionSelectIn):
    from . import router as context

    p = context.require_project()
    try:
        return set_active_solution(
            p.db,
            "level",
            payload.run_id,
            payload.solution_id,
            note=payload.note,
            audit_action="LEVEL_SOLUTION_RESTORED",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/level/compare")
def level_compare_revisions(run_id: str, solution_a: str, solution_b: str):
    from . import router as context

    p = context.require_project()
    try:
        return compare_level_solutions(p.db, run_id, solution_a, solution_b)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/traverse/import")
def traverse_import(payload: TraverseImportIn):
    from . import router as context

    p = context.require_project()
    path = Path(payload.file_path).expanduser().resolve()
    try:
        src = p.import_source(path, "ControlSync", "Traverse observations")
        courses = parse_traverse_csv(path)
        rid = import_traverse_run(
            p.db,
            payload.name,
            courses,
            start_n=payload.start_n,
            start_e=payload.start_e,
            end_n=payload.end_n,
            end_e=payload.end_e,
            source_id=src["source_id"],
            adjustment_method=payload.adjustment_method,
        )
        return {"run_id": rid, "course_count": len(courses), "source_id": src["source_id"]}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/traverse/runs")
def traverse_runs():
    from . import router as context

    return {"runs": list_traverse_runs(context.require_project().db)}


@router.post("/api/v9/traverse/solve")
def traverse_solve(payload: TraverseSolveIn):
    from . import router as context

    try:
        return solve_traverse_saved(
            context.require_project().db,
            payload.run_id,
            adjustment_method=payload.adjustment_method,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/geodesy/project-factor")
def geodesy_project_factor(payload: ScaleFitIn):
    from . import router as context

    p = context.require_project()
    try:
        samples = [
            ScaleSample(
                label=x.label or f"Sample {i + 1}",
                factor=x.factor,
                weight=x.weight,
                station=x.station,
                zone=x.zone,
                source=x.source,
            )
            for i, x in enumerate(payload.samples)
        ]
        result = fit_project_factor(samples, max_distortion_ppm=payload.max_distortion_ppm)
        saved = save_scale_solution(
            p.db,
            payload.name,
            result,
            [x.model_dump() for x in payload.samples],
            target_crs=payload.target_crs or p.manifest.get("crs", ""),
            settings={"max_distortion_ppm": payload.max_distortion_ppm},
        )
        return {**result, **saved, "professional_review_required": True}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/geodesy/projection-samples")
def geodesy_projection_samples(payload: ProjectionSamplesIn):
    try:
        return {
            "samples": projection_scale_samples(
                payload.target_crs, payload.points, source_crs=payload.source_crs
            )
        }
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/geodesy/project-factors")
def geodesy_project_factors():
    from . import router as context

    return {"solutions": list_scale_solutions(context.require_project().db)}


@router.post("/api/v9/spatial/import")
def spatial_import(payload: SpatialImportIn):
    from . import router as context

    p = context.require_project()
    try:
        return {
            "layers": import_spatial(
                p,
                [Path(x).expanduser().resolve() for x in payload.file_paths],
                Path(__file__).resolve().parents[1],
                role=payload.role,
            )
        }
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/spatial/layers")
def spatial_layers():
    from . import router as context

    return {"layers": list_spatial_layers(context.require_project().db)}


@router.post("/api/v9/field-to-finish")
def field_to_finish(payload: FieldToFinishIn):
    from . import router as context

    p = context.require_project()
    path = Path(payload.file_path).expanduser().resolve()
    try:
        p.import_source(path, "UtilitySync", "Carlson-style coded field data")
        result = build_linework(parse_coded_points(path))
        geo = to_geojson(result)
        out = (
            Path(payload.output_path).expanduser().resolve()
            if payload.output_path
            else p.paths.derived / "UtilitySync" / "field_to_finish.geojson"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(geo, indent=2), encoding="utf-8")
        p.db.audit(
            "UtilitySync",
            "FIELD_TO_FINISH_BUILT",
            object_type="linework",
            object_id=out.name,
            details={
                "line_count": result["line_count"],
                "qc_flags": result["qc_flags"],
                "path": str(out),
            },
        )
        return {**result, "geojson_path": str(out)}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/utility/sync-fieldbook")
def utility_sync(payload: UtilitySyncIn):
    from . import router as context

    p = context.require_project()
    try:
        return sync_fieldbook_results(
            p, context._fieldbook_app_module().runtime.storage.state.results
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))


def _utility_state_structures() -> list[dict]:
    from . import router as context

    state = context._fieldbook_app_module().runtime.storage.state
    return [r.model_dump(mode="json") for r in state.results]


@router.post("/api/v9/utility/recalculate-inverts")
def utility_recalculate_inverts(payload: UtilityInvertIn):
    from . import router as context

    p = context.require_project()
    field_app = context._fieldbook_app_module()
    try:
        from fieldbook_sync.intelligence import refresh_intelligence

        with field_app.runtime.storage.lock:
            field_app.runtime.elevation_is_rim = bool(payload.survey_elevation_is_rim)
            state = field_app.runtime.storage.state
            state.network_edges = refresh_intelligence(
                state.results,
                state.ocr_candidates,
                elevation_is_rim=field_app.runtime.elevation_is_rim,
                network_max_distance=field_app.runtime.network_max_distance,
                network_bearing_tolerance=field_app.runtime.network_bearing_tolerance,
            )
            saved = field_app.runtime.storage.load_settings()
            saved["elevation_is_rim"] = field_app.runtime.elevation_is_rim
            field_app.runtime.storage.save_settings(saved)
            field_app.runtime.storage.save()
        sync = sync_fieldbook_results(p, state.results)
        p.db.audit(
            "UtilitySync",
            "INVERTS_RECALCULATED",
            details={
                "survey_elevation_is_rim": field_app.runtime.elevation_is_rim,
                "structure_count": len(state.results),
            },
        )
        return {
            "ok": True,
            "survey_elevation_is_rim": field_app.runtime.elevation_is_rim,
            "structure_count": len(state.results),
            "sync": sync,
        }
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/utility/analyze")
def utility_analyze(payload: UtilityAnalyzeIn):
    from . import router as context

    p = context.require_project()
    state = context._fieldbook_app_module().runtime.storage.state
    structures = [r.model_dump(mode="json") for r in state.results]
    edges = [e.model_dump(mode="json") for e in state.network_edges]
    try:
        supported = score_supplemental_gis(
            p,
            edges,
            structures,
            tolerance=payload.tolerance,
            angle_tolerance=payload.angle_tolerance,
        )
        return {
            "connections": supported,
            "grades": pipe_grades(structures, supported),
            "gis_is_reference_only": True,
        }
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/utility/completion")
def utility_completion(match_tolerance: float = 25.0):
    from . import router as context

    try:
        return completion_status(
            context.require_project(), _utility_state_structures(), match_tolerance=match_tolerance
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/utility/completion-kmz")
def utility_completion_kmz(payload: UtilityKmlIn):
    from . import router as context

    p = context.require_project()
    out = (
        Path(payload.output_path).expanduser().resolve()
        if payload.output_path
        else p.paths.exports / "UtilitySync" / "Utility_Completion.kmz"
    )
    try:
        result = export_completion_kmz(
            p, _utility_state_structures(), out, match_tolerance=payload.match_tolerance
        )
        deliverable = register_deliverable(
            p,
            out,
            module="CrewSync",
            kind="utility_completion_kmz",
            metadata={k: v for k, v in result.items() if k != "path"},
        )
        return {**result, "deliverable": deliverable}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/attachments/add")
def attachment_add(payload: AttachmentIn):
    from . import router as context

    try:
        return attach_file(
            context.require_project(),
            Path(payload.file_path),
            module=payload.module,
            object_type=payload.object_type,
            object_id=payload.object_id,
            caption=payload.caption,
            metadata=payload.metadata,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/attachments")
def attachments(object_type: str = "", object_id: str = ""):
    from . import router as context

    return {
        "attachments": list_attachments(
            context.require_project(), object_type=object_type or None, object_id=object_id or None
        )
    }


@router.post("/api/v9/attachments/auto-photos")
def attachments_auto_photos(payload: AutoPhotoIn):
    from . import router as context

    p = context.require_project()
    ids = payload.point_ids or [
        str(r.point_id) for r in context._fieldbook_app_module().runtime.storage.state.results
    ]
    try:
        return auto_attach_photos(p, Path(payload.folder_path), ids)
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/reports/control-pdf")
def report_control_pdf(prepared_by: str = ""):
    from . import router as context

    p = context.require_project()
    out = p.paths.reports / f"{safe_name(p.manifest.get('name', 'Survey'))}_Control_Report.pdf"
    try:
        return control_report(p, out, prepared_by=prepared_by)
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/reports/survey-pdf")
def report_survey_pdf(payload: SurveyReportIn):
    from . import router as context

    p = context.require_project()
    out = (
        Path(payload.output_path).expanduser().resolve()
        if payload.output_path
        else p.paths.reports / f"{safe_name(p.manifest.get('name', 'Survey'))}_Survey_Report.pdf"
    )
    try:
        return project_report(
            p,
            out,
            title=payload.title,
            prepared_by=payload.prepared_by,
            project_number=payload.project_number,
            client=payload.client,
            scope=payload.scope,
            methodology=payload.methodology,
            findings=payload.findings,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/reports/fieldbook-pdf")
def report_fieldbook_pdf(payload: AnnotatedFieldbookIn):
    from . import router as context

    p = context.require_project()
    out = (
        Path(payload.output_path).expanduser().resolve()
        if payload.output_path
        else p.paths.reports / "Annotated_Field_Book.pdf"
    )
    try:
        from fieldbook_sync.annotated_pdf import export_annotated_fieldbook_pdf

        export_annotated_fieldbook_pdf(context._fieldbook_app_module().runtime.storage.state, out)
        return register_deliverable(
            p,
            out,
            module="FieldBookSync",
            kind="annotated_fieldbook_pdf",
            metadata={"dip_notes": True, "pipe_notes": True},
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/deliverables")
def deliverables():
    from . import router as context

    return {"deliverables": list_deliverables(context.require_project())}


@router.get("/api/v9/notifications/policy")
def notification_policy_get():
    from . import router as context

    return load_notification_policy(context.require_project())


@router.post("/api/v9/notifications/policy")
def notification_policy_save(payload: NotificationPolicyIn):
    from . import router as context

    try:
        return save_notification_policy(context.require_project(), payload.model_dump())
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/notifications/email")
def notification_email(payload: EmailNotificationIn):
    from . import router as context

    p = context.require_project()
    items = list_deliverables(p, 1000)
    item = next((x for x in items if x.get("deliverable_id") == payload.deliverable_id), None)
    if not item:
        raise HTTPException(404, "Deliverable was not found.")
    try:
        return send_deliverable_notification(
            p,
            item,
            recipients=payload.recipients,
            smtp_host=payload.smtp_host,
            smtp_port=payload.smtp_port,
            smtp_user=payload.smtp_user,
            from_address=payload.from_address,
            subject=payload.subject,
            message=payload.message,
            use_tls=payload.use_tls,
            attach_file=payload.attach_file,
            password=payload.password,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/notifications")
def notifications():
    from . import router as context

    return {"notifications": list_notifications(context.require_project())}


@router.get("/api/v9/trimble/status")
def trimble_status():
    return trimble_runtime_status()


@router.post("/api/v9/trimble/job-import")
def trimble_job_import(payload: TrimbleJobImportIn):
    from . import router as context

    p = context.require_project()
    source_path = Path(payload.file_path).expanduser().resolve()
    if not source_path.is_file():
        raise HTTPException(400, "Trimble JOB/JXL file was not found.")
    if source_path.suffix.lower() not in {".job", ".jxl", ".xml"}:
        raise HTTPException(400, "Select a Trimble Access .job or JobXML .jxl file.")
    try:
        src = p.import_source(
            source_path, "GISSync", "Original Trimble Access JOB/JobXML field data"
        )
        work = p.paths.derived / "GISSync" / "Trimble" / uuid4().hex
        work.mkdir(parents=True, exist_ok=True)
        immutable_source = Path(src["stored_path"])
        if not immutable_source.is_absolute():
            immutable_source = (p.paths.root / immutable_source).resolve()
        jxl_path, conversion = prepare_jobxml(immutable_source, work)
        parsed = parse_jobxml_points(jxl_path)
        canonical_jxl = (
            p.paths.derived
            / "GISSync"
            / "Trimble"
            / f"{safe_name(source_path.stem)}_{src['sha256'][:8]}.jxl"
        )
        canonical_jxl.parent.mkdir(parents=True, exist_ok=True)
        if jxl_path.resolve() != canonical_jxl.resolve():
            shutil.copy2(jxl_path, canonical_jxl)
        else:
            canonical_jxl = jxl_path
        imported = 0
        conflicts = []
        invalid = []
        if payload.import_points:
            now = utc_now()
            seen_this_job = set()
            with p.db.connect() as conn:
                existing = {
                    str(r[0])
                    for r in conn.execute(
                        "SELECT DISTINCT point_id FROM canonical_points"
                    ).fetchall()
                }
                for point in parsed.get("points") or []:
                    pid = str(point.get("point_id") or "").strip()
                    if not pid or point.get("northing") is None or point.get("easting") is None:
                        invalid.append(pid or "<blank>")
                        continue
                    if pid in seen_this_job or pid in existing:
                        conflicts.append(pid)
                        continue
                    seen_this_job.add(pid)
                    conn.execute(
                        "INSERT INTO canonical_points(point_uuid,point_id,northing,easting,elevation,description,point_class,source_id,derived_from_json,crs,horizontal_units,vertical_units,review_state,revision,created_utc,modified_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            uuid4().hex,
                            pid,
                            float(point["northing"]),
                            float(point["easting"]),
                            point.get("elevation"),
                            str(point.get("code") or ""),
                            payload.point_class,
                            src["source_id"],
                            json.dumps(
                                [
                                    {
                                        "kind": "TrimbleJobXML",
                                        "path": str(canonical_jxl.relative_to(p.paths.root)),
                                    }
                                ],
                                sort_keys=True,
                            ),
                            p.manifest.get("crs", ""),
                            p.manifest.get("horizontal_units", ""),
                            p.manifest.get("vertical_units", ""),
                            "UNREVIEWED",
                            1,
                            now,
                            now,
                        ),
                    )
                    imported += 1
        result = {
            "ok": True,
            "source_id": src["source_id"],
            "original_file": str(source_path),
            "stored_source": str(immutable_source),
            "jobxml_path": str(canonical_jxl),
            "conversion": conversion,
            "metadata": parsed.get("metadata") or {},
            "point_records": len(parsed.get("points") or []),
            "canonical_points_imported": imported,
            "point_id_conflicts": sorted(set(conflicts)),
            "invalid_point_records": invalid,
            "raw_observations_preserved": True,
            "note": "Original Trimble JOB is preserved as source evidence; JobXML is a derived readable representation. Existing PointIDs are never overwritten.",
        }
        p.db.audit(
            "GISSync",
            "TRIMBLE_JOB_IMPORTED",
            object_type="source",
            object_id=src["source_id"],
            details={
                "original_name": source_path.name,
                "jobxml_path": str(canonical_jxl),
                "point_records": result["point_records"],
                "canonical_points_imported": imported,
                "conflict_count": len(set(conflicts)),
                "conversion": conversion,
            },
        )
        return result
    except TrimbleJobError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/cloud/trimble/projects")
def cloud_trimble_projects(payload: TrimbleProjectsIn):
    try:
        return {"projects": trimble_list_projects(payload.access_token), "token_persisted": False}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/cloud/import")
def cloud_import(payload: CloudImportIn):
    from . import router as context

    try:
        return import_cloud_file(
            context.require_project(),
            provider=payload.provider,
            url=payload.url,
            access_token=payload.access_token,
            filename=payload.filename,
            module=payload.module,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/cloud/history")
def cloud_history():
    from . import router as context

    return {"history": list_sync_log(context.require_project())}
