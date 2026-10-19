"""Generate a private, source-labelled development handoff using only the stdlib.

This is a developer aid, not a release gate or an automatic memory uploader.
It reads Git metadata, three named release files, and an explicitly supplied
context file. It never discovers chats, opens project data, or reads test logs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

MAX_INPUT_BYTES = 64 * 1024
SHA = re.compile(r"(?:[a-f0-9]{40}|[a-f0-9]{64})\Z")
VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){1,3}(?:[-+][0-9A-Za-z.-]+)?\Z")
SENSITIVE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    r"|\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b"
    r"|(?:password|secret|access[_ -]?token|api[_ -]?key|authorization)\s*[:=]\s*\S{4,}",
    re.IGNORECASE,
)


class HandoffError(ValueError):
    """Input cannot safely be represented as a development handoff."""


def clean_text(value: object, label: str, limit: int = 1200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise HandoffError(f"{label} must be a nonempty string of at most {limit} characters.")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise HandoffError(f"{label} contains a control character.")
    if SENSITIVE.search(value):
        raise HandoffError(f"{label} appears to contain a credential; remove it before continuing.")
    return value.strip()


def fields(value: object, allowed: set[str], required: set[str], label: str) -> dict:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - allowed:
        raise HandoffError(f"{label} has missing or unsupported fields.")
    return value


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise HandoffError("JSON contains a duplicate field.")
        result[key] = value
    return result


def read_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise HandoffError("A named input is missing, is not a file, or is a symlink.")
    with path.open("rb") as stream:
        data = stream.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise HandoffError("A named input exceeds the 64 KiB limit.")
    return data


def parse_json(data: bytes) -> dict:
    def invalid_constant(_: str) -> None:
        raise HandoffError("JSON contains a non-finite number.")

    try:
        value = json.loads(
            data.decode("utf-8-sig"),
            object_pairs_hook=unique_object,
            parse_constant=invalid_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise HandoffError("A named JSON input is malformed.") from exc
    if not isinstance(value, dict):
        raise HandoffError("A named JSON input must contain an object.")
    return value


def git(repo: Path, *args: str) -> bytes:
    try:
        run = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(repo), *args],
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HandoffError("Git is unavailable or did not finish in 20 seconds.") from exc
    if run.returncode:
        # Git errors can contain remote URLs or credentials. Do not copy stderr.
        raise HandoffError("Git could not inspect this checkout.")
    return run.stdout


def git_snapshot(repo: Path) -> dict:
    if Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve() != repo:
        raise HandoffError("--repo must name the root of the checkout.")
    head = git(repo, "rev-parse", "--verify", "HEAD").decode().strip()
    tree = git(repo, "rev-parse", "--verify", "HEAD^{tree}").decode().strip()
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").decode().strip()
    raw = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = raw.split(b"\0")
    tracked = []
    untracked_count = 0
    index = 0
    while index < len(entries) and entries[index]:
        entry = entries[index]
        if len(entry) < 4 or entry[2:3] != b" ":
            raise HandoffError("Git returned an unrecognized status record.")
        code = entry[:2].decode("ascii")
        if code == "??":
            untracked_count += 1
        else:
            # Names are metadata only. No changed/untracked file content is read.
            item = {"status": code, "path": entry[3:].decode("utf-8", "replace")}
            if "R" in code or "C" in code:
                index += 1
                if index >= len(entries) or not entries[index]:
                    raise HandoffError("Git returned an incomplete rename record.")
                item["previous_path"] = entries[index].decode("utf-8", "replace")
            tracked.append(item)
        index += 1
    return {
        "head_commit": head,
        "head_tree": tree,
        "branch": None if branch == "HEAD" else branch,
        "clean": not tracked and untracked_count == 0,
        "tracked_changes": tracked,
        "untracked_file_count": untracked_count,
        "status_sha256": hashlib.sha256(raw).hexdigest(),
    }


def timestamp(value: object, now: datetime) -> str:
    text = clean_text(value, "checked_utc", 40)
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
            raise ValueError("UTC required")
        if stamp > now + timedelta(minutes=5):
            raise ValueError("future timestamp")
    except ValueError as exc:
        raise HandoffError("checked_utc must be a real UTC timestamp, not a future time.") from exc
    return stamp.isoformat().replace("+00:00", "Z")


def source_ref(value: object) -> str:
    text = clean_text(value, "source", 800)
    if text.startswith("https://"):
        try:
            parts = urlsplit(text)
        except ValueError as exc:
            raise HandoffError("Source URL is malformed.") from exc
        if not parts.hostname or parts.username or parts.password or parts.query:
            raise HandoffError("Source URLs must be HTTPS without credentials or query strings.")
    elif not text.startswith("local:"):
        raise HandoffError("source must be an HTTPS reference or a local: evidence description.")
    return text


def commit_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise HandoffError(f"{label} must be a full lowercase Git object ID.")
    return value


def context_data(data: dict, snapshot: dict, now: datetime) -> dict:
    fields(data, {"schema_version", "active_work", "evidence"}, {"schema_version"}, "Context")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise HandoffError("Context schema_version must be 1.")
    result = {"active_work": [], "evidence": []}
    for name in ("active_work", "evidence"):
        rows = data.get(name, [])
        if not isinstance(rows, list) or len(rows) > 40:
            raise HandoffError(f"{name} must be a list of at most 40 records.")
        for row in rows:
            common = {"summary", "source", "checked_utc", "commit", "tree"}
            if name == "active_work":
                fields(row, common | {"state"}, {"summary", "source", "checked_utc", "state"}, name)
                if row["state"] not in ("open", "merged", "closed", "unknown"):
                    raise HandoffError(
                        "Active work state must be open, merged, closed, or unknown."
                    )
            else:
                fields(
                    row,
                    common | {"kind", "result"},
                    {"summary", "source", "checked_utc", "kind", "result"},
                    name,
                )
                if row["kind"] not in ("ci", "test", "feedback", "acceptance"):
                    raise HandoffError("Evidence kind must be ci, test, feedback, or acceptance.")
                if row["result"] not in ("passed", "failed", "pending", "not_run", "reviewed"):
                    raise HandoffError("Evidence result is unsupported.")
                if row["kind"] != "feedback" and row["result"] == "reviewed":
                    raise HandoffError("Only feedback evidence may have result reviewed.")
            item = {
                "summary": clean_text(row["summary"], "summary"),
                "source": source_ref(row["source"]),
                "checked_utc": timestamp(row["checked_utc"], now),
                "provenance": "explicitly supplied; source not fetched or independently verified",
            }
            for key in ("commit", "tree"):
                if key in row:
                    item[key] = commit_id(row[key], key)
            if "tree" in item and "commit" not in item:
                raise HandoffError("A tree must be accompanied by its commit.")
            if (
                item.get("commit") == snapshot["head_commit"]
                and item.get("tree", snapshot["head_tree"]) != snapshot["head_tree"]
            ):
                raise HandoffError("Evidence tree contradicts the checked-out commit.")
            if name == "active_work":
                item["state"] = row["state"]
            else:
                item.update(kind=row["kind"], result=row["result"])
                if "commit" not in item:
                    scope = "unbound_to_commit"
                elif item["commit"] != snapshot["head_commit"]:
                    scope = "different_commit"
                elif not snapshot["clean"]:
                    scope = "same_commit_but_workspace_changed"
                else:
                    scope = "matches_clean_checkout_commit"
                item["scope"] = scope
                # A matching declared SHA is useful context, never a release certificate.
                item["release_clearance"] = False
            result[name].append(item)
    return result


def release_state(repo: Path) -> dict:
    state = {
        "version": None,
        "release_id": None,
        "hold_status": "unknown",
        "advertised_channels": [],
        "sources": [],
        "warnings": [],
    }
    for filename, key in (("VERSION.txt", "version"), ("RELEASE_ID.txt", "release_id")):
        try:
            raw = read_bytes(repo / filename)
            text = raw.decode("utf-8-sig").strip()
            if not VERSION.fullmatch(text) or len(text) > 120:
                raise HandoffError("Invalid release identity.")
            state[key] = text
            state["sources"].append({"path": filename, "sha256": hashlib.sha256(raw).hexdigest()})
        except (OSError, UnicodeError, HandoffError):
            state["warnings"].append(f"{filename} missing or malformed; identity is unknown.")
    state["identity_consistent"] = None
    if state["version"] and state["release_id"]:
        state["identity_consistent"] = (
            re.split(r"[-+]", state["version"])[0] == re.split(r"[-+]", state["release_id"])[0]
        )
        if not state["identity_consistent"]:
            state["warnings"].append(
                "VERSION.txt and RELEASE_ID.txt disagree; the effective release identity is unknown."
            )
    try:
        raw = read_bytes(repo / "update.json")
        manifest = parse_json(raw)
        channels = manifest.get("channels")
        if not isinstance(channels, dict) or any(
            not isinstance(v, dict) for v in channels.values()
        ):
            raise HandoffError("Invalid channels.")
        if any(
            not isinstance(k, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,30}", k)
            for k in channels
        ):
            raise HandoffError("Invalid channel name.")
        state["advertised_channels"] = sorted(channels)
        hold = manifest.get("release_hold")
        if hold is None:
            state["hold_status"] = "not_declared"
        else:
            if not isinstance(hold, dict) or type(hold.get("active")) is not bool:
                raise HandoffError("Invalid hold state.")
            held_channels = hold.get("channels", [])
            if not isinstance(held_channels, list) or any(
                k not in ("beta", "stable", "developer") for k in held_channels
            ):
                raise HandoffError("Invalid held channels.")
            state["hold_status"] = "active" if hold["active"] else "inactive"
            state["held_channels"] = held_channels
            if "reason" in hold:
                state["hold_reason"] = clean_text(hold["reason"], "release hold reason")
        state["sources"].append({"path": "update.json", "sha256": hashlib.sha256(raw).hexdigest()})
    except (OSError, HandoffError):
        state["hold_status"] = "unknown"
        state["warnings"].append(
            "update.json missing or malformed; release hold is unknown, not cleared."
        )
    state["release_clearance"] = "not_assessed_by_this_development_tool"
    return state


def build_handoff(repo: Path, task: str, context: Path | None = None) -> dict:
    repo = repo.resolve()
    now = datetime.now(timezone.utc)
    task = clean_text(task, "task", 2000)
    snapshot = git_snapshot(repo)
    supplied = (
        context_data(parse_json(read_bytes(context)), snapshot, now)
        if context
        else {"active_work": [], "evidence": []}
    )
    release = release_state(repo)
    if git_snapshot(repo) != snapshot:
        raise HandoffError("Checkout changed while reading; regenerate the handoff.")
    return {
        "schema_version": 1,
        "generated_utc": now.isoformat().replace("+00:00", "Z"),
        "active_task": task,
        "repository": snapshot,
        "release": release,
        **supplied,
        "limits": [
            "Regenerate before resuming; Git and release state may have changed.",
            "No CI, acceptance, or feedback source is fetched automatically; supplied evidence remains an attributed claim.",
            "A pass on another commit or a changed workspace is not a pass for this checkout.",
            "Historical BUILD_MANIFEST.json, QA reports, and chat transcripts are not read as current test evidence.",
            "No survey data, file diffs, untracked file bodies, environment values, remotes, or agent home directories are read.",
            "Memory is advisory. This document cannot clear a release hold or authorize publication.",
        ],
    }


def md_text(value: object) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return (
        text.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "\\|")
    )


def render_markdown(data: dict) -> str:
    repo, release = data["repository"], data["release"]
    lines = [
        "# SurveySync development handoff",
        "",
        "Private local snapshot. Review before sharing.",
        "",
        f"Generated: {data['generated_utc']}",
        "",
        "## Active task",
        "",
        md_text(data["active_task"]),
        "",
        "## Actual checkout",
        "",
        f"- Commit: {repo['head_commit']}",
        f"- Committed tree: {repo['head_tree']}",
        f"- Branch: {md_text(repo['branch'] or 'detached HEAD')}",
        f"- Clean workspace: {repo['clean']}",
        f"- Untracked files: {repo['untracked_file_count']} (names and contents omitted)",
    ]
    for item in repo["tracked_changes"]:
        lines.append(f"- Tracked change {item['status']}: {md_text(item['path'])}")
    lines += [
        "",
        "## Release state read from this checkout",
        "",
        f"- Version: {release['version'] or 'unknown'}",
        f"- Release identity: {release['release_id'] or 'unknown'}",
        f"- Update hold: **{release['hold_status']}**",
        f"- Advertised channels: {', '.join(release['advertised_channels']) or 'none/unknown'}",
        "- Release clearance: not assessed by this developer tool.",
    ]
    if "hold_reason" in release:
        lines.append(f"- Hold reason: {md_text(release['hold_reason'])}")
    lines += [f"- Warning: {md_text(w)}" for w in release["warnings"]]
    for section, title in (
        ("active_work", "Explicitly supplied work references"),
        ("evidence", "Explicitly supplied evidence"),
    ):
        lines += ["", f"## {title}", ""]
        if not data[section]:
            lines.append("None supplied. No current pass or feedback review is inferred.")
        for item in data[section]:
            status = item.get("state", item.get("result"))
            lines += [
                f"- {md_text(status)}: {md_text(item['summary'])}",
                f"  Source: {md_text(item['source'])}; checked {item['checked_utc']}.",
                f"  Commit: {item.get('commit', 'not bound')}; scope: {item.get('scope', 'work reference only')}.",
                "  Supplied context; this generator did not independently retrieve the source.",
            ]
    lines += ["", "## Limits", ""] + [f"- {line}" for line in data["limits"]]
    return "\n".join(lines) + "\n"


def write_handoff(repo: Path, data: dict) -> Path:
    repo = repo.resolve()
    output = repo / ".dev-handoff"
    targets = [output / "handoff.json", output / "handoff.md"]
    if (
        output.is_symlink()
        or output.resolve() != output
        or any(p.is_symlink() or p.resolve() != p for p in targets)
    ):
        raise HandoffError("Refusing a redirected output destination (symlink or junction).")
    for target in targets:
        rel = target.relative_to(repo).as_posix()
        if git(repo, "ls-files", "--", rel).strip():
            raise HandoffError("Refusing to overwrite a tracked handoff file.")
        try:
            ignored = git(repo, "check-ignore", "--", rel).strip()
        except HandoffError:
            ignored = b""
        if not ignored:
            raise HandoffError("Add /.dev-handoff/ to .gitignore before generating private output.")
    output.mkdir(mode=0o700, exist_ok=True)
    for target, content in zip(targets, (json.dumps(data, indent=2) + "\n", render_markdown(data))):
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=output, delete=False
            ) as stream:
                temp_path = Path(stream.name)
                stream.write(content)
            temp_path.replace(target)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--task", required=True, help="A concise task description, without private source data."
    )
    parser.add_argument(
        "--context", type=Path, help="Explicit JSON evidence/work references; no logs are scanned."
    )
    args = parser.parse_args(argv)
    try:
        repo = args.repo.resolve()
        data = build_handoff(repo, args.task, args.context)
        write_handoff(repo, data)
    except (OSError, HandoffError) as exc:
        print(f"Handoff not written: {exc}", file=sys.stderr)
        return 2
    print("Wrote private .dev-handoff/handoff.json and .dev-handoff/handoff.md")
    print(
        f"Checkout {data['repository']['head_commit']}; update hold {data['release']['hold_status']}."
    )
    print("No release clearance is inferred from this handoff.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
