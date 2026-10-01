# SurveySync 9.5.0-beta.1 QA report

Candidate scope: integration inventory and core shared workspace in Visual Survey QA.
Pre-build feedback checked read-only on 2026-10-01: Intake has 16 items, latest
FBR-0016; Form Responses has only headers. No feedback records were changed.

Validation is in progress. Release gate, linked browser workflow and exact Windows
installer/update acceptance must pass before publication. Existing source-preservation,
review/correction confirmation and stale-project refusal are retained in the browser
acceptance script. New regressions cover UUID multi-selection, source visibility,
viewport filtering, layouts, splitters, columns and missing optional integration metadata.

No installer is accepted or published by this report. Public 9.4.9 and its update
feeds remain the production baseline until candidate acceptance is complete.
