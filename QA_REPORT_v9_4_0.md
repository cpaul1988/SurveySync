# SurveySync 9.4.0 QA Report — Release Candidate

## Beta.3 — FieldBookSync-standard interface and installed UI repair

This candidate responds to CP's installed Beta.2 screenshots and request to make Home and the other modules look and feel like FieldBookSync.

- Both shells load `fieldbook-standard.css` after their existing styles. FieldBookSync palettes, body typography, cards, navigation, controls, spacing, and light/dark settings form the shared presentation layer. Saved preferences remain authoritative; no client branding or project data is reset.
- Home has the same compact project toolbar, workspace sidebar, metric cards, and workflow entry cards. Module-specific tools and data operations remain.
- Corrects the Element-versus-NodeList icon initialization error. Static serving accepts nested workflow-icon paths while rejecting traversal and resolved symlink escapes. Decorative icon failure cannot stop startup.
- Release notes load independently of project/status requests, identify `9.4.0-beta.3`, time out with Retry, and remain unread until Continue.
- Globe-derived transparent web/Windows icons and real 24-bit installer BMPs are regenerated together before compilation. Large and small wizard graphics have high-resolution alternatives. Dark-mode wordmarks use light lettering without inverting the globe.
- Removes a duplicate operations-router inclusion. The main router still registers the original operations router; no operations endpoints are removed.

Validation before submission: 387 tests passed, 1 skipped locally; JavaScript syntax, static quality, and documentation checks passed. Browser CI adds actual screenshots for 11 modules in light and dark mode, first-launch/acknowledgment/retry checks, image decoding, and responsive Home checks. CI and installed Windows acceptance are separate; a generated image or unit test is not proof that the installed wizard was visually checked.

Pre-build feedback: connected Intake sheet read through row 1001; 16 reports, latest FBR-0016 dated 2026-09-22. This candidate also incorporates the current chat's UI and branding reports. No tracker records were changed.

Branch: `v9.4.0-beta3-unified-ui`. Beta.2 and Stable artifacts remain unchanged until the normal tagged release workflow is explicitly run.


## Candidate

- Version: **9.4.0**
- Branch: `v9.4.0-release-candidate`
- Source integration branch: `v9.4.0-development`
- Release type: Beta candidate / installed-Windows acceptance candidate
- Stable promotion: **blocked until installed Windows acceptance completes**

## Required pre-build tracker check

Live trackers were checked on **September 26, 2026** before the 9.4.0 versioned candidate was prepared.

### Feedback Intake
- Tracker: **FieldBook Sync Feedback Tracker**
- Latest item: **FBR-0016 — Rod Height Bust Tool**
- Submitted: 2026-09-22
- Newer Intake items: **none**
- FBR-0016 status in product scope: represented in TopoSync rod-height workflow

### Error tracker
- Tracker: **SurveySync Error Log Tracker**
- Total errors: **0**
- Open errors: **0**
- Critical errors: **0**
- Retry/queued pending: **0**
- Errors tab contains header only
- Retry Queue contains header only

## Feature-complete quality evidence before version bump

The final feature integration for roadmap items 1–8 passed SurveySync Quality run **#158**:

- Workflow run ID: **36283699520**
- Tests: **362 passed / 1 skipped / 0 failed**
- Total coverage: **59.35%**
- Required coverage floor: 54%
- documentation gate: PASS
- static quality: PASS
- Ruff: PASS
- Ruff format: PASS after formatter correction
- mypy: PASS across 29 source files
- compileall: PASS
- JavaScript syntax checks: PASS
- dependency lock audit: PASS

This quality run covered the feature-complete code immediately before the release version stamp. The release-candidate branch must pass the shared gate again with VERSION.txt, installer metadata, release notes, QA report, build manifest, and UI/native version surfaces all set to 9.4.0.

## 9.4.0 regression scope

Dedicated 9.4 tests cover:

- product identity / Windows brand assets
- independent pySurveying-style network validation
- distance and mixed angular network cross-checks
- review-only data snooping
- JobXML namespace/version/nested section/encoding compatibility
- safe JobXML text recovery and fail-closed structural corruption
- native LAS metadata parsing
- immutable point-cloud source import
- optional point-cloud runtime behavior
- YAML workflow definition/run persistence
- source-import workflow triggers
- explicit approve/reject gates
- CRS operation accuracy and area-of-use diagnostics
- project unit mismatch review behavior
- Excel template placeholder discovery
- immutable template source preservation
- canonical-point table rendering with format propagation
- DRAFT ReportSync template deliverables
- mocked QGIS processing invocation with shell=False
- GRASS temporary-project command construction
- optional QGIS/GRASS runtime status
- new integration-route registration

Existing 9.x regressions remain in the complete suite.

## Protected validated workflows

9.4.0 does not replace or silently modify:

- Ronald's validated three-shot/best-three ControlSync workflow
- Ronald's validated three-wire level workbook workflow
- pyproj/PROJ as the CRS authority
- original Trimble/LAS/LandXML/Excel survey evidence
- review-gated rod-height corrections
- explicit professional acceptance decisions

## Release constraints

Stable promotion remains blocked until:

1. the final versioned candidate quality gate passes;
2. a numbered immutable Beta tag points at that exact candidate SHA;
3. the GitHub SurveySync Release workflow builds and publishes the Windows installer;
4. the published installer SHA-256 is recorded;
5. that exact installer completes installed-Windows/WebView acceptance;
6. any discovered acceptance defect is corrected in a new numbered Beta rather than overwriting the tested artifact.

## Installed acceptance matrix

Required smoke tests:

- install/provision/launch
- 9.4.0 version surfaces
- updater behavior
- project lifecycle/recovery
- feedback and diagnostics
- core ControlSync and leveling
- network validation
- Trimble JXL/.job
- COGO/LandXML/earthwork
- TopoSync rod-height and LAS
- workflow approval gates
- CRS diagnostics
- ReportSync Template Mapper
- QGIS/GRASS external bridge where installed
- Project Health/audit/deliverables
- FieldBookSync

Optional external capabilities that are not installed should report unavailable cleanly rather than blocking SurveySync startup.

## Versioned candidate quality result

SurveySync Quality run **#160** (run ID **36285028740**) passed on the versioned
9.4.0 release candidate:

- **362 passed**
- **1 skipped**
- **0 failed**
- **59.35% total line coverage**
- 54% required coverage floor
- documentation gate: PASS
- static-quality gate: PASS
- Ruff checks and formatting: PASS
- mypy: PASS across 29 source files
- clean production-runtime verification: PASS
- Windows 9.4 branding/icon verification: PASS
- Python compile checks: PASS
- JavaScript syntax checks: PASS
- dependency-lock audit: PASS

This QA evidence entry is documentation-only. The branch head is revalidated after
recording it so the exact candidate source remains green before tagging.

## Beta.1 installed acceptance finding

**REJECTED FOR PRESENTATION / UPDATE UX**

The first installed 9.4.0 Beta opened, but installed acceptance found:

- the Windows/application branding showed an S/monogram instead of the intended globe; and
- the expected first-launch release-notes dialog did not appear.

Root causes:

- `scripts/generate_surveysync_icon.ps1` generated a synthetic globe-grid icon and explicitly drew `S` in its center, overwriting the intended application icon during every release build;
- active SurveySync and shared FieldBookSync product surfaces referenced `surveysync_monogram.svg`;
- release-note acknowledgement used only version `9.4.0`, allowing a prior 9.4 development/beta session to suppress the notes dialog.

Beta.1 should not be used as the final installed-acceptance artifact.

## Beta.2 correction scope

Beta.2:

- generates Windows icons directly from the canonical SurveySync globe artwork;
- replaces active product-level monogram references with the globe;
- keeps workflow/module-specific icons unchanged;
- uses release ID `9.4.0-beta.2` for first-launch release-note acknowledgement;
- records acknowledgement only when the user presses Continue;
- adds regression coverage preventing the monogram/S generator from returning.

Pre-Beta.2 tracker check: latest feedback remains **FBR-0016**; SurveySync Error Log reports **0 total/open errors** and Retry Queue is empty.

## Beta.2 automated quality result

SurveySync Quality run **#165** (run ID **36287654750**) passed on the Beta.2
branding/release-notes implementation before this evidence-only documentation commit:

- generated SurveySync globe ICO: **133,338 bytes**, **7 frames**
- clean production runtime: PASS
- Windows branding/icon gate: PASS
- documentation gate: PASS
- static-quality gate: PASS
- Ruff / formatting: PASS
- mypy: PASS across 29 source files
- JavaScript syntax: PASS
- **365 tests passed**
- **1 test skipped**
- **0 failures**
- total line coverage: **59.35%**
- required coverage floor: 54%

The branch head is revalidated after recording this evidence. Beta.2 must be tagged
only at that final green SHA.

