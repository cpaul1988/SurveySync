# SurveySync / FieldBookSync API Reference

This is a developer-oriented index, not a complete OpenAPI dump.

## Field-note profile APIs

- `GET /api/field-note-profiles` — installed profiles, selected global mode, example counts.
- `POST /api/field-note-profiles` — save custom profile.
- `POST /api/field-note-profiles/{id}/duplicate` — editable custom copy.
- `DELETE /api/field-note-profiles/{id}` — delete custom profile only.
- `GET /api/field-note-profiles/{id}/export` — export `.fnp`.
- `POST /api/field-note-profiles/import` — import `.fnp` with path/size safety checks.
- `POST /api/select-field-note-profile` — set global analysis profile or Auto.

## v9.1.3 field-book workflow APIs

- `GET /api/fieldbook-profile-assignments` — imported books plus installed profile catalog.
- `POST /api/fieldbook-profile-assignment` — assign `AUTO` or a profile to one imported book. Body: `source_name`, `profile_id`, optional `mode`.
- `GET /api/fieldbook-training-preview?source_name=...&limit=5` — representative pages for in-context training.
- `GET /api/pages` — page URLs plus book profile, page override, and effective profile.
- `PUT /api/pages/{page_id}/field-note-profile` — set page-specific override.

## v9.2.0 ControlSync revision APIs

- `GET /api/v9/control/solutions?control_id=...` — list immutable stored control solutions and identify the active revision.
- `POST /api/v9/control/activate` — make an existing control solution active without deleting or cloning any revision. Body: `control_id`, `solution_id`, optional `note`.
- `GET /api/v9/control/compare?control_id=...&solution_a=...&solution_b=...` — compare N/E/Z deltas, horizontal shift, method/settings changes, and QC pass-state changes between two stored control solutions.
- `GET /api/v9/level/history?run_id=...` — list immutable stored level solutions and identify the active revision.
- `POST /api/v9/level/activate` — make an existing level solution active without changing stored observations or other solution revisions. Body: `run_id`, `solution_id`, optional `note`.
- `GET /api/v9/level/compare?run_id=...&solution_a=...&solution_b=...` — compare closure, adjusted ending elevation, method/settings changes, adjustment state, and QC flag changes.

## v9.1.4 reliability and diagnostics APIs

- `POST /api/project/save-as` — save the current FieldBookSync project to a chosen `.fbs` path. Body: `path`. The server prepares a bundle, validates that it is a ZIP, and atomically replaces the target.
- `GET /api/v9/update/check` — inspect the shared SurveySync release channel without closing the app.
- `POST /api/v9/update/check-and-install` — install only after explicit consent. Body: `confirm_install`. Without `true`, an available update returns `action: confirmation_required`.
- `POST /api/update/download-install` — legacy FieldBookSync compatibility route with the same confirmation behavior.
- `GET /api/v9/diagnostics/errors` — recent redacted local error-log entries.
- `GET /api/v9/diagnostics/error-log` — download the append-only `SurveySync_Error_Log.jsonl`.
- `POST /api/v9/diagnostics/export` — create a privacy-scoped diagnostic ZIP containing system/config summary, local logs, and the redacted error log.
- `POST /api/v9/diagnostics/error-log/sync` — submit recent error-log entries to the shared Google Apps Script tracker. Payloads use `route: error_log` and target the `Error Log` sheet.

## Training APIs

- `GET/POST /api/field-note-training/examples`
- `DELETE /api/field-note-training/examples/{profile_id}/{example_id}`
- `GET /api/field-note-training/examples/{profile_id}/{example_id}/image`
- `POST /api/results/{point_id}/teach-profile`

## v9.2.1 Operations Center APIs

- `GET/POST /api/v9/qa/rules` — read/save project QA rules.
- `POST /api/v9/qa/issues/status` — resolve/reopen a QA finding.
- `POST /api/v9/import/stage`, `GET /api/v9/import/stages`, `POST /api/v9/import/commit` — preview and explicitly commit canonical point imports.
- `GET/POST /api/v9/import/mappings` — read/save learned column mappings.
- `GET /api/v9/timeline` — project-wide audit timeline.
- `GET/POST /api/v9/snapshots`, `GET /api/v9/snapshots/compare`, `POST /api/v9/snapshots/restore` — continuity snapshots.
- `POST /api/v9/compare/points` — compare an external point file or another SurveySync project to the current project.
- `GET/POST /api/v9/export-profiles`, `POST /api/v9/export/run`, `POST /api/v9/deliverable-package` — repeatable export/delivery workflows.
- `GET /api/v9/project-map`, `GET /api/v9/review-center`, `GET /api/v9/explain` — visual/review/evidence services.
- `GET /api/v9/tasks`, `POST /api/v9/tasks/cancel`, `POST /api/v9/batch` — persistent task queue and batch work.

## v9.2.3 Control Survey Database

- `GET /api/v9/control/observations?control_id=&limit=` — list stored control survey shots.
- `POST /api/v9/control/analyze-all` — analyze every stored Control ID meeting the minimum observation count using arithmetic or weighted averaging.
- `POST /api/v9/control/import-analyze` — preserve all shots from a control file, then analyze all eligible controls and write a database summary report.
- `GET /api/v9/dialog/select-files` — native/browser-fallback multi-file picker used by shared path controls.

## v9.2.4 Project database APIs
- `GET /api/v9/project-templates` lists supported new-project templates.
- `GET /api/v9/data-manager/overview` returns DB schema/version, size, stale-result count and dataset counts.
- `GET /api/v9/data-manager/rows?dataset=...&search=...` returns bounded rows from an allow-listed dataset.
- `POST /api/v9/data-manager/edit` performs allow-listed audited edits; controlled datasets require `reason`.
- `GET /api/v9/database/health` runs non-destructive integrity/schema/foreign-key checks.
- `POST /api/v9/database/maintenance` creates a safety snapshot then performs safe WAL/ANALYZE/optimize maintenance.

## v9.2.5 Control Survey / coordinate APIs

- `GET /api/v9/crs/library?query=&limit=` — search installed projected or geographic EPSG/ESRI definitions offline.
- `GET /api/v9/crs/browser?path=&limit=` — browse the local CRS catalog as ESRI-style folders (Projected/Geographic, State Plane by state, UTM by datum family).
- `GET /api/v9/project/coordinate-system` — current grid CRS, units and Local Site settings.
- `POST /api/v9/project/coordinate-system` — validate/persist project CRS plus optional modified-ground transform.
- `GET /api/v9/control/workspace` — project coordinate context, grouped controls, all observations and latest QC run.
- `POST /api/v9/control/qc-best-three` — evaluate every valid three-shot combination per control; defaults H/V tolerance to 0.045. Optional/defaulted field-QC inputs are `require_field_metadata=true`, `min_time_separation_minutes=60`, `min_epochs=300`, `min_observation_minutes=5`, `min_satellites=5`, plus `spatial_group_tolerance`.
- `GET /api/v9/control/qc-run?run_id=` — retrieve a persisted QC run.
- `POST /api/v9/control/qc-deliverables?run_id=` — write accepted/reshoot CSV + QC XLSX.
- `GET /api/v9/control/export-profiles` — list project-scoped custom ControlSync exporter profiles.
- `POST /api/v9/control/qc-export` — accepted-control CSV/TXT using selected fields and project/geographic/alternate projected CRS output.
- `POST /api/v9/control/network-adjust` — separate constrained 2D weighted least-squares workflow for conventional control networks. Supports distance, azimuth, direction, and horizontal-angle observations; returns adjusted coordinates, residuals, redundancy numbers, standardized-residual review flags, covariance-derived 95% error ellipses, and optional Huber robust weights. Ronald's best-three workflow is not modified.
- `POST /api/v9/level/network-adjust` — separate weighted least-squares benchmark-network adjustment using elevation-difference observations and fixed benchmarks. Returns adjusted elevations, uncertainty, redundancy and standardized-residual review flags, with optional Huber robust weighting. The Ron three-wire workbook profile is not modified.

`coordinate_mode=geographic` emits Latitude/Longitude fields. `coordinate_mode=target` requires a projected target CRS when output fields are Northing/Easting.

### Control observation metadata
Control CSV intake recognizes common shot-time/date, epoch-count, duration and satellite-count headers. These values persist on `control_observations`. Strict Control Survey QC requires all three selected shots to prove the configured field criteria; missing metadata becomes REVIEW/UNVERIFIED, while explicit short-duration/time-spacing/satellite failures disqualify the candidate.

### ControlSync Trimble field-file intake

`POST /api/v9/control/import` accepts CSV/TXT/TSV plus Trimble Access `.job`, `.jxl`, and `.xml`. For `.job`, SurveySync uses the installed Trimble ASCII File Generator to create JobXML from the immutable project source copy. Response metadata includes `format`, `conversion`, `jobxml_path`, `trimble_metadata`, and `field_metadata_counts`. Reduced points are inserted into the project Control Survey database; if `Reductions` is empty, TBC-style `InventoryData` points are used instead. Non-shot reference/base points remain in source evidence and are excluded from repeated-control QC groups. Available JobXML occupation time, epochs, duration, and satellite count feed the standard ControlSync field-QC rules.

## v9.2.6 ControlSync delimited-file mapping endpoints

- `POST /api/v9/control/import-preview` — sniff CSV/TXT/TSV delimiter/header structure, auto-detect common control/GNSS columns, return confidence/missing-required fields and a row preview. Trimble JOB/JXL/XML reports that structured mapping is not required.
- `POST /api/v9/control/import-mapped` — import a confirmed mapping into the project Control Survey database. Optional `remember_mapping=true` stores the approved header signature/mapping inside the project for later files with the same headings.

## v9.2.6 ControlSync production endpoints

- `GET /api/v9/control/qc-profiles` — list project Control QC profiles.
- `POST /api/v9/control/qc-profiles` — create/update a profile including residual, grouping, field-duration, satellite and optional PDOP/HDOP/VDOP limits.
- `GET /api/v9/control/import-diagnostics` — identify the most recent control source type and the GNSS metadata actually present/missing.
- `GET /api/v9/control/grouping-reviews` — return probable misnumbers/conflicts from the latest QC run plus saved human decisions.
- `POST /api/v9/control/grouping-reviews` — Confirm, Reject or Reassign a control observation grouping without renaming its raw PointID.
- `POST /api/v9/control/merge-metadata` — merge missing raw GNSS occupation evidence into matching project control observations by PointID without changing their N/E/Z.
- `POST /api/v9/control/export-package` — build a ZIP containing accepted/reshoot deliverables and ControlSync provenance for a QC run.

`POST /api/v9/control/qc-best-three` now accepts an optional vertical grouping tolerance and optional maximum PDOP, HDOP and VDOP thresholds in addition to the existing residual/time/epoch-duration/satellite rules.


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.


### 9.3.0 TopoSync range QC

Standalone point import, editable code classifications, feature-chain range detection, evidence reports and reviewed-copy exports are implemented in `surveysync/topo` and `surveysync/static/topo_qc.js`. See [TopoSync workflow and limits](TOPO_ROD_HEIGHT_QC.md). Synthetic regression coverage is in `tests/test_topo_rod_ranges.py`; real field and Windows acceptance remain pending. Supplied branding replaces the product globe/installer assets.

## v9.3.1 Support Center, recovery, and data inspection

### Support Center

- `GET /api/v9/support/summary` — returns merged local diagnostic/sync state, locally stored feedback summaries, automatic retry state, and interrupted-session recovery availability.
- `POST /api/v9/support/errors/sync` — retries selected local diagnostic errors, or all pending errors when no IDs are supplied. Survey source files are not attached.
- `POST /api/v9/support/errors/report` — creates a project-independent Feedback Wizard bug report from one recorded SurveySync error and attempts Intake synchronization.
- `POST /api/v9/support/feedback/refresh` — requests tracker status for locally stored feedback report IDs.
- `POST /api/v9/support/recovery/restore-latest` — restores the latest matching recovery snapshot only when `confirmed=true` and the interrupted project matches the currently open project.
- `POST /api/v9/support/recovery/dismiss` — dismisses the current interrupted-session notice without restoring data.

### Survey Data Inspector

- `POST /api/v9/data-inspector/inspect` — inspects a local CSV/TXT/TSV/PNEZD/ASC/JOB/JXL/JobXML source, caches the result by source SHA-256, and returns detected schema/QC information plus compatible downstream targets.
- `GET /api/v9/data-inspector/recent` — lists recent cached source inspections.
- `POST /api/v9/data-inspector/cache/clear` — removes only Inspector cache artifacts; original survey sources are untouched.
- `POST /api/v9/topo/survey/preview-path` — accepts an Inspector-produced delimited path for TopoSync preview without altering the source.
- `GET /api/v9/topo/profiles`, `POST /api/v9/topo/profiles`, and `DELETE /api/v9/topo/profiles/{profile_id}` — manage reusable advisory rod-height QC profiles.
- `GET /api/v9/topo/runs` — lists recent TopoSync rod-height analyses in the active workspace.
- `POST /api/v9/topo/runs/{run_id}/review` — records an explicit candidate decision and review reason.
- `GET /api/v9/topo/reviews/calibration` — summarizes review history and may suggest an offset-consistency tolerance; it never applies that suggestion automatically.

## v9.3.2 open-source integration APIs

- `POST /api/v9/cogo/curve` — solve a simple circular horizontal curve from exactly two independent elements. Supported elements include radius, central angle, tangent, arc length, long chord, external, middle ordinate, and the explicitly named 100-foot-arc degree of curve. The degree-of-curve input is rejected for meter projects.
- `POST /api/v9/cogo/three-point-curve` — compute the center and radius of the unique circular curve through three Northing/Easting points; collinear points are rejected.
- `GET /api/v9/audit/verify` — verify the active project's SHA-256 audit chain and return event count, chain count, broken sequence/reason when invalid, and the current audit head hash when valid.
- `POST /api/v9/cogo/polygon` — compute closed-polygon area, signed area/orientation, perimeter, and centroid from Northing/Easting vertices.
- `POST /api/v9/cogo/station-offset` — project a point onto a polyline alignment and return station, nearest coordinate, segment azimuth, and signed offset. Positive offset is LEFT looking ahead.
- `POST /api/v9/cogo/curve-stake` — generate PC/full-station/PT stake coordinates, chord/deflection data, and tangent azimuths for a simple LEFT or RIGHT circular curve.

The extended curve engine is adapted from the MIT-licensed Cogokit project and is attributed in `THIRD_PARTY_NOTICES.md`. The audit-chain design is inspired by Block's Apache-2.0 Buzz audit architecture but implemented natively for SurveySync SQLite projects.

