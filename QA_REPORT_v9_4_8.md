# SurveySync 9.4.8-beta.1 candidate QA

Connected feedback Intake checked 2026-09-29 before build; FBR-0016 remains latest. No tracker writes or live submissions.

Synthetic regression scenarios cover three row layouts, full-loop preview, immutable original readings, shared turning-point sight isolation, rejected/partial/stale returns, source tampering, schema-6 project migration backup, active revision history, approved package and project API behavior. See tests/test_level_rechecks.py. The full local release gate passed: 686 tests passed, 1 skipped, 63.66% coverage against a 54% floor; release identity/docs, static quality, JavaScript syntax, lint, typing and dependency audit found no known vulnerabilities. Windows installer and representative field acceptance remain outstanding; nothing has been published.
