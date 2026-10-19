# Development handoff and optional local memory

The development handoff preserves the checkout identity, active task, release hold,
and explicitly supplied evidence when coding work moves between sessions. It is a
standalone Python standard-library tool. SurveySync does not import it, and the
application does not require ai-memory or another agent platform.

## Generate a handoff

Run from the repository root with Python 3.12 and Git available:

```console
python scripts/dev_handoff.py --task "Continue the development tools pilot; preserve the release hold"
```

The tool writes `.dev-handoff/handoff.json` and `.dev-handoff/handoff.md`. Open the
Markdown file to review the result. Supply `--repo` when targeting a different
checkout. The output directory is excluded from Git and from the installer and
beta-fixture packaging rules. The generator refuses tracked output files and
requires the ignore rule before writing. It also rejects detected output symlinks
and Windows junctions. These checks are ordinary filesystem safeguards, not a
claim of race-proof isolation against another process changing paths concurrently.

Regenerate the handoff at the start of a new session and after a checkout change.
The old file is a dated snapshot, not live repository status.

## What it reads

The automatic inputs are deliberately small:

- Git commit, committed tree, branch, tracked file status, and untracked-file count.
- `VERSION.txt`, `RELEASE_ID.txt`, and `update.json`, with SHA-256 for successfully
  read release metadata. Conflicting version files produce an explicit warning.
- The active task passed on the command line.
- One context JSON file, only when explicitly passed with `--context`.

The helper does not fetch GitHub, inspect agent home directories, read environment
values, scan chats or survey projects, collect diffs, or open untracked file bodies.
It does not read historical QA documents or `BUILD_MANIFEST.json` as proof of a
current test pass. The Git status hash fingerprints status metadata; it is not a
hash of the contents of a dirty working tree.

Output stays local. The helper does not upload memory, change agent settings,
install hooks, clear update holds, or publish a release. It rejects several obvious
credential formats in supplied text, but this is not comprehensive content
scrubbing. Review task descriptions and context before sharing them. Files are
not encrypted by this tool; the local account and filesystem remain the privacy
boundary.

## Add sourced work and validation context

Store an optional input at `.dev-handoff/context.json`, then run:

```console
python scripts/dev_handoff.py --task "Continue development from the current checkout" --context .dev-handoff/context.json
```

The file uses this structure. This is a **dated historical example**, not a live PR
or acceptance result. Refresh its sources and timestamp before using it as new
evidence:

```json
{
  "schema_version": 1,
  "active_work": [
    {
      "summary": "Security repair remains a separate pull request from the development tools pilot.",
      "source": "https://github.com/cpaul1988/SurveySync/pull/25",
      "checked_utc": "2026-10-19T12:43:26Z",
      "state": "open",
      "commit": "1dbd79f9412cebcc0065c7d1ceb724c91e297f58",
      "tree": "e5da65b79e2f3d42116ea032c30e7bcab4a863e1"
    }
  ],
  "evidence": [
    {
      "kind": "acceptance",
      "result": "passed",
      "summary": "Reported Windows acceptance is tied to the separate security-repair commit.",
      "source": "https://github.com/cpaul1988/SurveySync/actions/runs/38997702407",
      "checked_utc": "2026-10-19T12:43:26Z",
      "commit": "1dbd79f9412cebcc0065c7d1ceb724c91e297f58",
      "tree": "e5da65b79e2f3d42116ea032c30e7bcab4a863e1"
    }
  ]
}
```

`active_work` records a sourced state (`open`, `merged`, `closed`, or `unknown`) as
of `checked_utc`. It is separate from the actual checked-out commit. This preserves
open work such as PR #25 without confusing its acceptance with main or another
development branch.

Evidence kinds are `ci`, `test`, `feedback`, and `acceptance`. Results are `passed`,
`failed`, `pending`, or `not_run`; feedback additionally permits `reviewed`.
Each record needs a concise summary, source, and UTC timestamp. A source can be an
HTTPS URL without credentials/query strings, or a `local:` description identifying
an actual command or local record. The helper records these references without
opening them. Use full commit IDs; an optional tree must belong to that commit.
Keep feedback summaries limited to sanitized status and identifiers, not messages,
email addresses, or attachments.

| Supplied evidence | How the handoff represents it |
| --- | --- |
| Different commit | Historical evidence for another commit |
| Matching commit, dirty workspace | The commit matches; current workspace changes are not covered |
| Matching commit, clean workspace | A supplied claim matching the checked-out commit; its source is still not independently verified |
| No commit | Evidence not bound to a commit |
| Tree contradicts the current commit | Reject the context input |
| Missing or malformed updater state | Hold status is unknown, never silently cleared |

There is no overall "all checks passed" calculation. Every evidence record keeps
its source, checked time, scope, and attribution. This tool cannot confer release
clearance, including when a supplied record says `passed`.

## Optional ai-memory pilot

[ai-memory](https://github.com/akitaonrails/ai-memory) can provide searchable local
notes and an explicit handoff for another coding session. It is optional. Keep the
Git-based handoff above as the checkpoint that must be regenerated before resuming.
Do not let a recalled note override current Git, updater state, or release gates.

On 2026-10-19, a bounded Linux pilot used the official
[v3.1.1 release](https://github.com/akitaonrails/ai-memory/releases/tag/v3.1.1).
The 19,778,279-byte `ai-memory-linux-x86_64.tar.gz` archive matched both its
published checksum file and GitHub asset digest:

```text
d055aef2989eeceb08da7a2db3533d9389a689058c57b5f8a03d5f4439225a2d
```

Only the binary, license, default configuration reference, and installation
reference were extracted into an isolated development directory. The trial used
explicit `--data-dir` and `--config` arguments, MCP over standard input/output,
`--no-watcher`, `embedding_provider = "none"`, no LLM provider, and a disabled
auto-improvement scheduler. Disabling embeddings also avoided the optional local
model download. No global/user agent configuration, hooks, services, or application
dependencies were installed.

The trial imported two public-code-only notes, stopped the server, and opened a
second MCP client session. Search retrieved the PR #25 note; a full-page read
retained the exact commit, tree, and acceptance source. A pending handoff survived
the restart. Its first acceptance returned `claimed`; a second acceptance returned
`none_pending`. Both server processes were stopped after the trial.

This verifies the selected binary's local import, retrieval, persistence, and
single-use handoff mechanism on this Linux host. It does not verify native Windows
behavior, automatic Codex/Claude hook integration, retrieval quality on a large
history, or prevention of a coding-chat freeze. Upstream currently labels native
Windows experimental and WSL2 supported; see its
[support matrix](https://github.com/akitaonrails/ai-memory/blob/v3.1.1/docs/support-matrix.md).

Any future integration should start with a separate private store, explicitly
selected notes, and current source references. Do not run `setup`, `backfill`, or
agent hook installation merely to reproduce this bounded pilot. Those commands
have a broader scope than the import/search/handoff trial performed here.

## Focused verification

```console
python -m pytest -q tests/test_dev_handoff.py tests/test_development_packaging.py
python -m ruff check --select F scripts/dev_handoff.py tests/test_dev_handoff.py
python -m ruff format --check scripts/dev_handoff.py tests/test_dev_handoff.py
```

Regressions exercise stale and dirty-checkout evidence, absent commit binding,
contradictory trees/versions, malformed updater/context data, unexpected file reads,
credential-bearing inputs, ignored output requirements, and redirected paths.
Packaging regressions check that private handoffs stay out of installer and fixture output.
The Windows junction regression runs on Windows; it is explicitly skipped on
other platforms. These tests concern developer tooling, not SurveySync's installed
application acceptance.
