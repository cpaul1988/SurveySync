# SurveySync Data Flow

## Field-book path

1. User imports PDF/images through `/api/import-fieldbook`.
2. Source files are rendered into page images and enhanced review images.
3. Each imported field book receives persisted profile metadata (`AUTO` by default) and representative page IDs.
4. The user may select a book profile, preview the first useful pages, or open the Trainer filtered to that book.
5. Analysis locates PointIDs using OCR/evidence and sends profile context plus the effective page profile to semantic interpretation.
6. Deterministic QC compares written values, visual leader direction, explicit destination IDs, coordinates, reciprocal network evidence, and tolerances.
7. Results enter Review. Corrections can be saved normally or taught to a profile as labeled examples.
8. Reusable profile grammar/examples can be exported as `.fnp`.

## Effective profile precedence

`page override > field-book default > global selected profile > Auto/generic fallback`.

The page override and book default are stored separately so mixed-format books do not lose page-level exceptions when the default changes.

## Training data flow

Training examples store the page image, normalized annotation boxes, semantic labels, optional pipe association, and reviewer-approved result when taught from Review. Reusable AI prompt hints summarize annotation types and coarse layout only; prior project PointIDs/raw values are intentionally excluded.

## v9.2.1 safe point-import flow

`external point file → stage/preview → detected or learned column mapping → duplicate/invalid-row review → explicit commit → immutable source registration → canonical point insert (new PointIDs only) → audit/Review Center`. Existing PointIDs are reported as conflicts and are not overwritten.

## v9.2.1 operations flow

Project mutations feed the audit trail and timeline. Health Check evaluates shared rules and creates review findings. Recovery snapshots use SQLite backup semantics; restore first creates a pre-restore safety snapshot. Background/batch jobs persist status/progress/errors to the project database so failures are visible in the Review Center.

## v9.2.3 bulk control flow

Control survey file -> immutable source registry -> parsed repeated observations -> `control_observations` database -> group by Control ID -> generic batch QC/averaging -> immutable `control_solutions` revision per solved control -> Control Database analysis CSV/reporting. Raw observations remain preserved throughout.

## v9.2.4 project bootstrap and edit flow
New Project -> choose workflow template -> create folders -> copy clean master DB -> write manifest/project metadata -> apply QA defaults -> open project. Existing Project -> inspect DB schema -> if upgrade is required copy DB to migration_backups -> apply ordered migrations -> record migration audit event -> open project. Controlled Data Manager edit -> safety snapshot -> update allow-listed field -> append field-level edit history -> mark dependent result stale -> recalculate to return result state to CURRENT.

## v9.2.5 Control Survey data flow

`Control source file → immutable source registry → control_observations → grouped Control IDs → all 3-shot candidate combinations → control_qc_candidates/control_qc_runs → selected immutable control_solution → Accepted Control / Reshoot / custom export`.

TBC-style labels such as 7A/7B/7C derive group 7 without discarding the original PointID. `Code` is preserved with the selected candidate. Failed controls are not adjusted into tolerance; they remain RESHOOT/REVIEW and receive next-unused requested shot labels. Alternate-CRS export is `stored project/local coordinate → inverse Local Site transform → underlying grid CRS → PROJ target transform`.

When present, source shot time/date, epoch count, occupation duration and satellite count are persisted with each `control_observations` row. Candidate flow is therefore `spatial/name grouping → three-shot candidate → coordinate residual QC → field-observation QC → ranked selected candidate`. Strict mode blocks PASS when required field metadata cannot be verified.

## v9.2.6 Control evidence flow

A control source is classified before QC. Trimble Access JXL with FieldBook evidence can populate occupation/quality fields directly. TBC InventoryData-only JXL is treated as coordinate evidence and reports raw GNSS fields as missing. A second raw Access JXL can be registered and merged by PointID; merge operations enrich only missing metadata and never replace the stored project N/E/Z. All source IDs remain auditable.

Control grouping uses raw naming plus horizontal proximity and optional vertical proximity. Probable misnumbers are suggestions; Confirm/Reject/Reassign decisions are stored separately from the raw observation. QC then evaluates every three-shot combination, applies coordinate and field-observation rules, ranks valid candidates, preserves alternatives, and produces accepted/reshoot/provenance deliverables.

### ControlSync delimited import mapping (v9.2.6)

CSV/TXT/TSV control intake is a two-step safe import: SurveySync sniffs the delimiter/header row and proposes a column mapping, then the user reviews a source preview and confirms/corrects Point/Control ID, N/E/Z and optional GNSS quality fields before commit. Approved mappings are remembered per project/header signature. Unknown or ambiguous headings are never silently assigned to a required field when confidence is insufficient.


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.


### 9.3.0 TopoSync range QC

Standalone point import, editable code classifications, feature-chain range detection, evidence reports and reviewed-copy exports are implemented in `surveysync/topo` and `surveysync/static/topo_qc.js`. See [TopoSync workflow and limits](TOPO_ROD_HEIGHT_QC.md). Synthetic regression coverage is in `tests/test_topo_rod_ranges.py`; real field and Windows acceptance remain pending. Supplied branding replaces the product globe/installer assets.

## v9.3.1 Inspector and support flows

**Survey Data Inspector:** selected local source → SHA-256 → format/schema parse → QC summary/cache → refresh current project CRS/unit context → optional handoff to a compatible workflow. Trimble JOB/JXL sources are converted/parsed into a separate normalized cache artifact before handoff; the source file is unchanged.

**Interrupted recovery:** desktop launch → mark session active → active project path recorded → normal close marks session clean. A later launch that sees an active prior session exposes a recovery notice. Restore is offered only for a matching open project with an available automatic recovery snapshot and requires explicit confirmation.

**Support diagnostics:** local diagnostic JSONL → Support Center merged sync state → optional retry to Error Log endpoint or explicit “Report This Error” Feedback Wizard report. Diagnostic/support submission is designed to exclude raw survey source files unless a separate workflow explicitly attaches them.

