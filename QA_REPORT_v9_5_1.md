# SurveySync 9.5.1-beta.1 QA report

Pre-build feedback checked 2026-10-01: 16 Intake items, latest FBR-0016; no Form Responses and no Error Log Tracker entries. No tracker data modified.

Scope: read-only DXF import and linked CAD review, explicit unit/alignment confirmation, exact straight-segment checks, approximate curve screening, ordered closure and immutable source/report provenance. Original observations and project points remain unchanged. Limits fail closed rather than presenting a partial QA pass.

Validation in progress: geometry and API regressions, browser controls/light/dark/narrow layout, full release gate, installed Windows/runtime/update acceptance. This file is a pre-CI checkpoint. The candidate PR records final exact-source results and accepted artifact. Public Stable 9.5.0 feeds are unchanged.

Local release gate: 704 passed, 6 skipped, 63.99% coverage; identity/docs, static checks, Ruff, mypy and 105-pin audit passed. Local browser launch is blocked by container socket restrictions; real CAD browser acceptance is required on Windows.
