# SurveySync v9.1.4 Release Notes

SurveySync 9.1.4 is a reliability patch for updater consent, FieldBookSync project Save As, diagnostics, tracker routing, and Review UI layout.

## Highlights

- **Updater consent:** Check & Update now checks first and asks for explicit confirmation before staging an installer or closing SurveySync. The main SurveySync route and the FieldBookSync compatibility route share the same behavior.
- **Atomic Save As:** FieldBookSync uses the native desktop save dialog when available, posts the selected path to `/api/project/save-as`, validates the prepared `.fbs` as a ZIP, and atomically replaces the target.
- **Shared Error Log:** SurveySync records updater, HTTP, diagnostics, and Save As failures to a local redacted JSONL error log. The log can be reviewed, downloaded, bundled into a diagnostic ZIP, or synced to the tracker.
- **Apps Script routing:** Feedback payloads include `route: feedback` and target `Intake`; diagnostics use `route: error_log` and target `Error Log`.
- **Review modal hardening:** Review panes have bounded desktop layout, independent scrolling, sticky actions, safer image sizing, and a mobile fallback.

## Compatibility

v9.1.4 preserves the v9.1.3 field-book profile workflow: book profile assignment, representative preview, Train this field book, persisted profile metadata, and page override precedence remain unchanged.

The installer remains an in-place SurveySync update and keeps the FieldBook Sync migration cleanup and `.fbs` file association handoff.

## Developer Notes

- New focused regression coverage lives in `tests/test_v914_reliability.py`.
- New shared diagnostics helpers live in `surveysync/diagnostics.py`.
- The Apps Script endpoint in `tracker_endpoint/Code.gs` now routes both feedback and error-log payloads.
- Release documentation validation expects this file, `QA_REPORT_v9_1_4.md`, and `IMPLEMENTATION_INDEX.json` to match `VERSION.txt`.
