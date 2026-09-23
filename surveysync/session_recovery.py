from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .audit import utc_now
from .continuity import list_snapshots, restore_snapshot
from .project import SurveyProject


def state_path(config_root: str | Path) -> Path:
    root = Path(config_root) / "support"
    root.mkdir(parents=True, exist_ok=True)
    return root / "session_state.json"


def _read(config_root: str | Path) -> dict[str, Any]:
    path = state_path(config_root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(config_root: str | Path, data: dict[str, Any]) -> None:
    path = state_path(config_root)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def begin_session(config_root: str | Path) -> dict[str, Any]:
    prior = _read(config_root)
    previous_unclean: dict[str, Any] | None = None
    if prior.get("active") is True:
        previous_unclean = {
            "session_id": str(prior.get("session_id") or ""),
            "started_utc": str(prior.get("started_utc") or ""),
            "last_seen_utc": str(prior.get("last_seen_utc") or ""),
            "project_path": str(prior.get("project_path") or ""),
        }
    elif isinstance(prior.get("previous_unclean"), dict):
        previous_unclean = dict(prior["previous_unclean"])

    current = {
        "session_id": uuid4().hex,
        "started_utc": utc_now(),
        "last_seen_utc": utc_now(),
        "active": True,
        "clean_exit": False,
        "project_path": "",
        "previous_unclean": previous_unclean,
        "recovery_notice_dismissed": bool(prior.get("recovery_notice_dismissed", False))
        if previous_unclean
        else False,
    }
    if previous_unclean and previous_unclean != prior.get("previous_unclean"):
        current["recovery_notice_dismissed"] = False
    _write(config_root, current)
    return current


def set_project(config_root: str | Path, project_path: str | Path | None) -> dict[str, Any]:
    state = _read(config_root)
    if not state:
        return {}
    state["project_path"] = str(Path(project_path).expanduser().resolve()) if project_path else ""
    state["last_seen_utc"] = utc_now()
    _write(config_root, state)
    return state


def heartbeat(config_root: str | Path) -> dict[str, Any]:
    state = _read(config_root)
    if not state:
        return {}
    state["last_seen_utc"] = utc_now()
    _write(config_root, state)
    return state


def end_session(config_root: str | Path) -> dict[str, Any]:
    state = _read(config_root)
    if not state:
        return {}
    state["active"] = False
    state["clean_exit"] = True
    state["ended_utc"] = utc_now()
    state["last_seen_utc"] = utc_now()
    _write(config_root, state)
    return state


def dismiss_recovery_notice(config_root: str | Path) -> dict[str, Any]:
    state = _read(config_root)
    if not state:
        return {}
    state["recovery_notice_dismissed"] = True
    state["recovery_notice_dismissed_utc"] = utc_now()
    _write(config_root, state)
    return state


def recovery_summary(
    config_root: str | Path, project: SurveyProject | None
) -> dict[str, Any]:
    state = _read(config_root)
    prior = state.get("previous_unclean")
    prior = dict(prior) if isinstance(prior, dict) else None
    current_project = str(project.paths.root.resolve()) if project else ""
    prior_project = str(prior.get("project_path") or "") if prior else ""
    same_project = bool(current_project and prior_project and current_project == prior_project)
    latest = None
    if project:
        recovery = [
            item
            for item in list_snapshots(project)
            if item.get("kind") == "recovery" and item.get("exists")
        ]
        latest = recovery[0] if recovery else None
    return {
        "unclean_shutdown_detected": bool(
            prior and not state.get("recovery_notice_dismissed", False)
        ),
        "previous_session": prior,
        "current_project": current_project,
        "previous_project_matches_current": same_project,
        "latest_recovery_snapshot": latest,
        "restore_available": bool(same_project and latest),
        "active_session": bool(state.get("active")),
        "session_started_utc": str(state.get("started_utc") or ""),
    }


def restore_latest_recovery(
    config_root: str | Path, project: SurveyProject
) -> dict[str, Any]:
    summary = recovery_summary(config_root, project)
    if not summary["restore_available"]:
        raise ValueError(
            "No recovery snapshot is available for the project from the interrupted session."
        )
    latest = summary["latest_recovery_snapshot"]
    result = restore_snapshot(project, str(latest["snapshot_id"]))
    state = _read(config_root)
    state["recovery_notice_dismissed"] = True
    state["recovered_utc"] = utc_now()
    state["recovered_snapshot_id"] = str(latest["snapshot_id"])
    _write(config_root, state)
    return result
