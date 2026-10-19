"""Regression checks for misleading handoffs and unintended information capture."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev_handoff.py"
SPEC = importlib.util.spec_from_file_location("dev_handoff", SCRIPT)
handoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handoff)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def commit(repo):
    git(repo, "add", "--all")
    git(
        repo,
        "-c",
        "user.name=Handoff test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    (root / ".gitignore").write_text("/.dev-handoff/\n.env\n", encoding="utf-8")
    (root / "VERSION.txt").write_text("9.5.3", encoding="utf-8")
    (root / "RELEASE_ID.txt").write_text("9.5.3-beta.1", encoding="utf-8")
    (root / "update.json").write_text(
        json.dumps(
            {
                "release_hold": {
                    "active": True,
                    "channels": ["beta", "stable"],
                    "reason": "Security review remains open.",
                },
                "channels": {"developer": {"version": "9.2.6"}},
            }
        ),
        encoding="utf-8",
    )
    (root / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
    commit(root)
    return root


def context_file(repo, evidence=None, active_work=None):
    private = repo / ".dev-handoff"
    private.mkdir(exist_ok=True)
    path = private / "context.json"
    path.write_text(
        json.dumps(
            {"schema_version": 1, "evidence": evidence or [], "active_work": active_work or []}
        ),
        encoding="utf-8",
    )
    return path


def evidence(commit_sha=None, **extra):
    value = {
        "kind": "test",
        "result": "passed",
        "summary": "A focused test command completed.",
        "source": "local:python -m pytest tests/test_dev_handoff.py",
        "checked_utc": "2026-10-17T19:00:00Z",
    }
    if commit_sha:
        value["commit"] = commit_sha
    value.update(extra)
    return value


def test_old_pass_cannot_become_current_after_another_commit(repo):
    old = git(repo, "rev-parse", "HEAD")
    (repo / "tracked.py").write_text("VALUE = 2\n", encoding="utf-8")
    new = commit(repo)
    output = handoff.build_handoff(
        repo, "Continue development", context_file(repo, [evidence(old)])
    )
    assert output["repository"]["head_commit"] == new
    assert output["evidence"][0]["scope"] == "different_commit"
    assert output["evidence"][0]["release_clearance"] is False
    assert output["release"]["hold_status"] == "active"


def test_matching_sha_is_only_a_reported_claim_and_dirty_workspace_invalidates_scope(repo):
    sha = git(repo, "rev-parse", "HEAD")
    context = context_file(repo, [evidence(sha)])
    clean = handoff.build_handoff(repo, "Test continuation", context)
    assert clean["evidence"][0]["scope"] == "matches_clean_checkout_commit"
    assert "not fetched or independently verified" in clean["evidence"][0]["provenance"]
    (repo / "tracked.py").write_text("VALUE = 9\n", encoding="utf-8")
    dirty = handoff.build_handoff(repo, "Test continuation", context)
    assert dirty["evidence"][0]["scope"] == "same_commit_but_workspace_changed"
    assert dirty["repository"]["head_tree"] == clean["repository"]["head_tree"]


def test_missing_commit_never_infers_current_pass(repo):
    output = handoff.build_handoff(repo, "Review evidence", context_file(repo, [evidence()]))
    assert output["evidence"][0]["scope"] == "unbound_to_commit"


def test_other_open_pr_and_its_commit_survive_as_separate_work(repo):
    reference = {
        "summary": "Separate security repair with its own acceptance history.",
        "source": "https://github.com/cpaul1988/SurveySync/pull/25",
        "state": "open",
        "commit": "1dbd79f9412cebcc0065c7d1ceb724c91e297f58",
        "checked_utc": "2026-10-19T13:00:00Z",
    }
    # Use a fixed past timestamp so this regression is independent of the runner's date.
    reference["checked_utc"] = "2026-10-17T19:00:00Z"
    output = handoff.build_handoff(
        repo, "Development pilot", context_file(repo, active_work=[reference])
    )
    assert output["active_work"][0]["commit"] == reference["commit"]
    assert output["active_work"][0]["state"] == "open"
    assert output["repository"]["head_commit"] != reference["commit"]
    assert not output["evidence"]


def test_does_not_read_logs_fieldbooks_env_or_historical_passes(repo, monkeypatch):
    (repo / "BUILD_MANIFEST.json").write_text('{"qa":"OLD UNBOUND PASS CANARY"}', encoding="utf-8")
    (repo / "private-fieldbook.txt").write_text("SURVEY DATA CANARY", encoding="utf-8")
    (repo / ".env").write_text("PRIVATE_CREDENTIAL=SECRET FILE CANARY", encoding="utf-8")
    monkeypatch.setenv("SURVEYSYNC_HANDOFF_TEST_SECRET", "SECRET ENV CANARY")
    original = Path.open
    permitted = {repo / name for name in ("VERSION.txt", "RELEASE_ID.txt", "update.json")}

    def guarded_open(path, *args, **kwargs):
        assert path in permitted, f"Unexpected file read: {path.name}"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    output = handoff.build_handoff(repo, "Read only intended metadata")
    encoded = json.dumps(output)
    assert "CANARY" not in encoded
    assert "private-fieldbook.txt" not in encoded
    assert output["repository"]["untracked_file_count"] == 2
    assert output["evidence"] == []


@pytest.mark.parametrize(
    "manifest",
    [
        '{"release_hold":{"active":"false"},"channels":{}}',
        '{"release_hold":{"active":false,"channels":"stable"},"channels":{}}',
        '{"release_hold":{"active":true,"active":false},"channels":{}}',
        '{"channels":[]}',
        '{"channels":NaN}',
        "{broken",
    ],
)
def test_malformed_update_state_fails_to_unknown(repo, manifest):
    (repo / "update.json").write_text(manifest, encoding="utf-8")
    result = handoff.build_handoff(repo, "Inspect hold state")
    assert result["release"]["hold_status"] == "unknown"
    assert result["release"]["warnings"]
    assert result["release"]["release_clearance"] == "not_assessed_by_this_development_tool"


def test_absent_hold_is_not_release_clearance(repo):
    (repo / "update.json").write_text('{"channels":{}}', encoding="utf-8")
    result = handoff.build_handoff(repo, "Inspect release state")
    assert result["release"]["hold_status"] == "not_declared"
    assert result["release"]["release_clearance"] == "not_assessed_by_this_development_tool"


def test_conflicting_version_files_warn_instead_of_certifying_identity(repo):
    (repo / "RELEASE_ID.txt").write_text("9.5.4-beta.1", encoding="utf-8")
    result = handoff.build_handoff(repo, "Review identity")
    assert result["release"]["identity_consistent"] is False
    assert any("disagree" in warning for warning in result["release"]["warnings"])


@pytest.mark.parametrize(
    "bad",
    [
        {"schema_version": 1, "raw_chat": "should not be accepted"},
        {"schema_version": True},
        {"schema_version": 1, "evidence": [evidence("abc")]},
        {"schema_version": 1, "evidence": [evidence(checked_utc="2099-01-01T00:00:00Z")]},
        {"schema_version": 1, "evidence": [evidence(checked_utc="2026-10-17")]},
        {
            "schema_version": 1,
            "evidence": [evidence(source="https://user:password@example.org/log")],
        },
        {"schema_version": 1, "evidence": [evidence(source="https://example.org/log?token=abc")]},
        {"schema_version": 1, "evidence": [evidence(source="https://[invalid")]},
        {"schema_version": 1, "evidence": [evidence(summary="api_key=do-not-copy-this")]},
    ],
)
def test_malformed_or_sensitive_context_is_rejected_without_echo(repo, bad):
    path = context_file(repo)
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(handoff.HandoffError) as error:
        handoff.build_handoff(repo, "Inspect context", path)
    assert "do-not-copy-this" not in str(error.value)


def test_wrong_tree_for_same_commit_is_rejected(repo):
    context = context_file(repo, [evidence(git(repo, "rev-parse", "HEAD"), tree="f" * 40)])
    with pytest.raises(handoff.HandoffError, match="contradicts"):
        handoff.build_handoff(repo, "Review tree identity", context)


def test_output_requires_ignore_and_refuses_tracked_destinations(repo):
    snapshot = handoff.build_handoff(repo, "Test private output")
    (repo / ".gitignore").unlink()
    with pytest.raises(handoff.HandoffError, match="gitignore"):
        handoff.write_handoff(repo, snapshot)
    assert not (repo / ".dev-handoff").exists()
    (repo / ".gitignore").write_text("/.dev-handoff/\n", encoding="utf-8")
    output = handoff.write_handoff(repo, snapshot)
    assert json.loads((output / "handoff.json").read_text())["repository"] == snapshot["repository"]
    git(repo, "add", "-f", ".dev-handoff/handoff.md")
    with pytest.raises(handoff.HandoffError, match="tracked"):
        handoff.write_handoff(repo, snapshot)


def test_named_symlink_does_not_read_external_content(repo, tmp_path):
    target = tmp_path / "outside.json"
    target.write_text('{"schema_version":1}', encoding="utf-8")
    link = repo / "context-link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("The runner cannot create a symlink without additional privilege.")
    with pytest.raises(handoff.HandoffError, match="symlink"):
        handoff.build_handoff(repo, "Inspect explicit context", link)


def test_output_directory_redirect_is_rejected_before_writing(repo, tmp_path):
    outside = tmp_path / "other-output"
    outside.mkdir()
    output = repo / ".dev-handoff"
    try:
        output.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("The runner cannot create a symlink without additional privilege.")
    snapshot = handoff.build_handoff(repo, "Inspect output location")
    with pytest.raises(handoff.HandoffError, match="redirected"):
        handoff.write_handoff(repo, snapshot)
    assert list(outside.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction regression")
def test_windows_junction_output_is_rejected(repo, tmp_path):
    outside = tmp_path / "junction-target"
    outside.mkdir()
    output = repo / ".dev-handoff"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(output), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        pytest.skip("The runner cannot create a directory junction.")
    snapshot = handoff.build_handoff(repo, "Inspect Windows output location")
    with pytest.raises(handoff.HandoffError, match="redirected"):
        handoff.write_handoff(repo, snapshot)
    assert list(outside.iterdir()) == []


def test_duplicate_and_oversized_context_are_rejected(repo):
    path = context_file(repo)
    for raw in ('{"schema_version":1,"schema_version":1}', " " * (handoff.MAX_INPUT_BYTES + 1)):
        path.write_text(raw, encoding="utf-8")
        with pytest.raises(handoff.HandoffError):
            handoff.build_handoff(repo, "Inspect context", path)
