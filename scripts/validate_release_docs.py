from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()

REQUIRED_DOCS = [
    "CHANGELOG.md",
    "docs/ARCHITECTURE.md",
    "docs/FEATURE_MATRIX.md",
    "docs/DATA_FLOW.md",
    "docs/FIELDBOOKSYNC.md",
    "docs/PROJECT_SYSTEM.md",
    "docs/API_REFERENCE.md",
    "docs/DECISIONS.md",
    "docs/KNOWN_ISSUES.md",
    "docs/TEST_COVERAGE.md",
    "docs/RELEASE_HISTORY.md",
    "docs/RELEASE_CHECKLIST.md",
    "docs/FIELD_NOTE_PROFILE_TRAINER.md",
    "docs/OPEN_SOURCE_INTEGRATION_PLAN.md",
    "THIRD_PARTY_NOTICES.md",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"Documentation gate failed: {message}")


def main() -> None:
    require(VERSION, "VERSION.txt is empty")
    for rel in REQUIRED_DOCS:
        path = ROOT / rel
        require(path.is_file(), f"missing {rel}")
        text = path.read_text(encoding="utf-8").strip()
        require(len(text) >= 80, f"{rel} is unexpectedly empty")

    changelog = ROOT / "CHANGELOG.md"
    require(VERSION in changelog.read_text(encoding="utf-8"), "CHANGELOG.md does not name current version")

    release = ROOT / f"RELEASE_NOTES_v{VERSION.replace('.', '_')}.md"
    qa = ROOT / f"QA_REPORT_v{VERSION.replace('.', '_')}.md"
    require(release.is_file(), f"missing {release.name}")
    require(qa.is_file(), f"missing {qa.name}")
    require(VERSION in release.read_text(encoding="utf-8"), "release notes do not name current version")
    require(VERSION in qa.read_text(encoding="utf-8"), "QA report does not name current version")

    index_path = ROOT / "IMPLEMENTATION_INDEX.json"
    require(index_path.is_file(), "missing IMPLEMENTATION_INDEX.json")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    require(index.get("version") == VERSION, "implementation index version does not match VERSION.txt")
    features = index.get("features") or {}
    require(features, "implementation index has no features")
    for name, spec in features.items():
        for key in ("implementation", "tests", "documentation"):
            values = spec.get(key) or []
            require(values, f"{name} has no {key} entries")
            for rel in values:
                require((ROOT / rel).exists(), f"{name} references missing {rel}")

    manifest_path = ROOT / "BUILD_MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(manifest.get("version") == VERSION, "BUILD_MANIFEST version does not match VERSION.txt")
        feedback = manifest.get("feedback") or {}
        require(feedback.get("checked_before_build") is True, "BUILD_MANIFEST does not record the required pre-build feedback check")

    print(f"SurveySync {VERSION} documentation gate passed ({len(REQUIRED_DOCS)} living docs, {len(features)} indexed features).")


if __name__ == "__main__":
    main()
