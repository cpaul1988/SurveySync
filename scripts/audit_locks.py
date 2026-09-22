"""Audit every pinned platform branch, including Windows pins on Linux QA hosts."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCKS = ("requirements.lock", "requirements-dev.lock", "requirements-windows-ai.lock")
PIN = re.compile(r"^([A-Za-z0-9_.-]+(?:\[[^]]+\])?==[^\s;\\]+)", re.MULTILINE)


def pinned_packages(text: str) -> set[str]:
    return set(PIN.findall(text))


def main() -> int:
    pins: set[str] = set()
    for name in LOCKS:
        found = pinned_packages((ROOT / name).read_text(encoding="utf-8"))
        if not found:
            raise ValueError(f"{name}: empty dependency lock")
        pins.update(found)
    with tempfile.TemporaryDirectory(prefix="surveysync-audit-") as folder:
        req = Path(folder) / "all-platform-pins.txt"
        req.write_text("\n".join(sorted(pins)) + "\n", encoding="utf-8")
        print(f"Auditing {len(pins)} exact pins across all platform branches.", flush=True)
        return subprocess.run(
            [sys.executable, "-m", "pip_audit", "--no-deps", "--disable-pip", "-r", str(req)],
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
