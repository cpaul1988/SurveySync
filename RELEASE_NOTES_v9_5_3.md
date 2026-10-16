# SurveySync 9.5.3-beta.1 — FieldBookSync integration

Unreleased development candidate for FBR-0018. No stable/beta update feed has been changed.

## What changes

FieldBookSync uses the actual SurveySync application menu, module tabs, sidebar and project card. Its processing/review UI is a persistent, same-origin content pane. Ordinary module switches do not reload it. The existing review, mapping, batch, profile, trainer, analysis and history workflows remain available. FieldBook commands also appear in the common Tools menu.

The active SurveySync project is authoritative. The module inherits its name and ID, validates the project-local storage folder, and refuses a mismatched or stale view before data operations. Selecting the same project is idempotent. A failed new runtime does not close the previous project's job database. Active analysis, imports, batch work, live-network work and in-flight API responses prevent project replacement.

Legacy .fbs imports retain the source title as provenance but cannot replace the destination SurveySync project's identity. Reset and recovery retain that identity. Existing source/map coordinates are not transformed as part of this integration. A legacy module-only rename is rejected instead of silently creating a conflicting project name.

Feedback remains available with no project. Background Intake retries now retain the original report root even if the user switches projects during retry. Report IDs, local-first capture and shared Intake transport are unchanged. Native file-picker calls from the embedded module delegate to the main desktop bridge.

## Validation and availability

See QA_REPORT_v9_5_3.md for measured results. Windows/WebView2, browser acceptance and installer compilation must be verified on this exact candidate before promotion. This change does not publish an installer or alter installed software by itself.
