# SurveySync 9.3.1 — Reliability, Support Center, Data Inspector, and TopoSync review workflow

SurveySync 9.3.1 is a reliability-focused follow-up to 9.3.0. It keeps the 9.3.0 project/database model and conservative TopoSync rod-height workflow while adding production support, data inspection, recovery, and review tooling.

## Added

- **Support Center:** one place to review local diagnostic errors, retry/sync error logs, create a Feedback Wizard report from a specific error, refresh feedback status, download a redacted diagnostic bundle, and review interrupted-session recovery.
- **Interrupted-session recovery:** SurveySync records clean versus interrupted application sessions and can offer the latest matching automatic project recovery snapshot for explicit user-approved restore. File-association maintenance commands no longer create false crash-recovery notices.
- **Survey Data Inspector:** inspect CSV/TXT/TSV/PNEZD/ASC and Trimble JOB/JXL/JobXML sources before committing them to a workflow. It detects common point fields, duplicate PointIDs, missing elevations, invalid coordinates, likely remote coordinate outliers, point ranges, feature codes, and current project CRS/unit context.
- **Reusable inspection cache:** source inspection is keyed by SHA-256 so repeated reads are fast. Cached results refresh the currently active SurveySync project/CRS/unit context instead of carrying stale context from a different project.
- **Inspector handoff:** compatible sources can be handed to TopoSync Rod Height QC, ControlSync, or ReportSync Point Ranges without modifying the original survey file. Trimble sources are normalized to a separate cached CSV before downstream handoff.
- **TopoSync QC profiles:** save and reuse reviewed rod-height detection settings and feature-code classifications on a project/workstation workspace.
- **TopoSync run history and review decisions:** prior analysis runs can be reviewed, and each candidate can be marked Confirmed Bust, Not a Bust, or Needs Review with a required reason. Decisions are immutable review records and are added to the project audit trail when a project is open.
- **Calibration summary:** confirmed/rejected review history can suggest an offset-consistency tolerance for human consideration. SurveySync does not automatically change thresholds or elevations from this history.

## Fixed and hardened

- Fixed the SurveySync shell startup-update check so it runs during normal startup instead of being accidentally nested inside the browser storage-change event.
- Fixed the same shell event wiring so cross-tab/theme changes update appearance without re-running unrelated startup initialization.
- Prevented `--register-fbs` and `--unregister-fbs` maintenance launches from being recorded as active SurveySync sessions.
- Refreshed Data Inspector project context on cache hits to prevent stale CRS/unit/project labels after switching projects.
- Added 9.3.1 regression coverage for version surfaces, shell startup wiring, recovery-state behavior, inspection-cache context, TopoSync profile CRUD, run history, and review calibration.
- Added the new 9.3.1 backend modules to the release formatting gate.
- Updated Python, desktop, web-shell and Windows installer version surfaces to 9.3.1.

## Safety and review behavior

Rod-height findings remain **advisory**. SurveySync does not silently alter source observations. Corrected copies still require explicit review/confirmation and are written as new outputs with provenance. Recovery restore also requires explicit confirmation and only becomes available when the interrupted session's project matches the currently open project.

## Pre-build tracker check

The live feedback tracker was checked before preparing this candidate. The newest Intake item remains **FBR-0016**, the Rod Height Bust Tool request already incorporated into the TopoSync workflow. The SurveySync Error Log Tracker contained **0 error rows** and **0 retry-queue rows** at the pre-build check.

## Before Stable promotion

Run the shared Windows release gate and build on Windows, then field-test the installed Beta. At minimum verify project open/switch/recovery, Support Center sync/report actions, Survey Data Inspector on representative CSV and Trimble sources, Inspector downstream handoffs, TopoSync reviewed candidate workflow, updater consent/close/install/reopen behavior, and existing ControlSync/FieldBookSync regressions. Real field-verified rod-height positive/negative examples remain required before treating the detector as production-calibrated.

Authenticode signing and signed update manifests are not configured; do not represent this candidate as a signed Windows release.
