# SurveySync Test Coverage

## Automated suites

The maintained Windows/source gate runs `tests/` plus selected FieldBookSync legacy regression suites. Major covered areas include project lifecycle, updater/version logic, Point Range, Trimble JobXML/JOB adapter contract, Ron control outputs, BRT topology/QC, Field Note Profile CRUD/training/bundles, the v9.1.3 book-profile workflow, v9.1.4 reliability/diagnostics behavior, and v9.2.0 active-revision management.

## v9.2.0 regression target

`tests/test_v920_control_revisions.py` covers automatic activation of newly solved control/level revisions, control and level comparisons, rejection of cross-object restoration, non-destructive restore of an older revision, and PDF reporting from the restored active control solution.

## v9.1.4 regression target

`tests/test_v914_reliability.py` covers explicit update-install confirmation, the FieldBookSync legacy update proxy, atomic `.fbs` Save As, redacted diagnostics/error-log export, Apps Script route payloads, and the static Review modal/native Save As UI contracts.

## v9.1.3 regression target

`tests/test_v913_fieldbook_training_workflow.py` is the permanent regression test for FBR-0010. If future UI/backend changes remove profile selection after field-book import, training preview, trainer source filtering, or book/profile persistence, this suite should fail.

## Real-world tests still required

Automated fixtures cannot prove OCR quality on handwritten books, actual Trimble converter interoperability, installer/update behavior on every workstation, or third-party local AI runtime availability. These remain explicit Beta-to-Stable gates and are recorded in each QA report/build manifest.

## v9.2.1 regression target

`tests/test_v921_operations.py` covers shared Health/QA rules and coordinate sanity; staging/mapping and duplicate protection; recovery/manual snapshot creation, comparison and restore; project timeline; external-file and SurveySync-project comparison; custom export profiles and checksum-backed package manifests; visual map/Review Center/Why evidence; persistent task completion/failure; and Operations Center API wiring.


## v9.2.2 feedback compatibility
- `tests/test_v922_feedback_compat.py` reproduces the legacy deployed Intake gate and confirms the client submits the compatible FieldBook Sync envelope.
- Existing feedback attachment/retry/idempotency and SurveySync error-log routing regressions remain in the maintained suite.

## v9.2.3 bulk controls and path browsing

Tests cover multi-Control-ID import, append-only control observations, batch analysis with minimum-shot skipping, immutable solution creation, the new observation/analyze API routes, universal path-picker markup, and native multi-file bridge/source presence. Existing v9.2.2 feedback-compatibility coverage remains active.

## v9.2.4 database platform coverage
Tests verify independent template-created project DBs, project-template module selection, project metadata seeding, automatic schema migration with pre-migration backup, controlled-edit snapshots/history/stale-result marking, recalculation clearing stale control state, read-only dataset protection, DB integrity/maintenance, and Project Data Manager/API shell exposure.

## v9.2.5 correctness and static-quality coverage

- Regression case with a finite Northing and non-finite Easting inserted between valid points verifies pair alignment is never shifted.
- Regression verifies an extreme remote point is reported using the actual source PointID even when another row is invalid.
- Non-finite coordinate rows are counted/reported and excluded from min/max/median statistics as complete pairs.
- `scripts/validate_static_quality.py` runs in the Windows build and under pytest, checking exception baselines, monolith ceilings, duplicate routes/functions, mutable defaults, pickle/eval/exec/shell use, and common credential literals.

## v9.2.5 Control Survey workspace coverage

`tests/test_v925_control_workspace.py` covers offline CRS search plus the ESRI-style Projected/Geographic folder browser (including State Plane/Missouri), Local Site persistence and reversible grid/ground math, TBC-style suffix grouping, Code preservation, all-triplet best-three selection, failing-control reshoot suffix generation, Control QC persistence, API routes, default deliverables, saved custom exporter profiles, geographic header semantics, projected-target validation and the Control Survey UI contract. These run alongside the coordinate-sanity/static-quality hardening tests.

`tests/test_v925_control_workspace.py` also covers spatially inferred control grouping/misnumber detection (`1A`,`1B`,`2C` -> Control 1 / inferred 1C) and verifies reshoot suffixes continue from the inferred shot identity without altering raw IDs.
The same suite covers strict field-observation QC: common Time/Epochs/Duration/Satellites CSV parsing, 60-minute pairwise shot separation, the 300-epoch OR 5-minute rule, the 5-satellite minimum, explicit field failures, and REVIEW behavior when required metadata is absent.

Direct Trimble control intake coverage verifies JobXML control grouping plus GNSS occupation metadata extraction (shot time, epochs, duration, satellites), TBC JobXML `InventoryData` fallback when `Reductions` is empty, exclusion of non-shot PRS/reference points from repeated-control groups, and an API-level `.job` import using a simulated official-converter result before running strict ControlSync QC.

FBR-0015 regression coverage verifies the GISSync Trimble JOB/JobXML Browse control is wired to the resilient native picker and local fallback route.

## v9.2.6 ControlSync production coverage

`tests/test_v926_control_production.py` verifies rich Access-style JXL quality metadata, DOP threshold failures, coordinate-preserving dual-source metadata merge, vertical spatial separation, manual misnumber review states, persisted QC profiles, ArcGIS-style CRS folder families, resizable modal contracts, and complete QC package provenance. Existing v9.2.5 tests remain active for suffix grouping, real TBC InventoryData behavior, all-triplet selection, time/epoch-duration/satellite checks and direct Trimble JOB adapter behavior.


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.


### 9.3.0 TopoSync range QC

Standalone point import, editable code classifications, feature-chain range detection, evidence reports and reviewed-copy exports are implemented in `surveysync/topo` and `surveysync/static/topo_qc.js`. See [TopoSync workflow and limits](TOPO_ROD_HEIGHT_QC.md). Synthetic regression coverage is in `tests/test_topo_rod_ranges.py`; real field and Windows acceptance remain pending. Supplied branding replaces the product globe/installer assets.

## v9.3.1 release-candidate coverage

`tests/test_v931_release_candidate.py` is the permanent regression suite for the 9.3.1 integration pass. It checks that release/version surfaces agree on 9.3.1, startup update initialization is not nested in the browser storage event, maintenance-only file-association commands do not begin crash-recovery sessions, clean versus interrupted sessions are distinguished, cached Inspector results refresh the active project/CRS/unit context, TopoSync profiles round-trip safely, and TopoSync candidate review history/calibration remains advisory.

The shared release gate also runs the existing TopoSync range detector, diagnostics/feedback, updater, project database, ControlSync, FieldBookSync, and legacy regression suites. A successful automated gate still does not prove installed Windows/WebView behavior, official Trimble JOB converter interoperability, OCR/local-AI behavior, or production rod-height accuracy on field-verified data.

## v9.3.2 open-source integration coverage

`tests/test_v932_open_source_integrations.py` covers the attributed Cogokit-derived horizontal-curve reference case, explicit rejection of the 100-foot-arc degree-of-curve convention in meter projects, wrong-element-count validation, three-point circle geometry, COGOSync API/audit wiring, audit-chain tamper detection, v5 audit-history backfill into schema 6, Project Health blocking on a broken audit chain, deliverable-manifest audit-head capture, release branch guards, and third-party attribution files.

These tests validate SurveySync's adaptations; they do not substitute for field/software comparison of newly imported surveying algorithms before Stable promotion.

Coverage also includes a cross-project transplant regression: a cryptographically valid source-project chain is copied into a second project while the destination keeps its own chain identity, and verification must fail.

## 9.3.2 network adjustment

`tests/test_v932_network_adjustment.py` covers the separate ControlSync 2D weighted
least-squares workflow, including an independently sourced pySurveying distance-network
reference fixture, mixed linear/angular residual units, redundancy-sum behavior, 95%
error-ellipse output, rank-deficiency rejection, and audited API execution. The tests do
not replace field comparison against known survey software before Stable promotion.

## 9.3.2 weighted leveling network

- `tests/test_v932_level_network.py` checks a redundant fixed-datum benchmark network against a hand-verifiable least-squares reference, rank-deficient geometry rejection, and audited API integration.
- The workflow is intentionally separate from Ronald's validated three-wire workbook path; regression coverage ensures the new solver does not replace that profile.

## 9.3.2 vertical curve geometry

- `tests/test_v932_vertical_curve.py` checks a symmetric crest-curve reference case, equal-grade rejection, station/elevation sampling, and audited API integration.

## 9.3.2 cross sections, earthwork, and slope catch

- `tests/test_v932_earthwork.py` checks flat-profile cut area, average-end-area volume/mass-haul, a simple slope/ground catch intersection, and non-overlapping profile rejection.

## 9.3.2 horizontal alignment and LandXML

- `tests/test_v932_landxml_alignment.py` checks tangent/curve continuity, circular-curve midpoint geometry, LEFT-positive station/offset round trips on tangent and curve elements, invalid-curve rejection, LandXML 1.2 CgPoint/Parcel/Alignment round trips, and audited API import/export with immutable source preservation.
