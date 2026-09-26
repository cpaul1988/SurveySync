# SurveySync 9.3.2 Beta Build and Acceptance

## Candidate branch

Build Beta from:

`v9.3.2-open-source-integration`

Do not publish Beta from `main`. Do not promote Stable from the development branch.

## Automated GitHub build

Use **Actions → SurveySync Release → Run workflow**.

Choose the branch:

`v9.3.2-open-source-integration`

Inputs:

- **version:** `9.3.2`
- **action:** `publish_beta`

The workflow will:

1. verify `VERSION.txt` and `RELEASE_NOTES_v9_3_2.md`
2. install locked build/test dependencies
3. install Inno Setup
4. run `Build_SurveySync.ps1`
5. run the complete release quality gate
6. rebuild `SurveySync.exe` and `SurveySyncUpdater.exe`
7. verify native launchers
8. compile `SurveySync_Setup_9.3.2.exe`
9. create a SHA-256 sidecar
10. create GitHub prerelease tag `v9.3.2-beta`
11. publish the installer + SHA-256 + release notes
12. update the Beta channel in `update.json` on this branch

## Local Windows build

From the source root:

`Compile_SurveySync_v9.3.2.cmd`

or:

`powershell -ExecutionPolicy Bypass -File .\Build_SurveySync.ps1`

Required:

- Python 3.12
- Node.js
- Go
- Inno Setup 6

No test/build bypass flags are accepted for release builds.

## Installed Beta acceptance

After GitHub publishes the Beta:

1. Install `SurveySync_Setup_9.3.2.exe`.
2. Confirm SurveySync opens and displays 9.3.2.
3. Reopen an existing 9.3.1 project and verify DB migration/project health.
4. Run ControlSync best-three on a known project.
5. Run Network Adjustment on a known reference network.
6. Run Ron three-wire leveling on known data.
7. Run the weighted benchmark-network example.
8. In COGOSync:
   - build tangent → right curve → tangent
   - evaluate a station
   - stake a LEFT-positive offset
   - inverse the stake coordinate back to the same station/offset
9. Import a representative LandXML with points/alignment.
10. Export that alignment to a new LandXML and re-import it.
11. Run a vertical curve reference.
12. Run cross-section cut/fill and average-end-area earthwork.
13. Open Survey Data Inspector and test representative CSV and Trimble JOB/JXL.
14. Run TopoSync rod-height QC and confirm no automatic source edits occur.
15. Run Project Health and verify audit-chain PASS.
16. Build a deliverable ZIP and inspect audit-chain metadata.
17. Test Feedback Wizard and Support Center.
18. Test **Check & Update** behavior from an older installed SurveySync when practical.

Record any failures through the Feedback Wizard before Stable promotion.

## Stable promotion

Only after installed Beta acceptance:

1. merge PR #2 into `main`
2. run **SurveySync Release** from `main`
3. version: `9.3.2`
4. action: `promote_stable`

Stable promotion downloads the already-tested `v9.3.2-beta` installer and publishes that exact artifact/hash to the Stable channel. It does not rebuild a different installer.
