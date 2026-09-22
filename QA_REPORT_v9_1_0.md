# SurveySync v9.1.0 QA Report

## Status

**Beta candidate. Do not promote to Stable until the external feedback-submission retest passes.**

## Automated regression

Command:

```text
PYTHONPATH=. pytest -q tests legacy_tests/test_core.py legacy_tests/test_v8117_dip_book_statuses.py legacy_tests/test_v6_features.py legacy_tests/test_v8118_feedback_wizard.py
```

Result before packaging: **159 passed, 0 failed**.

Additional static/build checks:

- `python -m compileall -q surveysync fieldbook_sync tracker_endpoint` — PASS
- `node --check surveysync/static/app.js` — PASS
- `node --check fieldbook_sync/static/app.js` — PASS
- Windows x64 Go cross-build of `SurveySync.exe` — PASS
- Windows x64 Go cross-build of `SurveySyncUpdater.exe` — PASS


## Project manager regression coverage

Automated tests now verify:

- creating multiple SurveySync projects records a most-recently-used project list;
- opening an older project moves it to the top and rebinds FieldBookSync storage to that project;
- removing a project from the recent list does **not** delete its folder;
- project deletion rejects an incorrect confirmation name;
- deleting the active project detaches the FieldBookSync runtime first, removes the full project folder, clears active/recent references and returns SurveySync to a no-project state;
- the main shell and FieldBookSync shell both expose the SurveySync project manager.

## Authoritative workbook validation

### 3 Point Control Averaged Template.xlsx

SHA-256: `5ac2de69de57b6c687d9b2466d134c95cbab4b098ca846a8492d102dcfeb911c`

Validated formulas include:

- `K2=AVERAGE(B2:B4)`
- `L2=AVERAGE(C2:C4)`
- `M2=AVERAGE(D2:D4)`
- `F2=SQRT((B2-K2)^2+(C2-L2)^2)`
- `H2=D2-M2`, `H3=D3-M2`, `H4=M2-D4`

SurveySync's `ron_spreadsheet` calculation profile requires exactly three included observations and reproduces those formulas while also retaining conventional signed dz for tolerance QC.

### 3 Wire Level Loop Template.xlsx

SHA-256: `65f08aa550822dc1ccc0b37165682db377f492b74dfd6ed328e010c650556b96`

Validated formulas include:

- `C4=AVERAGE(D3:D5)`
- `H4=(D3-D5)*100`
- `G5=B3+C4`
- `E7=AVERAGE(F6:F8)`
- `I7=(F6-F8)*100`
- `G8=G5-E7`
- `H8=H4-I7`
- final close `I87=G86-B3`

The workbook does not define closure adjustment. Accordingly, the Ron workbook profile defaults to No adjustment; any later adjustment must be explicitly selected and is recorded as SurveySync logic.

## Feedback tracker review before release

The shared FieldBook Sync / SurveySync Intake tracker was reviewed before packaging.

Relevant open items:

- **FBR-0002 — Point Range tool not working properly (High / Blocker):** the current source uses the canonical project/loaded point data workflow and shared crew-allocation gap engine.
- **FBR-0003 — Survey Control Average & QC (Critical):** Ron's exact workbook is now available and its three-point method is implemented as a validated calculation profile.
- **FBR-0006 — Point Range Output (High):** requested low-to-high output or a sort option. Current source defaults low-to-high and exposes alternate sort modes.
- **FBR-0008 — Beta testers cannot submit bugs (Critical / Major):** Ron received HTTP 500 while CP reported successful submission. Client configuration migration was hardened, but a successful Ron retest is still required before Stable.
- FBR-0005 and FBR-0007 are explicit TEST entries and are not treated as product defects.

No newer Intake entry was present after FBR-0008 at the time of this QA review.

## Feedback fix implemented in client

- `fieldbook_sync/app.py` now reads the SurveySync repository feedback config.
- An official shared Apps Script endpoint remains built in as fallback if remote config cannot be fetched.
- The official config endpoint now wins over a stale legacy localStorage override.
- Local-first persistence remains unchanged; failed remote sync does not lose the report.
- Updated Apps Script source is included under `tracker_endpoint/`, but it has **not** been deployed from this environment. Therefore this QA report does not claim the remote HTTP 500 is server-side resolved.

## External Beta gates

Before Stable promotion:

1. Install/update to v9.1.0 on CP's Windows 11 machine.
2. Run a Ron 3-point control case from three imported project PointIDs and compare to the workbook.
3. Run a reviewed 3-wire level loop and compare raw reductions/close to the workbook.
4. Confirm Point Range output defaults low-to-high and can change sort mode.
5. Have **Ron** submit a Feedback Wizard report from the Beta machine and verify that it reaches Intake without HTTP 500.
6. Exercise Check & Update from both Home and FieldBookSync.
7. Smoke-test the installed Paddle bridge / local AI pipeline on Windows.


## Startup window hotfix QA

The extra dark window visible behind the native app was identified as the Windows Terminal/console created by the source `run_windows.bat` bootstrap, not a second SurveySync WebView or browser. The source launcher now re-launches itself hidden through Windows Script Host and exits the visible console immediately. A regression test verifies the hidden launcher helper, diagnostic `--console` escape hatch, bootstrap logging, and Windows error dialog path.

Maintained combined suite after the source-bootstrap hotfix: **157 passed, 0 failed**. The final native GUI-subsystem correction adds two launcher regression tests, bringing the maintained combined suite to **159 passed, 0 failed**. Python compileall and both SurveySync/FieldBookSync JavaScript syntax checks pass.


## Native launcher subsystem root-cause correction

The earlier source-bootstrap diagnosis did not fully explain the persistent terminal shown on the installed build. Direct PE-header inspection found the shipped `SurveySync.exe` and `SurveySyncUpdater.exe` were compiled as **Windows CUI (Subsystem 3)** binaries. That causes Windows to allocate a console/Terminal window even though the launcher itself correctly starts the Python child with `CREATE_NO_WINDOW`.

Corrective action:

- rebuild both Go launchers with `-H=windowsgui`;
- update `.github/workflows/release.yml` so every future release uses that flag;
- add a regression test that parses the shipped PE headers and requires **Subsystem 2 (Windows GUI)** for both launchers.

This is the root-cause fix for the persistent second terminal window on normal installed launches.
