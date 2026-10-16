# SurveySync 9.5.3-beta.1 QA report

## Scope and baseline

FBR-0018: inconsistent FieldBook navigation/theme, full-page module transitions, and the same active `test` project displayed as `Untitled Project`. Based on main commit 87ae4f2ea70d6d6efe2b87cbaa8ffae7e498db0b, retaining the October 12 dependency-security maintenance.

## Observed locally

The maintained pytest suite passed with **733 passed and 1 skipped**, including **15 new focused integration cases**. Tests include actual canonical name/ID/root, state isolation across two projects and reopen, idempotent same-project selection, failed constructor recovery, active-worker switch refusal, stale API/export tokens, foreign-state/recovery rejection, explicit snapshot import, no-project feedback reads, and original-root feedback retry updates.

Existing standalone fixture setup was corrected to isolate both the shared project and FieldBook runtime; the guard was not disabled. An old assertion permitting an independent module project name now verifies canonical name plus retained legacy-title provenance. The old full-page feedback-navigation assertion now verifies the shared-shell action.

Python syntax and the unchanged static-quality gate passed during implementation. Browser execution in the local authoring container was blocked by Chromium's loopback navigation policy (`ERR_BLOCKED_BY_ADMINISTRATOR`); this is not reported as an application test pass.

## Observed Windows CI evidence — October 16, 2026

These results apply to application source at head **cedfdb7a415f7c054e8d0bffbb10582ecec8b7e3**, tested with main through merge commit **0f12c583b5efc4bc146461b8b7db711e73e13555**. The final follow-up changes only this QA record and candidate artifact staging; application code is unchanged.

- **Quality run 38940649766: success.** Clean production startup, release identity/documentation/static gates, Ruff, configured Mypy targets, JavaScript syntax, and locked dependency audit passed. Windows regression result: **728 passed, 6 skipped, 1 deprecation warning**, coverage **64.93%** above the unchanged 54% gate. New project binding and session modules measured 94% and 98% coverage respectively.
- **UI Validation run 38940649729: success.** Real Windows Chromium module screens, light/dark profiles and branding tests passed, as did `scripts/fbr0018_browser_smoke.py`. Its seven assertions groups verified no-project feedback, canonical project name/ID/storage, ten persistent module transitions, four theme combinations, native bridge delegation, cancelled/accepted project changes with stale-download rejection, reload and legacy feedback deep links. There were no uncaught page errors. Native bridge delegation in this specific browser test uses a stub; it is not a claim of an installed native file-picker pass.
- **Remaining Audit Acceptance run 38940649757: success.** Existing desktop/workflow and external GIS acceptance remained green.
- **Windows installer compiled successfully** after the full gate in UI Validation, as an unpublished candidate artifact. File: `SurveySync_Setup_9.5.3-beta.1.exe`; bytes: **9,105,830**; SHA-256: **f3f907414e6e8ab8d08ca61050c3e6a1cc511401879dbc214a1ad21623012280**. The downloaded file matched its companion checksum. Screenshots and JSON results were downloaded and inspected.

Evidence: https://github.com/cpaul1988/SurveySync/pull/24 and its Actions checks. Browser evidence artifact `surveysync-ui-evidence` (12062839177); candidate artifact `SurveySync_Candidate_UI_Installer` (12064030154).

## Remaining release acceptance

**Installed Windows, repeated lifecycle, and released-version replacement acceptance are pending at the time of this record.** The Repair Acceptance run and any follow-up run must be checked before promotion. A compiled installer and browser success are not substituted for those installation tests. CI artifacts/logs remain the authority for later outcomes.

Candidate artifact staging now resolves release/version filenames dynamically, requires every expected file, and compares the final installer both to its sidecar checksum and the hash recorded before installed acceptance. This removes the inherited hard-coded 9.5.2 artifact paths without changing or bypassing acceptance gates. Long installed-test runs retain their evidence rather than being cancelled by a subsequent CI/documentation commit.

No automatic update channel, published release, main branch, or user's project data is changed by this candidate. Test a copy of a project before adopting a prerelease for field work.
