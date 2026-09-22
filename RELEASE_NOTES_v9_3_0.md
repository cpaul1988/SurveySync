# SurveySync 9.3.0 — Engineering hardening and TopoSync QC candidate

This source candidate makes builds reproducible, unifies release checks and begins the planned domain refactor. It preserves the 9.2.6 survey calculations and project schema.

- GitHub release notes now follow the requested version. CI calls the same Windows build script and Python quality gate as the local build. Failed checks block the release.
- Exact, SHA-256-verified dependency locks cover core runtime, development tools and optional Windows AI. The bootstrap fingerprints the core lock rather than its wrapper.
- Ruff checks undefined variables across both applications; extracted modules require consistent formatting. Gradual mypy checks cover request schemas, control calculations and rod-height QC. Whole-application line coverage must remain at least 54%.
- Dependency audits cover every platform branch, including Windows-only packages on a Linux test host. Weekly and pull-request quality workflows are included.
- API schemas, control math/report exports, project operations, survey routes, map/profile routes, vision processing, live analysis and batch workers have separate modules. Compatibility imports retain existing callers and runtime lookup respects project switches.
- All 22 FieldBookSync silent broad exception handlers now log their fallback failures. Some input/operations catches are narrower. Other broad handlers remain and are capped; this is not a claim that exception hardening is finished.
- Fixed an undefined variable in the recent-project metadata error path.
- TopoSync has an explicit Rod Height Bust QC entry. FieldBookSync distinguishes disabled QC and missing survey data. Non-finite coordinates cannot crash the spatial index. No elevations are changed.
- Windows release builds require Go and verify rebuilt launchers. Old 9.2.6 executables are not included as 9.3.0 binaries.

## Rod-height scope

The existing isolated-point detector remains in FieldBookSync → Home → Survey data → Rod Height QC. TopoSync → Rod Height Bust QC now has a separate standalone range detector.

Ron’s FBR-0016, submitted September 22, requests a different, advanced workflow: feature-code classification, chain continuity, common-offset ranges, terrain-break exclusions, standalone load/export and recommended corrections. Implemented in this candidate: standalone point/code-list import, editable classifications, geometric feature chains, correlated constant-offset ranges, exclusions, evidence scores, explicit review and separate corrected-copy exports. Scores are heuristics, not statistical probabilities. Uncertain boundaries and unreviewed units/order/codes block corrections. See docs/TOPO_ROD_HEIGHT_QC.md and the synthetic example. Field validation is still pending.

The supplied navy/gold globe, compass, satellite and SurveySync wordmark are integrated into application and installer assets. The exact original artwork is retained in branding/SurveySync_Logo.jpg.

## Before release

Build and test on Windows using BUILD_9_3_0.md. Validate real Trimble imports, ControlSync outputs, FieldBookSync analysis/project switching, updates and rod-height QC. Authenticode credentials and signed update manifests remain unconfigured. This package is not an installer and has not been published.
