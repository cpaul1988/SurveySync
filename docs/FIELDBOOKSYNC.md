# FieldBookSync Developer Guide

## Purpose

FieldBookSync converts scanned/photographed survey field notes into reviewable structured evidence. It is evidence-first: OCR/vision suggestions are not survey truth until deterministic checks and/or reviewer acceptance support them.

## Field Note Profiles

Built-ins: `BRT_STANDARD` and `GENERIC_SURVEY_NOTES`. Custom profiles describe detection cues, vocabulary, expected fields, symbols, and extraction/association rules. Built-in grammar is locked; custom copies are editable.

### v9.1.3 import workflow

After field-book import the dashboard exposes the selected book and its profile. `AUTO` leaves the book unforced. Selecting a profile stores that profile and version on the imported-book record and sets a book default on its pages. The page-specific override remains a separate field.

**Preview first pages** requests `/api/fieldbook-training-preview` and shows up to five representative pages. **Train this field book** opens the Trainer with a source filter already set to the current book. Saving a training example assigns the selected profile to that book with mode `trained`.

### v9.1.4 reliability workflow

Save As now uses the native desktop save dialog when the WebView bridge is available. The `/api/project/save-as` endpoint writes a temporary project bundle, validates that it is a ZIP-format `.fbs`, and replaces the destination atomically so a failed save does not leave a half-written project file.

Updater actions are split into check, confirmation, and install stages. The UI first shows the available version and release notes. SurveySync only stages the installer and requests shutdown after the operator confirms installation.

Unhandled HTTP failures, updater errors, diagnostics failures, and Save As errors are written to the shared SurveySync diagnostics Error Log with redacted secret-like context fields. A diagnostic ZIP can be generated for support without bundling source field-book images or survey source files.

The Review modal has v9.1.4 responsive bounds: on wide screens the image and form panes scroll independently with a sticky action row, while narrow screens fall back to a full-width stacked layout.

## BRT semantics

The BRT profile models a circular structure/manhole, north orientation, a structure PointID near the structure, and one leader per pipe/connection. `to ####` / `Az = to ####` is destination PointID evidence, not an azimuth number. Written azimuth, visual leader direction, explicit destination, and coordinate bearing are independent evidence channels; disagreements route to Review rather than silently rewriting the field note.

## Training limitation

In-app training is profile/example learning, not neural-network weight fine-tuning. The training library is deliberately useful as labeled ground truth for future separately validated model tuning.


## v9.2.2 feedback Intake compatibility
Feedback reports remain local-first and are submitted using the original `FieldBook Sync` application identifier. This is intentional: production has both legacy and current Google Apps Script deployments, while the current tracker accepts both identifiers. Error-log traffic continues to use the SurveySync routed payload.

## v9.2.3 shared path picker behavior

SurveySync's main-shell native path picker expansion does not change FieldBookSync's upload/dropzone behavior or its existing ArcGIS folder/project Browse controls. FieldBookSync continues to share the same Windows desktop bridge.

## v9.2.4 project-database relationship
FieldBookSync remains project-local under `Modules/FieldBookSync` and shares the parent SurveySync project's identity, database-backed survey foundation, snapshots and audit conventions. Its working caches/training files are not exposed as raw database rows in Project Data Manager.

## v9.2.5 persistence diagnostics

FieldBookSync project-state backup, recovery-copy, and recovery-parse failures are now logged instead of being silently ignored. This does not change recovery behavior; it makes persistence failures visible in diagnostics while the larger FieldBookSync route/app split remains scheduled for 9.3.0.


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.
