# SurveySync

SurveySync is a Windows surveying application with a shared project, source-evidence registry, coordinate context, audit history, and review/export workflows across its modules. See the [architecture](docs/ARCHITECTURE.md) and [engineering standards](docs/ENGINEERING_STANDARDS.md).

## Current source and distribution status

Read `VERSION.txt`, `RELEASE_ID.txt`, and the actual Git commit together to identify a source checkout. The active [update manifest](https://github.com/cpaul1988/SurveySync/blob/main/update.json), current pull requests, and their exact CI artifacts determine distribution and acceptance status. A version number or a historical passing test report does not establish that a different source tree is accepted.

At the [October 19, 2026 development checkpoint](docs/development/repository_tools_review_2026_10_19.md), Beta and Stable distribution remain held after the 9.5.3 Defender report. The separate [9.5.4 repair candidate in PR #25](https://github.com/cpaul1988/SurveySync/pull/25) has recorded Windows acceptance for specific artifacts; workstation acceptance and general rollout remain separate. Check the live sources before relying on this dated checkpoint.

## Continuing development

Use the [development handoff helper](docs/development/handoff.md) to record the current Git identity, working-tree status, release hold, active task, and explicitly supplied evidence. Handoffs stay in the ignored `.dev-handoff/` directory. They are development notes, never authority to change a release hold or survey observations.

The [Ghidra trial](docs/development/ghidra_trial.md) documents a separate static-analysis workflow for native binaries. Developer tools are not part of SurveySync's normal runtime.

## Historical 9.3.0 milestone

The following versioned milestone sections record earlier changes and limitations. For the 9.3.0 engineering-hardening and TopoSync milestone, see [BUILD_9_3_0.md](BUILD_9_3_0.md), its [release notes](RELEASE_NOTES_v9_3_0.md), and the [rod-height workflow](docs/TOPO_ROD_HEIGHT_QC.md). These historical sections do not override current source, privacy policy, or release status.

## Platform background

SurveySync v9 is the shared project platform that carries the FieldBook Sync v8 engine forward as **FieldBookSync** while moving project identity, storage, CRS/units, audit, QA/QC, environments, branding, updater metadata and feedback into one common foundation.

## v9.2.6 Control Survey workspace + hardening

v9.2.6 adds a simplified TBC-inspired Control Survey workflow: choose the project CRS from the offline library, optionally apply explicit Local Site / modified-ground settings, load the complete repeated-control dataset, inspect it spatially, cross-check numbering by proximity, validate shot time/epochs-or-duration/satellites, evaluate every three-shot combination with Ronald's validated QC method, and export accepted controls/reshoots through reusable CRS-aware profiles. It also fixes coordinate-sanity row alignment/PointID attribution, removes blind broad-exception passes from the SurveySync core, adds persistent core logging and adds a static-quality release gate. The 9.3.0 candidate extracts domain modules; remaining orchestration is capped for further incremental cleanup.

## v9.2.4 Project Database Platform

v9.2.4 formalizes the one-project/one-database architecture. New projects copy a clean master SQLite template and then receive project-specific identity, workflow-template settings, QA defaults and schema versioning. Existing projects are backed up before automatic schema migrations. A new Project Data Manager lets users browse project tables safely, make audited allow-listed edits, and run database health/maintenance without opening SQLite directly.

## v9.2.3 Control Survey Database + universal Browse

v9.2.3 makes the persistent Control Survey Database the primary ControlSync workflow: load all repeated control shots, review/group them by Control ID, and analyze every eligible control in one run. The exact three-shot workbook tool remains available as a specific validated method. TBC-equivalent analysis is intentionally deferred until Ronald's reference report/screenshots are supplied and validated.

Every local file/folder path box that previously required pasted text now has a native Browse action, including multi-file batch selection.

## v9.2.2 feedback-sync compatibility hotfix

v9.2.2 restores the backward-compatible FieldBook Sync feedback submission envelope so the in-app Feedback Log can sync to both the older deployed Intake Web App and the newer SurveySync tracker endpoint. Local-first logging, retry/idempotency, attachments, diagnostics, and SurveySync Error Log routing are unchanged.

## v9.2.1 Operations Center / platform-hardening milestone

v9.2.1 adds a project-wide Operations Center with Health Check + centralized QA rules, safe point-import staging and learned mappings, automatic/manual recovery snapshots, project timeline, file/project comparison, smart export profiles, checksum-backed deliverable packages, coordinate sanity warnings, visual project QC, batch/background processing, a Unified Review Center, and evidence-backed **Why?** explanations. See `RELEASE_NOTES_v9_2_1.md`.

## v9.2.0 ControlSync revision-management milestone

v9.2.0 starts the next SurveySync feature cycle with explicit solution revision management in ControlSync. Every new control or level solve remains immutable and becomes the active revision automatically. Operators can compare stored revisions, restore an earlier revision as active without deleting newer work, and generate control reports from the active revision. Existing projects with no explicit active-selection record continue to use the latest stored revision. See `RELEASE_NOTES_v9_2_0.md`.

## Retained v9.1.4 reliability release

v9.1.4 added explicit updater consent, atomic `.fbs` Save As, shared redacted diagnostics/Error Log support, and responsive Review layout hardening. Those protections remain unchanged in v9.2.1.

## Retained v9.1.3 field-book profile workflow

v9.1.3 completes FBR-0010 by bringing Field Note Profile selection and training into the normal field-book import workflow. After import, choose Auto or a book-specific profile, preview representative pages, and open the Trainer filtered to that book without re-importing the PDF. The page override remains independent for mixed-format books. See `RELEASE_NOTES_v9_1_3.md` for the complete behavior.


## What is implemented in v9.2.6

- Main product shell: **SurveySync**.
- Shared module naming and project slots: FieldBookSync, UtilitySync, ControlSync, TopoSync, COGOSync, BoundarySync, GISSync, ReportSync, QASync and CrewSync.
- User-selected project location. A SurveySync project is a normal folder containing `survey_sync_project.json` and project-owned subfolders/databases.
- Immutable source registry with SHA-256 provenance.
- Shared SQLite audit trail, QA issue store, source registry, canonical point registry, control observations and feedback ledger.
- Shared CRS + horizontal/vertical unit settings plus pyproj CRS inspection/transformation APIs.
- Developer / Beta / Production environments and developer / beta / stable release channels.
- Environment isolation: release channel changes remain explicit; the default public SurveySync manifest is retained across environments while custom feedback endpoints are cleared when switching environments.
- Data-driven SurveySync / client-demo branding profiles.
- Embedded **FieldBookSync v8.1.22 processing engine** using project-local state, pages, caches, recovery files, logs and analysis job database.
- Legacy `.fbs` migration into a chosen v9 project while preserving the original bundle in the immutable source registry.
- COGOSync foundation: inverse, bearing-distance and line-line intersection.
- ControlSync: generic control averaging plus the validated 3-point workbook profile, project-point selection, immutable solution revisions, three-wire level reduction/QC, and open/closed traverse calculation/adjustment.
- **v9.2.0 active revision workflow:** control and level solution history now expose the active revision, revision-to-revision comparison, and non-destructive restore. Control reports honor the selected active revision.
- **v9.2.6 Control Survey workspace:** offline EPSG/ESRI CRS selection, optional Local Site modified-ground transform, TBC-style P/N/E/elev/Code loading, spatial control map/Project Explorer, automated best-three QC at 0.045 H/V defaults, spatial misnumber detection/grouping, strict field-observation checks (60-minute separation, 300 epochs OR 5 minutes, 5+ satellites), accepted/reshoot lists and reusable CRS-aware custom exporters.
- **v9.2.1 Project Health / QA:** centralized project rules, READY/REVIEW/BLOCKING preflight, coordinate sanity, stale-output and failed-task checks.
- **v9.2.1 safe operations:** staged canonical-point imports with learned mappings and duplicate protection, recovery/manual snapshots, timeline, file/project comparison, reusable export profiles, checksum-backed deliverable packages, visual map QC, persistent background/batch work, unified review, and Why? evidence.
- UtilitySync: FieldBook structure/dip synchronization, deterministic invert calculations, supplemental GIS evidence, connection/grade QC, completion status, photo evidence and pickup/completion KMZ.
- GISSync / spatial foundation: typed spatial import, GeoPackage/common vector support, ASCII DXF import with explicit CRS, and Carlson-style field-to-finish linework reconstruction.
- Project-ground / scale-factor foundation: multi-zone scale sampling, fitted project factor, residual-distortion visualization and audited solutions; professional review remains required.
- ReportSync: crew point-range planning/sorting, professional survey/control PDFs, annotated FieldBook deliverables, deliverable registry, and optional stakeholder notification workflow.
- Retained from v9.1.1 — Point Range source selector: use current canonical project points by default or browse to a separate point file; CSV/TXT/XLSX outputs are generated together.
- Retained from v9.1.1 — direct Trimble Access intake: `.job` through the official Trimble ASCII File Generator plus direct `.jxl`/JobXML parsing, with original source preservation and PointID conflict review.
- Retained from v9.1.1 — BRT field-note profiles, reviewed annotation associations, explicit `to PointID` topology, and geometry cross-checks without silent correction. Automatic circle/leader segmentation and fully solved multi-directional handwriting remain outside the validated capabilities; see the [local field-book pipeline](docs/LOCAL_FIELDBOOK_PIPELINE.md).
- Retained from v9.1.2 — Field Note Profile Trainer: create named client/job-format grammars, visually annotate real pages, teach from reviewed corrections, use per-page overrides, and export/import reusable `.fnp` profile bundles. Labeled examples influence later profile interpretation through privacy-preserving structural hints; SurveySync does not claim that PaddleOCR/Qwen weights are retrained in-app.
- **v9.1.3 FBR-0010 workflow:** after field-book import, choose a profile per imported book, preview up to five representative pages, open **Train this field book** directly into a source-filtered Trainer, persist profile/version/mode with the project, and preserve page-level mixed-format overrides.
- **v9.1.3 release documentation gate:** architecture/feature/data-flow/API/decision/test/release docs plus `IMPLEMENTATION_INDEX.json` are validated before release QA/build.
- **v9.1.4 updater consent:** Check & Update shows availability first and only stages the installer plus shutdown handoff after explicit confirmation.
- **v9.1.4 Save As and diagnostics:** FieldBookSync native Save As writes atomic `.fbs` bundles; shared diagnostics record redacted support errors, create diagnostic ZIPs, and route Error Log sync separately from Feedback Intake.
- **v9.1.4 Review UI hardening:** Review modals use bounded desktop panes, sticky actions, responsive image sizing, and mobile fallback layout.
- Retained from v9.1.1 — Ron control deliverables: QC TXT plus FINAL or GPS RESHOOT TXT based on the validated 3-point solution.
- Field cloud foundation: Trimble Connect authenticated project/file integration hooks and a documented Leica integration boundary pending official API credentials/contract.
- QASync project foundation QA and source-integrity verification.
- Local-first feedback capture with automatic version/environment/channel/module/branding metadata and optional HTTPS endpoint sync. Survey source data is not sent by default.
- v9 updater foundation with HTTPS manifest, channel selection, installer size/SHA-256 verification, staging and native Windows handoff helper.
- Native Windows launchers: `SurveySync.exe` and `SurveySyncUpdater.exe` (x64).


## Prior v9.0.2 UI/theme foundation

- SurveySync application theme is now global across **all modules**, including the embedded FieldBookSync page.
- Light / Dark / System appearance is shared across Home, module workspaces and FieldBookSync. System follows the Windows color preference live.
- Theme profile and accent selections are stored once in shared SurveySync local preferences and mirrored to legacy FieldBookSync keys for backwards compatibility.
- The main menubar includes an appearance switcher, and System / Light / Dark are also available from View and Options.
- The Settings page contains application-wide theme, accent and appearance controls.
- The top-left SurveySync mark is now the branded globe rather than the temporary letter-S orbit mark.

## Control Average/QC and 3-wire profiles

The authoritative `3 Point Control Averaged Template.xlsx` and `3 Wire Level Loop Template.xlsx` have now been analyzed and turned into validated SurveySync calculation profiles. The control profile requires exactly three included shots and reproduces the workbook's arithmetic N/E/Z averages plus horizontal and A/B/C vertical residual displays. ControlSync can also select three existing canonical SurveySync PointIDs directly, matching the workbook's VLOOKUP-style workflow while retaining source-point provenance.

The Ron 3-wire level profile reproduces the workbook's three-reading BS/FS average, `(upper-lower)*100` stadia calculation, height-of-instrument/elevation chain, setup stadia balance, and closure calculation. The supplied level workbook contains no closure-adjustment formula, so SurveySync keeps adjustment as an explicit deterministic choice (`none`, `setups`, or `distance`) rather than claiming an unverified workbook method.


## Project switching and deletion

SurveySync v9.2.1 keeps a local recent-project list for fast switching. Use the **Projects** button or **File → Switch / Manage Projects** in the main shell. FieldBookSync also exposes **File → Switch SurveySync Project**.

- **Open** switches the shared SurveySync project and rebinds module storage.
- **Remove** forgets the recent-project shortcut only.
- **Delete** removes the entire project folder only after exact project-name confirmation.

Deleting the active project first detaches the embedded FieldBookSync runtime so its SQLite/cache files are not left locked on Windows.

## Project structure

```text
<Project Folder>/
  survey_sync_project.json
  Source/                 # immutable registered evidence
  Derived/
  Reports/
  Exports/
  Attachments/
  Modules/
    FieldBookSync/        # isolated v8 engine workspace
    ControlSync/
    COGOSync/
    ...
  .surveysync/
    survey_sync.db        # audit, QA, points, sources, control, feedback
    cache/
    logs/
```

## Run from source

```bat
run_windows.bat
```

Normal source launches hide the bootstrap console automatically so only the SurveySync desktop window remains visible. For troubleshooting, use `run_windows.bat --console`.

Or:

```bash
python desktop.py
```

Browser fallback:

```bash
python run_browser.py
```


## Local field-book processing

FieldBookSync rejects cloud document providers at settings and processing boundaries. Local document requests require verified installed model weights and literal loopback endpoints. Downloads for optional models or packages remain separate, explicitly initiated operations; inference does not silently download a model or fall back to a cloud provider.

The original rendered page remains authoritative. Original and grid-cleaned OCR views are retained separately, and semantic vision reads original imagery. Exact independent PointID evidence, disagreement checks, and manual review govern acceptance. Actual model accuracy, latency, memory fit, and cancellation on the target workstation require hardware acceptance.

See the [local field-book pipeline](docs/LOCAL_FIELDBOOK_PIPELINE.md) for the current processing boundaries and known limitations. Earlier milestone descriptions of selectable cloud providers are historical and do not override this policy.

## Windows installer

`installer/SurveySync.iss` is the Inno Setup source. `SurveySync.exe` and `SurveySyncUpdater.exe` are already built x64 Windows PE launchers. See `installer/BUILD_WINDOWS.md`.

## Tests

```bash
pytest -q tests legacy_tests/test_core.py legacy_tests/test_v8117_dip_book_statuses.py legacy_tests/test_v6_features.py
```

The v9 package includes focused platform tests plus preserved FieldBook core/regression coverage.

## Desktop navigation model
SurveySync uses one application shell. The top menubar contains application commands, the row immediately below contains module tabs, and the left rail contains tools for the active module. FieldBookSync retains its mature left-navigation workflow while participating in the same global module-tab navigation.

## FieldBook Sync 8.x migration
The v9 installer intentionally keeps the FieldBook Sync Inno Setup AppId (`D7432040-46E5-4F2B-A9AC-97B2DB7BAF4B`) so an existing v8 installation upgrades in place instead of appearing as a second unrelated application. It removes legacy executables/shortcuts, transfers `.fbs` association to SurveySync, and does not delete `%LOCALAPPDATA%\FieldBookSync` user data or `.fbs` project bundles.

## Field-test reliability additions

The v9 generation also incorporates the first external SurveySync/FieldBookSync field-test feedback: local-first feedback retry handling, a manual Field Book Entry review wizard, and stricter review-first PointID handling. AI-only fallback matches are treated as suggestions for manual review rather than silently changing the authoritative PointID result.

Feedback/bug reporting is now resilient to a failing remote Intake endpoint: the report is committed locally first, transient failures are retried in the background, attachment-related server failures get one metadata-only retry, and anything still unsynced remains visibly Pending for manual retry. This protects the report even if the Google Apps Script endpoint itself is temporarily unhealthy.

## Prior v9.0.2 shell / branding / feedback correction

This candidate retires the visible legacy FieldBookSync 8.1.22 startup splash. SurveySync Home now owns What's New, with an always-visible release card plus a first-launch in-shell release-notes dialog after an update. The FieldBookSync workspace opens directly.

The global application ribbon is standardized across SurveySync and FieldBookSync: File, Home, Edit, View, Data, Tools, Options, Help followed by the same module tab row. Module-specific navigation remains on the left side of the active module.

The installer and FieldBookSync classic branding now use the SurveySync navy/gold globe mark.

The full Feedback Wizard is restored as the application-wide feedback entry point. It can be opened before any project exists; local-first feedback capture is therefore available even when a user is reporting a startup, installer, or project-opening problem.

### Prior v9.0.2 ribbon consistency hotfix

FieldBookSync now uses the same full-width SurveySync environment strip, application menu bar, and module tab ribbon as the main shell. Its module-specific navigation begins below the global ribbon, matching the Home and other module layouts.


## Automatic AI selection
Automatic selection uses available local engines and installed models. For less than 6 GB dedicated VRAM, the documented performance plan keeps Paddle on CPU and reserves GPU memory for local vision, preferring an installed 2B vision model. Selection is not a model download or proof of workstation performance. See [local processing and hardware acceptance](docs/LOCAL_FIELDBOOK_PIPELINE.md).

## Updater and core QA consolidation

- **Check & Update** is now a single action throughout SurveySync and FieldBookSync. It checks the active SurveySync release channel, downloads a newer installer when needed, verifies size/SHA-256/Windows EXE header, writes the one shared `%LOCALAPPDATA%\SurveySync\pending_update.json` handoff, and closes SurveySync so the native helper can launch Setup.
- FieldBookSync no longer owns or exposes a separate update source. Its compatibility update routes proxy the SurveySync updater and its UI contains no FieldBookSync GitHub updater configuration.
- The default update manifest is `cpaul1988/SurveySync/main/update.json`; environment changes keep that shared manifest while selecting Developer/Beta/Stable through the release channel.
- Version comparison normalizes missing trailing numeric components: `9.1.4` and `9.1.4.0` compare equally; `9.1` remains earlier than `9.1.4`.
- Oversized partial downloads are deleted immediately.
- ReportSync point-range calculation now uses an O(n) gap walk instead of iterating every unused integer, and ambiguous empty input returns a clear error rather than a misleading empty report.
- FieldBookSync point-range output uses the same canonical gap algorithm.
- Survey/control header aliases are deterministic ordered tuples; `Height` is accepted as an elevation header.
- Export metadata now reports the current SurveySync version instead of the stale FieldBook Sync v8.0.0 string.

## Feedback before builds

Check the shared tracker identified by `feedback.json` before a build or package. Record the check time, newest feedback ID, and the sheets actually inspected. Historical checkpoint counts are not a live feedback check. The [October 19 development review](docs/development/repository_tools_review_2026_10_19.md) records this tooling change's read-only check; a future build needs a fresh check.
