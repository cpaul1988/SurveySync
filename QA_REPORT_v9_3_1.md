# SurveySync 9.3.1 QA report

Status: **BetaCandidate source hardening in progress; Windows quality workflow required before compile-ready signoff.**

## Scope reviewed

SurveySync 9.3.1 builds on the released 9.3.0 baseline and adds the Support Center, interrupted-session recovery, Survey Data Inspector, TopoSync QC profiles, analysis history, explicit candidate-review decisions, and advisory calibration summaries.

During release review, three integration defects were found and corrected before candidate validation:

1. The shell startup update check had been accidentally nested inside the browser storage-event handler, so normal startup did not execute that initialization correctly.
2. File-association maintenance launches began a recovery session before their early exit, which could make the next real launch appear to follow an unclean shutdown.
3. Survey Data Inspector cache hits retained the project/CRS/unit context captured when the source was first inspected, which could become stale after switching projects.

Regression coverage for all three fixes is included in `tests/test_v931_release_candidate.py`.

## Pre-build tracker review

The connected feedback tracker was checked on September 24, 2026 before candidate packaging.

- Latest Intake item: **FBR-0016 — Rod Height Bust Tool**. No newer Intake item was present.
- SurveySync Error Log Tracker: **0 error rows**.
- Retry Queue: **0 queued rows**.
- No feedback/tracker item was marked Released as part of this source-preparation step.

## Automated validation

The repository's shared `scripts/release_gate.py` is the authoritative automated gate. It checks release documentation, static safety, Ruff errors/undefined names, formatting, gradual mypy coverage, Python compilation, JavaScript syntax, the maintained pytest suites with a 54% whole-application coverage floor, and locked dependency vulnerability auditing.

The 9.3.1 candidate also adds the new recovery, Support Center, and Data Inspector modules to the release formatting gate.

**Current result in this document:** pending Windows GitHub quality workflow. This report must not claim a pass count or coverage percentage until that workflow completes successfully.

## Manual validation still required

Automated tests cannot replace installed Windows acceptance. Before Stable promotion, verify:

- real project switching and clean/interrupted recovery behavior;
- Support Center sync/report/diagnostic export on the deployed tracker endpoint;
- representative CSV/TXT/JXL and binary JOB inspection;
- Inspector handoff into TopoSync, ControlSync and Point Ranges;
- real field-verified rod-height positive and negative datasets;
- TopoSync profile/history/review/calibration behavior in Windows WebView;
- existing ControlSync and FieldBookSync production workflows;
- updater confirmation, close/install/reopen behavior;
- native launcher and Inno installer output/hash.

Authenticode signing and signed update manifests remain unconfigured. Rod-height recommendations remain advisory and original source elevations are never silently modified.
