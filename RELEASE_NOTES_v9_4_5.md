# SurveySync 9.4.5-beta.1 — revision and delivery review

Adds a connected project review workspace under Home, QASync and ReportSync. Compare revised point CSVs against canonical records with movement arrows, signed coordinate/elevation differences, additions and removals. Duplicate PointIDs remain ambiguous until old UUIDs are explicitly paired to incoming rows. CRS and units must match the project; no conversion is assumed.

Turn QA findings into crew PDF/CSV rechecks and record returned observations. Assign and release numeric point ranges with overlap and occupied-ID checks. Attach hashed photos, sketches and field-book PDFs to findings, then choose evidence for the PDF/CSV review report.

The readiness checklist tracks coordinate context, outstanding findings and rechecks, reservation conflicts, a current report and a reviewer acknowledgment. Teams can opt into enforcing the required checks when the existing deliverable package is built. Default package behavior remains available until the gate is enabled. Source files and canonical coordinates are unchanged.

See docs/REVISION_REVIEW_WORKFLOW.md for inputs, limits and behavior. This is an unpublished candidate; its exact Windows installer requires acceptance before Beta or Stable promotion.
