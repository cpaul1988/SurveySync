# SurveySync v9.2.2 BetaCandidate Release Notes

## Purpose

v9.2.2 is a focused feedback-sync compatibility hotfix for the released v9.2.1 build. A production test report was saved locally but could not sync to Intake because the deployed Google Apps Script endpoint still expected the earlier FieldBook Sync envelope.

## Fix

- Feedback submission now uses the backward-compatible `application: "FieldBook Sync"` envelope used by prior successful SurveySync/FieldBookSync releases.
- The envelope is accepted by both the legacy deployed Intake endpoint and the current `tracker_endpoint/Code.gs` implementation.
- Retry remains idempotent through `local_report_id`; retrying the pending 9.2.1 report after installing 9.2.2 will not intentionally create duplicate Intake rows.
- Local append-only feedback records, selected attachments, diagnostic ZIPs, and remote attachment fallback are unchanged.
- SurveySync Error Log routing remains on the newer routed SurveySync payload and is not downgraded.

## Scope

No ControlSync, Operations Center, QA/QC, staging, snapshots, comparison, delivery, updater, or field-book calculation behavior is changed by this hotfix.
