# SurveySync 9.5.2-beta.1 candidate QA

- Full Linux release gate: **718 passed, 1 skipped**, 64.35% coverage (54% floor).
- Release identity, living documentation, static quality, lint/format, mypy, compilation and JavaScript syntax checks passed. Locked-dependency audit: no known vulnerabilities reported.
- Focused CAD tests: **21 passed**. They exercise snapshot-bound decisions, invalid/stale saves, transactional audit history, conservative block matching, source integrity, comparison/export consistency, escaped HTML and spreadsheet-safe CSV.
- Browser acceptance passed using Chromium with a disposable project, serialized DXF and CSV survey points: import, alignment, layers, linked selection, closure, saved/reopened decision, revised-DXF comparison, selected-change overlay, actual report ZIP contents, light/dark/narrow layouts, stale-project rejection and original-byte preservation.
- Feedback Intake reviewed October 2: 16 entries, latest FBR-0016; unchanged since the prior review.

Windows installer lifecycle and representative real-job DXF/point acceptance remain pending. Synthetic fixture results do not establish field accuracy. Not published or promoted.
