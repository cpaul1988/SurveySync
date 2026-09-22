# SurveySync v9.1.0 Release Notes

## Beta candidate — survey-platform expansion

SurveySync 9.1.0 expands the v9 platform beyond the FieldBook-centered foundation while preserving raw survey evidence, review states and auditable derived results.


### Project switching and cleanup

- Added a **Projects** button in the main SurveySync header and **File → Switch / Manage Projects**.
- SurveySync now keeps a workstation-local recent-project list and moves the most recently opened project to the top automatically.
- Recent projects can be switched with one click without browsing back to the project folder each time.
- FieldBookSync includes **Switch SurveySync Project** in its global File menu, so the project manager is reachable from that module too.
- **Remove** only removes a project from the recent list and leaves the project folder untouched.
- **Delete** permanently removes the entire SurveySync project folder only after the user types the exact project name. The embedded FieldBookSync database is detached first so Windows file locks do not leave a half-deleted project.
- Missing recent-project folders are shown as missing and can be removed from the list without affecting other projects.

### Ron's exact control and level workbook profiles

- Added a validated **Ron 3-point control average** profile from `3 Point Control Averaged Template.xlsx`.
- Final Northing, Easting and Elevation use the workbook's exact arithmetic three-shot averages.
- Horizontal residuals and the workbook's A/B/C vertical display convention are reproduced.
- ControlSync can select three existing SurveySync PointIDs directly, preserving each source shot and creating an immutable solution revision.
- Added a validated **Ron 3-wire level reduction** profile from `3 Wire Level Loop Template.xlsx`.
- Three-wire BS/FS readings use the exact arithmetic average of upper/middle/lower; stadia uses `(upper-lower)*100`; HI/elevation chaining and closure reproduce the workbook formulas.
- The supplied level workbook contains no closure-adjustment formula. The Ron profile therefore defaults to **No adjustment**. Optional setup- or distance-proportional adjustment is explicit SurveySync logic and is not represented as Ron's workbook method.

### FieldBookSync / UtilitySync

- Evidence-first local FieldBook analysis remains the default: Windows AI fast pass when ready, PaddleOCR-VL for unresolved/risky evidence, targeted Qwen3-VL interpretation, then deterministic validation/review routing.
- Editable PointID reassignment during review preserves the original OCR/AI evidence and records the reviewer correction.
- Added deterministic rim-minus-dip invert calculations and pipe/structure provenance.
- Added supplemental sewer GIS evidence, pipe connection/grade QC foundations, completion status and pickup/completion KMZ output.
- Added structure/pipe photo evidence attachment foundations.
- Added Carlson-style field-to-finish linework reconstruction for `-BS`, `-ES`, `-PC`, `-PT` and related coded survey points.

### Point Range Finder

- Point ranges are treated as a crew-allocation workflow using every numeric PointID as occupied.
- Default output is now **lowest to highest**, responding to beta feedback FBR-0006.
- ReportSync also offers High-to-Low and Largest-Capacity sorting.
- ReportSync and FieldBookSync use the same gap algorithm and CSV/table semantics.
- The clean open-ended next-thousand block remains available as the safest new crew range.

### GIS / spatial data

- Added typed spatial import foundations with schema/type preservation metadata.
- Added GeoPackage/common vector handling and ASCII DXF import for supported point/line/curve entities.
- DXF with unknown coordinates requires an explicit CRS rather than guessing.
- Reference GIS remains visibly distinct from surveyed/confirmed data.

### Project ground / scale-factor tools

- Added multi-zone scale-factor sampling and project-factor fitting.
- Added residual distortion reporting/preview in ppm and project units.
- Solutions are stored as reviewed/auditable project-ground candidates; SurveySync does not simply average factors from different State Plane zones or silently declare a professional coordinate system.

### Control / traverse / reporting

- Added persistent control-solution revisions and audit history.
- Added deterministic level-loop QC and explicit optional adjustment methods.
- Added open/closed traverse calculations with Bowditch/Transit options when constraints support adjustment; raw observations remain preserved.
- Added professional survey/control PDF foundations with PLS/PE signature-and-seal areas.
- Added deliverable registry, annotated FieldBook deliverable foundations and optional stakeholder-notification workflow.

### Field data / cloud foundations

- Added Trimble Connect authenticated project/file integration foundations.
- Added a documented Leica integration boundary pending official API/service credentials and representative account/export validation. SurveySync does not invent undocumented Leica endpoints.

### Updater and releases

- The application retains one shared **Check & Update** flow across Home and FieldBookSync.
- Added a GitHub Actions Beta/Stable release workflow so publishing no longer depends on the standalone Publisher executable.
- Stable promotion reuses the exact tested Beta installer/hash instead of rebuilding it.

### Feedback / reporting wizard

- Feedback remains local-first and can be opened without a project.
- SurveySync now points to its own `feedback.json` configuration with the current shared Intake endpoint built in as a fallback.
- Official SurveySync feedback configuration now takes precedence over a stale per-machine FieldBook Sync endpoint override left from v8 migration.
- HTTP 413/429/500/502/503/504 attachment failures still receive a metadata-only retry and otherwise remain Pending locally for retry.

**Beta release gate:** FBR-0008 reports that Ron received HTTP 500 while CP could submit successfully. The client-side stale-endpoint/migration path has been corrected in this candidate, but the Google Apps Script server-side failure has not been independently reproduced or proven fixed. Ron should submit one real Beta feedback report successfully before this build is promoted to Stable.

### QA

- Maintained combined regression suite: **159 passed, 0 failed** in the final v9.1.0 candidate.
- Python compile checks pass.
- SurveySync and FieldBookSync JavaScript syntax checks pass.
- Windows x64 `SurveySync.exe` and `SurveySyncUpdater.exe` launchers were cross-built successfully.


## Startup single-window hotfix

- Source launches through `run_windows.bat` now immediately hand off to a hidden Windows bootstrap process so only the native SurveySync WebView window remains visible.
- `run_windows.bat --console` remains available for troubleshooting when a visible bootstrap console is useful.
- Hidden bootstrap failures now write `%LOCALAPPDATA%\SurveySync\logs\bootstrap.log` and show a Windows error dialog instead of failing invisibly.
- The installed `SurveySync.exe` native launcher remains the preferred normal launch path and already uses a no-console child process.


## Native launcher console-window fix

- Fixed the actual cause of the persistent Windows Terminal window behind SurveySync: the prebuilt `SurveySync.exe` launcher had accidentally been compiled as a **Windows CUI/console-subsystem** executable.
- `SurveySync.exe` and `SurveySyncUpdater.exe` are now built as **Windows GUI-subsystem** executables (`-H=windowsgui`), so normal installed launches no longer allocate a terminal window.
- The GitHub Actions release workflow now enforces the same GUI-subsystem linker flag, preventing the console window from returning in future Beta/Stable installers.
- Added a PE-header regression test that fails packaging if either shipped launcher reports Subsystem 3 (console) instead of Subsystem 2 (GUI).
- `run_windows.bat --console` remains the intentional troubleshooting route when a visible console is wanted.
