# SurveySync 9.3.2 — Open-source surveying integration and alignment foundation

SurveySync 9.3.2 expands the 9.3 platform with reviewable surveying computation, alignment/LandXML interoperability, stronger project audit integrity, and a safer Beta-to-Stable release process. The existing validated Ronald/EDSI ControlSync and three-wire leveling workflows remain unchanged.

## COGOSync and construction geometry

- **Horizontal curves:** attributed Cogokit-derived simple circular-curve solver plus three-point curve calculations.
- **Polygon geometry:** area, perimeter, centroid, and orientation.
- **Simple curve staking:** PC/full-station/PT coordinates with chord, deflection, and tangent-azimuth information.
- **Horizontal alignments:** continuous tangent/circular-curve station chains with survey azimuths clockwise from north.
- **Station/offset:** evaluate station to coordinate, inverse a coordinate to nearest alignment station/offset, and generate stake coordinates from station plus **LEFT-positive** offset.
- **Vertical curves:** equal-tangent parabolic curves using percent grades, with BVC/PVI/EVC, K-value, high/low point, and station/elevation samples.
- **Cross sections and earthwork:** cut/fill areas, average-end-area volumes, cumulative quantities, mass-haul ordinates, and deterministic 2D slope-catch intersection.

## LandXML 1.2

- Import/export of supported **CgPoint** records.
- Import/export of parcel Line geometry.
- Import/export of tangent/circular-curve Alignment geometry.
- Imported LandXML is copied into the SurveySync project's immutable Source tree and registered with SHA-256 provenance before parsing.
- XML input uses `defusedxml`.
- Unsupported alignment geometry such as spirals is reported for review rather than silently approximated.
- Profiles, surfaces, and spiral/clothoid LandXML geometry remain future expansion.

## ControlSync network adjustment

A new **separate** conventional-network workflow provides:

- weighted nonlinear 2D least-squares adjustment
- distance, azimuth, direction, and horizontal-angle observations
- fixed control constraints and starting coordinates
- covariance and coordinate uncertainty
- 95% error ellipses
- observation redundancy numbers
- standardized-residual review flags
- optional Huber robust weighting

This does **not** replace Ronald's validated three-shot/best-three ControlSync workflow.

## Weighted benchmark-network leveling

A separate benchmark-network adjustment supports:

- fixed benchmark datum constraints
- elevation-difference observations and observation sigmas
- adjusted elevations and elevation uncertainty
- redundancy and standardized-residual review flags
- optional Huber robust weighting

This does **not** replace Ronald's validated three-wire workbook reduction.

## Tamper-evident project audit

- Project audit history is SHA-256 chained.
- Each project carries a persistent chain identity, preventing a valid chain from another project from being transplanted and accepted.
- Project Health verifies the audit chain.
- Deliverable-package manifests include the verified audit head and chain identity.
- Source evidence and professional-review decisions remain auditable.

## Release architecture

SurveySync 9.3.2 separates:

1. source/candidate development
2. immutable Beta build and installed testing
3. promotion of the **exact tested Beta artifact** to Stable

Beta publication is blocked from `main`; Stable promotion is blocked until the tested candidate is merged to `main`. This prevents the branch/version ambiguity encountered during the 9.3.1 release process.

## Third-party integration

SurveySync retains its Python + FastAPI + WebView + SQLite 9.x architecture.

- Cogokit (MIT): selected curve/alignment/construction geometry adaptation.
- pySurveying (MIT): independent numerical/reference direction for network-adjustment validation; SurveySync uses its own adjustment implementation.
- jxl2txt (BSD-3-Clause): JobXML regression/reference direction.
- Buzz (Apache-2.0): audit/release/workflow architecture inspiration; Buzz's Nostr/Postgres/Redis/chat/Tauri infrastructure is not imported.

See `THIRD_PARTY_NOTICES.md` and `docs/OPEN_SOURCE_INTEGRATION_PLAN.md`.

## Safety and review behavior

- Original survey evidence is never silently rewritten.
- Network residual flags are review indicators, not automatic observation deletions.
- Robust weighting is explicit and reported.
- LandXML unsupported geometry is surfaced instead of guessed.
- Rod-height corrections remain review-gated and export to new copies.

## Pre-build tracker check

Checked before preparing the 9.3.2 Beta candidate on September 26, 2026:

- Latest Feedback Intake item: **FBR-0016** — Rod Height Bust Tool, already incorporated into the TopoSync workflow.
- SurveySync Error Log Tracker: **0 total errors / 0 open errors**.
- Retry/queued submissions: **0**.
- No newer feedback item was present at the pre-build check.

## Quality evidence before Beta build

The open-source integration branch passed SurveySync Quality run **#80** before the version bump:

- **321 passed**
- **1 skipped**
- **0 failed**
- **58.08% line coverage** against a 54% floor
- Ruff/static checks passed
- Ruff formatting passed
- mypy passed
- Python compile checks passed
- JavaScript syntax checks passed

The Beta publication workflow runs the complete shared release gate again and rebuilds both native Windows launchers before compiling the installer.

## Required installed-Windows Beta acceptance

Before Stable promotion, install the published 9.3.2 Beta and verify:

1. installer/updater closes and reopens SurveySync normally
2. app title/About/update surfaces report 9.3.2
3. existing project open/switch/recovery behavior
4. Support Center and Feedback Wizard
5. Survey Data Inspector with representative CSV/TXT and Trimble JOB/JXL
6. existing Ronald ControlSync best-three workflow
7. 2D Network Adjustment with a known reference network
8. existing Ron three-wire leveling workflow
9. weighted benchmark-network leveling
10. COGOSync horizontal alignment station/offset and stake-point round trip
11. LandXML import/export on representative point/parcel/alignment data
12. vertical curve reference calculation
13. cross-section/earthwork/slope-catch tools
14. TopoSync rod-height reviewed candidate workflow
15. deliverable package and Project Health audit-chain verification
16. FieldBookSync regression smoke test

Real field-positive/negative rod-height datasets remain required before treating rod-height detection as production-calibrated.

Authenticode signing and signed update manifests are not configured; do not represent this build as a signed Windows release.
