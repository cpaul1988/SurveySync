# SurveySync v9.2.3 BetaCandidate Release Notes

## ControlSync database-first workflow

v9.2.3 changes the primary ControlSync workflow from a three-shot-centered screen to a bulk Control Survey Database. A single control survey file can contain repeated shots for many Control IDs. SurveySync preserves every imported shot in the project SQLite database, shows grouped control counts and observation rows, and can analyze every eligible control point in one operation.

The existing validated **3 Point Control Averaged Template.xlsx** calculation remains available as a specific/legacy tool. It is no longer presented as the only or primary control workflow. The new bulk analyzer uses the already validated generic arithmetic or sigma-weighted averaging engine. SurveySync does **not** claim to reproduce Trimble Business Center (TBC) analysis yet; Ronald's forthcoming TBC report/screenshots are required before that profile is implemented or labeled as equivalent.

Bulk analysis writes a CSV summary containing each Control ID, status, observation count, solved N/E/Z, maximum horizontal/vertical residual, solution revision, and errors. Each successful solve remains an immutable solution revision and the raw observations are not deleted or rewritten.

## Universal file/folder browsing

Path-entry controls that previously required typing or pasting Windows paths now expose native browse buttons. This includes control observations, legacy `.fbs` migration, level/traverse observations, supplemental GIS, structure-photo folders, field-to-finish input, spatial import, and multi-file batch processing. Existing dedicated pickers for projects, Point Range, staging, comparison, and Trimble JOB remain intact.

The desktop bridge now supports multi-file selection. Browser-fallback mode has matching single-file, multi-file, and folder picker routes.

## Compatibility carried forward

The v9.2.2 backward-compatible Feedback Intake envelope is retained unchanged so pending v9.2.1 reports can still retry against the deployed legacy Apps Script endpoint.
