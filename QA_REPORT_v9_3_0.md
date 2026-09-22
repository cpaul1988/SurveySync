# SurveySync 9.3.0 QA report

Status: validated source candidate; Windows compilation and real-data acceptance pending.

## Verified in this environment

- Original 9.2.6 HEADERLESS_MAPPING_SAFE archive checksum verified; baseline 246 tests passed.
- Updated suite: **279 passed, 1 skipped, 0 failed**. The skip is the prebuilt native-EXE test; no outdated EXEs are packaged. Windows build requires fresh Go compilation and then verifies both PE GUI headers.
- Whole-application line coverage: **56.27%**, against an enforced 54% floor. This is measured coverage, not a claim of full workflow coverage.
- Ruff undefined-name/error checks pass across both application packages; format checks pass for 22 extracted/new modules.
- Gradual mypy checks pass for 11 source files, including the complete new TopoSync backend.
- Python compileall, JavaScript syntax, static safety and release-documentation gates pass. Workflow YAML parses successfully.
- All-platform audit: **102 exact package/version pins; no known vulnerabilities found**, including Windows-specific branches. Hashes are enforced at install time.
- Regression coverage includes stale-analysis rejection, project switching, control import/QC, round-trip revisions and source provenance. New tests cover isolated rod-height flags, non-finite input, no mutation, unique route registration, dynamic map runtime, missing-project status, failed-gate short-circuiting and the recent-project fallback bug.
- Static counts: SurveySync broad handlers reduced from 144 to 127; FieldBookSync remains at 149 broad handlers, but all 22 silent broad passes now log. No silent broad handler remains in either package.

- Added 25 TopoSync range/import/export regression cases, including the known −1.83 ft synthetic shift, terrain exclusions, unit conversion, uncertain boundaries, original-source preservation and native export creation. Browser automation could not execute because the Chromium download was truncated; no visual/WebView acceptance pass is claimed.
- Supplied master logo is retained byte-for-byte. Emblem PNG was visually inspected; installer and shortcut rendering still need Windows acceptance.

## Tracker review

Read feedback Intake and the shared error tracker before preparing this candidate. Latest Intake item: FBR-0016 (September 22), Ron’s advanced rod-height range-detection request. The error tracker has zero entries. No tracker item was marked Released. Existing isolated-point QC remains available; the advanced feature is implemented as a conservative review workflow in this candidate.

## Remaining release gates

Go and Inno Setup are unavailable here, so native launchers and the Windows installer were not compiled. The PowerShell/Windows workflow has not been executed here. Test Windows installation/update behavior, real Trimble data, WebView navigation, actual OCR/AI engines, code-profile filters and field-verified survey outputs before publication.

Authenticode and signed update manifests require a separately configured signing identity. Optional PaddleOCR/GPU environments remain outside the new core/Windows-AI locks. Domain extraction is substantial but retains compatibility adapters and application context; it does not eliminate all legacy coupling. FBR-0016 has synthetic/API regression tests; real-world false-positive acceptance data is still required.
