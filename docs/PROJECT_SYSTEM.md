# SurveySync Project System

SurveySync projects are the persistence boundary for module state, evidence, exports, audit information, and FieldBookSync training/profile data. Project switching must isolate FieldBookSync storage so one project's imported notes/results are not visible in another.

FieldBookSync autosaves `AppState`. Imported field-book records persist the source name, page count, profile selection, selected profile version, selection mode (`auto`, `user`, `trained`), reason, confidence placeholder, and representative training page IDs. Each page separately persists its book default and page-specific override.

Changing projects must reload the module storage and profile/training directories for that project. Original field-book page images remain separate from derived enhanced images and training copies.

## v9.2.1 continuity and operations state

Project-local operation settings live under `.surveysync/`: QA rules, learned column mappings, export profiles, and snapshot metadata. Recovery/manual `.ssnap` files remain project-local and contain the project manifest, a consistent SQLite backup, and bounded mutable FieldBookSync state; large evidence/page caches are intentionally not duplicated. Restoring a snapshot never deletes snapshot history and creates a pre-restore safety snapshot first.

## v9.2.3 path selection

SurveySync keeps user-entered paths visible/editable but now supplies Browse controls for path fields. Folder pickers return directories, file pickers return one source file, and batch pickers return multiple selected files one per line. Picker actions do not change project content until the user presses the associated import/run action.

## v9.2.4 one-project / one-database rule
A SurveySync project is self-contained. Its manifest, SQLite database, source evidence, reports, exports, attachments/photos, module workspaces, snapshots and migration backups live under that project's root. The master template database is read-only seed content shipped with SurveySync; project-specific values are written only after it is copied into a new project.

## v9.2.5 Coordinate System / Local Site project setup

New projects immediately prompt for a coordinate system. Operators browse the locally installed EPSG/ESRI library in Projected/Geographic folders (with State Plane by state and UTM by datum family) or search by name/WKID, choose horizontal/vertical units, and may enable Local Site / modified-ground settings. Local Site requires explicit grid origin, local/ground origin, grid-to-ground factor and clockwise rotation. These values are stored with the project and become the default coordinate context for ControlSync maps, QC provenance and exports. SurveySync does not infer these parameters from the observations.

## Control observation schema v4
Project database schema 4 adds `observed_time_provided`, `epoch_count`, `duration_seconds`, and `satellite_count` to `control_observations`. Existing projects receive the normal pre-migration database backup before v4 is applied. Legacy rows default to `observed_time_provided=0` so prior import timestamps are not treated as field shot times.


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.
