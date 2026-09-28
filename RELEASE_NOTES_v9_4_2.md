# SurveySync 9.4.2-beta.2 — remaining-audit candidate

This is a prerelease candidate, not a Stable promotion. Use a copy of a project and retain a full backup. The existing 9.4.1 repairs, Ron's control/three-wire conventions, source observations, historical reports and approved globe/EDSI appearance remain in place.

## Connected workflows

**TopoSync / Point Clouds:** inspect LAS/LAZ metadata, retain the original source and sample a bounded set of decoded points. Optional laspy and a LAZ backend are required for preview; unavailable capabilities are shown explicitly. This is not a full 3D viewer, a surface engine or automatic conversion to canonical survey points.

**Home and QASync / Project Automation:** edit and save supported actions, import/export YAML definitions, inspect run history and approve or reject pending work. Approval uses a saved definition snapshot. Changing a definition cannot silently change an already-pending approval. The automated fixtures do not send live stakeholder notifications.

**GISSync / CRS Diagnostics:** inspect profiles, compare candidate operations and test coordinates with AOI and finite-result validation. This panel does not change the original survey points. Project datum, vertical reference and grid suitability still require professional review.

**ReportSync / Excel Template Mapper:** inspect and retain an original workbook, save supported project/point field mappings, and render a separate draft output. Conflicting cells, formula overwrites, merged-cell collisions and existing output overwrites are rejected. Unsaved mappings cannot be silently rendered. Formula-like source text remains text. Existing formulas are preserved but not recalculated by openpyxl; review in a spreadsheet application before use.

**GISSync / External GIS Processing:** discover or explicitly select separately installed QGIS/GRASS executables, inspect QGIS list/help, enter typed parameters and confirm execution. Invalid selections fail rather than silently choosing another installation. External child processes do not inherit SurveySync's private Python loader paths. QGIS discovery retains tab-separated single-word algorithm labels; GRASS uses the temporary-project option advertised by its launcher.

## Release identity and packaging

The numeric application version is **9.4.2**, and the physical build identity is **9.4.2-beta.2**. Installer filenames, native title, About, release-note acknowledgment, cache keys and update prompts show the physical identity. Native and Python components compare numbered prereleases, including beta.2 before beta.10. Promotion of already-installed identical bytes does not require another installation.

A new build gate rejects mismatched Python/native/installer/UI/version metadata. The candidate must pass repeated native lifecycle checks and real same-numeric-version beta replacement in addition to existing installation, project, report and update tests. Test-only predecessor identities are never published as historical releases.

## Lifecycle hardening from repeated acceptance

HTTP Exit now schedules shutdown only after the complete acknowledgement has passed through all buffering middleware and the final transport send. A fixed 150 ms delay was not sufficient: a deterministic delayed-transport regression reproduces the old ordering failure. No exit timeout is increased, and the native close path still uses orderly shutdown.

Foundry Local capability inspection runs in a separately owned, deadline-bounded subprocess instead of loading a potentially stalled native catalog call into the GUI/server process for a status tile. A timeout is shown as unknown readiness, never falsely ready; model download and inference remain separate explicit operations. Concurrent refreshes share a completed capability probe, and the status route no longer performs a duplicate forced probe. This is not validation of live model accuracy or active-analysis cancellation.

## Known boundaries

The candidate is **unsigned**. Signed-manifest verification and certificate-based signing hooks are preparation only: production certificate/private-key configuration, public-key enrollment and strict trust enforcement are not activated. The optional signature verifier must be packaged before strict deployment.

Optional point decoders and external GIS software are not silently installed on users' computers. Actual external GIS examples validated on Linux do not establish every Windows GIS distribution. Real handwriting/OCR/provider accuracy and cancellation, official Trimble binary conversion and field-calibrated rod-height confidence still require independent evidence. A previously intermittent native shutdown timeout remains a tracked item until repeat testing and diagnostics establish the result; a successful single run is not proof of a fix.

Existing reports are not automatically rewritten by installing this candidate. Back up project folders and compare representative results to independent source evidence. No update feed or Stable tag is changed by merely building this candidate.

## Beta.2 field-book follow-up

Field-book cloud engines and second opinions are disabled by the local-only policy, including saved cloud selections and remote Ollama aliases. Original and grid-cleaned OCR views are retained together. Vision uses wider context crops from the original page, with unchanged exact-ID and manual-review requirements. On a 4-GB GPU, Paddle uses CPU while vision retains the GPU budget. Cache keys now include profile context; streamed responses close on failure/cancellation and incomplete results are rejected. Rod-height review summaries normalize units and supersede prior decisions. See docs/LOCAL_FIELDBOOK_PIPELINE.md for the real-sample negative OCR result and hardware/accuracy limits.
