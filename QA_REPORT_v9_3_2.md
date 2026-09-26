# SurveySync 9.3.2 QA Report — Beta Candidate

## Candidate

- Version: **9.3.2**
- Branch: `v9.3.2-open-source-integration`
- Baseline Stable: **9.3.1**
- Release type: Beta candidate
- Stable promotion: blocked until installed Windows acceptance is completed

## Pre-build feedback check

Checked September 26, 2026 before candidate packaging:

- Latest Feedback Intake: **FBR-0016 — Rod Height Bust Tool**
- Newer Intake items: **none**
- SurveySync Error Log Tracker total/open errors: **0 / 0**
- Critical errors: **0**
- Retry/queued submissions: **0**

FBR-0016 is already represented in the TopoSync rod-height workflow.

## Quality evidence

Before the 9.3.2 version bump, the complete integration branch passed SurveySync Quality run **#80**:

- 321 tests passed
- 1 test skipped
- 0 failures
- 58.08% total line coverage
- required coverage floor: 54%
- Ruff static checks: PASS
- Ruff formatting: PASS
- mypy: PASS
- Python compile checks: PASS
- JavaScript syntax checks: PASS
- documentation gate: PASS
- static safety gate: PASS

Quality run **#85** after the 9.3.2 version bump stopped at the fail-closed documentation gate because this version-specific QA report did not yet exist. No source-code/test failure was reached in that run. This report resolves that required documentation item; the quality workflow must pass again on the current candidate before Beta publication.

## 9.3.2 regression scope

Dedicated 9.3.2 regression coverage includes:

- horizontal/three-point curves
- polygon metrics
- simple circular-curve staking
- continuous tangent/circular-curve alignment
- LEFT-positive station/offset round trips on tangent and curve elements
- LandXML CgPoint/Parcel/Alignment round trips
- audited immutable-source LandXML API import/export
- vertical parabolic curves
- cross-section cut/fill
- average-end-area earthwork and mass-haul
- 2D slope-catch intersection
- conventional 2D least-squares control networks
- covariance/error ellipses
- redundancy and standardized residuals
- weighted benchmark-network leveling
- project-bound tamper-evident audit chain
- cross-project audit-chain transplant rejection
- Project Health audit verification
- deliverable audit-head manifest provenance
- Beta/Stable release branch guards

## Protected validated workflows

9.3.2 does not replace:

- Ronald's validated three-shot/best-three ControlSync workflow
- Ronald's validated three-wire level workbook workflow
- pyproj/PROJ as authoritative CRS transformation engine
- original survey/source evidence with calculated output

## Known boundaries

The Beta does not claim production support for:

- LandXML spiral/clothoid geometry
- LandXML surfaces/profiles beyond the implemented alignment/parcel/point subset
- full 3D slope staking
- Authenticode-signed installer
- cryptographically signed update manifests
- field-calibrated rod-height probability estimates

Unsupported LandXML alignment geometry is surfaced for review rather than silently approximated.

## Beta.1 Installed Acceptance Result

**FAILED — startup before UI**

The first 9.3.2 Beta installer completed its CI/build workflow but the installed application crashed before opening the SurveySync UI.

Root cause confirmed from the packaged dependency model:

- `surveysync/landxml_io.py` imports `defusedxml` during router startup.
- CI installs `requirements-dev.lock`, which contained `defusedxml==0.7.1`.
- The Windows installer provisions the application environment from `requirements.lock`.
- `requirements.lock` did not contain `defusedxml`.

Corrective action for Beta.2:

- production input/lock updated with `defusedxml`
- installer runtime verification now imports `defusedxml`
- `tests/test_v932_installer_runtime.py` prevents recurrence
- numbered immutable Beta candidates are supported
- Beta publication now requires a pre-created exact candidate tag, avoiding GitHub App workflow-tag permission failures

Beta.1 is rejected for Stable promotion.

## Beta.2 Candidate Quality Evidence

SurveySync Quality run **#98** passed on the corrected Beta.2 candidate after the production-runtime fix:

- **323 passed**
- **1 skipped**
- **0 failed**
- **58.08% line coverage** against a 54% floor
- documentation gate: PASS
- static-quality gate: PASS
- Ruff checks/format: PASS
- mypy: PASS
- Python compile checks: PASS
- JavaScript syntax: PASS
- dependency lock audit: PASS

The additional regression coverage verifies that LandXML's `defusedxml` dependency exists in the production requirements input/lock used by Setup and that Setup smoke-tests actual SurveySync startup imports before reporting success.

## Required Beta publication gate

The GitHub **SurveySync Release** workflow must:

1. run from `v9.3.2-open-source-integration`
2. receive version `9.3.2`
3. use action `publish_beta`
4. rerun the shared release gate
5. rebuild both native launchers
6. verify native launcher integrity
7. compile the Windows installer
8. create the SHA-256 sidecar
9. publish prerelease `v9.3.2-beta`
10. update the Beta manifest

## Required installed Windows acceptance

Before Stable promotion, test the published Beta installer on Windows/WebView with representative SurveySync projects and data. At minimum verify updater/install/reopen, project open/switch/recovery, existing ControlSync/Ron leveling workflows, new network/level adjustments, COGOSync alignment and LandXML, vertical curves, earthwork, Survey Data Inspector, Trimble JOB/JXL, TopoSync rod-height review, Project Health/audit verification, deliverable packages, Support Center, Feedback Wizard, and FieldBookSync smoke regression.

Stable promotion must use the exact tested Beta installer/hash rather than rebuilding a different artifact.
