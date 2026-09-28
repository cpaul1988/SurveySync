"""Project-scoped declarative SurveySync workflow engine.

The engine is intentionally small and auditable. Safe actions may run automatically.
Actions that can issue deliverables or contact people always pause for explicit human
approval before execution.
"""

from __future__ import annotations

import copy
import threading
from functools import wraps
import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from .audit import utc_now
from .delivery import build_deliverable_package, export_points
from .notifications import load_policy, send_deliverable_notification
from .project import SurveyProject, safe_name
from .qa import run_project_qa
from .reporting import list_deliverables

SUPPORTED_TRIGGERS = {
    "manual",
    "project_opened",
    "source_imported",
    "qa_completed",
    "export_completed",
    "deliverable_created",
}

ACTION_POLICIES: dict[str, dict[str, Any]] = {
    "run_qa": {
        "requires_approval": False,
        "description": "Run the SurveySync Project Health Check.",
    },
    "run_export_profile": {
        "requires_approval": False,
        "description": "Run a saved export profile and create derived output files.",
    },
    "create_review_item": {
        "requires_approval": False,
        "description": "Create a QASync review item without altering survey evidence.",
    },
    "build_deliverable": {
        "requires_approval": True,
        "description": (
            "Build a FINAL deliverable package. Existing notification policy may "
            "send a configured stakeholder email when the deliverable is registered."
        ),
    },
    "send_notification": {
        "requires_approval": True,
        "description": "Send a configured stakeholder email for a deliverable.",
    },
}


class WorkflowError(RuntimeError):
    pass


# One lock serializes definition edits and approvals in this application process.
# It is not a distributed lock for simultaneously opened network-share projects.
_ENGINE_LOCK = threading.RLock()


def serialized(function):
    @wraps(function)
    def call(*args, **kwargs):
        with _ENGINE_LOCK:
            return function(*args, **kwargs)
    return call


def _workflow_path(project: SurveyProject) -> Path:
    return project.paths.root / ".surveysync" / "workflows.yaml"


def _runs_dir(project: SurveyProject) -> Path:
    path = project.paths.root / ".surveysync" / "workflow_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_path(project: SurveyProject, run_id: str) -> Path:
    return _runs_dir(project) / f"{safe_name(run_id)}.json"


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def _read_workflow_document(project: SurveyProject) -> dict[str, Any]:
    path = _workflow_path(project)
    if not path.is_file():
        return {"version": 1, "workflows": []}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise WorkflowError(f"Could not read workflow definitions: {exc}") from exc
    if raw is None:
        return {"version": 1, "workflows": []}
    if isinstance(raw, list):
        raw = {"version": 1, "workflows": raw}
    if not isinstance(raw, dict) or not isinstance(raw.get("workflows", []), list):
        raise WorkflowError("Workflow YAML must contain a 'workflows' list.")
    return {"version": int(raw.get("version") or 1), "workflows": list(raw.get("workflows") or [])}


def _write_workflow_document(project: SurveyProject, document: dict[str, Any]) -> None:
    text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    _atomic_text(_workflow_path(project), text)


def _normalize_action(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise WorkflowError(f"Workflow action {index + 1} must be an object.")
    action_type = str(raw.get("type") or "").strip().lower()
    if action_type not in ACTION_POLICIES:
        raise WorkflowError(
            f"Workflow action {index + 1} has unsupported type {action_type or '(blank)'}."
        )
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        raise WorkflowError(f"Workflow action {index + 1} params must be an object.")
    try:
        encoded = json.dumps(params, allow_nan=False)
        if len(encoded.encode("utf-8")) > 65536:
            raise ValueError("Action parameters exceed 64 KB")
        params = json.loads(encoded)
    except (TypeError, ValueError, RecursionError) as exc:
        raise WorkflowError(f"Action parameters must be bounded finite JSON: {exc}") from exc
    policy = ACTION_POLICIES[action_type]
    return {
        "type": action_type,
        "params": dict(params),
        "requires_approval": bool(policy["requires_approval"]),
    }


def normalize_workflow(spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise WorkflowError("Each workflow must be an object.")
    if "enabled" in spec and type(spec["enabled"]) is not bool:
        raise WorkflowError("Workflow enabled must be true or false.")
    name = str(spec.get("name") or "").strip()
    if not name:
        raise WorkflowError("Workflow name is required.")
    trigger = str(spec.get("trigger") or "manual").strip().lower()
    if trigger not in SUPPORTED_TRIGGERS:
        raise WorkflowError(
            "Workflow trigger must be one of: " + ", ".join(sorted(SUPPORTED_TRIGGERS))
        )
    actions_raw = spec.get("actions") or []
    if not isinstance(actions_raw, list) or not actions_raw:
        raise WorkflowError("Workflow requires at least one action.")
    if len(actions_raw) > 100:
        raise WorkflowError("At most 100 actions are supported per workflow.")
    workflow_id = str(spec.get("workflow_id") or spec.get("id") or uuid4().hex).strip()
    if not workflow_id:
        raise WorkflowError("Workflow ID is invalid.")
    return {
        "workflow_id": safe_name(workflow_id),
        "name": name,
        "enabled": bool(spec.get("enabled", True)),
        "trigger": trigger,
        "description": str(spec.get("description") or "").strip(),
        "actions": [_normalize_action(action, index) for index, action in enumerate(actions_raw)],
    }


def list_workflows(project: SurveyProject) -> list[dict[str, Any]]:
    document = _read_workflow_document(project)
    return [normalize_workflow(dict(item)) for item in document["workflows"]]


@serialized
def save_workflow(project: SurveyProject, spec: dict[str, Any]) -> dict[str, Any]:
    workflow = normalize_workflow(spec)
    document = _read_workflow_document(project)
    items = []
    replaced = False
    for raw in document["workflows"]:
        current = normalize_workflow(dict(raw))
        if current["workflow_id"] == workflow["workflow_id"]:
            items.append(workflow)
            replaced = True
        else:
            items.append(current)
    if not replaced:
        items.append(workflow)
    document["version"] = 1
    document["workflows"] = items
    _write_workflow_document(project, document)
    project.db.audit(
        "Core",
        "WORKFLOW_SAVED",
        object_type="workflow",
        object_id=workflow["workflow_id"],
        details={
            "name": workflow["name"],
            "trigger": workflow["trigger"],
            "enabled": workflow["enabled"],
            "action_types": [action["type"] for action in workflow["actions"]],
        },
    )
    return workflow


@serialized
def delete_workflow(project: SurveyProject, workflow_id: str) -> dict[str, Any]:
    target = safe_name(workflow_id)
    document = _read_workflow_document(project)
    before = len(document["workflows"])
    kept = []
    for raw in document["workflows"]:
        current = normalize_workflow(dict(raw))
        if current["workflow_id"] != target:
            kept.append(current)
    if len(kept) == before:
        raise WorkflowError("Workflow was not found.")
    document["workflows"] = kept
    _write_workflow_document(project, document)
    project.db.audit(
        "Core",
        "WORKFLOW_DELETED",
        object_type="workflow",
        object_id=target,
    )
    return {"workflow_id": target, "deleted": True}


def export_workflows_yaml(project: SurveyProject) -> str:
    document = {
        "version": 1,
        "workflows": list_workflows(project),
    }
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


@serialized
def import_workflows_yaml(project: SurveyProject, yaml_text: str) -> dict[str, Any]:
    if not isinstance(yaml_text, str) or len(yaml_text.encode("utf-8")) > 1024 * 1024:
        raise WorkflowError("Workflow YAML must be text no larger than 1 MB.")
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise WorkflowError(f"Workflow YAML is invalid: {exc}") from exc
    if isinstance(raw, list):
        workflows = raw
    elif isinstance(raw, dict):
        workflows = raw.get("workflows") or []
    else:
        raise WorkflowError("Workflow YAML must be a list or contain a 'workflows' list.")
    if not isinstance(workflows, list):
        raise WorkflowError("Workflow YAML 'workflows' value must be a list.")
    if len(workflows) > 200:
        raise WorkflowError("At most 200 workflows are supported per project.")
    normalized = [normalize_workflow(item) for item in workflows]
    if len({w["workflow_id"] for w in normalized}) != len(normalized):
        raise WorkflowError("Workflow IDs must be unique.")
    _write_workflow_document(project, {"version": 1, "workflows": normalized})
    project.db.audit(
        "Core",
        "WORKFLOWS_IMPORTED",
        object_type="workflow_collection",
        object_id=str(project.manifest.get("project_id") or ""),
        details={"count": len(normalized)},
    )
    return {"count": len(normalized), "workflows": normalized}


def _load_run(project: SurveyProject, run_id: str) -> dict[str, Any]:
    path = _run_path(project, run_id)
    if not path.is_file():
        raise WorkflowError("Workflow run was not found.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"Workflow run state could not be read: {exc}") from exc
    if not isinstance(raw, dict):
        raise WorkflowError("Workflow run state is invalid.")
    return raw


def _save_run(project: SurveyProject, state: dict[str, Any]) -> None:
    state["updated_utc"] = utc_now()
    _atomic_text(
        _run_path(project, str(state["run_id"])),
        json.dumps(state, indent=2, sort_keys=True, default=str),
    )


def list_runs(project: SurveyProject, limit: int = 100) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(
        _runs_dir(project).glob("*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[: max(1, min(int(limit), 500))]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict):
            rows.append(raw)
    return rows


def _workflow_by_id(project: SurveyProject, workflow_id: str) -> dict[str, Any]:
    target = safe_name(workflow_id)
    for workflow in list_workflows(project):
        if workflow["workflow_id"] == target:
            return workflow
    raise WorkflowError("Workflow was not found.")


def _latest_deliverable(project: SurveyProject, deliverable_id: str = "") -> dict[str, Any]:
    rows = list_deliverables(project, 100)
    if deliverable_id:
        for row in rows:
            if str(row.get("deliverable_id") or "") == str(deliverable_id):
                return row
        raise WorkflowError("Requested deliverable was not found.")
    if not rows:
        raise WorkflowError("No deliverable is available for notification.")
    return rows[0]


def _execute_action(
    project: SurveyProject,
    action: dict[str, Any],
    *,
    context: dict[str, Any],
) -> dict[str, Any]:
    action_type = str(action["type"])
    params = dict(action.get("params") or {})

    if action_type == "run_qa":
        result = run_project_qa(project)
        return {
            "action": action_type,
            "status": result.get("status"),
            "readiness": result.get("readiness"),
            "errors": result.get("errors"),
            "warnings": result.get("warnings"),
        }

    if action_type == "run_export_profile":
        profile_id = str(params.get("profile_id") or "survey_points")
        result = export_points(project, profile_id)
        return {
            "action": action_type,
            "profile_id": profile_id,
            "folder": result.get("folder"),
            "files": result.get("files"),
            "point_count": result.get("point_count"),
        }

    if action_type == "create_review_item":
        code = str(params.get("code") or "WORKFLOW_REVIEW").strip().upper()
        message = str(params.get("message") or "Workflow requested human review.").strip()
        object_id = str(params.get("object_id") or context.get("object_id") or "")
        issue_id = project.db.add_qa(
            "QASync",
            "WARN",
            code,
            message,
            object_id=object_id,
            details={
                "workflow_context": context,
                "guidance": str(
                    params.get("guidance")
                    or "Review the workflow context and supporting project evidence."
                ),
            },
        )
        return {"action": action_type, "issue_id": issue_id, "code": code}

    if action_type == "build_deliverable":
        profile_id = str(params.get("profile_id") or "client_deliverable")
        label = str(params.get("label") or context.get("label") or "Workflow deliverable")
        result = build_deliverable_package(project, profile_id=profile_id, label=label)
        return {
            "action": action_type,
            "deliverable_id": result.get("deliverable_id"),
            "filename": result.get("filename"),
            "sha256": result.get("sha256"),
            "notification": result.get("notification"),
        }

    if action_type == "send_notification":
        deliverable = _latest_deliverable(
            project, str(params.get("deliverable_id") or context.get("deliverable_id") or "")
        )
        policy = load_policy(project)
        if not policy.get("enabled"):
            raise WorkflowError("Notification policy is disabled.")
        if not policy.get("smtp_host") or not policy.get("recipients"):
            raise WorkflowError("Notification policy is incomplete.")
        result = send_deliverable_notification(
            project,
            deliverable,
            recipients=list(policy.get("recipients") or []),
            smtp_host=str(policy.get("smtp_host") or ""),
            smtp_port=int(policy.get("smtp_port") or 587),
            smtp_user=str(policy.get("smtp_user") or ""),
            from_address=str(policy.get("from_address") or ""),
            subject=str(params.get("subject") or ""),
            message=str(params.get("message") or ""),
            use_tls=bool(policy.get("use_tls", True)),
            attach_file=bool(policy.get("attach_file", False)),
        )
        return {"action": action_type, **result}

    raise WorkflowError(f"Unsupported workflow action: {action_type}")


def _continue_run(
    project: SurveyProject,
    state: dict[str, Any],
    *,
    approved_index: int | None = None,
) -> dict[str, Any]:
    workflow = _workflow_by_id(project, str(state["workflow_id"]))
    # Never approve an edited definition in place of the action the user reviewed.
    if state.get("workflow_snapshot") != workflow:
        raise WorkflowError("Workflow changed after this run began. Reject it and start a new run.")
    actions = workflow["actions"]
    state["status"] = "RUNNING"
    state["pending_action"] = None

    while int(state["next_action_index"]) < len(actions):
        index = int(state["next_action_index"])
        action = actions[index]
        if action["requires_approval"] and approved_index != index:
            state["status"] = "WAITING_APPROVAL"
            state["pending_action"] = {
                "index": index,
                "type": action["type"],
                "params": action.get("params") or {},
                "description": ACTION_POLICIES[action["type"]]["description"],
            }
            _save_run(project, state)
            project.db.audit(
                "Core",
                "WORKFLOW_WAITING_APPROVAL",
                object_type="workflow_run",
                object_id=state["run_id"],
                details={
                    "workflow_id": state["workflow_id"],
                    "action_index": index,
                    "action_type": action["type"],
                },
            )
            return state

        try:
            result = _execute_action(
                project,
                action,
                context=dict(state.get("context") or {}),
            )
        except (WorkflowError, ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
            state["status"] = "FAILED"
            state["error"] = str(exc)
            state["failed_action_index"] = index
            _save_run(project, state)
            project.db.audit(
                "Core",
                "WORKFLOW_FAILED",
                object_type="workflow_run",
                object_id=state["run_id"],
                details={
                    "workflow_id": state["workflow_id"],
                    "action_index": index,
                    "action_type": action["type"],
                    "error": str(exc),
                },
            )
            return state

        state.setdefault("results", []).append(
            {
                "action_index": index,
                "action_type": action["type"],
                "result": result,
                "completed_utc": utc_now(),
            }
        )
        state["next_action_index"] = index + 1
        approved_index = None
        _save_run(project, state)

    state["status"] = "COMPLETED"
    state["completed_utc"] = utc_now()
    state["pending_action"] = None
    _save_run(project, state)
    project.db.audit(
        "Core",
        "WORKFLOW_COMPLETED",
        object_type="workflow_run",
        object_id=state["run_id"],
        details={
            "workflow_id": state["workflow_id"],
            "result_count": len(state.get("results") or []),
        },
    )
    return state


@serialized
def start_workflow(
    project: SurveyProject,
    workflow_id: str,
    *,
    context: dict[str, Any] | None = None,
    trigger_override: str | None = None,
) -> dict[str, Any]:
    workflow = _workflow_by_id(project, workflow_id)
    if not workflow["enabled"]:
        raise WorkflowError("Workflow is disabled.")
    run_id = uuid4().hex
    state = {
        "run_id": run_id,
        "workflow_id": workflow["workflow_id"],
        "workflow_name": workflow["name"],
        "workflow_snapshot": copy.deepcopy(workflow),
        "trigger": trigger_override or workflow["trigger"],
        "status": "QUEUED",
        "next_action_index": 0,
        "context": dict(context or {}),
        "results": [],
        "pending_action": None,
        "error": "",
        "created_utc": utc_now(),
        "updated_utc": utc_now(),
    }
    _save_run(project, state)
    project.db.audit(
        "Core",
        "WORKFLOW_STARTED",
        object_type="workflow_run",
        object_id=run_id,
        details={
            "workflow_id": workflow["workflow_id"],
            "trigger": state["trigger"],
            "context": state["context"],
        },
    )
    return _continue_run(project, state)


@serialized
def approve_run(
    project: SurveyProject,
    run_id: str,
    *,
    approved: bool,
    note: str = "",
) -> dict[str, Any]:
    state = _load_run(project, run_id)
    if state.get("status") != "WAITING_APPROVAL":
        raise WorkflowError("Workflow run is not waiting for approval.")
    pending = state.get("pending_action") or {}
    index = int(pending.get("index", -1))
    if index < 0:
        raise WorkflowError("Workflow run has no valid pending action.")

    if not approved:
        state["status"] = "REJECTED"
        state["approval_note"] = str(note or "")
        state["rejected_utc"] = utc_now()
        state["pending_action"] = None
        _save_run(project, state)
        project.db.audit(
            "Core",
            "WORKFLOW_APPROVAL_REJECTED",
            object_type="workflow_run",
            object_id=run_id,
            details={
                "workflow_id": state["workflow_id"],
                "action_index": index,
                "note": str(note or ""),
            },
        )
        return state

    if state.get("workflow_snapshot") != _workflow_by_id(project, str(state["workflow_id"])):
        raise WorkflowError("Workflow changed after this run began. Reject it and start a new run.")
    state["approval_note"] = str(note or "")
    project.db.audit(
        "Core",
        "WORKFLOW_ACTION_APPROVED",
        object_type="workflow_run",
        object_id=run_id,
        details={
            "workflow_id": state["workflow_id"],
            "action_index": index,
            "action_type": pending.get("type"),
            "note": str(note or ""),
        },
    )
    return _continue_run(project, state, approved_index=index)


def dispatch_trigger(
    project: SurveyProject,
    trigger: str,
    *,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    trigger_name = str(trigger or "").strip().lower()
    if trigger_name not in SUPPORTED_TRIGGERS:
        raise WorkflowError("Unsupported workflow trigger.")
    results = []
    for workflow in list_workflows(project):
        if not workflow["enabled"] or workflow["trigger"] != trigger_name:
            continue
        results.append(
            start_workflow(
                project,
                workflow["workflow_id"],
                context=context,
                trigger_override=trigger_name,
            )
        )
    return results


def engine_status() -> dict[str, Any]:
    return {
        "format_version": 1,
        "storage": "project .surveysync/workflows.yaml",
        "triggers": sorted(SUPPORTED_TRIGGERS),
        "actions": {
            key: {
                "requires_approval": bool(value["requires_approval"]),
                "description": value["description"],
            }
            for key, value in ACTION_POLICIES.items()
        },
        "principle": (
            "Unknown actions fail closed. Deliverable creation and stakeholder "
            "notification require explicit human approval."
        ),
    }
