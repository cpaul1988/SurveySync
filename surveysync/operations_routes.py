from __future__ import annotations
from .api_models import (
    QaRulesIn,
    QaIssueStatusIn,
    StageImportIn,
    CommitStageIn,
    LearnMappingIn,
    SnapshotCreateIn,
    SnapshotRestoreIn,
    CompareFileIn,
    ExportProfileIn,
    ExportRunIn,
    PackageBuildIn,
    BatchIn,
    TaskCancelIn,
)
from pathlib import Path
import sqlite3
from fastapi import APIRouter, HTTPException
from .qa import run_project_qa
from .qa_rules import load_rules as load_qa_rules, save_rules as save_qa_rules
from .staging import stage_import, list_stages, commit_stage, learn_mapping, load_mapping_profiles
from .continuity import create_snapshot, list_snapshots, compare_snapshot, restore_snapshot
from .comparison import compare_point_source
from .delivery import (
    load_profiles as load_export_profiles,
    save_profile as save_export_profile,
    export_points as run_export_profile,
    build_deliverable_package,
)
from .operations import (
    project_timeline,
    review_center,
    explain as explain_item,
    project_map_geojson,
)
from .task_queue import (
    submit as submit_background_task,
    list_tasks as list_background_tasks,
    cancel as cancel_background_task,
)

router = APIRouter()


@router.post("/api/v9/qa/run")
def qa_run():
    from . import router as context

    return run_project_qa(context.require_project())


@router.get("/api/v9/qa/issues")
def qa_issues():
    from . import router as context

    return context.require_project().db.qa_issues()


@router.get("/api/v9/qa/rules")
def qa_rules_get():
    from . import router as context

    return {"rules": load_qa_rules(context.require_project())}


@router.post("/api/v9/qa/rules")
def qa_rules_save(payload: QaRulesIn):
    from . import router as context

    try:
        return {"rules": save_qa_rules(context.require_project(), payload.rules)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/qa/issues/status")
def qa_issue_status(payload: QaIssueStatusIn):
    from . import router as context

    try:
        return context.require_project().db.set_qa_status(payload.issue_id, payload.status)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/import/stage")
def import_stage(payload: StageImportIn):
    from . import router as context

    try:
        return stage_import(
            context.require_project(),
            Path(payload.file_path),
            kind=payload.kind,
            mapping=payload.mapping,
            preview_rows=payload.preview_rows,
        )
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/import/stages")
def import_stages(limit: int = 50):
    from . import router as context

    return {"stages": list_stages(context.require_project(), limit)}


@router.post("/api/v9/import/commit")
def import_commit(payload: CommitStageIn):
    from . import router as context

    try:
        return commit_stage(context.require_project(), payload.stage_id, learn=payload.learn)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/import/mappings")
def import_mappings():
    from . import router as context

    return {"profiles": load_mapping_profiles(context.require_project())}


@router.post("/api/v9/import/mappings")
def import_mapping_learn(payload: LearnMappingIn):
    from . import router as context

    try:
        return learn_mapping(
            context.require_project(), payload.headers, payload.mapping, payload.label
        )
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/timeline")
def timeline(limit: int = 250):
    from . import router as context

    return {"events": project_timeline(context.require_project(), limit)}


@router.post("/api/v9/snapshots")
def snapshot_create(payload: SnapshotCreateIn):
    from . import router as context

    try:
        return create_snapshot(context.require_project(), label=payload.label, kind=payload.kind)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/snapshots")
def snapshots():
    from . import router as context

    return {"snapshots": list_snapshots(context.require_project())}


@router.get("/api/v9/snapshots/compare")
def snapshot_compare(snapshot_id: str):
    from . import router as context

    try:
        return compare_snapshot(context.require_project(), snapshot_id)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/snapshots/restore")
def snapshot_restore(payload: SnapshotRestoreIn):
    from . import router as context

    try:
        return restore_snapshot(context.require_project(), payload.snapshot_id)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/compare/points")
def compare_points(payload: CompareFileIn):
    from . import router as context

    try:
        return compare_point_source(
            context.require_project(),
            Path(payload.file_path),
            horizontal_tolerance=payload.horizontal_tolerance,
            vertical_tolerance=payload.vertical_tolerance,
        )
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/export-profiles")
def export_profiles():
    from . import router as context

    return {"profiles": load_export_profiles(context.require_project())}


@router.post("/api/v9/export-profiles")
def export_profile_save(payload: ExportProfileIn):
    from . import router as context

    try:
        return save_export_profile(context.require_project(), payload.model_dump())
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/export/run")
def export_profile_run(payload: ExportRunIn):
    from . import router as context

    try:
        return run_export_profile(context.require_project(), payload.profile_id)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/deliverable-package")
def deliverable_package(payload: PackageBuildIn):
    from . import router as context

    try:
        return build_deliverable_package(
            context.require_project(), profile_id=payload.profile_id, label=payload.label
        )
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/project-map")
def project_map():
    from . import router as context

    return project_map_geojson(context.require_project())


@router.get("/api/v9/review-center")
def review_items():
    from . import router as context

    return review_center(context.require_project())


@router.get("/api/v9/explain")
def explain(kind: str, object_id: str):
    from . import router as context

    try:
        return explain_item(context.require_project(), kind, object_id)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/v9/tasks")
def tasks(limit: int = 100):
    from . import router as context

    return {"tasks": list_background_tasks(context.require_project(), limit)}


@router.post("/api/v9/tasks/cancel")
def task_cancel(payload: TaskCancelIn):
    from . import router as context

    try:
        return cancel_background_task(context.require_project(), payload.task_id)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/v9/batch")
def batch(payload: BatchIn):
    from . import router as context

    p = context.require_project()
    action = str(payload.action or "stage_points").lower()
    paths = [
        str(Path(x).expanduser().resolve()) for x in payload.file_paths if str(x or "").strip()
    ]
    if action not in {"stage_points", "compare_points", "preflight_package"}:
        raise HTTPException(
            400, "Batch action must be stage_points, compare_points, or preflight_package."
        )

    def work(*, progress, cancelled):
        results = []
        if action == "preflight_package":
            progress(0.15, "Running Project Health Check")
            health = run_project_qa(p)
            if cancelled():
                return {"cancelled": True, "health": health}
            if health.get("errors"):
                return {"health": health, "package": None, "blocked": True}
            progress(0.6, "Building deliverable package")
            package = build_deliverable_package(
                p, profile_id="client_deliverable", label="Batch preflight package"
            )
            return {"health": health, "package": package, "blocked": False}
        total = max(1, len(paths))
        for idx, path in enumerate(paths, 1):
            if cancelled():
                return {"cancelled": True, "results": results}
            progress((idx - 1) / total, f"Processing {Path(path).name}")
            try:
                if action == "stage_points":
                    results.append(
                        {"path": path, "ok": True, "result": stage_import(p, Path(path))}
                    )
                else:
                    results.append(
                        {"path": path, "ok": True, "result": compare_point_source(p, Path(path))}
                    )
            except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
                results.append({"path": path, "ok": False, "error": str(exc)})
        progress(1.0, "Completed")
        return {"results": results, "count": len(results)}

    return submit_background_task(
        p,
        action,
        f"Batch {action.replace('_', ' ')}",
        work,
        payload={"file_paths": paths, "action": action},
    )
