# Build SurveySync 9.3.1 on Windows

This branch is the SurveySync 9.3.1 BetaCandidate source. Keep the current stable 9.3.0 installer available for rollback. User projects are stored separately from the source/build folder and must not be moved into the build tree.

## Prerequisites

Install:

- Python 3.12 x64
- Node.js 24
- Go
- Inno Setup 6

From Command Prompt in the extracted/cloned 9.3.1 source folder:

```bat
py -3.12 -m venv .build-venv
call .build-venv\Scripts\activate.bat
python -m pip install --require-hashes -r requirements-dev.lock
Compile_SurveySync_v9.3.1.cmd
```

The compile command calls the same `Build_SurveySync.ps1` release path used by release automation. It runs the fail-closed documentation, static-quality, Ruff, formatting, mypy, Python compile, JavaScript syntax, pytest/coverage, and dependency-audit gates before creating native launchers or the installer. Release checks cannot be skipped.

Expected output:

```text
installer\output\SurveySync_Setup_9.3.1.exe
installer\output\SurveySync_Setup_9.3.1.exe.sha256
```

Go rebuilds `SurveySync.exe` and `SurveySyncUpdater.exe` from the current source. Inno Setup then packages the application and locked runtime dependencies. A stale launcher must never be substituted for a failed native build.

## Required Beta acceptance

After a successful compile, install 9.3.1 over a working 9.3.0 installation and verify:

1. Existing SurveySync projects open, save, switch, and preserve settings/data.
2. A normal clean close does not show an interrupted-session warning on next launch.
3. Force-close a test session after an automatic recovery snapshot exists, reopen the same project, review the Support Center recovery notice, and restore only after explicit confirmation.
4. Run the file-association registration path and confirm it does not create a false interrupted-session warning.
5. Support Center displays diagnostics, exports a redacted support ZIP, and can sync/report a synthetic non-survey diagnostic without attaching survey source data.
6. Survey Data Inspector correctly reads representative headered and headerless point files, detects duplicates/missing values, displays the active project's CRS/units, and refreshes that context after switching projects even when the source inspection is cached.
7. Inspect a real Trimble JXL and, where the official Trimble converter is installed, a binary JOB. Confirm normalized data is a new cache artifact and the original source is unchanged.
8. Use Inspector handoff to TopoSync, ControlSync, and Point Ranges where each target is offered.
9. In TopoSync, save/reload a QC profile, analyze known positive and negative rod-height examples, save explicit review decisions, inspect run history/calibration, and export only a reviewed corrected copy.
10. Re-smoke ControlSync best-three QC, FieldBookSync analysis/profile workflow, feedback submission, updater consent, and close/install/reopen behavior.
11. Confirm application, installer, About/release notes, and update reporting all display **9.3.1**.
12. Confirm the installer SHA-256 file matches the built installer.

Do not promote to Stable solely because automated tests pass. Real Windows/WebView and representative survey-data acceptance remain required.
