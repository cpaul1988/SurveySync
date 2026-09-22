## 9.2.2 BetaCandidate - Feedback Intake compatibility hotfix
- Restored the legacy-compatible `application: "FieldBook Sync"` feedback envelope.
- Feedback now syncs against both the older deployed Intake Web App and the newer SurveySync tracker endpoint.
- No survey-data, QA, ControlSync, Operations Center, or error-log behavior changed.
- Added a regression test reproducing the production `Unsupported FieldBook Sync feedback payload.` failure.

# SurveySync Release History

## 9.2.1 BetaCandidate - Project operations and safety

Adds the shared Operations Center: Project Health/QA rules, safe point-import staging and learned mappings, recovery/manual snapshots, timeline, revised-file/project comparison, smart export profiles, checksum-backed package builder, coordinate sanity, project map QC, batch/background tasks, Unified Review Center, and Why? evidence explanations. v9.2.0 ControlSync active revision behavior remains unchanged.


## 9.2.0 BetaCandidate - ControlSync active revision management

Adds explicit active-solution state for control and level calculations, immutable revision history in the UI, revision comparison, non-destructive restore, audit events for activation/restoration, and active-revision-aware ControlSync PDF reporting. Existing projects fall back to their latest stored revision until an explicit active revision is selected.

## 9.1.4 - Reliability, diagnostics, and updater consent

Implements the v9.1.4 reliability pass: update installs require explicit confirmation before staging or shutdown, FieldBookSync Save As writes atomic ZIP-validated `.fbs` bundles, Review modal layout is bounded on desktop/mobile, and shared diagnostics can export or sync a redacted local Error Log. Apps Script tracker payloads now route feedback to Intake and diagnostics to Error Log.

## 9.1.3 — Field-book training workflow

Implements FBR-0010: book-specific profile dropdown after import, representative-page preview, Train This Field Book handoff, persisted book/profile metadata, Trainer source filter/quick preview, and explicit page-over-book precedence. Adds documentation validation as a release gate.

## 9.1.2 — Field Note Profile Trainer

Introduced reusable field-note grammars, BRT and generic built-ins, visual training annotations, correction teaching, learned structural prompt hints, page overrides, and `.fnp` import/export.

## 9.1.1 — Intake / survey workflow stabilization

Completed Point Range current-project/file workflows, direct Trimble Access JOB/JXL intake, BRT-specific semantic/QC support, and Ron control final/reshoot deliverables.

## 9.1.0 and earlier

Established the SurveySync modular shell, shared project architecture, updater, themes, Project Manager, and embedded FieldBookSync migration path. Historical release notes/QA reports remain in the repository for detailed changes.

## 9.2.3 BetaCandidate - Control database + universal Browse

- Reframed ControlSync around loading all control survey shots into the persistent project database.
- Added analyze-all workflow and per-control batch summary reporting.
- Kept the validated Ron three-point workbook calculation as a secondary specific method.
- Added native Browse behavior to previously manual local path fields, including multi-file batch selection.
- Preserved the v9.2.2 backward-compatible feedback Intake envelope.

## 9.2.4 BetaCandidate - project database platform
Introduced the formal one-project/one-database contract, master template DB, schema migration backups, project workflow templates, Project Data Manager, audited controlled edits and database health/maintenance.

## 9.2.5 BetaCandidate - correctness and error visibility
- Fixed row misalignment and wrong-PointID risk in coordinate sanity.
- Added explicit invalid-pair evidence and corrected remote-outlier thresholding.
- Eliminated blind broad-exception passes from the SurveySync core; audited FieldBook state persistence.
- Added persistent SurveySync core logs and a static-quality release gate.
- Added canonical `CHANGELOG.md`; deferred route modularization to 9.3.0.

## 9.2.5 expanded Control Survey BetaCandidate

In addition to the correctness/error-visibility hardening, the unreleased 9.2.5 candidate now contains the TBC-inspired Control Survey workspace, offline project CRS library, Local Site modified-ground settings, automated best-three QC, spatial misnumber detection, field-observation validity checks (time/epochs-duration/satellites), accepted/reshoot outputs and reusable CRS-aware custom control exporters. This supersedes the earlier unreleased 9.2.5 package.

## 9.2.6 BetaCandidate - ControlSync production quality

Adds rich raw-JXL quality evidence, dual-source metadata merge, reviewed spatial misnumbering, vertical grouping, reusable field-QC profiles/DOP ceilings, richer control review/map/provenance, complete QC packages, resizable dialogs and the expanded ArcGIS/Esri-aligned CRS browser.


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.


### 9.3.0 TopoSync range QC

Standalone point import, editable code classifications, feature-chain range detection, evidence reports and reviewed-copy exports are implemented in `surveysync/topo` and `surveysync/static/topo_qc.js`. See [TopoSync workflow and limits](TOPO_ROD_HEIGHT_QC.md). Synthetic regression coverage is in `tests/test_topo_rod_ranges.py`; real field and Windows acceptance remain pending. Supplied branding replaces the product globe/installer assets.
