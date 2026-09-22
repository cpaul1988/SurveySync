# SurveySync v9.2.4 BetaCandidate Release Notes

SurveySync 9.2.4 formalizes the project database architecture. Every SurveySync project now owns an independent, versioned SQLite database created from the SurveySync master project template. New projects can start from workflow templates such as Standard Survey, EDSI Engineering/Topo, Boundary, Sewer/Utility, Control Network, or Construction Staking; the selected template seeds module availability and project QA defaults without sharing data between projects.

## Project database foundation

- Each project keeps its own `.surveysync/survey_sync.db` and database schema version.
- New projects copy the clean `surveysync/resources/project_template.db` master template before project-specific metadata is written.
- Existing project databases are migrated automatically. Before a schema upgrade, SurveySync saves a pre-migration database copy under `.surveysync/migration_backups`.
- Project metadata records project ID, name, client, job/project number and selected project template.
- Project folders now explicitly include snapshot, migration-backup, photo and deliverable locations while retaining existing v9 project compatibility.

## Project Data Manager

A new Project Data Manager under the Data menu provides a survey-friendly view of project database records. It exposes survey points, control observations/solutions, level runs/observations/solutions, traverse data, utility structures/pipes, sources, attachments, QA findings, deliverables, audit history, and field-level edit history.

Records are classified as editable, controlled-edit, or read-only. System evidence, audit records and calculated solution tables remain read-only. Controlled survey observations require a written reason, create a safety snapshot before modification, record the old/new field values, and mark dependent calculations stale until recalculated.

## Database Health & maintenance

Database Health now reports SQLite integrity status, foreign-key findings, schema version, journal mode, file size, and stale calculated results. Safe Database Maintenance creates a project snapshot first, then checkpoints WAL and runs SQLite ANALYZE/optimize without altering survey values.

## Compatibility

- v9.2.3 bulk Control Survey Database and universal Browse behavior are retained.
- v9.2.2 backward-compatible Intake/feedback sync is retained.
- Existing v9 projects are migrated in place with a pre-migration DB backup when schema changes are required.
- FieldBookSync keeps its existing project-local module workspace under `Modules/FieldBookSync`; Project Data Manager does not expose raw SQL editing.
