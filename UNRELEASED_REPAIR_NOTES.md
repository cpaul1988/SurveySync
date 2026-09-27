# Unreleased repair candidate — verified 9.4 audit defects

Corrects repeat LandXML import, PointID headers, non-finite numeric input, exact-closure JSON, mixed-unit pipe grades, large-coordinate polygon precision, blocked navigation/Exit commands, native shutdown, corrupt-ledger recovery and manual Ron control repeat/identity/code output. Explicit level-book row-layout selection retains Ron's reduction conventions. Previous valid control results and report history survive handled recalculation failures.

The shutdown watcher now follows Runtime replacement during project switching. New tests preserve that behavior alongside source-ID attribution, unit calculations, rollback and Windows file locking.

## Verified Windows checkpoint

Application/test commit `c79f37c1b6c9e4b342775a081b46315359457038` passed Windows Quality #182, UI Validation #17 and Repair Acceptance #4. The unchanged release gate recorded **471 passed, 1 skipped**. Real installation, native project create/reopen, four control revisions, API shutdown, actual Windows file selection/cancellation, Point Range CSV/TXT/XLSX generation and actual File -> Exit passed. No native bridge was mocked. Detailed source and artifact identities are recorded in `docs/VERIFIED_AUDIT_REPAIRS.md`.

## Not yet a release

This is not published 9.4.0 Beta.4 and is not a new Stable release. Existing version stamps remain for internal regression testing only. Do not distribute this candidate as the previously approved installer. Full staged updater replacement, G01–G05 desktop completion, live OCR/provider accuracy, official Trimble/external GIS checks and rod-height field calibration remain open. No user project or published update feed was changed.
