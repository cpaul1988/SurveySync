# SurveySync v9.2.1 BetaCandidate QA Report

## Scope

This QA pass covers the v9.2.1 Operations Center/platform-hardening work: project health/rules, staged point imports and learned mappings, continuity snapshots, comparisons, export/package profiles, project map/review explanations, and persisted background tasks/batch work. It also retains the v9.2.0 ControlSync revision regression suite and prior v9.x reliability tests.

## Automated validation

- Python source compilation: required before packaging.
- Main SurveySync JavaScript syntax: required before packaging.
- FieldBookSync JavaScript syntax: required before packaging.
- Documentation gate: required before packaging.
- Maintained pytest suite: **203 passed, 0 failed** (`tests/` plus the selected FieldBookSync legacy regression suites used by `Build_SurveySync.ps1`).
- `tests/test_v921_operations.py` specifically covers the new project-wide health/rules behavior, staging/duplicate protection, snapshot restore/autosave/timeline, point-file/project comparison, export profiles/package manifests, map/review/Why evidence, background queue completion/failure, Operations Center APIs, and deterministic SQLite-handle closure for Windows snapshot cleanup.

## Windows BetaCandidate fix

- The first Windows compile exposed a real snapshot cleanup defect: Python's `sqlite3.Connection` transaction context manager does not close the underlying handle on exit. Windows therefore kept the temporary `survey_sync.db` locked and `TemporaryDirectory` cleanup failed with `WinError 32`.
- `surveysync/continuity.py` now uses deterministic `closing(...)` semantics for snapshot backup, snapshot comparison, and live WAL checkpoint connections.
- A regression test explicitly verifies the snapshot backup source and destination handles are closed.

## Safety assertions

- Existing PointIDs are skipped and reported during staged commit; no duplicate overwrite path was added.
- Coordinate sanity checks return warnings only and do not transform coordinates.
- Snapshot restore verifies snapshot checksum/project identity and creates a pre-restore safety snapshot.
- Background task failures persist for review rather than disappearing from the UI.
- Deliverable packages include per-file SHA-256 checksums.

## Current-runtime limitation

This Linux packaging runtime validates Python/JavaScript/tests and can inspect the existing Windows binaries, but it does not compile the final Inno Setup installer. The included `SurveySync.exe` retains Windows GUI-subsystem metadata and its same-length embedded source-candidate version literal is advanced to 9.2.1. The normal Windows build must rebuild the Go launchers and compile `SurveySync_Setup_9.2.1.exe` before Stable promotion.

## Required real-machine Beta checks

Exercise v9.2.1 on Windows by updating an existing v9.2.0 installation, then test forced-close recovery, manual snapshot/restore, staged duplicate PointIDs, another-project comparison, custom export profile/package generation, batch cancellation/failure, Review Center/Why explanations, Point Range, Trimble JOB, FieldBookSync Review, diagnostics/updater consent, and ControlSync revision restore/reporting. Promote only the exact field-tested installer/hash.
