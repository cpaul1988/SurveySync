# SurveySync v9.1.2 QA Report

## Status

**Beta candidate.** The source package and native Windows GUI launchers are regression-tested. The final Inno Setup installer still must be compiled and exercised on a real Windows workstation before Stable promotion.

## Feedback gate before build

The shared **FieldBook Sync Feedback Tracker / Intake** was checked live before development, and the raw **Form Responses 1** tab was also checked for unprocessed submissions.

- **FBR-0009** remained the newest Intake item.
- No FBR-0010 or later item was present.
- The raw Form Responses tab contained only its header, so there was no hidden/unprocessed form submission waiting to be triaged.
- v9.1.1's FBR-0009 Point Range fix remains preserved in v9.1.2.

## Automated regression

Command:

```text
PYTHONPATH=. pytest -q tests legacy_tests/test_core.py legacy_tests/test_v8117_dip_book_statuses.py legacy_tests/test_v6_features.py legacy_tests/test_v8118_feedback_wizard.py
```

Result:

**178 passed, 0 failed.**

Additional checks:

- `python -m compileall -q surveysync fieldbook_sync tracker_endpoint` — PASS
- `node --check surveysync/static/app.js` — PASS
- `node --check fieldbook_sync/static/app.js` — PASS
- Windows x64 `SurveySync.exe` cross-build — PASS
- Windows x64 `SurveySyncUpdater.exe` cross-build — PASS
- Both native launchers verified as PE **Subsystem 2 / Windows GUI** — PASS

## v9.1.2 Field Note Profile Trainer coverage

The new v9.1.2 tests verify:

1. `BRT_STANDARD` and `GENERIC_SURVEY_NOTES` built-in profiles are created automatically.
2. The BRT built-in profile retains the user-taught structure-circle / north / individual-leader / destination-PointID grammar.
3. Built-in profile rules are locked; a custom copy can be created and edited safely.
4. Real-page labeled training examples persist normalized annotation boxes and local image evidence.
5. Stored examples contribute privacy-preserving structural grammar hints to later profile-aware analysis.
6. Previous project names, PointIDs, handwritten numeric values and accepted-result text are excluded from reusable learned prompt summaries.
7. `.fnp` export/import round-trips a custom profile and labeled examples.
8. Importing a built-in `.fnp` creates a custom ID instead of replacing the locked built-in profile.
9. Unsafe `.fnp` ZIP member paths are rejected, and bundle/member size limits are enforced by the importer.
10. Page evidence supports arbitrary named field-note profiles plus advisory profile confidence.
11. The extraction schema exposes `field_note_profile` and `field_note_profile_confidence`.
12. The FieldBookSync UI exposes Field Note Trainer, page annotation, `.fnp` import and Teach-this-profile controls.

## Review-to-training behavior

The normal Structure Review window now offers **Teach this profile** when page evidence exists. The UI first saves the review correction, then creates the labeled training example from the saved PointID/result. This prevents a user from teaching a stale pre-correction interpretation.

The original OCR/AI evidence remains unchanged in the audit trail. Profile learning adds derived/local training evidence; it does not rewrite source observations.

## Learning behavior and privacy

v9.1.2 performs **profile/example learning**, not neural-network weight fine-tuning.

For each profile, SurveySync can derive structural hints from locally labeled examples: annotation types, pipe-linked annotation types and coarse normalized layout centers. Raw source filenames, PointIDs, handwritten values and accepted-result content from previous examples are deliberately omitted from the reusable prompt summary. This is important because the same profile may later be used with an explicitly selected cloud provider.

PaddleOCR/Qwen model weights are not silently retrained by the application. The stored labeled dataset can support separately validated model tuning in a future release.

## Mixed-format field books

- Global default: **Auto-detect per page**.
- Optional active named profile for analysis.
- Optional page-specific override.
- Unknown or weakly matching layouts fall back to `GENERIC_SURVEY_NOTES` / review instead of being forced into the BRT grammar.

This allows one PDF to contain BRT utility pages, generic sketches, level/control pages or future client-specific formats without defining BRT as the universal field-note language.

## `.fnp` bundles

A profile and its labeled examples can be exported/imported as a SurveySync `.fnp` bundle. Import uses controlled destinations rather than archive extraction, rejects unsafe member paths, caps archive content sizes, protects built-in IDs and keeps imported examples local.

## Preserved v9.1.1 workflows

The maintained regression suite continues to cover:

- FBR-0009 Point Range Current Project Points + Browse/Select Point File behavior.
- CSV/TXT/XLSX Point Range outputs and sorting.
- Trimble JOB/JXL intake and official-converter adapter behavior.
- Ronald's 3-point control QC + FINAL/RESHOOT deliverables.
- BRT explicit `to Point` topology and leader-vs-written-azimuth QC.
- Unified SurveySync updater, feedback, project and FieldBook compatibility behavior.

## Native Windows binaries

`SurveySync.exe`

- SHA-256: `c13ac03f0fbd62a6d7471e9e8ca137aef286404f70423214848310939d74d3e4`
- Size: 2,229,760 bytes
- PE subsystem: Windows GUI (2)

`SurveySyncUpdater.exe`

- SHA-256: `0648672e3df98fca8622ede75ac83ab8621a4d60906e4a91962021378ce8e0b5`
- Size: 2,259,968 bytes
- PE subsystem: Windows GUI (2)

## Installer status

The build environment does not contain Inno Setup/ISCC. Therefore **`SurveySync_Setup_9.1.2.exe` is not claimed as built here**.

The source package includes `Build_SurveySync.ps1` and `Build_SurveySync.cmd`. On Windows the helper reruns QA, builds GUI-subsystem launchers when Go is available, locates Inno Setup 6, compiles `installer/SurveySync.iss`, and writes the installer SHA-256 file.

## Windows beta release gates

Before Stable promotion:

1. Compile `SurveySync_Setup_9.1.2.exe` with Inno Setup 6 on Windows.
2. Exercise a real v9.1.1 → v9.1.2 update/install and verify project/settings retention.
3. Open the supplied BRT field book, confirm Auto selects/uses the BRT grammar on representative structure pages, and review leader associations.
4. Create one second custom field-note profile from a different note format and annotate representative pages in the trainer.
5. Correct at least one reviewed result, choose **Teach this profile**, and verify the new example appears in the trainer library.
6. Export that custom profile as `.fnp`, import it into another project/workstation, and verify examples/profile rules are retained.
7. Test a mixed-format field book with at least one page-level profile override.
8. Smoke-test installed PaddleOCR/Qwen and rerun Point Range + Trimble JOB workflows.
9. Submit a beta feedback report and confirm it reaches Intake.
