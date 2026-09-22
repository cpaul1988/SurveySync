"""One fail-closed release gate for Windows builds and GitHub CI."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMATTED = [
    "surveysync/topo",
    "surveysync/api_models.py",
    "surveysync/control_math.py",
    "surveysync/operations_routes.py",
    "surveysync/survey_routes.py",
    "fieldbook_sync/api_models.py",
    "fieldbook_sync/map_routes.py",
    "fieldbook_sync/profile_routes.py",
    "fieldbook_sync/vision_pipeline.py",
    "fieldbook_sync/live_analysis.py",
    "fieldbook_sync/batch_workers.py",
    "fieldbook_sync/rod_height_qc.py",
    "scripts/release_gate.py",
    "scripts/audit_locks.py",
    "scripts/verify_native.py",
    "surveysync/control_exports.py",
]
TESTS = [
    "tests",
    "legacy_tests/test_core.py",
    "legacy_tests/test_v8117_dip_book_statuses.py",
    "legacy_tests/test_v6_features.py",
    "legacy_tests/test_v8118_feedback_wizard.py",
]


def commands(python: str, node: str) -> list[list[str]]:
    steps = [
        [python, "scripts/validate_release_docs.py"],
        [python, "scripts/validate_static_quality.py"],
        [python, "-m", "ruff", "check", "surveysync", "fieldbook_sync"],
        [python, "-m", "ruff", "check", "--select", "F", *FORMATTED],
        [python, "-m", "ruff", "format", "--check", *FORMATTED],
        [python, "-m", "mypy"],
        [python, "-m", "compileall", "-q", "surveysync", "fieldbook_sync", "tracker_endpoint"],
    ]
    for folder in ("surveysync/static", "fieldbook_sync/static"):
        steps.extend(
            [node, "--check", str(p.relative_to(ROOT))]
            for p in sorted((ROOT / folder).rglob("*.js"))
        )
    steps.append(
        [
            python,
            "-m",
            "pytest",
            "-q",
            *TESTS,
            "--cov",
            "--cov-report=xml:coverage.xml",
            "--cov-report=term:skip-covered",
        ]
    )
    steps.append([python, "scripts/audit_locks.py"])
    return steps


def main() -> int:
    node = shutil.which("node")
    if node is None:
        print("Release blocked: install Node.js to run JavaScript syntax checks.", file=sys.stderr)
        return 1
    for command in commands(sys.executable, node):
        print("Gate:", " ".join(command), flush=True)
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            print("Release blocked by the failed check above.", file=sys.stderr)
            return result.returncode
    print("All release quality gates passed. Windows acceptance testing is still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
