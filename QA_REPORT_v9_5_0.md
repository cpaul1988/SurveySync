# SurveySync 9.5.0-beta.1 QA report

Candidate scope: integration inventory and core shared workspace in Visual Survey QA.
Pre-build feedback checked read-only on 2026-10-01: Intake has 16 items, latest
FBR-0016; Form Responses has only headers. No feedback records were changed.

Local full release gate passed: 692 passed, 6 skipped, 63.65% coverage; all
identity, documentation, syntax, Ruff, mypy and 102-pin vulnerability checks passed.
Windows acceptance remains in progress on the final source; PR #21 records the
exact current runs and retained installer. Keyboard focus preservation on table
redraw is included in the real browser acceptance. Release gate, linked browser workflow and exact Windows
installer/update acceptance must pass before publication. Existing source-preservation,
review/correction confirmation and stale-project refusal are retained in the browser
acceptance script. New regressions cover UUID multi-selection, source visibility,
viewport filtering, layouts, splitters, columns and missing optional integration metadata.

No installer is accepted or published by this report. Public 9.4.9 and its update
feeds remain the production baseline until candidate acceptance is complete.
