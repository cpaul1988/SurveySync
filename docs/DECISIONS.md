# SurveySync Engineering Decisions

## D-001 Evidence before interpretation

Raw OCR/visual evidence is preserved independently from profile interpretation. Reason: field-note layouts are variable and a wrong semantic assumption must not rewrite what was actually observed.

## D-002 Book default and page override are separate

Introduced/completed in v9.1.3. A field book may have one normal format with exceptional pages. Storing only one profile field would make changing the book default destroy mixed-format exceptions. Precedence is page override > book default > global profile > Auto.

## D-003 In-app training does not mutate neural weights

Training stores labeled examples and derives reusable structural grammar hints. Reason: weight fine-tuning is hardware/toolchain dependent and can regress other handwriting styles. Labeled examples create a controlled dataset for future model tuning.

## D-004 Built-in profile grammar is locked

Built-in rules are known application behavior. Users may add examples or duplicate a built-in into an editable custom profile, but cannot silently rewrite the factory grammar.

## D-005 Explicit field-note topology is evidence

For BRT-style `to PointID` notes, explicit written destination evidence takes precedence over a geometric guess. Coordinates, written azimuth, and visual leader direction remain independent QC channels.

## D-006 Documentation is a build gate

Starting v9.1.3, required developer docs and implementation index are validated before release tests/build. A doc/code mismatch is treated as a release problem rather than ignored documentation drift.

## D-007 Update install requires operator consent

Starting v9.1.4, Check & Update only checks and reports availability until the operator confirms installation. Reason: staging an installer and closing the app are disruptive actions and must not happen as a surprise side effect of a status check.

## D-008 Support diagnostics are local-first and redacted

SurveySync records support errors to a local append-only Error Log before any remote sync attempt. Secret-like fields are redacted, and diagnostic bundles intentionally include metadata/logs rather than survey source files, field-book images, OCR crops, or API credentials.
## D-009 Solution revisions are immutable; restore changes only the active pointer

Starting v9.2.0, every new control or level solve is retained as its own solution revision and becomes active automatically. Restoring an older result updates a small `solution_selections` record; it never deletes, rewrites, or clones the historical solution. Reports use the explicitly active revision, with latest-revision fallback for projects created before this feature. This preserves traceability while letting a surveyor return to a previously reviewed solution.

## D-010 v9.2.1 quality checks warn before they alter data

Project Health, coordinate sanity, staged import conflicts, and Why? evidence are advisory/guardrail layers. SurveySync does not silently swap coordinates, infer a CRS transform, overwrite an existing PointID, or auto-resolve a professional survey QC finding.

## D-011 v9.2.1 recovery is snapshot-based and restore is defensive

Automatic/manual snapshots preserve a consistent database copy. Restore validates checksum and project identity and creates a pre-restore safety snapshot before replacement. This favors recoverability over destructive undo semantics.

## v9.2.3: bulk control before TBC emulation

ControlSync now supports loading and analyzing all control shots, but SurveySync will not label the generic batch solver as TBC-equivalent. Ronald's reference TBC report/screenshots must be validated before implementing that exact profile. The prior Ron three-point workbook profile remains available but is intentionally secondary to the database-first workflow.

All text fields representing local file/folder paths should provide a native Browse action; manual path entry remains available.

## v9.2.4: template database plus migrations
SurveySync uses a clean copied template DB for new projects, but migrations remain authoritative for long-term compatibility. Copy-only versioning would strand older projects whenever tables change. Raw SQL editing is intentionally not exposed; user edits are limited by dataset and field, with stronger controls on observations that affect derived survey results.

## v9.2.5: harden before modularizing

Correctness fixes and diagnostics are isolated in 9.2.5. The large `surveysync/router.py` and `fieldbook_sync/app.py` split is deferred to 9.3.0 so a mechanical architecture refactor is not mixed with production correctness changes. Until then, static ceilings prevent those files and their route counts from growing.

Broad `Exception` handling is treated as technical debt. The 9.2.5 gate prevents growth of broad handlers, eliminates blind broad-exception passes from the SurveySync core, and freezes the remaining FieldBookSync blind-pass count for later per-domain reduction.

## v9.2.5 Control Survey workflow decisions

- Reproduce the useful TBC workflow shape (project coordinates → load → map/explorer → export), not TBC's entire feature surface.
- Ronald's validated three-shot arithmetic/residual method remains the QC authority; automated selection only chooses which three source observations feed that same math.
- 0.045 horizontal and 0.045 vertical are visible/editable defaults, not hidden constants.
- Never silently adjust a failing control into tolerance; produce a reshoot/review result and preserve the closest candidate for provenance.
- Local Site is explicit and reversible. SurveySync stores grid CRS separately and never derives a ground factor/rotation from the loaded data.
- A geographic exporter must use semantic Latitude/Longitude headers; angular values must never be mislabeled Northing/Easting.
- Custom exporter profiles are project-scoped so client/job deliverable conventions follow the project database.

- ControlSync spatial grouping never overwrites the raw survey PointID. A spatially inferred assignment is analysis metadata only; ambiguous clusters are flagged for review and not auto-merged.
- Field-observation rules are independent of coordinate residuals: selected shots default to ≥60 minutes apart, ≥300 epochs OR ≥5 minutes duration, and ≥5 satellites. Explicit field failures disqualify a candidate. Missing metadata does not get invented; strict mode returns REVIEW/UNVERIFIED.
- Old projects are migrated with a separate `observed_time_provided` flag so historical import timestamps cannot masquerade as true shot times.


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.
