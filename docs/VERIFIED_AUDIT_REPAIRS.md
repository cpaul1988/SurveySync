# Unreleased 9.4 verified-audit repairs

## Verified checkpoint — September 27, 2026

The earlier saved-package handoff was Linux-only and blocked from GitHub. That limitation is resolved. Repairs are on `fix-v9.4.0-verified-audit`, draft PR #12, based on unchanged Stable main `9965284c69e6a7cd95fe0750838130f4a39bd6e2`.

Application/test source `c79f37c1b6c9e4b342775a081b46315359457038` passed all three Windows workflows: Quality #182 (`36350961422`), UI Validation #17 (`36350961424`), and Repair Acceptance #4 (`36350961418`). The exact PR-merge checkout archived by Repair Acceptance is `94ea0e422f97cec8c3e77e7c263d126c63fb0637`. This documentation-only follow-up does not change those application/test bytes.

The unchanged release gate recorded **471 passed, 1 skipped**, with 60.82% instrumented line coverage against its unchanged 54% floor. The suite contains 78 retained audit/repair/bridge cases in addition to the original selection. Ruff, formatting, mypy (29 governed files), documentation, static quality, Python compilation, JavaScript syntax and dependency-lock audit passed. The source-only native-binary test skips before compilation; the Windows build subsequently verified both compiled PE/GUI launchers. These results are not a claim that all possible workflows or inputs are bug-free.

## Repair matrix

| Audit | Correction and verified scope |
|---|---|
| A01 | Repeated LandXML imports resolve the existing immutable source's usable path; repeat API import passes. |
| A02/A03 | Leveling and Field-to-Finish accept supported PointID header aliases without changing actual identifiers, including leading zeros. |
| A04 (qualified layout risk) | Explicit paired-setup, separate-sight and station-row layouts. Ambiguous turning-point rows require a choice; point/HI roles are distinguished. Original Ron reduction remains unchanged; no implicit closure adjustment. The actual row-layout control passes. |
| A05 | Reject non-finite readings and coordinates at covered import/direct-calculation boundaries; reject unsupported declared units and negative tolerances. |
| A06 | Perfect traverse closure is JSON-safe with an explicit status and null precision ratio; coordinates are not perturbed. |
| A07 | Pipe grade converts declared vertical and horizontal units; all nine unit pairs and adverse grades pass. Original measurements are retained. |
| A08/A09 | Correct collection selectors for Survey Data, Data Inspector and Support Center; File Exit calls the exposed exit_app bridge. Real menu/toolbar tests and installed File Exit pass. |
| A10 | Local-origin polygon area/centroid with accurate summation; large coordinates, small parcels and both orientations pass. |
| A11 | Native WebView consumes the API/updater shutdown signal. The watcher follows Runtime replacement after project switching. Installed API exit and File Exit close the process and local service. Full replacement updating remains separate. |
| A12/A14/A15 | Manual control retains exact PointIDs, selection order and first-shot code. Repeat calculations create distinct revisions/report folders. Solve/export/audit failures roll back to the previous valid set; concurrent requests serialize. Residual identity is independent of list position. |
| A13 | Close partially initialized SQLite connections before quarantine. Preserve corrupt ledger/sidecars; fail visibly on rename errors instead of reopening damaged data. Windows recovery tests pass. |

## Actual installed-Windows evidence

Repair Acceptance compiled and silently installed the real candidate, including its private runtime, into a disposable runner directory. Tests verified selected installed source bytes against the tested checkout, launched the real SurveySync.exe, created/reopened a temporary project, and computed manual control revisions 1–4 across two sessions. Source codes and residual PointIDs were checked. API-triggered shutdown exited with code zero and closed port 8765 in **6.312 and 5.891 seconds**.

A separate installed WebView2 test used the actual exposed native bridge and a real Windows Open dialog to select a three-point survey CSV. The real Point Range button produced CSV, TXT and XLSX reports. CSV was parsed and XLSX reopened with openpyxl; the source file remained byte-for-byte unchanged. A second dialog was cancelled and retained the previous selection. The actual File -> Exit menu then closed the launcher and API in **7.125 seconds**, with no uncaught JavaScript errors in that sequence. The browser was not closed by the test before checking File Exit.

Only this disposable test process enables pywebview remote debugging through a temporary child-scoped hook. The launcher, installed application source and native bridge are not replaced or mocked; production debugging remains off. This is not validation of every workstation, DPI setting, file-picker filter, export format or target CAD/GIS program. The dialog screenshot was captured early in painting; interaction/result assertions, not that screenshot alone, establish picker acceptance.

Existing 11-module light/dark and 16-theme switching/branding acceptance also passed. Additional local deterministic numeric stress checks passed 1,500 level-layout cases and 1,000 translated-polygon cases; those are supplementary checks, not extra pytest test counts.

## Artifact identities

Repair Acceptance evidence artifact: `10942171999`, archive SHA-256 `44553cea352752e2de8d438e31ba559ea2564d3a121a8ab253863707c13eee05`.

Unpublished installer artifact: `10942880134`, archive SHA-256 `0b572d3a81bfa3f5e8c31f85bfd6337bed2c3a752495b9b26c657b2a594a70b6`.

Internal executable `SurveySync_Setup_9.4.0.exe`: **8,833,454 bytes**, SHA-256 `7a08f1c355b07d5cfeaf029c4f77b7165a17e31ab06807e566a696469672fb17`. The downloaded archive and executable hashes were independently recomputed and matched the recorded checksums. The internal version stamp remains 9.4.0 for regression testing; this is NOT the published Beta.4 executable and must not be distributed under its identity. A separately identified release candidate is required before user distribution.

## Preserved design and limits

Ron N/E/Z means, horizontal residuals and the special C-row vertical display convention are unchanged. This pass checks documented formula expectations with synthetic observations; it is not a fresh independent reread of his private workbook. Original source observations, report history, bulk best-three workflow and approved globe/EDSI appearance are retained.

Manual-control transactions cover handled failures and serialized SQLite writes, not atomic power-loss recovery across database and filesystem. Separate-sight rows retain instrument heights while explicitly exposing their role and point elevation. No boundary closure is forced to evade validation.

G01–G05 remain open desktop-completion work: point-cloud intake, YAML workflow management, new CRS diagnostics, template mapping and QGIS/GRASS controls. Full staged updater replacement, active analysis/provider cancellation, live OCR/AI accuracy, official Trimble binary conversion, optional external GIS execution and field-calibrated rod-height confidence remain acceptance work. No paid provider calls, live feedback test submissions or user-project mutations were made.

The pre-build Intake check returned 16 reports, latest FBR-0016. That is not proof of reporting delivery from every workstation. No application version, update-feed entry, release tag, published installer or Stable branch was changed. PR #12 remains draft and unmerged.
