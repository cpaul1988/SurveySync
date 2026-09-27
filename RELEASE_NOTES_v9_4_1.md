# SurveySync 9.4.1 — Verified audit repairs

This release repairs the reproducible 9.4.0 defects while preserving Ron's calculation conventions, original survey evidence, prior reports and the approved globe/EDSI interface.

## Control integrity

Manual three-point averaging retains exact PointIDs, source selection order, first-shot code and residual attribution. Repeating a calculation creates another solution revision and report folder. Handled solver/export/audit failures restore the previous valid set, and concurrent manual requests serialize. The arithmetic means and special C-row vertical display convention are unchanged. Previously produced reports are not silently rewritten; review and recalculate affected work from the original observations.

## Calculations and data intake

Pipe grade converts declared horizontal and vertical units before division. Polygon area/centroid uses a local origin and accurate summation at large coordinates. Perfect traverse closure returns a JSON-safe explicit status without perturbing coordinates. Repeated LandXML intake resolves the retained source path. Leveling and Field-to-Finish accept supported PointID header aliases without modifying identifiers. Covered numeric boundaries reject NaN/infinity and invalid tolerances/units.

Level-book row layout is explicit: paired setups, separate sights, or station/turning-point rows. Ambiguous rows require selection. Point elevations and instrument heights are distinct, the starting benchmark remains fixed and adjustment is only applied when selected. Ron's three-wire reduction is retained.

## Desktop, recovery and updates

Survey Data, Data Inspector, Support Center and File Exit command paths are repaired. Native shutdown follows the current Runtime after project changes. Damaged analysis-job ledgers are closed before quarantine; failed preservation is visible rather than silently reopening damaged bytes.

Update staging validates strict numeric versions, HTTPS including redirects, bounded metadata, exact file size, SHA-256 and MZ headers. Failed downloads close handles before cleanup on Windows. A single download runs at a time; changed update configuration invalidates the handoff. Native components now honor the same configured data root. The updater runs from a copied helper outside the installation, passes the existing installation directory to Setup, records Setup's actual result and verifies the installed version.

## Version and release identity

The application, installer, native launcher, cache keys and first-launch release notes identify 9.4.1. This is a distinct installer from 9.4.0/Beta.4. Stable publication must reuse the tested executable, update the app's feed and designate the public GitHub release as Latest. No old tag or installer is overwritten.

## Migration and known boundaries

The old published 9.4.0 shutdown defect cannot be fixed inside an already-running old executable. An old installation may require closing its window once after approving an update; the direct 9.4.1 installer is also supported. Installer replacement must preserve existing projects, source files, report history and saved appearance.

The five backend-only workflows identified by the audit remain desktop-completion work: point clouds, YAML automation, new CRS diagnostics, Excel template mapping and external GIS processing controls. No claim is made for live OCR/AI accuracy, official Trimble binary conversion, external QGIS/GRASS execution, all native filters/target export programs, power-loss atomicity across database and files, or rod-height field calibration. Authenticode signing and signed manifests are not configured. Same-version numbered beta selection remains numeric-version based; this distinct 9.4.1 patch avoids the 9.4.0 same-version ambiguity.

## Verification record

Release evidence is attached to the GitHub Actions run for the exact source and installer. Prior repair checkpoint: 471 passed, 1 skipped plus installed-native tests. The new versioned candidate must pass those checks and the additional staging/native updater tests and full replacement cycle before publication. Earlier evidence is not substituted for the new candidate's results.
