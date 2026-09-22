"""Report and reviewed-copy exports; no mutation of source or project elevations."""

from __future__ import annotations

import csv
import io


def candidate_report_csv(report: dict) -> str:
    output = io.StringIO(newline="")
    fields = [
        "candidate_id",
        "start_point",
        "end_point",
        "estimated_rod_bust",
        "recommended_correction",
        "vertical_units",
        "offset_std_dev",
        "confidence",
        "status",
        "correction_ready",
        "supporting_features",
        "affected_point_ids",
        "blockers",
        "reason",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for candidate in report["result"]["candidates"]:
        row = {key: candidate.get(key, "") for key in fields}
        row["vertical_units"] = report["result"]["settings"]["vertical_units"]
        for name in ("supporting_features", "affected_point_ids", "blockers"):
            row[name] = "; ".join(row[name])
        writer.writerow(row)
    return output.getvalue()


def reviewed_copy_csv(report: dict, candidate_ids: list[str], reason: str) -> tuple[str, dict]:
    if not reason.strip() or not candidate_ids:
        raise ValueError("Select at least one eligible range and enter the review reason.")
    choices = {c["candidate_id"]: c for c in report["result"]["candidates"]}
    corrections: dict[str, float] = {}
    for candidate_id in set(candidate_ids):
        candidate = choices.get(candidate_id)
        if (
            not candidate
            or not candidate["correction_ready"]
            or candidate["recommended_correction"] is None
        ):
            raise ValueError(
                f"{candidate_id}: correction is blocked; inspect its evidence and review requirements."
            )
        for pid in candidate["affected_point_ids"]:
            correction = float(candidate["recommended_correction"])
            if pid in corrections and abs(corrections[pid] - correction) > 1e-9:
                raise ValueError(
                    "Selected ranges overlap with different corrections. Resolve the ranges first."
                )
            corrections[pid] = correction
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "PointID",
            "Northing",
            "Easting",
            "Elevation",
            "Code",
            "OriginalElevation",
            "AppliedCorrection",
            "SourceRow",
        ]
    )
    for point in report["points"]:
        correction = corrections.get(point["point_id"], 0.0)
        writer.writerow(
            [
                point["point_id"],
                format(point["northing"], ".17g"),
                format(point["easting"], ".17g"),
                format(point["elevation"] + correction, ".17g"),
                point["code"],
                format(point["elevation"], ".17g"),
                format(correction, ".17g"),
                point["source_row"],
            ]
        )
    audit = {
        "source_sha256": report["source_sha256"],
        "selected_candidates": sorted(set(candidate_ids)),
        "review_reason": reason.strip(),
        "changed_point_ids": list(corrections),
        "operation": "EXPORTED_REVIEWED_COPY",
        "source_modified": False,
    }
    return output.getvalue(), audit
