# SurveySync 9.5.3-beta.1 QA report

## Scope and baseline

FBR-0018: inconsistent FieldBook navigation/theme, full-page module transitions, and the same active `test` project displayed as `Untitled Project`. Based on main commit 87ae4f2ea70d6d6efe2b87cbaa8ffae7e498db0b, retaining the October 12 dependency-security maintenance.

## Observed locally

The maintained pytest suite passed with **733 passed and 1 skipped**, including **15 new focused integration cases**. Tests include actual canonical name/ID/root, state isolation across two projects and reopen, idempotent same-project selection, failed constructor recovery, active-worker switch refusal, stale API/export tokens, foreign-state/recovery rejection, explicit snapshot import, no-project feedback reads, and original-root feedback retry updates.

Existing standalone fixture setup was corrected to isolate both the shared project and FieldBook runtime; the guard was not disabled. An old assertion permitting an independent module project name now verifies canonical name plus retained legacy-title provenance. The old full-page feedback-navigation assertion now verifies the shared-shell action.

Python syntax and the unchanged static-quality gate passed during implementation. Browser execution in the local authoring container was blocked by Chromium's loopback navigation policy (`ERR_BLOCKED_BY_ADMINISTRATOR`); this is not reported as an application test pass.

## Required candidate acceptance

Run scripts/fbr0018_browser_smoke.py against the real local app server on the CI runner. It covers the no-project wizard, shared sidebar and underlying identity, persistent document/filter/file selection over ten module transitions, exact shared theme tokens, native bridge delegation, project-change cancellation, stale download rejection, reload and legacy deep links. No report is sent to the live Intake during automated acceptance.

Run the existing release gate and browser/theme suites, compile the numbered Windows installer, and complete installed Windows acceptance before promotion. CI artifacts/logs are the authority for those outcomes, not this pre-run document. No automatic update channel is changed by this candidate.
