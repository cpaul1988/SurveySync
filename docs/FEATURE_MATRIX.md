# SurveySync Feature Matrix

| Area | Feature | Status | Primary implementation | Tests |
| --- | --- | --- | --- | --- |
| FieldBookSync | Field-book PDF/image import | Implemented | `fieldbook_sync/app.py`, `fieldbook_sync/fieldbook.py` | legacy + v9 tests |
| FieldBookSync | BRT standard note grammar | Implemented | `fieldbook_sync/field_note_profiles.py`, `ai_reader.py`, `intelligence.py` | `test_v912_field_note_profiles.py`, `test_v911_features.py` |
| FieldBookSync | Field Note Profile Trainer | Implemented | profile module + FieldBookSync UI | `test_v912_field_note_profiles.py` |
| FieldBookSync | Book-specific profile selector after import | Implemented v9.1.3 | `app.py`, `models.py`, dashboard UI | `test_v913_fieldbook_training_workflow.py` |
| FieldBookSync | Representative first-page training preview | Implemented v9.1.3 | `/api/fieldbook-training-preview`, UI | `test_v913_fieldbook_training_workflow.py` |
| FieldBookSync | Mixed-format page override | Implemented | page profile endpoint + Trainer | v9.1.2/v9.1.3 tests |
| FieldBookSync | Atomic native Save As for `.fbs` projects | Implemented v9.1.4 | `desktop.py`, `fieldbook_sync/app.py`, project bundle writer | `test_v914_reliability.py` |
| FieldBookSync | Responsive Review modal bounds | Implemented v9.1.4 | `fieldbook_sync/static/app.js`, `styles.css` | `test_v914_reliability.py` |
| FieldBookSync | `.fnp` import/export | Implemented | `field_note_profiles.py` | v9.1.2 tests |
| ReportSync | Available Point Ranges | Implemented | `surveysync/reports.py`, `router.py` | v9.1.1 tests |
| ControlSync | Ron 3-point QC/final/reshoot | Implemented | `surveysync/control.py` | v9.1.1 tests |
| ControlSync | Active revision compare/restore for control and level solutions | Implemented v9.2.0 | `surveysync/revisions.py`, control/level services, router, UI, reporting | `test_v920_control_revisions.py` |
| Trimble | JOB via official converter / JXL direct | Implemented | `surveysync/trimble_job.py` | v9.1.1 tests |
| Updater | Beta/Stable manifest and one-button update | Implemented | `surveysync/updater.py`, `scripts/update_manifest.py` | v9 API/core tests |
| Updater | Consent-required install/shutdown | Implemented v9.1.4 | `surveysync/router.py`, FieldBookSync compatibility route, UI | `test_v914_reliability.py` |
| Feedback | Shared Intake tracker submission | Implemented | `fieldbook_sync/feedback.py` | feedback legacy tests |
| Diagnostics | Shared redacted Error Log and support ZIP | Implemented v9.1.4 | `surveysync/diagnostics.py`, `router.py`, Apps Script route | `test_v914_reliability.py` |

| QASync | Project Health + centralized QA rules + coordinate sanity | Implemented v9.2.1 | `surveysync/qa.py`, `qa_rules.py`, `coordinate_sanity.py` | `test_v921_operations.py` |
| Core | Recovery/manual snapshots + project timeline | Implemented v9.2.1 | `surveysync/continuity.py`, `operations.py` | `test_v921_operations.py` |
| Core | Safe point-import staging + learned column mappings | Implemented v9.2.1 | `surveysync/staging.py` | `test_v921_operations.py` |
| Core | Revised file / SurveySync project point comparison | Implemented v9.2.1 | `surveysync/comparison.py` | `test_v921_operations.py` |
| ReportSync | Smart export profiles + checksum-backed deliverable packages | Implemented v9.2.1 | `surveysync/delivery.py` | `test_v921_operations.py` |
| Core | Background batch queue + Review Center + Why? + visual QC map | Implemented v9.2.1 | `surveysync/task_queue.py`, `operations.py`, UI | `test_v921_operations.py` |

## v9.2.3 additions

| Capability | Status | Notes |
| --- | --- | --- |
| Bulk Control Survey Database | Implemented | Stores repeated shots for all Control IDs in project SQLite |
| Analyze All Controls | Implemented | Arithmetic/weighted generic analysis, immutable solutions, summary CSV |
| TBC exact analysis profile | Pending reference validation | Requires Ronald's TBC report/screenshots before implementation |
| Universal path browsing | Implemented | Native file/folder browse plus multi-file batch selection |

## v9.2.4 additions
- Project-specific template database and schema migrations.
- Standard, EDSI Engineering/Topo, Boundary, Sewer/Utility, Control Network and Construction Staking project templates.
- Project Data Manager with search, audited edits and protected read-only tables.
- Controlled-edit safety snapshots, field-level history and stale-result invalidation.
- Database integrity/foreign-key/schema health plus safe WAL/ANALYZE/optimize maintenance.

## v9.2.5 additions

- Coordinate sanity uses row-aligned Northing/Easting/PointID tuples and reports invalid coordinate rows explicitly.
- Remote coordinate checks preserve source PointID attribution and use a robust cluster-relative threshold.
- SurveySync core persistent logging plus FieldBookSync state-persistence warnings improve support diagnostics.
- Static quality gate freezes blind/broad exception growth and pre-9.3 API monolith growth while blocking common unsafe Python patterns and duplicate routes/functions.
- `CHANGELOG.md` is the canonical human-readable release summary going forward.

### v9.2.5 Control Survey additions

| Capability | Status | Notes |
| --- | --- | --- |
| TBC-inspired Control Survey workspace | Implemented | Set project CRS/Local Site, load all repeated shots, spatial map/Project Explorer, run QC, export |
| Offline CRS library | Implemented | ESRI-style Projected/Geographic folder browser + search over installed EPSG/ESRI definitions; State Plane grouped by state, UTM by datum family; no web dependency |
| Local Site / modified-ground transform | Implemented | Explicit grid/local origins, grid→ground factor, clockwise rotation; reversible |
| Best-three all-control QC | Implemented | Every 3-shot combination, 0.045 H/V defaults, immutable selected solution + provenance |
| Accepted/reshoot outputs | Implemented | CSV + XLSX; next-unused requested reshoot suffixes |
| Reusable custom control exporters | Implemented | Select fields/Code/LatLon; defaults to project/local coordinates; alternate projected CRS supported |
| Full TBC site calibration/geoid/GNSS adjustment | Not claimed | Requires separate validated algorithms/reference workflows |

| Spatial misnumber detection | Implemented | Configurable horizontal clustering cross-checks Control IDs; probable typos are flagged and used as non-destructive QC assignments only when confidence rules pass |
| Field observation QC | Implemented | Defaults: ≥60 min between selected shots, ≥300 epochs OR ≥5 min occupation, ≥5 satellites; missing metadata is REVIEW when strict mode is enabled |

| ControlSync | Direct Trimble JOB / JobXML control intake | Implemented v9.2.5 | Official JOB→JobXML converter path; supports normal `Reductions` and TBC `InventoryData` fallback; available GNSS occupation metadata enters Control QC | `test_v925_control_workspace.py`, `test_v911_features.py` |

## v9.2.6 additions

| Area | Feature | Status | Primary implementation | Tests |
| --- | --- | --- | --- | --- |
| ControlSync | Rich Trimble Access JXL occupation metadata + DOP/receiver/antenna fields | Implemented when present in source | `trimble_job.py`, `control.py`, schema 5 | `test_v926_control_production.py` |
| ControlSync | Dual-source grid-coordinate + raw-GNSS metadata merge | Implemented | `control.py`, `control_workspace_routes.py` | `test_v926_control_production.py` |
| ControlSync | Misnumber review + horizontal/vertical spatial grouping | Implemented | `control.py`, ControlSync UI | v9.2.5 + v9.2.6 tests |
| ControlSync | Project QC profiles + DOP ceilings | Implemented | schema 5, `control.py`, ControlSync UI | `test_v926_control_production.py` |
| ControlSync | Complete QC/provenance package | Implemented | `control_workspace_routes.py` | `test_v926_control_production.py` |
| ControlSync | Automatic delimited-header detection + reviewable/remembered column mapping | Implemented v9.2.6 | `control_import_mapping.py`, `control.py`, `control_workspace_routes.py`, ControlSync UI | `test_v926_control_production.py` |
| Core UI | Resizable remembered modal dialogs | Implemented | SurveySync/FieldBookSync JS/CSS | `test_v926_control_production.py` |
| CRS | ArcGIS/Esri-aligned folder navigation | Implemented for locally available EPSG/ESRI catalog | `crs.py`, SurveySync UI | v9.2.5 + v9.2.6 tests |


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.


### 9.3.0 TopoSync range QC

Standalone point import, editable code classifications, feature-chain range detection, evidence reports and reviewed-copy exports are implemented in `surveysync/topo` and `surveysync/static/topo_qc.js`. See [TopoSync workflow and limits](TOPO_ROD_HEIGHT_QC.md). Synthetic regression coverage is in `tests/test_topo_rod_ranges.py`; real field and Windows acceptance remain pending. Supplied branding replaces the product globe/installer assets.

## v9.3.1 additions

| Area | Feature | Status | Primary implementation | Tests |
| --- | --- | --- | --- | --- |
| Support | Unified Support Center with local diagnostic status, retry/sync, Report This Error, feedback-status refresh and redacted diagnostic export | Implemented | `surveysync/support_center.py`, `surveysync/static/support_center.js` | `test_v931_release_candidate.py` + existing diagnostics/feedback regressions |
| Core | Clean/interrupted session tracking and explicit matching-project recovery restore | Implemented | `surveysync/session_recovery.py`, `desktop.py`, Support Center | `test_v931_release_candidate.py` |
| Data | Survey Data Inspector for delimited and Trimble survey sources with SHA-256 cache and workflow handoff | Implemented | `surveysync/data_inspector.py`, `surveysync/static/data_inspector.js` | `test_v931_release_candidate.py` |
| TopoSync | Reusable rod-height QC profiles | Implemented | `surveysync/topo/profiles.py`, `routes.py` | `test_v931_release_candidate.py` |
| TopoSync | Run history, explicit candidate review decisions, advisory calibration summary | Implemented | `surveysync/topo/storage.py`, `routes.py`, `topo_qc.js` | `test_v931_release_candidate.py`, `test_topo_rod_ranges.py` |
| Shell | Normal-start update check and corrected cross-tab appearance event wiring | Fixed v9.3.1 | `surveysync/static/app.js` | `test_v931_release_candidate.py` |



## v9.3.2 open-source integration additions

| Area | Feature | Status | Primary implementation | Tests |
| --- | --- | --- | --- | --- |
| COGOSync | Horizontal tangent/circular-curve alignment with station evaluation, LEFT-positive inverse and station/offset stake points | Implemented Beta | `horizontal_alignment.py`, `alignment_routes.py`, COGOSync UI | `test_v932_landxml_alignment.py` |
| COGOSync | LandXML 1.2 CgPoint / Parcel Line / tangent-curve Alignment import-export with immutable source preservation | Implemented Beta | `landxml_io.py`, `alignment_routes.py` | `test_v932_landxml_alignment.py` |
| COGOSync | Vertical parabolic curves | Implemented Beta | `cogo_extended.py`, `cogo_routes.py` | `test_v932_vertical_curve.py` |
| COGOSync | Cross-section cut/fill, average-end-area earthwork and 2D slope catch | Implemented Beta | `earthwork.py`, `cogo_routes.py` | `test_v932_earthwork.py` |
| ControlSync | Conventional 2D weighted least-squares network adjustment | Implemented Beta | `network_adjustment.py`, `network_routes.py` | `test_v932_network_adjustment.py` |
| ControlSync | Weighted benchmark-network leveling adjustment | Implemented Beta | `level_network.py`, `level_network_routes.py` | `test_v932_level_network.py` |
