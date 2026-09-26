# Open-Source Integration Plan

## Goal

Use mature, permissively licensed open-source work to expand SurveySync without
replacing the project database, audit/provenance model, conservative review
gates, or the validated Ron/EDSI-specific workflows that already exist.

The rule for every integration is:

1. Preserve SurveySync's project/source provenance.
2. Never silently alter original survey evidence.
3. Keep a reviewable calculation record.
4. Validate imported algorithms against independent fixtures before production use.
5. Prefer MIT/BSD/Apache-2.0 code and preserve attribution.

## Code-level comparison

### COGOSync

Current SurveySync:
- inverse
- bearing/distance forward calculation
- line-line intersection
- pyproj-based CRS transformations

Cogokit adds:
- circular-curve element solver
- three-point curve
- spiral/clothoid basics
- triangle solvers
- polygon area/perimeter
- Bowditch adjustment
- Helmert transforms
- alignment station/offset
- stakeout and slope staking
- cross sections/earthwork
- LandXML and broader export helpers

Decision:
- Keep SurveySync's existing basic COGO functions because they are small,
  audited, and already covered by regressions.
- Adopt selected Cogokit algorithms behind SurveySync APIs rather than importing
  Cogokit's Job/database layer.
- First integration implemented in 9.3.2:
  `surveysync/cogo_extended.py` + horizontal/three-point curve APIs and UI.

9.3.2 Phase B implemented:
- polygon area/perimeter with centroid/orientation
- polyline alignment station/offset with explicit left-positive convention
- simple circular-curve station staking with PC/full-station/PT output

Next:
- horizontal/vertical curve geometry expansion
- slope staking
- cross sections/earthwork

### ControlSync

Current SurveySync:
- Ronald's validated three-shot control workflow
- all-triplet best-three selection
- field-observation QC
- GNSS metadata/provenance
- immutable solution revisions
- accepted/reshoot outputs
- generic weighted/arithmetic averaging

pySurveying adds:
- general weighted least-squares
- nonlinear 2D control networks
- covariance
- Qxx/Qvv
- redundancy numbers
- standardized residuals
- robust adjustment
- iterative data snooping
- error ellipses

Cogokit adds:
- distance/angle/direction/azimuth least-squares network adjustment
- Helmert transforms
- GPS baseline observations

Decision:
- Do **not** replace Ronald's validated workbook workflow.
- Add a separate "Network Adjustment" workflow for conventional survey networks.
- Use one engine as the production implementation and the other as an
  independent regression/reference engine where practical.
- Require fixed-point/constraint declaration and observation sigmas.
- Report covariance/error ellipses and residual diagnostics rather than only
  adjusted coordinates.

Recommended production direction:
- SurveySync-native adapter around pySurveying-style statistical outputs.
- Cogokit/independent fixtures as secondary numerical verification.

### Leveling

Current SurveySync:
- single-wire and three-wire ingestion
- Ronald workbook-compatible three-wire calculations
- stadia/middle-wire checks
- setup/distance closure adjustment
- revision history

pySurveying adds:
- weighted least-squares leveling networks

Cogokit adds:
- differential level-run reduction/loop closure

Decision:
- Preserve the Ron three-wire profile exactly.
- Add a separate weighted network-adjustment mode for interconnected benchmarks.
- Never blend workbook-profile leveling and general network least-squares into
  one hidden calculation mode.

### Traverse

Current SurveySync:
- closed/fixed-end traverse
- Bowditch
- Transit rule
- closure and precision
- immutable solution revisions

Cogokit adds:
- equivalent Compass/Bowditch implementation
- observation-reduction workflow
- Tienstra resection
- broader field workflow

Decision:
- Keep SurveySync's Bowditch/Transit solver.
- Use Cogokit fixtures as a regression cross-check.
- Adopt resection/field observation reduction as separate functions.

### CRS / Geodesy

Current SurveySync:
- pyproj/PROJ CRS library
- EPSG/ESRI search
- State Plane browsing
- project local-site grid/ground transform
- coordinate transforms

Cogokit adds:
- custom projection implementations
- State Plane tables
- Vincenty direct/inverse
- grid/geodetic conversions

Decision:
- Keep pyproj/PROJ as SurveySync's authoritative CRS transformation engine.
- Do not replace PROJ with hand-maintained zone tables.
- Add geodesic/Vincenty-style calculation only where it is useful as a survey
  computation, not as the CRS authority.

### Trimble JobXML

Current SurveySync:
- direct JXL parsing
- official Trimble ASCII File Generator path for proprietary .JOB
- Reductions/InventoryData/FieldBook handling
- GNSS metadata extraction
- preservation of original source evidence

jxl2txt adds:
- BSD-licensed XSLT-oriented JobXML conversion patterns

Decision:
- Keep SurveySync's parser and official .JOB conversion path.
- Add jxl2txt-derived/compatible JobXML fixtures and schema cases to regression tests.
- Do not replace the parser with an XSLT-only pipeline.

### Audit / provenance

Current SurveySync:
- append-oriented audit_events table
- immutable source copies + SHA-256
- data-edit history
- solution revisions

Buzz adds:
- cryptographically chained audit entries
- exact actor/action history
- workflows and signed-event architecture

Decision:
- Do not import Buzz's Nostr/Postgres/Redis architecture.
- Adopt the tamper-evident hash-chain concept locally in SQLite.
- Implemented in 9.3.2:
  `audit_chain` table, migration/backfill, chained SHA-256 entries, and
  `verify_audit_chain()` / `GET /api/v9/audit/verify`.

Future:
- include audit-chain verification in Project Health.
- include audit head hash in deliverable manifests.

### Workflows / automation

Current SurveySync:
- background task queue
- explicit module actions
- updater/release automation

Buzz adds:
- declarative YAML workflows
- triggers, conditions, ordered actions, timeouts
- human/agent action model

Decision:
- Build a SurveySync-native workflow engine rather than embedding Buzz's relay.
- Candidate triggers:
  - project opened
  - source imported
  - QA completed
  - control QC passed
  - deliverable created
  - export completed
- Candidate actions:
  - run QA
  - run export profile
  - build deliverable package
  - send configured notification
  - create review item
- Mutating/certification actions must remain explicitly review-gated.

## Release architecture borrowed from Buzz

Buzz separates:
1. immutable candidate build
2. installed testing
3. promotion of the exact tested artifact

SurveySync 9.3.2 adopts stricter branch semantics:
- `publish_beta` is rejected on `main`.
- `promote_stable` is rejected anywhere except `main`.
- Stable promotion occurs only after the tested candidate is merged.
- The promoted installer remains the exact Beta artifact/hash.

This prevents the branch/version ambiguity encountered during the 9.3.1 release.

## Repositories evaluated

### Approved for code/adaptation

| Repository | License | Use |
|---|---|---|
| devinmlowe/cogokit | MIT | COGO, curves, alignments, stakeout, LandXML, reference fixtures |
| hujinghaoabcd/pySurveying | MIT | least-squares/QC/reference validation |
| mrahnis/jxl2txt | BSD-3-Clause | JobXML schema/XSLT regression expansion |
| block/buzz | Apache-2.0 | audit/workflow/release architecture |

### Use as normal dependencies, not forks

| Repository | Reason |
|---|---|
| mozman/ezdxf | mature DXF library; dependency is preferable to maintaining a fork |
| pyproj4/pyproj | authoritative Python binding to PROJ |
| shapely/shapely | mature geometry engine |
| PDAL/PDAL | point-cloud pipeline; integrate as optional external capability |
| OSGeo/gdal | broad geospatial format translation; avoid vendoring/forking |

### Reference only until clarified

`ewilmoth23/meridian` is technically relevant, but its repository LICENSE and
README say MIT while its pyproject metadata says Proprietary. No Meridian source
should be copied into SurveySync until upstream licensing is unambiguous.

### Avoid for direct integration

GPL-licensed survey engines (for example pysurv) can be useful for reading and
independent conceptual comparison, but direct incorporation into SurveySync is
deferred because it would impose materially different distribution obligations.

## 9.3.2 integration sequence

### Phase A — implemented on this branch
- third-party notice tracking
- Cogokit-derived horizontal curve engine
- three-point curve
- COGOSync UI/API
- Buzz-inspired audit chain
- audit-chain verification endpoint
- Beta/Stable release branch guards

### Phase B — implemented on this branch
- Project Health audit-chain check
- audit head in deliverable ZIP manifest
- polygon area/perimeter with centroid and orientation
- polyline alignment station/offset with LEFT-positive convention
- simple horizontal-curve station staking

### Phase C — partially implemented
- **general least-squares network adjustment** — implemented as a separate ControlSync workflow supporting distance, azimuth, direction, and horizontal-angle observations.
- **residual/redundancy/error-ellipse reports** — implemented with observation redundancy, standardized-residual review flags, optional Huber robust weighting, covariance, and 95% point error ellipses.
- **independent numerical cross-validation** — pySurveying's MIT-licensed distance-network fixture is adapted into SurveySync regression coverage without copying the upstream adjustment engine.
- weighted leveling network — next.
- additional Cogokit/independent mixed-network fixtures — next.

### Phase D
- LandXML import/export expansion
- jxl2txt-derived JobXML regression matrix
- optional PDAL/laspy point-cloud module

### Phase E
- SurveySync declarative automation/workflow engine inspired by Buzz
- explicit human approval gates for high-impact survey operations

## Production validation

No imported surveying algorithm should be promoted solely because its upstream
project has tests. Before a SurveySync Stable release it must have:
- SurveySync-owned regression fixtures
- edge-case tests
- unit/convention tests
- comparison against known-good survey software/workbooks where available
- clear output provenance naming the method/version
- human-review behavior for ambiguous or professional-judgment cases

- Audit hashes are bound to a persistent project chain identity, following Buzz's tenant-binding principle without importing Buzz's relay/database stack.
