# Verified audit repair continuation (unreleased)

## Source integration

The saved 28-file repair package was imported on `fix-v9.4.0-verified-audit` after validating every before/after SHA-256. The decompressed migration payload identity is `bbe73d6b6f96ac61a7692a9d55f38bcc327e58220af87d41b27dad28823d61f0`. Four modified, formatting-governed files were then formatted with the locked Ruff 0.16.8. No application version, tag, published installer, main branch or update-feed entry changed. The temporary source-import workflow/payload were removed after integration.

The resumed local Linux run recorded 470 passed, 1 skipped. This is not installed-Windows acceptance.

## Windows acceptance gate

`SurveySync Repair Acceptance` adds checks beyond the unchanged existing release gate:

- real menu and toolbar command paths for Survey Data, Data Inspector and Support Center;
- explicit level row-layout control;
- existing 11-module/light-dark and 16-theme branding tests;
- compilation of both native launchers and the real Inno Setup installer;
- private-runtime provisioning in a disposable runner installation;
- installed-source byte checks, synthetic project creation, four manual-control revisions in two application sessions, code/PointID attribution, orderly exit and reopening;
- full release tests including deliberate corrupt-job-ledger recovery on Windows.

CI installer output is an **unreleased audit repair artifact**, not a new beta or Stable release. Existing build numbering is retained for internal acceptance only; do not distribute it as the published Beta.4. A separately identified release candidate is required before distribution.

## Boundaries

The real updater replacement cycle and native file-picker interaction still require acceptance. The five backend-only desktop workflows remain open. No live OCR/paid-provider calls, official Trimble binary conversion, external GIS execution or rod-height confidence calibration is claimed. Ron's calculation profiles, source observations, approved appearance and previous reports must remain intact.

Pre-build Intake was read through row 1001 on 2026-09-27: 16 reports, latest FBR-0016. No tracker records were changed.
