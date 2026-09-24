# SurveySync Release Checklist

Before every build/package:

1. Check the live FieldBook Sync Feedback Tracker Intake and raw Form Responses for anything newer than the last incorporated FBR.
2. Review `docs/DECISIONS.md`, `docs/KNOWN_ISSUES.md`, `docs/FEATURE_MATRIX.md`, and the affected module documentation before changing behavior.
3. Implement code changes and add/update regression tests for every fixed feedback item.
4. Update developer docs and `IMPLEMENTATION_INDEX.json` to match actual code behavior.
5. Run `python scripts/validate_release_docs.py`.
6. Run Python compile checks, JavaScript syntax checks, and the maintained regression suite.
7. Document anything automation cannot validate in the current QA report and `BUILD_MANIFEST.json` release gates.
8. Recheck the feedback tracker immediately before final packaging.
9. Verify all version references, release notes, installer filename, updater manifest workflow, and hashes.
10. Build the Windows installer and field-test Beta before Stable promotion. Stable must promote the exact tested Beta artifact/hash.


### v9.2.1 additional Beta checks

- Force-close the app after project changes and verify a recent recovery snapshot can be compared/restored.
- Stage a point file containing duplicate PointIDs and verify existing canonical records are not overwritten.
- Compare another SurveySync project and verify added/removed/changed counts.
- Create/run a custom export profile and inspect the deliverable ZIP manifest/checksums.
- Queue/cancel/fail a background job and verify Review Center + Why? retain useful evidence.


### v9.2.2 hotfix validation
- Build/install over released 9.2.1 on Windows.
- Retry the pending production feedback report and verify a valid FBR ID is returned.
- Confirm a second retry is idempotent and does not create a duplicate Intake row.
- Confirm Error Log sync still routes independently.

### v9.2.3 validation

- Import repeated control shots covering multiple Control IDs and confirm shot counts/database rows.
- Analyze all controls; verify PASS/REVIEW/INSUFFICIENT_SHOTS and immutable revisions.
- Validate bulk report CSV.
- Exercise each newly browsable file/folder field in the installed Windows shell and multi-file batch selection.
- Regression-test Ron three-point, Control revision restore/reporting, and v9.2.2 feedback retry compatibility.

### v9.2.4 validation
- Confirm new project creates its own `.surveysync/survey_sync.db` from the master template.
- Confirm opening an older schema creates a migration backup before upgrading.
- Confirm controlled Data Manager edits require a reason and create a snapshot.
- Confirm recalculating edited control/level/traverse data clears stale state.
- Confirm database maintenance does not change survey values.
- Confirm existing v9.2.3 control and v9.2.2 feedback workflows remain operational.

### v9.2.5 validation
- Create a new project, search/select the real project CRS, and verify it persists on reopen.
- Validate a known Local Site grid/ground coordinate pair, factor and clockwise rotation against trusted survey software before production use.
- Load Ronald's real multi-shot data; verify map placement, suffix grouping, best-three selection and 0.045 H/V results against the validated workbook.
- Verify failing controls create the correct next-unused reshoot IDs and do not silently adjust source observations.
- Export accepted/reshoot CSV/XLSX and reload a saved custom exporter profile.
- Verify geographic output uses Latitude/Longitude headers and project mode defaults to the project/local-site coordinate values.

- Run `python scripts/validate_static_quality.py` before compile/test and do not raise the exception/monolith baselines to make a failure disappear.
- Exercise coordinate sanity with an asymmetric non-finite pair and a known remote point; verify both reported PointIDs are correct and source values remain unchanged.
- Verify `surveysync.log` is created and populated when a controlled best-effort fallback is triggered.
- Re-smoke 9.2.4 project database/Data Manager, 9.2.3 Control Database, 9.2.2 Intake sync, and snapshot/update workflows.

## v9.2.6 additions

- Confirm schema 5 template DB integrity and migration backup behavior.
- Run the maintained regression suite including `test_v926_control_production.py`.
- Verify SurveySync and FieldBookSync JavaScript syntax plus Python compileall.
- Verify resizable Coordinate System picker and remembered popup sizing on Windows.
- Import a coordinate-only TBC JXL and confirm missing raw GNSS metadata is explicitly diagnosed.
- When available, import/merge a raw Trimble Access JXL and compare shot times, epochs/duration, satellites, DOP and receiver/antenna fields against Trimble Access.
- Validate accepted/reshoot/provenance package contents before promotion.


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.


### 9.3.0 TopoSync range QC

Standalone point import, editable code classifications, feature-chain range detection, evidence reports and reviewed-copy exports are implemented in `surveysync/topo` and `surveysync/static/topo_qc.js`. See [TopoSync workflow and limits](TOPO_ROD_HEIGHT_QC.md). Synthetic regression coverage is in `tests/test_topo_rod_ranges.py`; real field and Windows acceptance remain pending. Supplied branding replaces the product globe/installer assets.

## v9.3.1 additional Beta checks

- Confirm the live Feedback Tracker has no Intake item newer than the recorded build-manifest item and check both Errors and Retry Queue immediately before packaging.
- Verify normal clean exit, forced/interrupted exit, matching-project recovery availability, explicit restore confirmation, and recovery-notice dismissal.
- Run `--register-fbs` / `--unregister-fbs` maintenance paths and confirm they do not create a false interrupted-session notice.
- Inspect headered/headerless delimited data and representative JXL/JOB data. Confirm duplicate IDs, missing elevations, invalid coordinates, point range, code count, CRS and units are correct.
- Switch projects and re-open a cached inspection; active project/CRS/unit context must update even though the source SHA-256 cache is reused.
- Validate Inspector handoff to each offered downstream workflow without modifying the original source.
- Save/reload/delete a TopoSync QC profile; record Confirmed/Not Bust/Needs Review decisions and verify the audit/history display.
- Treat calibration output as advisory only. No review history may silently change QC thresholds or survey elevations.
- Re-smoke 9.3.0 TopoSync corrected-copy safeguards, ControlSync, FieldBookSync, feedback, diagnostics and update consent.
- Build fresh native launchers and the Inno installer; verify all visible version surfaces and the SHA-256 output are 9.3.1.

