# Verified audit repair continuation (unreleased)

## Source integration

The saved 28-file repair package was imported on `fix-v9.4.0-verified-audit` after validating every before/after SHA-256. The decompressed migration payload identity is `bbe73d6b6f96ac61a7692a9d55f38bcc327e58220af87d41b27dad28823d61f0`. Four modified, formatting-governed files were then formatted with the locked Ruff 0.16.8. No application version, tag, published installer, main branch or update-feed entry changed. The temporary source-import workflow/payload were removed after integration.

## Windows evidence and follow-up

Run 36348822822 passed the full release gate (470 passed, 1 skipped), Ruff, mypy, documentation, compilation, JavaScript and dependency checks. Actual menu/toolbar and level-layout controls passed, as did existing module and theme browser acceptance. The real installer compiled and installed successfully on the disposable Windows runner. The installed native launcher created/reopened a temporary project, computed control revisions 1 through 4 in two sessions, preserved codes/PointIDs, and exited with code zero while closing the API in 7.406 and 5.719 seconds.

The added real native file-picker test did not reach the picker: its test-only remote-debugging connection timed out. This is not a successful picker/exit-menu check or an established product picker defect. The follow-up enables pywebview's documented REMOTE_DEBUGGING_PORT setting through a temporary sitecustomize hook scoped to the disposable child Python executable. The actual launcher, installed application source, production settings and bridge remain unchanged; no persistent debug endpoint is added.

Review also found that the first shutdown watcher could remain bound to a Runtime replaced when switching projects. It now observes the current runtime with bounded waits. A fourth bridge regression reproduces the replacement deterministically; all four bridge tests pass locally. The full next candidate therefore has 471 expected passing tests plus the existing skip, but that is not a claim about its pending Windows run.

## Acceptance gate

`SurveySync Repair Acceptance` runs the unchanged release gate, real command/layout controls, existing 11-module and 16-theme checks, actual Inno installation/private-runtime provisioning, native control/exit/reopen acceptance and real Windows picker/report/Exit interactions. Installer artifacts are retained only after all required steps succeed. Evidence is retained on both success and failure.

CI output is an **unreleased audit repair artifact**, not a new beta or Stable release. Existing numbering is retained for internal acceptance only; do not distribute it as the published Beta.4. A separately identified release candidate is required before distribution.

## Boundaries

The full updater replacement cycle remains acceptance work. The five backend-only desktop workflows remain open. No live OCR/paid-provider calls, official Trimble binary conversion, external GIS execution or rod-height confidence calibration is claimed. Ron's calculation profiles, source observations, approved appearance and previous reports must remain intact.

Pre-build Intake was read through row 1001 on 2026-09-27: 16 reports, latest FBR-0016. No tracker records were changed.
