#!/usr/bin/env python3
"""Score private FieldBook labels against saved local predictions, without inference.

Only Python's standard library is used. Images, project paths, and remote services
are never opened. See docs/FIELDBOOK_BENCHMARK.md for the deliberately strict gold
schema and the distinction between unlabelled and visibly absent fields.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any
import zipfile


SCHEMA_VERSION = 1
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_PAGES = 10000
MAX_STRUCTURES_PER_PAGE = 1000
MAX_PIPES_PER_STRUCTURE = 128
PIPE_FIELDS = ("dip", "diameter_in", "material", "azimuth_deg", "connected_point_raw")
NUMERIC_FIELDS = {"dip", "diameter_in", "azimuth_deg"}
DIP_STATUSES = {"YES", "NO", "CNA", "CNL", "NOT_FOUND", "REVIEW"}
REVIEW_STATES = {"UNREVIEWED", "ACCEPTED", "EDITED", "REJECTED"}
REVIEW_DECISIONS = {"REVIEW_DETAILS", "MANUAL_REVIEW"}
DECISIONS = REVIEW_DECISIONS | {"AUTO_ACCEPT", ""}
PRIVATE_DIR = ".fieldbook-benchmark"


class BenchmarkError(ValueError):
    """A malformed, ambiguous, or unsafe benchmark input."""


def _fail(where: str, message: str) -> None:
    # Do not embed a private PointID, field value, source name, or path in errors.
    raise BenchmarkError(f"{where}: {message}")


def _object(value: Any, where: str) -> dict:
    if not isinstance(value, dict):
        _fail(where, "expected an object")
    return value


def _keys(value: dict, required: set[str], optional: set[str], where: str) -> None:
    if not required.issubset(value):
        _fail(where, "a required key is missing")
    if set(value) - required - optional:
        _fail(where, "unknown key; check the documented schema")


def _text(value: Any, where: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(where, "expected a nonempty string without surrounding whitespace")
    if len(value) > 512 or any(ord(c) < 32 for c in value):
        _fail(where, "string is too long or contains control characters")
    return value


def _boolean(value: Any, where: str) -> bool:
    if type(value) is not bool:
        _fail(where, "expected true or false")
    return value


def _number(value: Any, where: str, *, minimum: int | None = None) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _fail(where, "expected a JSON number, not a string or boolean")
    try:
        result = Decimal(str(value))
    except Exception:
        _fail(where, "invalid number")
    if (
        not result.is_finite()
        or not math.isfinite(float(result))
        or (result != 0 and float(result) == 0)
        or (minimum is not None and result < minimum)
    ):
        _fail(where, "number is nonfinite or outside the allowed range")
    return result


def _integer(value: Any, where: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(where, "expected an integer in the allowed range")
    return value


def _sha(value: Any, where: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        _fail(where, "expected a SHA-256 hex digest")
    return value.lower()


def _bbox(value: Any, where: str) -> tuple[Decimal, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 4:
        _fail(where, "expected null or a four-number original-page bounding box")
    box = tuple(_number(v, where, minimum=0) for v in value)
    if any(v > 1000 for v in box) or box[0] >= box[2] or box[1] >= box[3]:
        _fail(where, "bounding box must have positive area within 0..1000")
    return box


def _field(name: str, value: Any, where: str) -> Any:
    if value is None:
        return None
    if name in NUMERIC_FIELDS:
        number = _number(value, where)
        if name == "diameter_in" and number <= 0:
            _fail(where, "diameter must be positive")
        if name == "azimuth_deg" and not 0 <= number < 360:
            _fail(where, "azimuth must be within [0, 360)")
        return number
    return _text(value, where)


def _json_object(pairs: list[tuple[str, Any]]) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise BenchmarkError("JSON contains a duplicate object key")
        out[key] = value
    return out


def _bad_constant(_value: str) -> None:
    raise BenchmarkError("JSON contains a nonfinite number")


def _json(text: str, where: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_json_object,
            parse_float=Decimal,
            parse_constant=_bad_constant,
        )
    except (ValueError, UnicodeError, RecursionError, InvalidOperation, OverflowError):
        _fail(where, "invalid JSON, duplicate object key, or nonfinite number")


def _local_path(value: str | Path, where: str) -> Path:
    raw = os.fspath(value)
    if not raw or any(ord(c) < 32 for c in raw):
        _fail(where, "expected a local path without control characters")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", raw) or raw.startswith(("\\\\", "//")):
        _fail(where, "network URLs and UNC paths are not accepted")
    if re.match(r"^(?:data|s3|gs|https?|ftp):", raw, flags=re.I):
        _fail(where, "only local filesystem paths are accepted")
    return Path(raw)


def _read_bytes(path: str | Path, where: str) -> bytes:
    target = _local_path(path, where)
    try:
        if not target.is_file() or target.stat().st_size > MAX_INPUT_BYTES:
            _fail(where, "input is not a regular file or exceeds the size limit")
        with target.open("rb") as handle:
            payload = handle.read(MAX_INPUT_BYTES + 1)
    except (OSError, ValueError):
        _fail(where, "cannot read local input")
    if len(payload) > MAX_INPUT_BYTES:
        _fail(where, "input exceeds the size limit")
    return payload


def _decode(payload: bytes, where: str) -> str:
    if len(payload) > MAX_JSON_BYTES:
        _fail(where, "JSON exceeds the size limit")
    try:
        return payload.decode("utf-8-sig")
    except UnicodeError:
        _fail(where, "input must be UTF-8 JSON")


def parse_gold(text: str) -> list[dict]:
    pages = []
    page_ids = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        where = f"gold line {line_number}"
        page = _object(_json(line, where), where)
        _keys(
            page,
            {"schema_version", "page_id", "source_sha256", "structures_complete", "structures"},
            {"image_path", "dip_unit"},
            where,
        )
        if type(page["schema_version"]) is not int or page["schema_version"] != SCHEMA_VERSION:
            _fail(where, "unsupported schema_version")
        page_id = _text(page["page_id"], where)
        if page_id in page_ids:
            _fail(where, "duplicate page label")
        page_ids.add(page_id)
        _sha(page["source_sha256"], where, nullable=True)
        _boolean(page["structures_complete"], where)
        if "image_path" in page:
            _local_path(_text(page["image_path"], where), where)
        if "dip_unit" in page:
            _text(page["dip_unit"], where, nullable=True)
        structures = page["structures"]
        if not isinstance(structures, list) or len(structures) > MAX_STRUCTURES_PER_PAGE:
            _fail(where, "structures must be a bounded array")
        structure_ids, point_ids = set(), set()
        for si, structure in enumerate(structures):
            at = f"{where}, structure {si + 1}"
            structure = _object(structure, at)
            _keys(
                structure,
                {"structure_id", "point_id", "pipes_complete", "pipes"},
                {"dip_status", "structure_bbox"},
                at,
            )
            sid = _text(structure["structure_id"], at)
            pid = _text(structure["point_id"], at, nullable=True)
            if sid in structure_ids or (pid is not None and pid in point_ids):
                _fail(at, "duplicate structure or exact PointID label on one page")
            structure_ids.add(sid)
            if pid is not None:
                point_ids.add(pid)
            _boolean(structure["pipes_complete"], at)
            status = structure.get("dip_status")
            if status is not None and (not isinstance(status, str) or status not in DIP_STATUSES):
                _fail(at, "invalid dip_status")
            if "structure_bbox" in structure:
                structure["structure_bbox"] = _bbox(structure["structure_bbox"], at)
            pipes = structure["pipes"]
            if not isinstance(pipes, list) or len(pipes) > MAX_PIPES_PER_STRUCTURE:
                _fail(at, "pipes must be a bounded array")
            pipe_ids, boxes = set(), set()
            for pi, pipe in enumerate(pipes):
                pat = f"{at}, pipe {pi + 1}"
                pipe = _object(pipe, pat)
                _keys(pipe, {"pipe_id", "leader_bbox", "fields"}, set(), pat)
                pipe_id = _text(pipe["pipe_id"], pat)
                if pipe_id in pipe_ids:
                    _fail(pat, "duplicate pipe label")
                pipe_ids.add(pipe_id)
                pipe["leader_bbox"] = _bbox(pipe["leader_bbox"], pat)
                if pipe["leader_bbox"] is not None:
                    if pipe["leader_bbox"] in boxes:
                        _fail(pat, "duplicate pipe bounding box cannot identify separate bindings")
                    boxes.add(pipe["leader_bbox"])
                fields = _object(pipe["fields"], pat)
                _keys(fields, set(), set(PIPE_FIELDS), pat)
                pipe["fields"] = {k: _field(k, v, pat) for k, v in fields.items()}
        pages.append(page)
        if len(pages) > MAX_PAGES:
            _fail("gold", "too many pages")
    if not pages:
        _fail("gold", "no page labels supplied")
    return pages


def _prediction(record: Any, where: str, result: dict | None = None) -> dict:
    record = _object(record, where)
    result = result or {}
    if "schema_version" in record and (
        type(record["schema_version"]) is not int or record["schema_version"] != SCHEMA_VERSION
    ):
        _fail(where, "unsupported prediction schema_version")
    page_id = _text(record.get("page_id"), where)
    pid = record.get("matched_point_id", record.get("point_id"))
    point_id = _text(pid, where)
    if "matched_point_id" in record and "point_id" in record and record["point_id"] != point_id:
        _fail(where, "conflicting PointID fields")
    decision = record.get("evidence_decision", "")
    if not isinstance(decision, str) or decision not in DECISIONS:
        _fail(where, "invalid evidence_decision")
    status = record.get("dipped", record.get("dip_status"))
    if status is not None and (not isinstance(status, str) or status not in DIP_STATUSES):
        _fail(where, "invalid dip status")
    review = result.get("review_state", record.get("review_state", "UNREVIEWED"))
    if not isinstance(review, str) or review not in REVIEW_STATES:
        _fail(where, "invalid manual review_state")
    manually_overridden = result.get(
        "manually_overridden", record.get("manually_overridden", False)
    )
    _boolean(manually_overridden, where)
    pipes = record.get("pipes")
    if not isinstance(pipes, list) or len(pipes) > MAX_PIPES_PER_STRUCTURE:
        _fail(where, "pipes must be a bounded array")
    converted = []
    for pi, raw_pipe in enumerate(pipes):
        at = f"{where}, pipe {pi + 1}"
        raw_pipe = _object(raw_pipe, at)
        source_page = raw_pipe.get("source_page_id")
        if source_page not in (None, "", page_id):
            _fail(at, "pipe source_page_id differs from its evidence page")
        converted.append(
            {
                "leader_bbox": _bbox(raw_pipe.get("leader_bbox"), at),
                "fields": {k: _field(k, raw_pipe[k], at) for k in PIPE_FIELDS if k in raw_pipe},
            }
        )
    return {
        "page_id": page_id,
        "point_id": point_id,
        "pipes": converted,
        "dip_status": status,
        "decision": decision,
        "review_state": review,
        "manually_overridden": manually_overridden,
    }


def parse_predictions(text: str, *, jsonl: bool = False) -> tuple[list[dict], dict, dict]:
    predictions, metadata, page_hashes = [], {}, {}
    if jsonl:
        records = [
            (_json(line, f"prediction line {i}"), f"prediction line {i}")
            for i, line in enumerate(text.splitlines(), start=1)
            if line.strip()
        ]
        for record, where in records:
            predictions.append(_prediction(record, where))
            if "source_sha256" in record:
                digest = _sha(record["source_sha256"], where, nullable=True)
                if digest is not None:
                    old = page_hashes.setdefault(predictions[-1]["page_id"], digest)
                    if old != digest:
                        _fail(where, "conflicting page hashes")
    else:
        data = _object(_json(text, "prediction export"), "prediction export")
        if "results" not in data or not isinstance(data["results"], list):
            _fail(
                "prediction export",
                "expected SurveySync results array, not a GIS or summary export",
            )
        metadata = _object(data.get("benchmark_metadata", {}), "benchmark metadata")
        page_hashes = _object(data.get("page_sha256", {}), "page hashes")
        page_hashes = {
            _text(k, "page hashes"): _sha(v, "page hashes", nullable=True)
            for k, v in page_hashes.items()
        }
        result_ids = set()
        for ri, result in enumerate(data["results"]):
            where = f"export result {ri + 1}"
            result = _object(result, where)
            pid = _text(result.get("point_id"), where)
            if pid in result_ids:
                _fail(where, "duplicate ResultRecord PointID")
            result_ids.add(pid)
            records = result.get("evidence_records")
            if not isinstance(records, list):
                _fail(
                    where,
                    "evidence_records is required; aggregated pipes cannot stand in for raw predictions",
                )
            for ei, record in enumerate(records):
                predictions.append(_prediction(record, f"{where}, evidence {ei + 1}", result))
    return predictions, metadata, page_hashes


def load_predictions(path: str | Path) -> tuple[list[dict], dict, dict, str]:
    payload = _read_bytes(path, "predictions")
    digest = hashlib.sha256(payload).hexdigest()
    target = _local_path(path, "predictions")
    if zipfile.is_zipfile(io.BytesIO(payload)):
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                members = [x for x in archive.infolist() if x.filename == "audit.json"]
                if len(members) != 1 or members[0].file_size > MAX_JSON_BYTES:
                    _fail("prediction ZIP", "expected one bounded audit.json member")
                # Never extract any member or follow an image/source path.
                payload = archive.read(members[0])
        except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile):
            _fail("prediction ZIP", "cannot read audit.json")
        is_jsonl = False
    else:
        is_jsonl = target.suffix.casefold() in {".jsonl", ".ndjson"}
    predictions, metadata, page_hashes = parse_predictions(
        _decode(payload, "predictions"), jsonl=is_jsonl
    )
    return predictions, metadata, page_hashes, digest


def _iou(a: tuple, b: tuple) -> Decimal:
    intersection = max(Decimal(0), min(a[2], b[2]) - max(a[0], b[0])) * max(
        Decimal(0), min(a[3], b[3]) - max(a[1], b[1])
    )
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union


def match_pipes(gold: list[dict], predicted: list[dict], threshold: Decimal) -> dict[int, int]:
    """Accept mutual unique spatial matches. Never match using OCR/field values."""
    links = {
        i: [
            j
            for j, p in enumerate(predicted)
            if g["leader_bbox"] is not None
            and p["leader_bbox"] is not None
            and _iou(g["leader_bbox"], p["leader_bbox"]) >= threshold
        ]
        for i, g in enumerate(gold)
    }
    degrees = Counter(j for choices in links.values() for j in choices)
    return {
        i: choices[0]
        for i, choices in links.items()
        if len(choices) == 1 and degrees[choices[0]] == 1
    }


def _same(field: str, expected: Any, actual: Any) -> bool:
    if expected is None or actual is None:
        return expected is actual
    if field == "material":
        return expected.casefold() == actual.casefold()
    return expected == actual


def _rate(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def _observation_signature(prediction: dict) -> tuple:
    """Compare normalized records without using gold, pipe order, or decisions."""
    pipes = Counter(
        (
            pipe["leader_bbox"],
            tuple(
                (field, value.casefold() if field == "material" and value is not None else value)
                for field, value in sorted(pipe["fields"].items())
            ),
        )
        for pipe in prediction["pipes"]
    )
    return prediction["dip_status"], frozenset(pipes.items())


def _group_predictions(predictions: list[dict]) -> dict[tuple[str, str], dict]:
    """Conservative consensus over saved views; preserve every raw observation.

    Agreement is exact after field normalization and ignores pipe ordering.
    Disputed groups receive no pipe-value credit. Only geometry present in every
    observation and an undisputed status survive, independently of gold labels.
    """
    observations: dict[tuple[str, str], list[dict]] = {}
    for prediction in predictions:
        observations.setdefault((prediction["page_id"], prediction["point_id"]), []).append(
            prediction
        )
    groups = {}
    for key, records in observations.items():
        first = records[0]
        signature = _observation_signature(first)
        conflict = any(_observation_signature(record) != signature for record in records[1:])
        combined = dict(first, _observations=records, _duplicate_conflict=conflict)
        if conflict:
            status = {record["dip_status"] for record in records}
            combined["dip_status"] = first["dip_status"] if len(status) == 1 else None
            common_boxes = Counter(pipe["leader_bbox"] for pipe in first["pipes"])
            for record in records[1:]:
                common_boxes &= Counter(pipe["leader_bbox"] for pipe in record["pipes"])
            combined["pipes"] = [
                {"leader_bbox": box, "fields": {}}
                for box, count in common_boxes.items()
                for _ in range(count)
            ]
        groups[key] = combined
    return groups


def score(
    gold: list[dict],
    predictions: list[dict],
    *,
    min_iou: float = 0.3,
    page_hashes: dict | None = None,
) -> dict:
    threshold = _number(min_iou, "min_iou")
    if not 0 < threshold <= 1:
        _fail("min_iou", "must be greater than zero and no more than one")
    pages = {p["page_id"]: p for p in gold}
    truth = {
        (p["page_id"], s["point_id"]): s
        for p in gold
        for s in p["structures"]
        if s["point_id"] is not None
    }
    predictions_by_key = _group_predictions(predictions)
    counts = Counter()
    counts["raw_prediction_observations"] = len(predictions)
    counts["unique_prediction_groups"] = len(predictions_by_key)
    counts["duplicate_observations"] = len(predictions) - len(predictions_by_key)
    for group in predictions_by_key.values():
        if len(group["_observations"]) > 1:
            counts["duplicate_prediction_groups"] += 1
            counts[
                "conflicting_duplicate_groups"
                if group["_duplicate_conflict"]
                else "agreeing_duplicate_groups"
            ] += 1
    field_total, field_correct = Counter(), Counter()
    verdicts: dict[tuple[str, str], bool | None] = {}
    for page in gold:
        expected = page["source_sha256"]
        actual = (page_hashes or {}).get(page["page_id"])
        if expected is not None and actual is not None:
            if expected.lower() != actual.lower():
                _fail("page identity", "gold and prediction image hashes differ")
            counts["verified_page_hashes"] += 1
        else:
            counts["unverified_page_hashes"] += 1
        counts["unknown_point_labels"] += sum(s["point_id"] is None for s in page["structures"])
        counts["unlabelled_identity_pipes"] += sum(
            len(s["pipes"]) for s in page["structures"] if s["point_id"] is None
        )

    for key, structure in truth.items():
        prediction = predictions_by_key.get(key)
        pipes = prediction["pipes"] if prediction else []
        matches = match_pipes(structure["pipes"], pipes, threshold)
        counts["gold_pipes"] += len(structure["pipes"])
        incorrect = False
        fully_labelled = structure["pipes_complete"] and structure.get("dip_status") is not None
        if structure.get("dip_status") is not None:
            counts["status_labels"] += 1
            status_ok = bool(prediction and prediction["dip_status"] == structure["dip_status"])
            counts["correct_status"] += status_ok
            incorrect |= not status_ok
        if structure["pipes_complete"]:
            counts["predicted_pipes_on_complete_structures"] += len(pipes)
            counts["unbound_predicted_pipes_on_complete_structures"] += len(pipes) - len(matches)
            if len(pipes) != len(structure["pipes"]):
                incorrect = True
        for gi, gpipe in enumerate(structure["pipes"]):
            fields = gpipe["fields"]
            eligible = gpipe["leader_bbox"] is not None
            if not eligible:
                counts["unlabelled_pipe_geometry"] += 1
                fully_labelled = False
                continue
            counts["localized_pipe_labels"] += 1
            matched = gi in matches
            counts["spatially_matched_pipes"] += matched
            pfields = pipes[matches[gi]]["fields"] if matched else {}
            correct = matched and all(
                k in pfields and _same(k, v, pfields[k]) for k, v in fields.items()
            )
            for field, value in fields.items():
                field_total[field] += 1
                field_correct[field] += bool(
                    matched and field in pfields and _same(field, value, pfields[field])
                )
            if fields:
                counts["binding_labels"] += 1
                counts["correct_bindings"] += correct
                incorrect |= not correct
            else:
                counts["unlabelled_pipe_fields"] += 1
            complete = set(fields) == set(PIPE_FIELDS)
            if complete:
                counts["complete_pipe_labels"] += 1
                counts["correct_complete_pipes"] += correct
            else:
                counts["partially_labelled_pipes"] += 1
                fully_labelled = False
        if prediction and prediction["_duplicate_conflict"] and fully_labelled:
            incorrect = True
        verdicts[key] = False if incorrect else (True if prediction and fully_labelled else None)
        if fully_labelled:
            counts["complete_structure_labels"] += 1
            counts["correct_complete_structures"] += verdicts[key] is True

    for prediction in predictions_by_key.values():
        key = prediction["page_id"], prediction["point_id"]
        page = pages.get(prediction["page_id"])
        if page is None:
            counts["prediction_groups_outside_labelled_pages"] += 1
            counts["predictions_outside_labelled_pages"] += len(prediction["_observations"])
            continue
        counts["scoped_prediction_groups"] += 1
        if key in truth:
            counts["point_tp"] += 1
            verdict = verdicts[key]
        elif page["structures_complete"] and all(
            s["point_id"] is not None for s in page["structures"]
        ):
            counts["point_fp"] += 1
            verdict = False
        else:
            counts["point_predictions_unassessed"] += 1
            verdict = None
        # Decisions remain observation-based. A duplicate AUTO_ACCEPT must not
        # disappear because another view was routed to manual review.
        for observation in prediction["_observations"]:
            counts["scoped_predictions"] += 1
            counts["manual_" + observation["review_state"]] += 1
            counts["manually_overridden"] += observation["manually_overridden"]
            decision = observation["decision"]
            if decision == "AUTO_ACCEPT":
                counts["auto_accept"] += 1
                if verdict is None:
                    counts["auto_accept_unassessed"] += 1
                else:
                    counts["auto_accept_assessed"] += 1
                    counts["false_auto_accept"] += not verdict
            elif decision in REVIEW_DECISIONS:
                counts["review_required"] += 1
            else:
                counts["decision_unknown"] += 1

    return {
        "labelled_pages": len(gold),
        "exact_point_id_precision": _rate(
            counts["point_tp"], counts["point_tp"] + counts["point_fp"]
        ),
        "exact_point_id_recall": _rate(counts["point_tp"], len(truth)),
        "dip_status_accuracy": _rate(counts["correct_status"], counts["status_labels"]),
        "pipe_spatial_match_recall": _rate(
            counts["spatially_matched_pipes"], counts["localized_pipe_labels"]
        ),
        "labelled_pipe_binding_accuracy": _rate(
            counts["correct_bindings"], counts["binding_labels"]
        ),
        "complete_pipe_record_accuracy": _rate(
            counts["correct_complete_pipes"], counts["complete_pipe_labels"]
        ),
        "complete_structure_record_accuracy": _rate(
            counts["correct_complete_structures"], counts["complete_structure_labels"]
        ),
        "field_accuracy": {
            field: _rate(field_correct[field], field_total[field]) for field in PIPE_FIELDS
        },
        "false_auto_accept_rate": _rate(
            counts["false_auto_accept"], counts["auto_accept_assessed"]
        ),
        "review_rate": _rate(
            counts["review_required"], counts["review_required"] + counts["auto_accept"]
        ),
        "counts": {
            key: counts[key]
            for key in (
                "gold_pipes",
                "raw_prediction_observations",
                "unique_prediction_groups",
                "duplicate_observations",
                "duplicate_prediction_groups",
                "agreeing_duplicate_groups",
                "conflicting_duplicate_groups",
                "scoped_prediction_groups",
                "scoped_predictions",
                "point_tp",
                "point_fp",
                "point_predictions_unassessed",
                "predictions_outside_labelled_pages",
                "prediction_groups_outside_labelled_pages",
                "unknown_point_labels",
                "unlabelled_identity_pipes",
                "unlabelled_pipe_geometry",
                "unlabelled_pipe_fields",
                "partially_labelled_pipes",
                "predicted_pipes_on_complete_structures",
                "unbound_predicted_pipes_on_complete_structures",
                "auto_accept",
                "auto_accept_assessed",
                "auto_accept_unassessed",
                "false_auto_accept",
                "review_required",
                "decision_unknown",
                "manually_overridden",
                "manual_UNREVIEWED",
                "manual_ACCEPTED",
                "manual_EDITED",
                "manual_REJECTED",
                "verified_page_hashes",
                "unverified_page_hashes",
            )
        },
    }


def _metadata(raw: dict, mode: str) -> dict:
    """Copy only documented metadata, never arbitrary export/private project data."""
    out = {
        "mode": mode,
        "source_commit": None,
        "model": None,
        "hardware": {},
        "measurements": {},
        "provenance": "supplied, not independently measured",
    }
    if "schema_version" in raw and (
        type(raw["schema_version"]) is not int or raw["schema_version"] != 1
    ):
        _fail("benchmark metadata", "unsupported schema_version")
    if "mode" in raw and raw["mode"] != mode:
        _fail("benchmark metadata", "export mode differs from the CLI run name")
    if raw.get("source_commit") is not None:
        commit = raw["source_commit"]
        if not isinstance(commit, str) or not re.fullmatch(
            r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", commit
        ):
            _fail("benchmark metadata", "source_commit must be a full Git commit hash")
        out["source_commit"] = commit.lower()
    if raw.get("implementation_sha256") is not None:
        out["implementation_sha256"] = _sha(raw["implementation_sha256"], "benchmark metadata")
    for name in ("model", "generated_at", "review_timing_basis"):
        if raw.get(name) is not None:
            out[name] = _text(raw[name], "benchmark metadata")
    if "source_dirty" in raw:
        out["source_dirty"] = _boolean(raw["source_dirty"], "benchmark metadata")
    if "provenance_warnings" in raw:
        warnings = raw["provenance_warnings"]
        if not isinstance(warnings, list) or len(warnings) > MAX_PAGES:
            _fail("benchmark metadata", "provenance_warnings must be a bounded string array")
        out["provenance_warnings"] = [_text(value, "benchmark metadata") for value in warnings]
    if "ocr_provenance" in raw:
        where = "OCR provenance metadata"
        provenance = _object(raw["ocr_provenance"], where)
        _keys(
            provenance,
            {
                "observed_modes",
                "observed_model_asset_sha256",
                "observed_page_count",
                "observed_view_count",
            },
            set(),
            where,
        )
        modes = provenance["observed_modes"]
        if (
            not isinstance(modes, list)
            or len(modes) > 2
            or any(
                not isinstance(value, str) or value not in {"blocks", "spotting"} for value in modes
            )
            or len(set(modes)) != len(modes)
        ):
            _fail(where, "observed_modes must contain unique blocks/spotting values")
        digests = provenance["observed_model_asset_sha256"]
        if not isinstance(digests, list) or len(digests) > MAX_PAGES:
            _fail(where, "observed_model_asset_sha256 must be a bounded digest array")
        digests = [_sha(value, where) for value in digests]
        if len(set(digests)) != len(digests):
            _fail(where, "observed model asset digests must be unique")
        out["ocr_provenance"] = {
            "observed_modes": sorted(modes),
            "observed_model_asset_sha256": sorted(digests),
            "observed_page_count": _integer(provenance["observed_page_count"], where),
            "observed_view_count": _integer(provenance["observed_view_count"], where),
        }
    hardware = _object(raw.get("hardware", {}), "hardware metadata")
    for name in ("os", "cpu", "gpu"):
        if name in hardware:
            out["hardware"][name] = _text(hardware[name], "hardware metadata")
    for name in ("ram_gib", "vram_gib"):
        if name in hardware:
            out["hardware"][name] = float(_number(hardware[name], "hardware metadata", minimum=0))
    measurements = _object(raw.get("measurements", {}), "measurement metadata")
    for name in (
        "wall_seconds",
        "peak_rss_mib",
        "peak_vram_mib",
        "correction_seconds",
        "cancel_seconds",
    ):
        if name in measurements:
            out["measurements"][name] = float(
                _number(measurements[name], "measurement metadata", minimum=0)
            )
    for name in ("corrected_structures", "reviewed_structures", "oom_count"):
        if name in measurements:
            out["measurements"][name] = _integer(measurements[name], "measurement metadata")
    times = measurements.get("page_seconds")
    if times is not None:
        if not isinstance(times, list) or len(times) > MAX_PAGES:
            _fail("measurement metadata", "page_seconds must be a bounded array")
        values = sorted(float(_number(t, "measurement metadata", minimum=0)) for t in times)
        out["measurements"]["page_seconds"] = {
            "count": len(values),
            "p50": values[math.ceil(len(values) * 0.5) - 1] if values else None,
            "p95": values[math.ceil(len(values) * 0.95) - 1] if values else None,
        }
    return out


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, text=True, capture_output=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _worktree_root(start: Path) -> Path | None:
    # The filesystem fallback ensures an unavailable Git executable cannot turn
    # off the private-directory rule inside a checkout or linked worktree.
    reported = _git(["rev-parse", "--show-toplevel"], start)
    if reported is not None:
        return Path(reported).resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def evaluator_provenance() -> dict:
    script = Path(__file__).resolve()
    status = _git(["status", "--porcelain"], script.parent)
    return {
        "commit": _git(["rev-parse", "HEAD"], script.parent),
        "worktree_dirty": bool(status) if status is not None else None,
        "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "python": sys.version.split()[0],
    }


def write_private_report(path: str | Path, report: dict, *, overwrite: bool = False) -> None:
    target = _local_path(path, "output")
    absolute = Path(os.path.abspath(target))
    try:
        resolved = target.resolve()
    except (OSError, ValueError, RuntimeError):
        _fail("output", "cannot resolve the local output path")
    if os.path.normcase(str(absolute)) != os.path.normcase(str(resolved)):
        _fail("output", "symlink or junction output paths are not accepted")
    parent = resolved.parent
    ancestor = parent
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    root = _worktree_root(ancestor)
    if root is not None:
        private_root = root / PRIVATE_DIR
        if not resolved.is_relative_to(private_root):
            _fail("output", f"inside a Git worktree, reports must be below {PRIVATE_DIR}/")
        relative = str(resolved.relative_to(root))
        ignored = _git(["check-ignore", "--", relative], root)
        if not ignored:
            _fail("output", "the private report directory must be gitignored first")
    if resolved.exists() and not overwrite:
        _fail("output", "report exists; use --overwrite for this explicit destination")
    temp = None
    try:
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=parent, delete=False) as handle:
            temp = Path(handle.name)
            json.dump(report, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
        if resolved.exists() and not overwrite:
            _fail("output", "report was created concurrently")
        temp.replace(resolved)
    except (OSError, ValueError, TypeError):
        _fail("output", "could not write the local report")
    finally:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def _separate_output(output: str | Path, inputs: list[str | Path]) -> None:
    target = _local_path(output, "output")
    try:
        resolved = target.resolve()
        for source in inputs:
            original = _local_path(source, "input")
            if resolved == original.resolve() or (target.exists() and target.samefile(original)):
                _fail("output", "the report must not replace an input file")
    except OSError:
        _fail("output", "cannot compare local input and output paths")


def build_report(
    gold_path: str | Path, runs: list[tuple[str, str]], *, min_iou: float = 0.3
) -> dict:
    gold_bytes = _read_bytes(gold_path, "gold")
    gold = parse_gold(_decode(gold_bytes, "gold"))
    report = {
        "schema_version": SCHEMA_VERSION,
        "kind": "surveysync_fieldbook_benchmark",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gold_sha256": hashlib.sha256(gold_bytes).hexdigest(),
        "evaluator": evaluator_provenance(),
        "policy": {
            "prediction_stage": "raw_page_evidence",
            "min_leader_bbox_iou": min_iou,
            "matching": "mutual_unique_geometry_only",
            "duplicate_observations": "gold_independent_consensus; disputed groups receive no pipe_value_credit",
            "identity_denominator": "unique_exact_page_point_id_groups",
            "decision_denominator": "all_raw_observations_on_labelled_pages",
            "numeric_comparison": "exact",
            "missing_gold_key": "unknown",
            "null_gold_field": "verified_absent",
            "no_ground_truth_denominator": None,
            "image_paths_opened": False,
            "release_or_security_clearance": False,
        },
        "runs": {},
    }
    for mode, path in runs:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", mode) or mode in report["runs"]:
            _fail("run", "mode names must be unique short identifiers")
        predictions, metadata, page_hashes, digest = load_predictions(path)
        report["runs"][mode] = {
            "prediction_sha256": digest,
            "metadata": _metadata(metadata, mode),
            "metrics": score(gold, predictions, min_iou=min_iou, page_hashes=page_hashes),
        }
    if not runs:
        _fail("run", "at least one prediction run is required")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, help="Private gold JSONL, one page per line")
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="MODE=LOCAL_PATH",
        help="Repeat to compare block, spotting, or a saved local challenger",
    )
    parser.add_argument("--output", required=True, help="Private local JSON report destination")
    parser.add_argument(
        "--min-iou", type=float, default=0.3, help="Unique leader-box IoU threshold (default 0.3)"
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace this exact output file")
    args = parser.parse_args(argv)
    try:
        runs = []
        for raw in args.run:
            if "=" not in raw:
                _fail("run", "expected MODE=LOCAL_PATH")
            mode, path = raw.split("=", 1)
            runs.append((mode, path))
        _separate_output(args.output, [args.gold, *(path for _, path in runs)])
        report = build_report(args.gold, runs, min_iou=args.min_iou)
        write_private_report(args.output, report, overwrite=args.overwrite)
    except BenchmarkError as exc:
        print(f"Benchmark rejected: {exc}", file=sys.stderr)
        return 2
    print(
        f"Saved private benchmark report for {len(runs)} run(s); no inference or uploads performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
