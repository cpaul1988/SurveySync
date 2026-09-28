# 9.4.2-beta.1 preparation — September 28, 2026

User requested the distinct next candidate after remaining-audit development. Stable 9.4.1, its installer/tag and both published update feeds remain unchanged. PR #13 is still draft and unmerged. This candidate must not be distributed under the 9.4.1 identity.

## Baseline lifecycle repetition

The exact prior internal executable with SHA-256 `a44973780170d44548611f6eb7332943fc53201eb5f7121634ef32d203c8797a` was retrieved without rebuilding and tested in a disposable Windows installation. Run `36431673400` / job `108959145379` passed all 24 independent cycles: eight project-switch cycles, eight early API exits and eight normal native-window closes. Every cycle exited zero within the unchanged 15-second deadline, closed the API, recorded a clean session and preserved both projects' canonical points plus source CSV bytes. Observed exit range: 3.516–8.156 seconds. No retries converted failed cycles to passes.

Evidence artifact `10973434190`, archive SHA-256 `81da23d1b8368e16fc8fbaed7f7004faa99ac50d76e2137515e4a3142d8bcc96`, downloaded and independently verified. This does not establish the cause of the earlier isolated native timeout. No production shutdown behavior was changed on the strength of a successful repetition.

## Distinct candidate preparation

Numeric version 9.4.2 and physical identity 9.4.2-beta.1 now agree across source, launcher, installer, window title, About, release-note acknowledgment and UI cache keys. A new gate checks cross-surface consistency. Historical numeric-version test fixtures now explicitly mock their complete old identity; current-surface tests validate the packaged full identity instead of assuming a prerelease equals its numeric core. Existing assertions are retained or replaced with the equivalent full-identity contract.

Local Linux/Python 3.13 regression selection: **591 passed, 1 skipped**. This is local evidence, not the pending candidate Windows gate. Documentation/static quality, Python source compilation and main-shell JavaScript syntax passed locally.

The normalized 35-file reviewed delta is SHA-256 `f322fa51eaf93ee73bf9f9e4d6619bfb8f1eb54961e60402e67f8dfab9566c21`. Every before/after file digest was checked. The Actions token cannot edit workflow definitions; the source importer therefore wrote only its 33 application/document/test files. The authorized connector applies the two workflow changes separately, without changing bot permissions.

## Candidate acceptance

The installed gate now requires another 24-cycle stress sequence on the actual numbered candidate and three real replacement scenarios: same-numeric-version beta.0 test predecessor to beta.1, unmodified published 9.4.1 to the candidate, and the existing released 9.4.0 migration. The beta.0 fixture is a real temporary Setup build whose identity stamps alone differ; it is not fabricated as a historical public release. The target executable is never rebuilt after acceptance. HTTPS, checksums, confirmation, native helper, actual Setup and preserved project/point/settings checks remain mandatory.

The full four-workflow run set is required. Completed results must be recorded against its exact source/installer; this preparation document is not a pass certificate. Existing provider/field/production-signing boundaries remain as described in RELEASE_NOTES_v9_4_2.md. Pre-build Intake returned 16 records, latest FBR-0016; no tracker edits, live feedback test submissions or provider calls were made.
