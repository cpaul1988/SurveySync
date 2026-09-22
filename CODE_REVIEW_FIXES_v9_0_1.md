# SurveySync v9.0.1 Code Review Fixes

The September code review findings were incorporated into this candidate.

## Fixed

1. Version tuples are normalized to four numeric components before comparison.
2. Oversized staged update downloads are deleted before the error is raised.
3. Export metadata no longer reports the stale FieldBook Sync v8.0.0 version.
4. Header alias precedence is deterministic; sets were replaced with ordered tuples.
5. `Height` is accepted as an elevation header in FieldBookSync survey imports.
6. ReportSync available-range calculation is a gap walk rather than an integer-domain scan.
7. Empty point files require both explicit bounds rather than silently producing an empty report.
8. FieldBookSync's updater is no longer independent. Legacy API endpoints are compatibility proxies to the SurveySync updater.
9. The visible update UX is a single **Check & Update** action in both shells.
10. SurveySync's default manifest points to `cpaul1988/SurveySync/main/update.json`; the native handoff always lives under `%LOCALAPPDATA%\SurveySync`.

## Validation

- Python compileall passed.
- Main shell JavaScript syntax check passed.
- FieldBookSync JavaScript syntax check passed.
- Maintained SurveySync + FieldBookSync regression selection: **125 passed, 0 failed**.
