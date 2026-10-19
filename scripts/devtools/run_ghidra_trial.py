"""Run bounded headless analysis of a hash-identified executable without launching it.

Requires a separately installed Ghidra release and supported JDK. All Ghidra
projects, logs, pseudocode, preferences and temporary files stay under --output.
This is a developer investigation utility, not a release or antivirus gate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import time


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ghidra-dir", required=True, type=Path)
    parser.add_argument("--jdk-dir", required=True, type=Path)
    parser.add_argument("--sample", required=True, type=Path)
    parser.add_argument("--sha256", required=True, dest="expected_sha256")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--analysis-timeout", type=int, default=240)
    args = parser.parse_args()
    expected = args.expected_sha256.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        parser.error("--sha256 must contain exactly 64 hexadecimal characters")
    if not 1 <= args.analysis_timeout <= 900:
        parser.error("--analysis-timeout must be between 1 and 900 seconds")
    sample = args.sample.resolve(strict=True)
    ghidra = args.ghidra_dir.resolve(strict=True)
    jdk = args.jdk_dir.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("--output must be absent or empty to preserve earlier evidence")
    actual = sha256(sample)
    if actual != expected:
        parser.error(f"Input SHA-256 mismatch: expected {expected}; observed {actual}")
    script = Path(__file__).with_name("SurveySyncStaticAudit.java").resolve(strict=True)
    headless = ghidra / "support" / "analyzeHeadless"
    java = jdk / "bin" / "java"
    if not headless.is_file() or not java.is_file():
        parser.error("Expected Unix Ghidra support/analyzeHeadless and JDK bin/java")
    for directory in (output, output / "project", output / "profile", output / "tmp"):
        directory.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["JAVA_HOME"] = str(jdk)
    environment["PATH"] = str(jdk / "bin") + os.pathsep + environment.get("PATH", "")
    environment["JAVA_TOOL_OPTIONS"] = shlex.join(
        [f"-Duser.home={output / 'profile'}", f"-Djava.io.tmpdir={output / 'tmp'}"]
    )
    environment["GHIDRA_HEADLESS_MAXMEM"] = "2G"
    command = [
        str(headless), str(output / "project"), "SurveySyncStaticTrial",
        "-import", str(sample),
        "-scriptPath", str(script.parent),
        "-postScript", script.name, str(output / "static_report.json"),
        "-analysisTimeoutPerFile", str(args.analysis_timeout),
        "-max-cpu", "2",
        "-log", str(output / "analysis.log"),
        "-scriptlog", str(output / "script.log"),
    ]
    version = subprocess.run(
        [str(java), "-version"], check=True, capture_output=True, text=True, env=environment
    )
    started = datetime.now(timezone.utc).isoformat()
    timer = time.monotonic()
    timed_out = False
    with (output / "console.log").open("w", encoding="utf-8") as log:
        with subprocess.Popen(
            command, env=environment, cwd=output, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True,
        ) as process:
            try:
                exit_code = process.wait(timeout=args.analysis_timeout + 240)
            except subprocess.TimeoutExpired:
                timed_out = True
                # Ghidra's shell launcher waits for Java. Stop the entire analysis
                # process group so a timed-out child cannot continue in the background.
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                exit_code = 124
    post_hash = sha256(sample)
    report = output / "static_report.json"
    report_written = report.is_file()
    report_sha256 = None
    report_parse_error = None
    analysis_report = {}
    if report_written:
        try:
            report_bytes = report.read_bytes()
            report_sha256 = hashlib.sha256(report_bytes).hexdigest()
            parsed = json.loads(report_bytes)
            if not isinstance(parsed, dict):
                raise ValueError("Static report root must be a JSON object")
            analysis_report = parsed
        except (OSError, UnicodeError, ValueError) as error:
            # Preserve evidence even when a failed/interrupted exporter leaves
            # incomplete JSON, invalid text, or a report that cannot be read.
            report_parse_error = f"{type(error).__name__}: {error}"
    analysis_timed_out = analysis_report.get("analysis_timeout_occurred")
    manifest = {
        "schema_version": 1,
        "started_at_utc": started,
        "elapsed_seconds": round(time.monotonic() - timer, 3),
        "sample_name": sample.name,
        "sample_path": str(sample),
        "sample_size_bytes": sample.stat().st_size,
        "expected_sha256": expected,
        "sha256_before": actual,
        "sha256_after": post_hash,
        "sample_unchanged": actual == post_hash,
        "java_version_output": version.stdout + version.stderr,
        "ghidra_directory": str(ghidra),
        "analysis_timeout_seconds": args.analysis_timeout,
        "command": command,
        "script_sha256": sha256(script),
        "runner_sha256": sha256(Path(__file__)),
        "exit_code": exit_code,
        "outer_timeout_reached": timed_out,
        "report_written": report_written,
        "report_parse_error": report_parse_error,
        "analysis_timeout_occurred": analysis_timed_out,
        "report_sha256": report_sha256,
        "console_log_sha256": sha256(output / "console.log"),
        "target_execution": "Target was supplied only as a Ghidra import; never launched.",
        "limitations": "Static inspection is not an antivirus verdict or release clearance.",
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    if (
        not manifest["sample_unchanged"]
        or not manifest["report_written"]
        or report_parse_error is not None
        or analysis_timed_out is not False
    ):
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
