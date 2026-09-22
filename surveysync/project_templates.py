from __future__ import annotations

from copy import deepcopy

PROJECT_TEMPLATES = {
    "standard": {
        "id": "standard", "name": "Standard Survey", "description": "General SurveySync project with all modules available.",
        "enabled_modules": None,
        "qa_overrides": {},
    },
    "edsi_engineering_topo": {
        "id": "edsi_engineering_topo", "name": "EDSI - Engineering / Topo", "description": "Engineering/topographic project with strict point integrity and review checks.",
        "enabled_modules": ["FieldBookSync","UtilitySync","ControlSync","TopoSync","COGOSync","GISSync","ReportSync","QASync","CrewSync"],
        "qa_overrides": {"duplicate_point_ids": {"severity":"ERROR","max_allowed":0}, "missing_point_coordinates": {"severity":"ERROR","max_allowed":0}},
    },
    "boundary": {
        "id": "boundary", "name": "Boundary Survey", "description": "Boundary/record survey project with COGO, GIS, QA and reporting enabled.",
        "enabled_modules": ["ControlSync","COGOSync","BoundarySync","GISSync","ReportSync","QASync","CrewSync"],
        "qa_overrides": {"duplicate_point_ids": {"severity":"ERROR","max_allowed":0}},
    },
    "sewer_utility": {
        "id": "sewer_utility", "name": "Sewer / Utility", "description": "Utility field-book, structures, dips/inverts, GIS and reporting workflow.",
        "enabled_modules": ["FieldBookSync","UtilitySync","ControlSync","TopoSync","GISSync","ReportSync","QASync","CrewSync"],
        "qa_overrides": {"missing_elevations": {"severity":"WARN","max_ratio":0.10}},
    },
    "control_network": {
        "id": "control_network", "name": "Control Network", "description": "Control, leveling, traverse and QA-focused project.",
        "enabled_modules": ["ControlSync","COGOSync","GISSync","ReportSync","QASync","CrewSync"],
        "qa_overrides": {"control_failures": {"severity":"ERROR","max_allowed":0}, "require_crs": {"severity":"WARN"}},
    },
    "construction_staking": {
        "id": "construction_staking", "name": "Construction Staking", "description": "Control, topo, COGO, QA and crew-delivery project.",
        "enabled_modules": ["ControlSync","TopoSync","COGOSync","GISSync","ReportSync","QASync","CrewSync"],
        "qa_overrides": {"duplicate_point_ids": {"severity":"ERROR","max_allowed":0}, "unreviewed_points": {"severity":"WARN","max_allowed":0}},
    },
}


def get_template(template_id: str | None) -> dict:
    key = str(template_id or "standard").strip().lower()
    if key not in PROJECT_TEMPLATES:
        raise ValueError(f"Unknown project template: {template_id}")
    return deepcopy(PROJECT_TEMPLATES[key])


def list_templates() -> list[dict]:
    return [deepcopy(PROJECT_TEMPLATES[k]) for k in PROJECT_TEMPLATES]
