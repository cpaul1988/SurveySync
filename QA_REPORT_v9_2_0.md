# SurveySync v9.2.0 BetaCandidate QA Report

## Scope

This milestone adds active revision selection, comparison, and non-destructive restore for ControlSync control and level solutions, plus active-revision-aware ControlSync PDF reporting.

## Feedback review

Pre-build live tracker review completed on 2026-09-19:

- Latest Intake item: `FBR-0012`.
- No Intake item newer than FBR-0012 was present.
- `Form Responses 1` contained only the header row; no unprocessed legacy form submission was present.
- No `Error Log` worksheet existed at build start, indicating no shared diagnostic event had yet created that tab.

## Automated coverage

`tests/test_v920_control_revisions.py` verifies:

- newest control/level solve becomes active;
- historical solutions remain immutable;
- control and level revision comparison deltas;
- an older revision can be restored by active-pointer change only;
- a solution belonging to a different object cannot be activated;
- a ControlSync PDF uses the restored active control revision.

The full release gate also runs the existing SurveySync and selected legacy FieldBookSync regression suites so v9.1.4 reliability behavior and earlier workflows remain covered.

## Build-environment limits

The current container can run Python and JavaScript validation but does not compile the Inno Setup Windows installer. The included native SurveySync launcher retains Windows GUI subsystem metadata and its same-length embedded product-version literal is advanced to 9.2.0 for source-package consistency; a normal Windows build should rebuild both launchers from Go source before Stable promotion.

## Status

Final live tracker recheck completed at `2026-09-19T23:48:15Z`: no FBR-0013/newer Intake row, no legacy Form Responses submission, and no Error Log worksheet.

The dependency-complete source regression gate passed **194 tests with 0 failures**. Python `compileall`, both maintained JavaScript syntax checks, and the release-documentation gate also passed. Package hashes are recorded with the final source archive. Windows installer build, upgrade test, and installed-app smoke test remain Beta-to-Stable gates.
