"""Immutable local TopoSync review records with source hashes and project audit entries."""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from ..audit import utc_now
from ..project import SurveyProject


def workspace() -> tuple[Path, SurveyProject | None]:
    from .. import router as context

    with context.project_lock:
        project = context.current_project
        root = (
            project.paths.module_root / "TopoSync" / "RodHeightQC"
            if project
            else context.config_store.root / "topo_qc"
        )
        root.mkdir(parents=True, exist_ok=True)
        return root, project


def record_path(root: Path, record_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", record_id):
        raise ValueError("Invalid TopoSync record ID.")
    return root / f"{record_id}.json"


def save_record(root: Path, data: dict) -> str:
    record_id = uuid4().hex
    path = record_path(root, record_id)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(
            {**data, "record_id": record_id, "created_utc": utc_now()}, handle, allow_nan=False
        )
    return record_id


def load_record(root: Path, record_id: str, kind: str) -> dict:
    path = record_path(root, record_id)
    if not path.is_file():
        raise ValueError(
            "Review record is not in this workspace. Reopen its project or load the source again."
        )
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("kind") != kind:
        raise ValueError("Wrong TopoSync record type.")
    return result
