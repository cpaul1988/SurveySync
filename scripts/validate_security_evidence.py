"""Validate bounded, hash-bound Defender evidence. Does not claim vendor clearance."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

MAX_AGE_SECONDS = 48 * 60 * 60
MAX_REPORT_BYTES = 4 * 1024 * 1024
HEX = re.compile(r"^[a-f0-9]{64}$")


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Missing timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must have timezone")
    return parsed.astimezone(timezone.utc)


def validate(report: dict[str, Any], expected: dict[str, str], *, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise ValueError("Unknown security report schema")
    if report.get("result") != "passed":
        raise ValueError("Security scan did not pass")
    age = (now - timestamp(report.get("completed_utc"))).total_seconds()
    if not 0 <= age <= MAX_AGE_SECONDS:
        raise ValueError("Stale or future-dated security evidence")
    if not expected or any(not HEX.fullmatch(h) for h in expected.values()):
        raise ValueError("Expected artifact hashes are missing or invalid")
    status = report.get("defender")
    if not isinstance(status, dict):
        raise ValueError("Missing Defender status")
    for flag in ("AMServiceEnabled", "AntivirusEnabled", "RealTimeProtectionEnabled"):
        if status.get(flag) is not True:
            raise ValueError("Defender protection was not active: " + flag)
    if not status.get("AMEngineVersion") or not status.get("AntivirusSignatureVersion"):
        raise ValueError("Defender engine/signature identity is missing")
    sig_age = (now - timestamp(status.get("AntivirusSignatureLastUpdatedUtc"))).total_seconds()
    if not -300 <= sig_age <= MAX_AGE_SECONDS:
        raise ValueError("Defender security intelligence is stale")
    scans = report.get("scans")
    if not isinstance(scans, list) or not scans:
        raise ValueError("No artifact scans")
    found = {}
    for scan in scans:
        if not isinstance(scan, dict) or type(scan.get("exit_code")) is not int or scan["exit_code"] != 0:
            raise ValueError("Scanner returned an error or detection")
        if scan.get("mode") != "custom-detection-only" or scan.get("threat_detected") is not False:
            raise ValueError("Scan result is not explicit no-detection evidence")
        name, before, after = scan.get("name"), scan.get("sha256_before"), scan.get("sha256_after")
        if not isinstance(name, str) or name in found or not isinstance(before, str) or not HEX.fullmatch(before):
            raise ValueError("Ambiguous artifact identity")
        if before != after or scan.get("exists_after") is not True:
            raise ValueError("Scanned artifact was changed, removed, or quarantined")
        if not isinstance(scan.get("output_sha256"), str) or not HEX.fullmatch(scan["output_sha256"]):
            raise ValueError("Scanner log is not identified")
        found[name] = before
    if found != expected:
        raise ValueError("Scan evidence does not identify the exact expected artifacts")


def validate_file(report_path: Path, paths: list[Path]) -> None:
    if report_path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError("Security report exceeds size limit")
    expected = {}
    for path in paths:
        if not path.is_file() or path.is_symlink() or path.name in expected:
            raise ValueError("Missing, symlinked, or duplicate release artifact: " + str(path))
        expected[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    validate(report, expected)
    for scan in report["scans"]:
        name = scan.get("output_file", "")
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(".txt"):
            raise ValueError("Unsafe scanner log path")
        log = report_path.parent / name
        if not log.is_file() or log.is_symlink() or hashlib.sha256(log.read_bytes()).hexdigest() != scan["output_sha256"]:
            raise ValueError("Scanner log differs from captured evidence")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("Usage: validate_security_evidence.py REPORT FILE [FILE ...]")
    validate_file(Path(sys.argv[1]), [Path(x) for x in sys.argv[2:]])
    print("Exact artifact security evidence validated. A scan pass is not Microsoft false-positive clearance.")
