# SurveySync 9.4.0 Beta Build and Installed Acceptance

## Candidate branch

Build the first 9.4.0 Beta from:

`v9.4.0-release-candidate`

Do not publish Beta from `main`. Do not promote Stable from the candidate branch.

## Required pre-build state

The 9.4.0 build manifest records the required live tracker check:

- Feedback Intake latest: **FBR-0016 — Rod Height Bust Tool**
- newer Intake items: **none**
- SurveySync Error Log Tracker: **0 total / 0 open**
- Retry Queue: **0**

If any newer feedback/error appears before a later numbered Beta, repeat the tracker check and update `BUILD_MANIFEST.json` / `QA_REPORT_v9_4_0.md`.

## Automated GitHub Beta build

1. Confirm the versioned candidate quality workflow is green.
2. Create a tag at the **exact tested candidate SHA**:
   - first candidate: `v9.4.0-beta`
   - later candidates: `v9.4.0-beta.2`, `v9.4.0-beta.3`, etc.
3. Open **Actions → SurveySync Release → Run workflow**.
4. Choose branch `v9.4.0-release-candidate`.
5. Inputs:
   - **version:** `9.4.0`
   - **action:** `publish_beta`
   - **beta_suffix:** the exact suffix used by the tag, e.g. `beta`

The workflow verifies the tag points to the workflow SHA, then:

1. validates VERSION.txt and 9.4 release documentation
2. installs locked build/test dependencies
3. creates a clean production venv from requirements.lock
4. verifies SurveySync production startup imports
5. installs Inno Setup
6. runs the complete shared quality gate
7. rebuilds SurveySync.exe and SurveySyncUpdater.exe
8. verifies native launcher integrity
9. compiles `SurveySync_Setup_9.4.0.exe`
10. writes `SurveySync_Setup_9.4.0.exe.sha256`
11. publishes the GitHub prerelease
12. updates the Beta channel manifest

## Local Windows build

From the source root:

`Compile_SurveySync_v9.4.0.cmd`

or:

`powershell -ExecutionPolicy Bypass -File .\Build_SurveySync.ps1`

Required:

- Python 3.12
- Node.js
- Go
- Inno Setup 6

No test/build bypass flags are accepted for release builds.

## Installed 9.4.0 Beta acceptance

After GitHub publishes the Beta, install the exact published installer and verify:

1. Setup completes runtime provisioning without error and SurveySync opens.
2. Title/About/update surfaces show **9.4.0**.
3. Create/open/switch projects and test interrupted-session recovery.
4. Test Support Center, Feedback Wizard, Error Log, and Check & Update.
5. Run Survey Data Inspector on representative CSV/TXT and Trimble JXL/.job where the Trimble converter is installed.
6. Run Ronald ControlSync best-three on known data.
7. Run conventional Network Adjustment and confirm independent validation status.
8. Run Ron three-wire leveling and weighted benchmark-network leveling.
9. Exercise COGOSync alignment/station-offset/LandXML/vertical curve/earthwork tools.
10. Run TopoSync rod-height review and confirm original source is unchanged.
11. Import a representative LAS and verify point-cloud metadata/source provenance.
12. Create a YAML workflow and verify a high-impact action stops at `WAITING_APPROVAL`.
13. Run project CRS diagnostics, including a unit mismatch or area-of-use review case.
14. Register/render a representative company/client Excel template and verify the original workbook remains unchanged.
15. If QGIS is installed, run one harmless QGIS Processing smoke test.
16. If GRASS is installed, run one harmless GRASS module smoke test.
17. Run Project Health and verify audit-chain PASS.
18. Build a deliverable package and inspect audit metadata.
19. Run a FieldBookSync smoke regression.

If QGIS, GRASS, laspy, PDAL, or Trimble conversion components are not installed, their status should report unavailable cleanly without blocking SurveySync startup.

Record any failure before Stable promotion. Fixes require a **new numbered Beta tag/artifact**.

## Stable promotion

Only after the exact Beta installer passes installed acceptance:

1. merge the tested release-candidate source to `main`;
2. run **SurveySync Release** from `main`;
3. version: `9.4.0`;
4. action: `promote_stable`;
5. beta_suffix: the exact tested Beta suffix.

Stable promotion downloads the tested Beta installer and verifies its integrity. It does not rebuild a different installer.
