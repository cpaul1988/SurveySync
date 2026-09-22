# SurveySync v9.2.1 BetaCandidate Release Notes

## Purpose

v9.2.1 is a platform-hardening release. It keeps the v9.2.0 ControlSync revision workflow intact and adds a shared Operations Center so data quality, recovery, review, comparison, delivery, and long-running work are handled consistently across SurveySync.

## Improvements 1–16

1. **Project Health Check / Preflight** — one project-wide scan reports READY, REVIEW, or BLOCKING across project identity, CRS/units, immutable sources, canonical points, control/level QC, attachments, deliverables, coordinate sanity, and background-task failures.
2. **Central QA/QC Rules Engine** — project-local rules in `.surveysync/qa_rules.json` control reusable guardrails instead of scattering tolerances across screens. Rules can be enabled/disabled without deleting their definitions.
3. **Import Staging Area** — the canonical point-file workflow now supports preview → mapping → conflict review → commit. Staging records are persistent and existing PointIDs are never overwritten. This is the first integrated staging path; legacy specialized Control/GIS/FieldBook importers remain direct in 9.2.1 for compatibility.
4. **Smart Column / Code Mapping** — common PointID/Northing/Easting/Elevation/Description headers are detected automatically and approved mappings are remembered for later files with the same header signature.
5. **Universal Project Timeline** — audited activity from SurveySync modules is presented as a project timeline for traceability.
6. **Autosave + Crash Recovery** — bounded automatic recovery snapshots are created when the project changes. Snapshot creation uses SQLite backup semantics and runs opportunistically while SurveySync is active.
7. **Manual Project Snapshots** — operators can create named snapshots, compare them to current project counts/revision state, and restore safely. A pre-restore safety snapshot is always created first.
8. **File / Project Comparison** — revised point files or another SurveySync project can be compared against the current project for added, removed, changed, and unchanged points with coordinate/elevation/description deltas.
9. **Smart Export Profiles** — reusable CSV/PNEZD/GeoJSON output recipes remember precision and packaging preferences. Custom profiles can be created in the Operations Center.
10. **Deliverable Package Builder** — creates a ZIP with selected outputs plus `SurveySync_Manifest.json` containing project identity, CRS/units, sizes, and SHA-256 checksums.
11. **Coordinate Sanity Detection** — conservative checks flag suspicious ranges, possible Northing/Easting reversal, apparent geographic/projected mismatch, remote outliers, and mixed context. SurveySync warns only; it never silently transforms or repairs survey coordinates.
12. **Project Map / Visual QC** — a shared project overview plots canonical survey points, utility structures, and active control solutions for quick spatial inspection.
13. **Batch Processing** — point-file staging, point comparison, and preflight/package jobs can be queued in batches.
14. **Background Task Queue** — longer jobs have persistent QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED state, progress, cancellation, and error capture instead of freezing the main shell.
15. **Unified Review Center** — open QA findings, unreviewed points, staged-import conflicts, and failed background tasks are collected in one place.
16. **Why? Explanations** — review items expose the evidence and reason behind QA flags, point-review state, failed tasks, and staged-import warnings.

## Safety behavior

- Original source evidence remains immutable and checksum-backed.
- Staged imports do not overwrite an existing PointID.
- Snapshot restore validates project identity/checksum and creates a safety snapshot before replacement.
- Coordinate sanity is advisory and never changes coordinates automatically.
- QA findings are review evidence, not a substitute for professional survey judgment.
- v9.2.0 ControlSync solution history remains immutable; active-revision selection behavior is unchanged.

## Beta validation focus

Windows Beta testing should exercise recovery after a forced app close, staged duplicate-point handling, a project-to-project comparison, custom export profiles, deliverable ZIP manifest verification, batch cancellation/failure reporting, Review Center explanations, and all retained v9.2.0 ControlSync revision workflows.


## BetaCandidate refresh: Windows snapshot handle fix

The first real Windows build identified a SQLite handle-lifetime issue in snapshot creation. Python's SQLite connection context manager commits/rolls back transactions but does not close the connection itself. On Windows this left the temporary snapshot database locked and caused `WinError 32` during cleanup; the snapshot API then surfaced the same failure as HTTP 400. v9.2.1 now closes snapshot SQLite handles deterministically before temporary-directory cleanup and includes a regression test for that behavior.
