from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import ResultRecord


BASELINE_SCHEMA = "fieldbook-sync-validation-v1"


def _pipe_signature(pipe: Any) -> tuple:
    diameter = getattr(pipe, "diameter_in", None)
    dip = getattr(pipe, "dip", None)
    azimuth = getattr(pipe, "azimuth_deg", None)
    return (
        None if diameter is None else round(float(diameter), 2),
        None if dip is None else round(float(dip), 3),
        None if azimuth is None else round(float(azimuth) % 360.0, 1),
    )


def result_truth_record(result: ResultRecord) -> dict[str, Any]:
    return {
        "point_id": result.point_id,
        "status": result.status.value,
        "dip_status": result.dip_status.value,
        "pipes": [list(_pipe_signature(p)) for p in result.pipes],
        "review_state": result.review_state.value,
    }


def save_baseline(path: str | Path, *, name: str, project_name: str, results: Iterable[ResultRecord], app_version: str) -> dict[str, Any]:
    path = Path(path)
    records = [result_truth_record(r) for r in results]
    payload = {
        "schema": BASELINE_SCHEMA,
        "name": name,
        "project_name": project_name,
        "app_version": app_version,
        "records": records,
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
    return payload


def load_baseline(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != BASELINE_SCHEMA or not isinstance(data.get("records"), list):
        raise ValueError("Unsupported or corrupt validation baseline.")
    return data


def compare_to_baseline(results: Iterable[ResultRecord], baseline: dict[str, Any]) -> dict[str, Any]:
    current = {r.point_id: result_truth_record(r) for r in results}
    truth = {str(r.get("point_id")): r for r in baseline.get("records", []) if r.get("point_id") is not None}
    truth_ids = set(truth)
    current_ids = set(current)
    shared = truth_ids & current_ids
    missing = sorted(truth_ids - current_ids)
    extra = sorted(current_ids - truth_ids)

    status_matches = sum(1 for pid in shared if current[pid].get("status") == truth[pid].get("status"))
    dip_matches = sum(1 for pid in shared if current[pid].get("dip_status") == truth[pid].get("dip_status"))
    pipe_count_matches = sum(1 for pid in shared if len(current[pid].get("pipes", [])) == len(truth[pid].get("pipes", [])))
    exact_pipe_matches = sum(1 for pid in shared if current[pid].get("pipes", []) == truth[pid].get("pipes", []))
    denom = max(1, len(truth_ids))
    shared_denom = max(1, len(shared))

    found_truth = {pid for pid, rec in truth.items() if rec.get("status") not in {"NO", "NOT_FOUND"}}
    found_current = {pid for pid, rec in current.items() if rec.get("status") not in {"NO", "NOT_FOUND"}}
    tp = len(found_truth & found_current)
    fp = len(found_current - found_truth)
    fn = len(found_truth - found_current)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)

    return {
        "baseline_name": baseline.get("name") or "Baseline",
        "truth_count": len(truth_ids),
        "current_count": len(current_ids),
        "shared_count": len(shared),
        "missing_point_ids": missing[:100],
        "extra_point_ids": extra[:100],
        "point_id_coverage": round(len(shared) / denom, 4),
        "found_precision": round(precision, 4),
        "found_recall": round(recall, 4),
        "status_accuracy": round(status_matches / shared_denom, 4),
        "dip_status_accuracy": round(dip_matches / shared_denom, 4),
        "pipe_count_accuracy": round(pipe_count_matches / shared_denom, 4),
        "exact_pipe_accuracy": round(exact_pipe_matches / shared_denom, 4),
    }
