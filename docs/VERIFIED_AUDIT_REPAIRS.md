# Unreleased 9.4 verified-audit repairs

Scope: correct independently reproducible defects against the approved Beta.4 application source (`1382bff0dc5b6bc452d7d64be5f6ac17cd2177a0`). The repair branch starts at Stable main `9965284c69e6a7cd95fe0750838130f4a39bd6e2`. Publication scripts, the released installer, tags, update feed and Stable remain unchanged.

## Actual verification status for this handoff

The configured release-gate test selection passed locally: 470 passed, 1 skipped. Of these, 77 cases are newly retained audit/repair/bridge contracts. The custom documentation and static-quality gates passed; Python compilation and both shell JavaScript syntax checks passed. These runs used Linux / Python 3.13, not the target Windows runtime.

Ruff/mypy and actual browser/native Windows acceptance have NOT passed in this handoff: Ruff/mypy and browser binaries are unavailable in the local environment, and a tool-side GitHub write block prevented transferring the repairs to CI. The repair branch still points to unchanged main 9965284. The scripts for actual browser controls and installed-Windows close/reopen verification are included but remain unrun successfully.

All corrections are local source changes. There is no new installer, no updated Stable feed, no release tag and no merged repair PR. This package must not be represented as an approved build. G01-G05 and external/provider acceptance remain open as described below.

## Repair matrix

| Audit | Correction and verification |
|---|---|
| A01 | Duplicate source imports return a usable absolute stored path without changing the immutable source registry path. Repeated LandXML API import reproduced. |
| A02/A03 | Case/space/underscore/hyphen-insensitive PointID header aliases in leveling and Field-to-Finish. Actual point identifiers retain leading zeros and case. |
| A04 (qualified) | Explicit paired-setup, separate-sight and station-row layouts. Ambiguous turning-point rows require an explicit selection. Point and instrument-height roles are separate; original Ron three-wire reduction is retained. No closure adjustment unless explicitly selected. |
| A05 | Reject non-finite numeric readings and coordinates at import and direct calculation boundaries. Reject unsupported declared units and negative tolerances. |
| A06 | Exact traverse closure returns a JSON-safe null ratio plus PERFECT_CLOSURE, without perturbing coordinates. The report labels perfect closure. |
| A07 | Pipe grade converts declared vertical/horizontal units before division; all nine unit pairs and adverse grades tested. Source measurements are unchanged. |
| A08/A09 | Collection selectors repaired for Survey Data, Data Inspector and Support Center. File Exit calls the exposed exit_app bridge, with API fallback. |
| A10 | Polygon area/centroid calculated relative to a local origin with accurate summation. Large absolute coordinates and tiny polygons tested, both orientations. |
| A11 | Native WebView observes the real API/updater shutdown event and invokes the existing orderly shutdown path. Actual installed Windows shutdown/reopen acceptance is a separate CI requirement. |
| A12/A14/A15 | Manual control keeps source code, exact PointID and selection order; repeated operations create distinct immutable revisions and report folders. Explicit SQLite transaction keeps the last valid solution if solve/export/audit fails. Residuals carry their own IDs; QC/reshoot exports do not relabel by array position. Concurrent requests are serialized. |
| A13 | Partially initialized ledger connections close before recovery. Only genuine CORRUPT/NOTADB errors trigger quarantine. DB and sidecars are preserved; rename failures are surfaced, not silently ignored. |

## Preserved design

Ron N/E/Z arithmetic means, horizontal residuals and the workbook's special C-row vertical display are unchanged. This pass verifies the documented formula expectations with synthetic points, not a fresh independent reread of the private workbook. Bulk best-three control, original survey observations, client themes and shared application appearance are retained.

Manual-control atomicity covers handled operation failures and serializes SQLite writes. It is not a claim of atomic power-loss recovery across the database and filesystem. Unique report folders prevent timestamp collisions; failed-operation cleanup targets only the newly created folder.

Level layouts are persisted with each solution. Separate-sight legacy rows still expose raw instrument heights, but row_role and point_elevation explicitly distinguish them from point elevations. The UI supplies a row-layout selector. Automatic mode intentionally rejects an ambiguous station/turning-point book rather than silently changing Ron's workflow.

## Verification

Permanent tests: `tests/test_audit_reproductions.py`, `tests/test_verified_repairs.py`. These include duplicate imports, PointID aliases, non-finite data, strict JSON closure, unit conversions, 500 seeded point-range allocations, 1,000 COGO round trips, repeated control calculations, source-ID attribution, report output, failure rollback, concurrency and ledger recovery.

Additional production-control checks: `scripts/verify_repaired_ui.py`. Installed native acceptance: `scripts/verify_repaired_native.py` (two create/recalculate/close/reopen cycles using a disposable CI installation and temporary projects). Existing release quality gates and 11-module/16-theme suites remain unchanged and required. Passing tests are recorded in CI; code presence alone is not acceptance evidence.

## Remaining boundaries

G01–G05 (point-cloud intake, YAML workflow management, CRS diagnostics, template mapping and QGIS/GRASS desktop integration) remain explicitly tracked UI-completion work; this repair pass does not mark those backend-only workflows complete. Live OCR/AI accuracy, proprietary Trimble conversion, installed external GIS engines, actual user/VPN file dialogs, active provider cancellation, and full staged updater replacement still require dedicated acceptance. No paid provider calls, live feedback test submissions or user-project mutations are performed.

Pre-build feedback review: connected Intake was checked through row 1001; 16 reports, latest FBR-0016 dated September 22. This is not proof that remote error reporting works on every workstation.
