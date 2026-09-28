# SurveySync 9.4.4-beta.1 - QA review reports

Adds a PDF and CSV review package to Visual Survey QA under Home and QASync. Reports include full-project findings, saved decisions and reasons, record UUIDs, coordinate context, registered source references, and before/after elevations from separately approved correction exports. Screen filters and unsaved previews are excluded.

The ZIP contains QA_Review.pdf, findings.csv, corrections.csv, exact JSON evidence, and SHA-256 checksums. Native desktop saves a unique package under Exports/VisualQA/Reports and reveals its folder; browser sessions download it.

Original observations and canonical coordinates are unchanged. Source hashes are registered import hashes, not fresh verification. Prepared-by labels and checksums are not professional or cryptographic signatures. Stale project/evidence, invalid input, and oversized reports fail explicitly. See docs/QA_REVIEW_REPORTS.md for scope and limits.

This is a candidate; publication requires acceptance of its exact installer. Field-book hardware validation, official Trimble conversion and production signing remain outside this update.
