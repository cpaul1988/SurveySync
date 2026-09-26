# 9.3.2 — Open-source integration foundation (Unreleased)

- Added attributed MIT-derived horizontal and three-point curve calculations to COGOSync, with explicit 100-foot-arc degree-of-curve handling and project-unit safety.
- Added Phase B COGOSync production tools: polygon area/perimeter/centroid, polyline station-offset with LEFT-positive convention, and station-based simple-curve staking with PC/full-station/PT output.
- Added a separate ControlSync weighted least-squares network adjustment workflow with distance/azimuth/direction/angle observations, residual and redundancy diagnostics, optional Huber robust weighting, and 95% coordinate error ellipses. Ronald's validated best-three workflow remains unchanged.
- Added a separate weighted benchmark-network leveling adjustment with fixed-datum constraints, observation sigmas, redundancy/standardized-residual review, optional Huber weighting, and elevation uncertainty. Ronald's validated three-wire workbook workflow remains unchanged.
- Added a Buzz-inspired, SHA-256 chained project audit ledger with migration/backfill, tamper verification, Project Health enforcement, and audit-head inclusion in deliverable manifests.
- Added release workflow guards so Beta publication cannot run from main and Stable promotion cannot run before the tested candidate reaches main.
- Added THIRD_PARTY_NOTICES.md and a maintained open-source integration plan covering Cogokit, pySurveying, jxl2txt, Buzz, and major geospatial dependencies.
- Stable 9.3.1 remains unchanged while this work is validated on the v9.3.2-open-source-integration branch.

# 9.3.1 — Reliability, support, and review hardening

Adds the integrated Support Center, explicit interrupted-session recovery, Survey Data Inspector with SHA-256 caching and downstream handoff, TopoSync QC profiles/run history/review decisions, and advisory calibration summaries. Fixes startup-update event wiring, false recovery state from file-association maintenance, and stale project/CRS/unit context on Inspector cache hits. See `RELEASE_NOTES_v9_3_1.md`.

# 9.3.0 — Engineering hardening

Shared fail-closed build gates, exact hashed dependencies, gradual lint/types/coverage, domain extraction, visible diagnostic fallbacks and standalone TopoSync rod-height range QC with reviewable correction exports. The supplied SurveySync logo is integrated. See RELEASE_NOTES_v9_3_0.md.

# SurveySync Changelog

This is the canonical human-readable release history. Detailed per-build QA evidence remains in the versioned QA reports for reproducibility, but new feature/fix history should be added here first.

## 9.2.6 - ControlSync production quality
- Added ControlSync CSV/TXT/TSV header/mapping wizard with delimiter/header detection, source preview, user correction, headerless PNEZD defaults, and per-project remembered mappings for true headered layouts. Headerless mappings are deliberately re-reviewed every import so same-width files with different column orders cannot inherit a stale mapping.

### Added
- Rich Trimble Access JobXML occupation metadata: shot date/time, epochs, duration, satellite count, PDOP/HDOP/VDOP, fix type, receiver identity, antenna type and antenna height when the source JXL actually contains those fields. Missing source evidence remains UNVERIFIED.
- Dual-source control evidence merge: a coordinate/grid JXL can be enriched from a raw Access JXL by PointID without moving the accepted project coordinates; both source IDs remain in provenance.
- Project-scoped Control QC profiles for residual tolerances, horizontal/vertical spatial grouping, field-observation rules, satellite minimums and optional DOP ceilings.
- Human-reviewed spatial misnumber workflow with Confirm, Reject and Reassign decisions while preserving raw PointIDs.
- Import diagnostics that identify raw Access JXL versus TBC inventory-only JXL and show available/missing GNSS evidence.
- Complete ControlSync QC package ZIP containing accepted controls, reshoot list, XLSX QC workbook and JSON provenance.
- Rich observation table/filtering and status-aware Control map plus per-control Why? provenance for selected and alternate triplets.

### Improved
- Coordinate-system browser now follows the ArcGIS/Esri Projected Coordinate Systems and Geographic Coordinate Systems folder model, including State Plane datum/state folders, UTM, State Systems, County Systems, National Grids, Continental and World families for the locally available EPSG/ESRI catalog.
- SurveySync and FieldBookSync dialogs are resizable; SurveySync remembers dialog size by workflow and FieldBookSync remembers its modal size. The CRS picker opens large by default.
- Spatial grouping can enforce a separate vertical tolerance so nearby XY shots at materially different elevations are not automatically grouped.
- Duplicate/re-import preflight reports exact repeats and PointID/coordinate conflicts before data is added. Control observation indexes improve large-project lookup performance.

### Boundaries
- TBC inventory-only JXL files with an empty FieldBook cannot provide raw occupation time, DOP, satellite, epoch or receiver evidence; SurveySync reports those fields as missing rather than inventing values.
- `.job` remains a proprietary Trimble format and uses Trimble's official converter when available; `.jxl` is read directly.
- Esri's proprietary installed coordinate-system folder metadata is not exposed by PROJ, so SurveySync mirrors the documented ArcGIS folder organization across the EPSG/ESRI systems available locally rather than copying private ArcGIS installation metadata.

## 9.2.5 - Control Survey workflow, correctness and error visibility

### Added
- TBC-inspired Control Survey workspace: project coordinate setup → load all repeated control shots → spatial map/Project Explorer → run all-control QC → accepted/reshoot deliverables.
- Offline EPSG/ESRI coordinate-system library with an ESRI-style folder browser (Projected / Geographic, State Plane by state, UTM by datum family) plus project-level Local Site / modified-ground settings with explicit grid/local origins, grid-to-ground factor and clockwise rotation.
- Automated best-three control selection using Ronald's validated arithmetic-average/residual method with 0.045 H/V defaults, all-triplet provenance, immutable active solutions and next-available reshoot labels.
- Field-observation QC for selected shots: minimum 60-minute separation, 300 epochs OR 5-minute occupation, and at least 5 satellites, with strict metadata verification enabled by default in the Control Survey workspace.
- Reusable project-scoped ControlSync export profiles with selectable Point/Control ID, N/E/Z, Code, residuals, source shots, status, WGS84 Lat/Long and alternate projected CRS output.
- Direct ControlSync import of Trimble `.job` and JobXML `.jxl/.xml` files using the existing official Trimble converter path, with available GNSS shot time/epoch/duration/satellite metadata carried into field QC. JobXML exported by TBC with empty `Reductions` and populated `InventoryData` is supported directly.

### Fixed
- FBR-0015: GISSync Trimble JOB/JobXML Browse now falls back to the local Windows picker if the pywebview native dialog fails, and uses the universal unfiltered picker path for maximum Windows compatibility.
- Trimble JobXML intake now falls back to `InventoryData` when `Reductions` is empty, matching real TBC exports. Non-shot PRS/reference points remain in immutable source evidence but are not turned into false one-observation ControlSync groups.
- Control shot grouping now treats trailing alphabetic shot suffixes as observations of the same base control, so `100A`, `100B`, `100C` group under Control `100` whether the label arrives in Point ID or Control ID. Existing projects created by the older parser are auto-normalized without changing coordinates or source point labels.
- Spatial control grouping now cross-checks naming against horizontal location. A likely typo such as `2C` landing with `1A`/`1B` is flagged as a probable misnumber and may be associated with Control `1` for QC as inferred `1C`, while the raw `2C` PointID remains unchanged. Ambiguous nearby IDs are flagged for review instead of silently merged.
- Reshoot numbering now continues from the grouped base control (`100D`, `100E`, `100F`) instead of generating doubled suffixes such as `100AA`.
- Control CSV intake now stores shot time provenance, epoch count, occupation duration and satellite count when present; missing metadata is REVIEW/UNVERIFIED under strict field QC instead of being silently accepted.
- Coordinate sanity now validates Northing/Easting as row-aligned pairs instead of filtering each axis independently.
- Non-finite coordinate pairs are excluded explicitly and reported with their actual PointIDs.
- Remote-coordinate outlier attribution now keeps each distance tied to its source row, preventing the wrong PointID from being reported.
- Geographic custom exports no longer place angular values under Northing/Easting headers.

### Improved
- TBC-style `P,N,E,elev,Code` control files preserve original shot labels and Code/Description values.
- Accepted-control XLSX records CRS/units and Local Site metadata for traceability.
- SurveySync core fallback paths now log diagnostic context instead of silently swallowing broad exceptions.
- Added persistent rotating `surveysync.log` and a static-quality build gate.

### Architecture
- Project DB schema 4 stores project coordinate settings, Control QC runs/candidates, and per-shot field-observation metadata (time provenance, epochs, duration and satellites).
- No domain-route split is performed in 9.2.5. The large route files remain frozen pending the planned 9.3.0 mechanical modularization.

## 9.2.4 - Project database platform
- Formalized one-project/one-database architecture, template DB bootstrap, schema migration backups, project workflow templates, Project Data Manager, controlled edits, and database health/maintenance.

## 9.2.3 - Control database and universal Browse
- Made bulk Control Survey Database the primary ControlSync workflow and added native Browse controls to path inputs.

## 9.2.2 - Feedback Intake compatibility hotfix
- Restored the legacy-compatible feedback envelope so pending reports sync to both endpoint generations.

## 9.2.1 - Operations Center and safety
- Added project health/QA rules, staging, snapshots, comparison, export profiles, background queue, Review Center, map QC, and Why? explanations.

## 9.2.0 - Active solution revisions
- Added non-destructive control/level active revision management, comparison, restore, and active-revision-aware reporting.

## 9.1.4 - Reliability and diagnostics
- Added updater consent, atomic Save As, shared diagnostics/Error Log support, and Review layout hardening.
