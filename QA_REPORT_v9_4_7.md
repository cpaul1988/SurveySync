# SurveySync 9.4.7-beta.1 candidate QA

Connected feedback Intake checked 2026-09-29 before build; FBR-0016 remains latest. No tracker writes or live submissions.

Synthetic regression scenarios cover crew packet and reserved IDs, staged return with no production mutation, preview and approved import, rejection, partial return, stale database, tampered source, failed QC, unrelated-control revision isolation and project API behavior. See tests/test_control_reshoots.py. The full local release gate passed: 679 tests passed, 1 skipped, 63.35% coverage against a 54% floor, static quality, release identity/docs, JavaScript syntax, lint, typing and dependency audit with no known vulnerabilities. Windows installer and representative field-data acceptance remain outstanding. No installer has been published.
