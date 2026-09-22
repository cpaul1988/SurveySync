"""TopoSync standalone point-file review endpoints."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Literal
from zipfile import BadZipFile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .codes import CodeRule, default_rules
from .detection import DetectionSettings, analyze
from .exports import candidate_report_csv, reviewed_copy_csv
from .imports import parse_code_file, parse_points, survey_preview
from .storage import load_record, save_record, workspace

router = APIRouter(prefix="/api/v9/topo", tags=["TopoSync"])
MAX_BYTES = 30 * 1024 * 1024


class AnalyzeIn(BaseModel):
    source_id: str
    mapping: dict[str, str]
    rules: list[CodeRule] = Field(max_length=5000)
    settings: DetectionSettings = Field(default_factory=DetectionSettings)


class CorrectedCopyIn(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=5000)
    review_reason: str = Field(min_length=3, max_length=2000)
    confirmed: bool = False


async def _file_bytes(file: UploadFile) -> bytes:
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(
            413, "File exceeds the 30 MiB review limit. Split by acquisition session."
        )
    return data


@router.get("/code-rules")
def code_rules() -> dict:
    root, _ = workspace()
    profile = root / "code_rules.json"
    rules = (
        json.loads(profile.read_text(encoding="utf-8"))
        if profile.is_file()
        else [r.model_dump() for r in default_rules()]
    )
    return {
        "rules": rules,
        "roles": [
            "surface",
            "discontinuity",
            "ditch",
            "creek",
            "structure",
            "support",
            "setup",
            "unknown",
        ],
    }


@router.post("/code-rules/import")
async def import_code_rules(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".txt", ".tsv", ".xlsx"}:
        raise HTTPException(400, "Upload a CSV, TXT, TSV or XLSX code list.")
    data = await _file_bytes(file)
    try:
        with tempfile.TemporaryDirectory(prefix="surveysync-codes-") as folder:
            path = Path(folder) / ("codes" + suffix)
            path.write_bytes(data)
            rules = parse_code_file(path)
        return {
            "rules": [r.model_dump() for r in rules],
            "review_required": True,
            "message": "Description-based suggestions require review. Unknown codes remain unclassified.",
        }
    except (ValueError, UnicodeError, OSError, IndexError, BadZipFile) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/survey/preview")
async def preview_survey(
    file: UploadFile = File(...), header: Literal["auto", "yes", "no"] = Form("auto")
) -> dict:
    if Path(file.filename or "").suffix.lower() not in {".csv", ".txt", ".tsv", ".pnezd", ".asc"}:
        raise HTTPException(400, "Upload a delimited CSV/TXT/TSV/PNEZD survey export.")
    data = await _file_bytes(file)
    try:
        text = data.decode("utf-8-sig")
        scan = survey_preview(text, None if header == "auto" else header == "yes")
        root, project = workspace()
        source_id = save_record(
            root,
            {
                "kind": "source",
                "source_name": Path(file.filename or "survey.csv").name,
                "source_sha256": hashlib.sha256(data).hexdigest(),
                "original_bytes_base64": base64.b64encode(data).decode("ascii"),
                "source_text": text,
                "scan": scan,
            },
        )
        if project:
            project.db.audit(
                "TopoSync",
                "ROD_QC_SOURCE_LOADED",
                object_id=source_id,
                details={"sha256": hashlib.sha256(data).hexdigest(), "rows": scan["row_count"]},
            )
        return {
            **{k: v for k, v in scan.items() if k != "rows"},
            "source_id": source_id,
            "project": project.manifest.get("name") if project else None,
        }
    except (ValueError, UnicodeError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/analyze")
def analyze_survey(payload: AnalyzeIn) -> dict:
    try:
        root, project = workspace()
        source = load_record(root, payload.source_id, "source")
        points = parse_points(source["scan"], payload.mapping)
        result = analyze(points, payload.rules, payload.settings)
        report = {
            "kind": "analysis",
            "source_id": payload.source_id,
            "source_name": source["source_name"],
            "source_sha256": source["source_sha256"],
            "mapping": payload.mapping,
            "rules": [r.model_dump() for r in payload.rules],
            "points": [p.to_dict() for p in points],
            "algorithm_version": "rod-height-chain-v1",
            "result": result,
        }
        run_id = save_record(root, report)
        if project:
            project.db.audit(
                "TopoSync",
                "ROD_HEIGHT_QC_ANALYZED",
                object_id=run_id,
                details={
                    "source_id": payload.source_id,
                    "candidates": len(result["candidates"]),
                    "settings": payload.settings.model_dump(),
                },
            )
        return {
            "run_id": run_id,
            "source_name": source["source_name"],
            "source_sha256": source["source_sha256"],
            **result,
        }
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/runs/{run_id}/export")
def export_report(run_id: str, format: Literal["csv", "json"] = "csv") -> Response:
    try:
        root, _ = workspace()
        report = load_record(root, run_id, "analysis")
        content = (
            candidate_report_csv(report)
            if format == "csv"
            else json.dumps({k: v for k, v in report.items() if k != "points"}, indent=2)
        )
        return Response(
            content,
            media_type="text/csv" if format == "csv" else "application/json",
            headers={
                "Content-Disposition": f'attachment; filename="Rod_Height_QC_{run_id[:8]}.{format}"'
            },
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/runs/{run_id}/corrected-copy")
def export_corrected_copy(run_id: str, payload: CorrectedCopyIn) -> Response:
    if not payload.confirmed:
        raise HTTPException(400, "Explicit review confirmation is required.")
    try:
        root, project = workspace()
        report = load_record(root, run_id, "analysis")
        content, audit = reviewed_copy_csv(report, payload.candidate_ids, payload.review_reason)
        save_record(root, {"kind": "export_audit", "run_id": run_id, **audit})
        if project:
            project.db.audit(
                "TopoSync", "ROD_QC_REVIEWED_COPY_EXPORTED", object_id=run_id, details=audit
            )
        return Response(
            content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="Reviewed_Rod_Height_Copy_{run_id[:8]}.csv"'
            },
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/code-rules/save")
def save_code_rules(rules: list[CodeRule]) -> dict:
    if not rules or len(rules) > 5000:
        raise HTTPException(400, "Save between 1 and 5,000 code rules.")
    normalized = [r.model_copy(update={"code": r.code.strip().upper()}) for r in rules]
    if any(not r.code for r in normalized) or len({r.code for r in normalized}) != len(normalized):
        raise HTTPException(400, "Codes must be nonempty and unique.")
    root, _ = workspace()
    temporary = root / "code_rules.pending"
    temporary.write_text(
        json.dumps([r.model_dump() for r in normalized], indent=2), encoding="utf-8"
    )
    temporary.replace(root / "code_rules.json")
    return {"saved": len(normalized)}


class SavedExportIn(BaseModel):
    kind: Literal["csv", "json", "corrected"]
    candidate_ids: list[str] = Field(default_factory=list, max_length=5000)
    review_reason: str = Field(default="", max_length=2000)
    confirmed: bool = False


@router.post("/runs/{run_id}/save-export")
def save_export(run_id: str, payload: SavedExportIn) -> dict:
    """Desktop-safe export to a new file; never overwrites an existing survey."""
    from uuid import uuid4

    try:
        root, project = workspace()
        report = load_record(root, run_id, "analysis")
        if payload.kind == "corrected":
            if not payload.confirmed:
                raise ValueError("Explicit review confirmation is required.")
            content, audit = reviewed_copy_csv(report, payload.candidate_ids, payload.review_reason)
        elif payload.kind == "csv":
            content, audit = candidate_report_csv(report), None
        else:
            content, audit = (
                json.dumps({k: v for k, v in report.items() if k != "points"}, indent=2),
                None,
            )
        folder = root / "exports"
        folder.mkdir(exist_ok=True)
        suffix = "json" if payload.kind == "json" else "csv"
        path = folder / f"Rod_QC_{payload.kind}_{uuid4().hex[:12]}.{suffix}"
        with path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(content)
        if audit:
            save_record(
                root, {"kind": "export_audit", "run_id": run_id, "output_path": str(path), **audit}
            )
            if project:
                project.db.audit(
                    "TopoSync", "ROD_QC_REVIEWED_COPY_EXPORTED", object_id=run_id, details=audit
                )
        return {"path": str(path), "folder": str(folder), "source_modified": False}
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
