# SurveySync Architecture

## Product shell

SurveySync is the application shell. `surveysync/router.py` exposes the v9 APIs and shared project services. FieldBookSync is an embedded module served by `fieldbook_sync/app.py`; it uses the same SurveySync project lifecycle, updater, theme system, and feedback path.

## Persistence boundaries

The SurveySync project owns canonical project data and module workspaces. FieldBookSync persists `AppState` through `fieldbook_sync/storage.py`. Original survey/field-book evidence is preserved separately from derived OCR, interpretation, QC, and reviewed results. Profile/training files are local artifacts under the FieldBookSync project workspace and `.fnp` is the transport format for reusable field-note profiles.

## FieldBookSync intelligence layers

The reader deliberately separates: image preparation → OCR/PointID evidence → profile-aware semantic interpretation → deterministic survey/network QC → reviewer acceptance. Field Note Profiles influence interpretation but cannot create survey evidence. Page-specific override has higher precedence than book default; book default has higher precedence than global/Auto mode.

## Release architecture

`VERSION.txt` is the product version source. `Build_SurveySync.ps1` runs the documentation gate, Python compilation, automated tests, launcher build (when Go is available), Inno Setup compilation, and installer SHA-256 creation. GitHub Beta publication and Stable promotion use the exact tested Beta installer artifact.

## v9.2.1 shared operations architecture

`qa_rules.py` and `qa.py` provide one project-wide health/rules layer. `staging.py` owns non-destructive point-file preview/commit and learned mappings. `continuity.py` owns bounded recovery/manual snapshots. `comparison.py`, `delivery.py`, `task_queue.py`, and `operations.py` provide comparison, repeatable delivery, persistent background work, timeline/review/Why, and map-QC services. These are exposed through `router.py` and the shared Operations Center rather than reimplemented per module.

## v9.2.3 Control Survey Database

ControlSync's persistent `control_observations` table is now the primary control intake store. Bulk files may contain repeated shots for multiple Control IDs. The UI queries that database directly and batch analysis creates immutable `control_solutions` revisions through the same solver used by single-control workflows. TBC-specific behavior is intentionally not inferred from screenshots alone; a validated reference report/profile is required before adding a TBC-equivalent calculation label.

Path selection is centralized through the SurveySync native bridge (`choose_file`, `choose_files`, `choose_folder`) with browser-fallback API routes for local Windows use.

## v9.2.4 Project database architecture
Each SurveySync project owns one independent SQLite database at `.surveysync/survey_sync.db`. New project creation copies a clean master database template, writes project-specific metadata, then applies the selected project template. SQLite `PRAGMA user_version` is the authoritative database schema version. Opening an older project creates a pre-migration database backup before sequential migrations run. Project Data Manager accesses only allow-listed datasets; it is not a raw SQL console.

## v9.2.5 hardening boundary and logging

SurveySync core modules log under the `surveysync.*` logger tree to a daily rotating `surveysync.log` in the workstation SurveySync logs directory. The build configures this logger once from the shared config root. Best-effort operations may continue after a failure, but they must leave diagnostic context rather than using a blind broad-exception pass. The large route modules are intentionally not split in 9.2.5; a static gate freezes their growth pending the mechanical 9.3.0 per-domain split.

## v9.2.5 Control Survey and coordinate context

ControlSync's new workspace is split between the existing project/control services and `surveysync/control_workspace_routes.py` so the pre-9.3 root router does not grow further. Project coordinate settings are persisted in both the manifest and `project_coordinate_settings`. Control QC runs/candidates are project-owned SQLite records. The underlying grid CRS and optional Local Site affine transform are deliberately stored separately. Alternate-CRS exports reverse Local Site coordinates to grid before invoking PROJ.

The Control Survey map is an in-app coordinate overview, not a full GIS renderer. Source observations remain immutable; automated best-three selection creates derived candidate/run records and immutable control-solution revisions rather than rewriting observations.
Project DB schema 4 extends `control_observations` with field-observation metadata: explicit shot-time provenance, epoch count, duration seconds and satellite count. These are source/QC facts, not derived coordinate edits.

## ControlSync production layer (v9.2.6)

Project DB schema 5 adds richer GNSS observation columns, Control QC profiles, import diagnostics and manual grouping overrides. ControlSync keeps immutable source evidence separate from effective analysis grouping. Raw PointIDs and coordinates are not rewritten by spatial inference or metadata merge.

Spatial candidate discovery uses a tolerance-sized in-memory grid/hash rather than all-pairs comparison, with project database indexes on control ID, PointID, N/E and observation time for common large-project lookups. Route modularization remains deferred to the 9.3.0 mechanical split.


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.

## v9.3.1 support and inspection services

The 9.3.1 shell keeps support/recovery and data inspection outside the main `surveysync/router.py` orchestration module. `session_recovery.py` owns workstation session-state persistence, `support_center.py` owns support/retry/recovery routes, and `data_inspector.py` owns immutable-source inspection/cache behavior. All are included as subrouters by the shared SurveySync router.

Inspector caches are workstation-local derived artifacts keyed by source SHA-256. Project identity/CRS/units are refreshed at read time so the cache does not become an accidental project-state authority. Trimble normalization produces a separate derived CSV; the original source is never overwritten.

TopoSync QC profiles and review records remain project/workspace scoped and separate from raw survey evidence. Review/calibration state is advisory and cannot silently mutate observations.

## v9.3.2 open-source integration foundation

Project database schema 6 adds a tamper-evident `audit_chain` alongside `audit_events`. Each event is canonically hashed with SHA-256 and linked to the previous event hash. Existing audit history is deterministically backfilled during the v5→v6 migration. New audit writes use an immediate SQLite transaction so the event row and chain row are committed atomically and concurrent background tasks cannot select the same sequence number.

Project Health verifies the chain without modifying it. Deliverable-package manifests include the verified pre-package audit head hash, event count, and hash version so an issued package can be tied to a concrete project-audit state.

COGOSync keeps its existing small native inverse/forward/intersection functions and adds an attributed extended curve module rather than importing another project's database or application architecture. CRS transformation authority remains pyproj/PROJ.

SurveySync 9.3.2 also introduces a reusable horizontal-alignment domain layer in `surveysync/horizontal_alignment.py`. Tangents and circular curves are represented as one continuous station chain; LandXML import/export normalizes through that same model rather than maintaining separate geometry math. Imported LandXML is first copied into the project's immutable Source tree and registered by SHA-256. Spiral/profile/surface LandXML geometry is not silently approximated; unsupported records are surfaced for review.

Each project stores a persistent random chain identity in `audit_chain_meta`; that identity is included in every canonical audit hash so a valid audit/event chain copied from another project database will not verify in the destination project.
