from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path

from .project import SurveyProject

logger = logging.getLogger(__name__)

DEFAULT_RULES = {
    "require_crs": {"enabled": True, "severity": "WARN"},
    "require_horizontal_units": {"enabled": True, "severity": "ERROR"},
    "require_vertical_units": {"enabled": True, "severity": "WARN"},
    "duplicate_point_ids": {"enabled": True, "severity": "ERROR", "max_allowed": 0},
    "missing_point_coordinates": {"enabled": True, "severity": "ERROR", "max_allowed": 0},
    "missing_elevations": {"enabled": True, "severity": "WARN", "max_ratio": 0.25},
    "unreviewed_points": {"enabled": True, "severity": "WARN", "max_allowed": 0},
    "source_integrity": {"enabled": True, "severity": "ERROR"},
    "control_failures": {"enabled": True, "severity": "ERROR", "max_allowed": 0},
    "level_qc_flags": {"enabled": True, "severity": "WARN", "max_allowed": 0},
    "coordinate_sanity": {"enabled": True, "severity": "WARN"},
    "broken_attachments": {"enabled": True, "severity": "WARN", "max_allowed": 0},
    "failed_background_tasks": {"enabled": True, "severity": "WARN", "max_allowed": 0},
    "stale_derived_results": {"enabled": True, "severity": "WARN", "max_allowed": 0},
}


def _path(project: SurveyProject) -> Path:
    return project.paths.db.parent / "qa_rules.json"


def _normalize_rule(rule: dict, default: dict) -> dict:
    out = deepcopy(default)
    if isinstance(rule, dict):
        out.update(rule)
    out["enabled"] = bool(out.get("enabled", True))
    sev = str(out.get("severity") or default.get("severity") or "WARN").upper()
    out["severity"] = sev if sev in {"INFO", "WARN", "ERROR"} else "WARN"
    return out


def load_rules(project: SurveyProject) -> dict:
    rules = deepcopy(DEFAULT_RULES)
    path = _path(project)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if key in rules:
                        rules[key] = _normalize_rule(value, rules[key])
        except Exception:
            logger.warning("Could not load project QA rules from %s; defaults will be used.", path, exc_info=True)
    return rules


def save_rules(project: SurveyProject, incoming: dict) -> dict:
    current = load_rules(project)
    if not isinstance(incoming, dict):
        raise ValueError("QA rules must be an object keyed by rule name.")
    for key, value in incoming.items():
        if key not in current:
            raise ValueError(f"Unknown QA rule: {key}")
        current[key] = _normalize_rule(value, current[key])
    path = _path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    project.db.audit("QASync", "QA_RULES_UPDATED", object_type="project", object_id=project.manifest.get("project_id", ""), details={"rules": current})
    return current
