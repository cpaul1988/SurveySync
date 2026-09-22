# SurveySync v9.1.4 QA Report

v9.1.4 prepares the reliability patch for FBR-0011/FBR-0012: updater consent, atomic FieldBookSync Save As, shared diagnostics/error-log export and sync, Apps Script routing, and Review UI responsiveness.

## Automated Coverage

- Added `tests/test_v914_reliability.py` for update confirmation, legacy update proxy behavior, Save As ZIP validation, diagnostics/error-log redaction and export, feedback/error-log tracker routing, and static UI contracts.
- Updated active version expectations in `tests/test_v9_api.py` and `tests/test_v9_core.py`.
- Documentation gate: passed with `python scripts/validate_release_docs.py`.
- Python compile checks: passed with `python -m compileall -q surveysync fieldbook_sync tracker_endpoint`.
- JavaScript syntax checks: passed for `surveysync/static/app.js`, `fieldbook_sync/static/app.js`, and `tracker_endpoint/Code.gs` via Node stdin parsing.
- Native launcher sanity: `SurveySync.exe` and `SurveySyncUpdater.exe` retain Windows GUI PE subsystem value `2`. Because Go is not installed in this scratch runtime, `SurveySync.exe` received a same-length embedded version literal patch from `9.1.3` to `9.1.4`; a full Go rebuild remains a Windows release gate.

## Current Runtime Limitation

The scratch runtime used for this package does not include `pytest`, `fastapi`, and related test dependencies, so the FastAPI regression suite could not be executed here. The Windows release gate must run the maintained command from `Build_SurveySync.ps1` before promoting the artifact:

```bash
python -m pytest -q tests legacy_tests/test_core.py legacy_tests/test_v8117_dip_book_statuses.py legacy_tests/test_v6_features.py legacy_tests/test_v8118_feedback_wizard.py
```

## Manual / Windows Gates Still Required

- Recheck the live Feedback Intake and Error Log tracker immediately before final packaging/promotion.
- Build `SurveySync_Setup_9.1.4.exe` with Inno Setup 6 on Windows.
- Verify the GUI subsystem for `SurveySync.exe` and `SurveySyncUpdater.exe` after any launcher rebuild.
- Install/update a real v9.1.3 machine to v9.1.4.
- Exercise Check & Update confirmation and cancel paths.
- Save As an existing `.fbs` project through the native dialog and reopen the saved copy.
- Open Review on desktop and narrow displays and verify action buttons, form fields, and image panes remain reachable.
- Sync a test feedback item to Intake and a synthetic redacted error-log item to Error Log using the deployed Apps Script endpoint.
