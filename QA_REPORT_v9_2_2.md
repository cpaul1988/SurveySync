# SurveySync v9.2.2 BetaCandidate QA Report

## Regression target

This hotfix reproduces the live v9.2.1 failure in which an older deployed Intake Web App returns `Unsupported FieldBook Sync feedback payload.` when given the newer SurveySync feedback envelope. The new compatibility test models that gate and requires the desktop client to use the one feedback envelope accepted by both endpoint generations.

## Required release checks

- Documentation gate.
- Python compileall for `surveysync`, `fieldbook_sync`, and `tracker_endpoint`.
- Full maintained SurveySync + FieldBookSync regression suite.
- JavaScript syntax checks for both shells.
- Verify feedback regression payload uses `application: "FieldBook Sync"` and does not require the newer route fields.
- Windows build and installed-client retry of the currently pending local report before Stable promotion.

## Production validation

After installing 9.2.2, open Feedback Log and press **Retry Intake Sync** on the pending report. Expected result: the badge changes to `SYNCED` and a new FBR ID appears in the shared Intake sheet.
