# SurveySync 9.4.0 — Integration, Automation, Interoperability, and Product Refresh

## Beta.4 — Theme-only EDSI co-branding

- Non-EDSI themes use the SurveySync globe alone, including FieldBookSync.
- EDSI Adaptive, EDSI Dark and EDSI Light show the EDSI logo beside the globe in both shells: headers, sidebars, Home, splash markup, About and release notes.
- Switching away from an EDSI theme removes the companion immediately; saved preferences and project data are retained.
- Dark-mode client lettering remains readable without changing the globe colors. Windows icons and the installer remain SurveySync-branded.
- Adds live Options-switch, persistence, cross-window, module, dialog and responsive regression coverage. Full release quality gates remain required.

See `docs/THEME_BRANDING.md` for behavior and validation. This is a test candidate, not a Stable release or native-Windows acceptance signoff.


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


SurveySync 9.4.0 completes the first eight-item open-source integration roadmap while preserving the validated Ronald/EDSI control and leveling workflows, immutable source evidence, project audit chain, and explicit professional-review boundaries.

## Product identity and Windows experience

- Introduces the SurveySync **Surveying Navy / Topographic Gold / Canvas Cream** product identity and **UNIFYING GLOBAL DATA** tagline.
- Updates the Windows installer, shortcut, native window/taskbar icon, favicon surfaces, Inno Setup wizard graphics, About panel, and workflow navigation artwork.
- Adds the 12-icon surveying workflow library across SurveySync and FieldBookSync while preserving client-specific branding profiles such as EDSI.
- Stamps the Python core, native launcher, Windows installer, main shell, and FieldBookSync shell as **9.4.0**.

## 1. COGOSync / open-source surveying integration foundation

SurveySync 9.4 carries forward the attributed MIT-derived COGO and construction geometry foundation:

- horizontal circular curves and three-point curves
- polygon area/perimeter/centroid
- station-based curve staking
- tangent/circular-curve horizontal alignments
- LEFT-positive station/offset calculations
- vertical parabolic curves
- cross-section cut/fill, earthwork, mass-haul, and 2D slope-catch calculations
- LandXML 1.2 point, parcel-line, and supported alignment geometry

Original survey evidence remains separate from calculated output.

## 2. Independent pySurveying-style network validation

ControlSync's conventional 2D least-squares network workflow now includes a separate independent validation engine.

The production network adjustment uses SurveySync's numerical Jacobian path, while the validator uses analytic derivatives and NumPy least-squares. It cross-checks:

- adjusted coordinates
- normalized residuals
- redundancy
- sigma0
- 95% error-ellipse axes

Validation status is reported as **PASS**, **REVIEW**, or **UNAVAILABLE**. Review-only data snooping can identify possible gross-error observations without deleting or changing the original observations.

Ronald's validated best-three control workflow remains unchanged.

## 3. Trimble JobXML compatibility hardening

Direct JXL/JobXML support is expanded across Trimble Access and TBC-style variations:

- namespace/version-independent parsing
- nested Reductions / InventoryData / FieldBook / Environment discovery
- UTF-8/UTF-16/BOM handling
- preferred PointName/PointID aliases
- attribute-based point fields
- Reductions-first behavior with InventoryData supplementation
- GNSS occupation metadata merge
- narrow text-level recovery for illegal XML control characters and bare ampersands
- fail-closed structural XML corruption handling

Proprietary binary .job files still use Trimble's official ASCII File Generator path; SurveySync does not reverse-engineer the binary format.

## 4. Optional LAS / LAZ point-cloud support

TopoSync adds optional point-cloud intake:

- dependency-free LAS 1.0–1.4 header metadata inspection
- point count, point format, scale, offset, bounds, and VLR metadata
- immutable LAS/LAZ source preservation with audit provenance
- optional laspy support for richer metadata and bounded point sampling
- optional PDAL CLI fallback for compressed LAZ/COPC metadata

Neither laspy nor PDAL is required for normal SurveySync startup.

## 5. Project workflow automation

SurveySync adds project-scoped YAML workflows with persistent run state.

Supported triggers include:

- manual
- project opened
- source imported
- QA completed
- export completed
- deliverable created

Supported safe actions include Project Health, saved export profiles, and Review Center items.

**FINAL deliverable creation and stakeholder notification are hard approval-gated.** Workflow YAML cannot disable those requirements. Unknown actions fail closed, and arbitrary shell/Python execution is not supported.

## 6. CRS diagnostics via pyproj / PROJ

GISSync now exposes the evidence behind coordinate-system operations:

- CRS authority/name/type
- datum, ellipsoid, and prime meridian
- axis order, direction, units, and conversion factors
- area of use
- available and unavailable source-to-target operations
- published operation accuracy
- missing transformation-grid evidence
- best-operation availability
- project unit mismatch review flags
- optional sample-coordinate area-of-use checks
- Local Site / grid-to-ground context

PROJ remains SurveySync's authoritative CRS transformation engine. SurveySync does not silently change a project CRS or automatically download transformation grids.

## 7. ReportSync Excel Template Mapper

ReportSync can now preserve and populate company/client Excel deliverables without hard-coding each workbook layout.

Features include:

- immutable .xlsx/.xlsm template preservation
- {{placeholder}} discovery
- reusable scalar-cell mappings
- canonical-point table mappings
- template-row style propagation
- embedded placeholder replacement
- source SHA-256 provenance
- rendered workbook registration as **DRAFT** deliverables

DRAFT template output intentionally does not trigger final-deliverable notification policy.

## 8. Optional QGIS / GRASS GIS processing bridges

SurveySync can optionally use independently installed QGIS or GRASS GIS applications as external processing engines.

QGIS bridge capabilities:
- runtime discovery/status
- Processing algorithm list
- algorithm help
- explicit algorithm execution

GRASS bridge capabilities:
- runtime discovery/status
- validated g.*, r.*, v.*, db.*, and i.* module execution
- temporary-project execution using the selected CRS

The bridge uses validated argument arrays and `shell=False`. SurveySync does not vendor, embed, link against, or import QGIS/GRASS application source code.

## Existing 9.x safety and reliability retained

9.4.0 retains:

- append-oriented and tamper-evident project audit history
- project-bound audit-chain verification
- immutable imported source evidence with SHA-256
- Project Health / Review Center
- staged imports and comparison
- active solution revisions
- Support Center and diagnostics
- Survey Data Inspector
- TopoSync rod-height review workflow
- exact-artifact Beta-to-Stable promotion architecture
- clean production-runtime verification before installer build

## Pre-build feedback and error check

Checked **September 26, 2026** before 9.4.0 release-candidate preparation:

- Latest Feedback Intake item: **FBR-0016 — Rod Height Bust Tool**
- Newer Intake items: **none**
- SurveySync Error Log Tracker: **0 total errors / 0 open errors**
- Critical errors: **0**
- Retry/queued submissions: **0**

FBR-0016 is already represented in the TopoSync rod-height workflow.

## Feature-complete quality evidence before version bump

The feature-complete 9.4 integration branch passed SurveySync Quality run **#158** (run ID **36283699520**) before the release stamp:

- **362 passed**
- **1 skipped**
- **0 failed**
- **59.35% line coverage** against a 54% floor
- documentation gate: PASS
- static-quality gate: PASS
- Ruff checks: PASS
- Ruff formatting: PASS
- mypy: PASS across 29 source files
- Python compile checks: PASS
- JavaScript syntax checks: PASS
- dependency lock audit: PASS

The versioned release-candidate branch must pass the same quality gate again before Beta publication.

## Beta.2 branding and first-launch notes correction

Installed Beta.1 acceptance identified two presentation defects:

1. the generated Windows application/installer/shortcut icon used an **S/monogram** treatment instead of the intended SurveySync globe; and
2. release notes could be suppressed on first launch when the same workstation had already marked version 9.4.0 as seen from an earlier development/beta build.

Beta.2 corrects both:

- Windows `.ico` generation now resamples the canonical `branding/SurveySync_globe_512.png` artwork into the multi-resolution 16/24/32/48/64/128/256 icon instead of drawing an S.
- SurveySync top-left product branding, product splash, About dialog, release-notes dialog, favicon, and the shared FieldBookSync SurveySync header now use `surveysync_globe.svg`.
- Module/workflow icons remain module-specific; this change only standardizes SurveySync **product** branding.
- The release-notes API now exposes a release-specific ID (`9.4.0-beta.2`).
- First-launch release-note acknowledgement is keyed to that release ID instead of version alone.
- Release notes are marked seen only after the user clicks **Continue**.

Beta.1 is not the preferred 9.4 acceptance artifact. Installed acceptance should continue with Beta.2.

## Installed Windows acceptance required before Stable

The 9.4.0 Beta is not Stable until the exact published installer is installed and checked on Windows.

At minimum verify:

1. installer runtime provisioning completes and SurveySync opens normally
2. About/title/update surfaces report 9.4.0
3. project create/open/switch/recovery
4. Support Center, Feedback Wizard, and Error Log
5. Survey Data Inspector
6. Ronald ControlSync best-three workflow
7. conventional network adjustment plus independent validation
8. Ron three-wire leveling and weighted benchmark network
9. Trimble JXL and official .job conversion path where Trimble components are installed
10. COGOSync alignment/LandXML/vertical curve/earthwork
11. TopoSync rod-height review and LAS point-cloud metadata intake
12. workflow automation, including WAITING_APPROVAL behavior
13. CRS diagnostics and unit/area-of-use warnings
14. ReportSync Excel Template Mapper with a representative client/company workbook
15. QGIS / GRASS bridge status and a real processing smoke test where those applications are installed
16. Project Health, audit verification, deliverable package, and FieldBookSync regression smoke

Stable promotion must reuse the **exact tested Beta installer and SHA-256**.

## Known release boundaries

- QGIS, GRASS, laspy, PDAL, and Trimble conversion components are optional external capabilities.
- QGIS/GRASS availability in CI is not required; installed-machine acceptance is required when those bridges will be used.
- Real field-positive and field-negative rod-height datasets remain necessary for production calibration of rod-height detection.
- Authenticode signing and cryptographically signed update manifests are not configured. Do not represent this build as a signed Windows release.
