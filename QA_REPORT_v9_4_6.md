# SurveySync 9.4.6-beta.1 candidate QA

Feedback Intake checked after 9.4.5 publication, before this build: FBR-0016 remains latest, with no new rows. GitHub issues had no new reports. No feedback tracker writes or live submissions.

Reproduced 9.4.5 defects: partial crew return was marked complete; saved review report had no workspace download. The patch adds regression tests for partial and legacy returns, project-bound hash-verified report download, unresolved revision matches, and report/acknowledgment invalidation after review changes.

Local release gate passed: 673 tests passed, 1 skipped, 63.06% coverage against a 54% floor; static checks, typing, release identity/docs, and dependency audit passed with no known vulnerabilities. Windows installer and UI acceptance are still required before promotion. This candidate is not published to Beta or Stable.
