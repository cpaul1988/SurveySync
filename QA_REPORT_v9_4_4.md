# SurveySync 9.4.4-beta.1 QA

Feedback checked 2026-09-28: Intake has 16 entries, latest FBR-0016; no new entries or live test submissions.

Regression coverage includes PDF/CSV/JSON agreement, saved decisions, separate correction events, exact identifiers, formula text, missing elevations, empty findings, stale project/snapshot refusal, unique native output paths, audit-failure cleanup, and explicit report limits. Browser acceptance exercises the actual export button with an active search filter and verifies full-project report scope. Installed Windows acceptance additionally saves and reads the report ZIP through the real native bridge.

The unchanged release gate and four Windows workflows remain required before installer acceptance. Automated fixtures do not establish professional survey accuracy, field-book hardware performance, or fresh retained-source verification. Candidate evidence belongs to the PR and workflow runs, not the existence of this document.
