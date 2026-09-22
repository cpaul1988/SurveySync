# SurveySync v9.1.1 QA Report

## Status

**Beta candidate.** The source package and native Windows GUI launchers are built and regression-tested. The final Inno Setup installer must still be compiled and exercised on a real Windows 11 workstation before Stable promotion.

## Feedback gate before build and packaging

The shared **FieldBook Sync Feedback Tracker / Intake** was checked before development and checked again immediately before packaging. The newest submission remained **FBR-0009**; no FBR-0010 or later entry was present.

- **FBR-0009 — Point Range doesn't allow me to pick file (Critical / Blocker):** fixed in v9.1.1 source. ReportSync now defaults to the canonical points in the active SurveySync project and also exposes an explicit Browse / Select Point File workflow.
- **FBR-0006 — Point Range Output:** low-to-high remains the default, with high-to-low and largest-capacity sorting retained.
- **FBR-0002 — Point Range workflow:** canonical current-project points are now a first-class source instead of requiring an external file.
- **FBR-0008 — beta testers could not submit bugs:** RP successfully submitted FBR-0009 from v9.1.0 and it reached Intake, demonstrating that the external beta submission path is functioning from his workstation. Local-first persistence, retry behavior, and diagnostics remain in place.

## Automated regression

Command:

```text
PYTHONPATH=. pytest -q tests legacy_tests/test_core.py legacy_tests/test_v8117_dip_book_statuses.py legacy_tests/test_v6_features.py legacy_tests/test_v8118_feedback_wizard.py
```

Result:

**170 passed, 0 failed.**

Additional checks:

- `python -m compileall -q surveysync fieldbook_sync tracker_endpoint` — PASS
- `node --check surveysync/static/app.js` — PASS
- `node --check fieldbook_sync/static/app.js` — PASS
- Windows x64 `SurveySync.exe` cross-build — PASS
- Windows x64 `SurveySyncUpdater.exe` cross-build — PASS
- Both native launchers verified as PE **Subsystem 2 / Windows GUI** — PASS

## v9.1.1 targeted coverage

The new v9.1.1 test set verifies:

1. Trimble JobXML/JXL point parsing and numeric PointID extraction.
2. ReportSync Point Range current-project mode and external-file mode.
3. Point Range CSV, TXT, and XLSX output.
4. Official Trimble converter command contract using a controlled fake converter executable.
5. Direct `.job` intake end-to-end through the conversion adapter in the test environment.
6. FieldBookSync JXL import through the active CodeProfile.
7. Canonical Trimble point import preserves source evidence and does not overwrite conflicting PointIDs.
8. Ronald's three-point workflow writes QC plus FINAL or RESHOOT TXT deliverables.
9. BRT explicit `to Point` topology takes precedence over a merely nearby geometric candidate.
10. Written azimuth versus visual leader-direction disagreement routes to QC review.
11. v9.1.1 UI surfaces Point Range browsing and Trimble JOB/JXL controls, and FieldBookSync advertises the expanded survey-file extensions.

## Ronald workbook integrity

### 3 Point Control Averaged Template.xlsx

SHA-256: `5ac2de69de57b6c687d9b2466d134c95cbab4b098ca846a8492d102dcfeb911c`

The validated v9.1.0 `ron_spreadsheet` calculation profile remains unchanged in v9.1.1. The new work is deliverable generation: QC TXT is always produced, a FINAL TXT is produced when the three-shot solution passes tolerance, and a RESHOOT TXT identifies failing observations when tolerance is exceeded.

### 3 Wire Level Loop Template.xlsx

SHA-256: `65f08aa550822dc1ccc0b37165682db377f492b74dfd6ed328e010c650556b96`

The validated three-wire reduction profile remains unchanged. The source workbook defines no closure-adjustment method, so **No adjustment** remains the default unless a SurveySync adjustment method is explicitly selected.

## Point Range validation

v9.1.1 supports two explicit inputs:

- **Current Project Points** — default; every numeric canonical SurveySync PointID is occupied.
- **Choose Point File** — optional external file source for CSV/TXT/TSV/PNEZD/ASC and supported Trimble JOB/JXL/JobXML inputs.

The same canonical gap engine and sorting rules feed CSV, TXT, and XLSX outputs. Existing point numbers are not offered as available ranges.

## Trimble Access JOB / JobXML validation

SurveySync does not reverse-engineer proprietary Trimble `.job` binary content. A selected `.job` is preserved as immutable source evidence and, when conversion is required, SurveySync invokes the supported Trimble ASCII/File and Report Generator layer to obtain JobXML/JXL for deterministic parsing. JXL/JobXML can also be imported directly.

Parsed point records can enter the canonical SurveySync point registry, but existing PointIDs are not overwritten. Conflicts are returned for review.

The converter adapter and complete `.job` route have automated test coverage with a controlled converter substitute. **A real Trimble Access `.job` still needs to be tested on the target Windows workstation with the actual Trimble utility installed.**

## BRT FieldBook intelligence validation

v9.1.1 adds explicit data fields and review logic for the BRT standard structure sketch: structure identity, north-orientation metadata, separate pipe leaders, leader-associated pipe attributes, visual leader direction, and written destination PointIDs such as `to 3394`.

Explicit written topology is preserved and given precedence over nearest-neighbor geometry. Survey coordinates, written azimuths, and visual leader direction are used as independent QC evidence. Disagreement creates a review flag; SurveySync does not silently rewrite the field notes.

This is a BRT-aware semantic/evidence workflow. It is **not** represented as a guaranteed deterministic computer-vision circle detector, and real-book validation remains required.

## Native Windows binaries

`SurveySync.exe`

- SHA-256: `891048af57eb8e79dbd188fb2f4e98dc9e9b06476b3a5bb90ab363329bba4115`
- Size: 2,229,760 bytes
- PE subsystem: Windows GUI (2)

`SurveySyncUpdater.exe`

- SHA-256: `0648672e3df98fca8622ede75ac83ab8621a4d60906e4a91962021378ce8e0b5`
- Size: 2,259,968 bytes
- PE subsystem: Windows GUI (2)

## Installer status

The build environment for this package is Linux and does not contain Inno Setup/ISCC. Therefore **`SurveySync_Setup_9.1.1.exe` is not claimed as built here**.

The package includes `Build_SurveySync.ps1` and `Build_SurveySync.cmd`. On Windows, the helper can rerun QA, rebuild the two GUI-subsystem launchers, locate Inno Setup 6, compile `installer/SurveySync.iss`, and generate an installer SHA-256 file.

## Windows beta release gates

Before Stable promotion:

1. Compile `SurveySync_Setup_9.1.1.exe` with Inno Setup 6 on Windows.
2. Exercise a real v9.1.0 → v9.1.1 update/install and verify project/settings retention.
3. Test Point Range using both Current Project Points and Browse / Select Point File.
4. Import a representative real Trimble Access `.job` with the actual Trimble converter installed.
5. Run the supplied BRT field book through FieldBookSync and review leader/pipe associations and `to Point` topology.
6. Run both PASS and RESHOOT Ronald three-point control cases and compare to the workbook.
7. Smoke-test the installed PaddleOCR/local-AI pipeline.
8. Submit a beta feedback report and confirm that it appears in Intake.
