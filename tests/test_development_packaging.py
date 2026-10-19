"""Private development notes must never enter a staged application payload."""

from fnmatch import fnmatchcase
from pathlib import Path
import re

import pytest

from scripts.build_beta_fixture import copy_fixture_source


ROOT = Path(__file__).resolve().parents[1]


def test_fixture_copy_preserves_source_and_omits_private_notes(tmp_path):
    source = tmp_path / "source"
    fixture = tmp_path / "fixture"
    public = source / "surveysync" / "example.py"
    private = source / ".dev-handoff" / "nested" / "context.json"
    cache = source / ".pytest_cache" / "state"
    for path, data in ((public, b"public code\n"), (private, b"private note"), (cache, b"cache")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    copy_fixture_source(source, fixture)

    assert (fixture / "surveysync" / "example.py").read_bytes() == public.read_bytes()
    assert not (fixture / ".dev-handoff").exists()
    assert not (fixture / ".pytest_cache").exists()
    assert private.read_bytes() == b"private note"


@pytest.mark.parametrize(
    "private_path",
    [r".dev-handoff\handoff.json", r".dev-handoff\handoff.md", r".dev-handoff\nested\context.json"],
)
def test_recursive_installer_rule_excludes_private_handoff_tree(private_path):
    """Check the installer source contract; this is not an Inno compilation test."""
    text = (ROOT / "installer" / "SurveySync.iss").read_text(encoding="utf-8")
    rules = [
        line
        for line in text.splitlines()
        if re.search(r'^Source:\s*"\.\.\\\*"', line) and "recursesubdirs" in line
    ]
    assert rules, "Review installer packaging rules before relying on handoff exclusion."
    for rule in rules:
        match = re.search(r'Excludes:\s*"([^"]+)"', rule)
        assert match, "Recursive source inclusion must explicitly exclude private handoffs."
        patterns = match[1].lower().split(",")
        assert any(fnmatchcase(private_path.lower(), pattern) for pattern in patterns)
        assert not any(fnmatchcase(r"surveysync\example.py", pattern) for pattern in patterns)
