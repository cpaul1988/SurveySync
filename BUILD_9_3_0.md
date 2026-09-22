# Build SurveySync 9.3.0 on Windows

This is a source candidate, not an already compiled installer. Extract to a new folder. Keep the previous working release available for rollback. Your user projects remain separate from this source folder.

Prerequisites: Python 3.12 x64, Node.js 24, Go, and Inno Setup 6. Run these commands from the extracted source folder in Command Prompt:

```
py -3.12 -m venv .build-venv
call .build-venv\Scripts\activate.bat
python -m pip install --require-hashes -r requirements-dev.lock
Compile_SurveySync_v9.3.0.cmd
```

The shared gate runs before compilation. Dependencies need network access for initial installation and the vulnerability audit. A failed check stops the build. Do not use SkipTests or SkipLauncherBuild; release builds reject those bypasses.

Output: `installer\output\SurveySync_Setup_9.3.0.exe`, plus its SHA-256 file. Go rebuilds both native launchers from the current source; the source ZIP deliberately contains no stale prebuilt launcher. Inno Setup includes the runtime locks and provisions dependencies with hash verification.

Before publication, install the candidate on a test Windows workstation and verify:

1. Existing project open/save, project switching and restored settings.
2. Header/headerless CSV mapping and your Green Line JXL import.
3. Control averaging, best-three QC, misnumber review and exports against accepted results.
4. FieldBookSync analysis, stale-result rejection, pause/resume and feedback.
5. TopoSync → Rod Height Bust QC: load the synthetic example and then real field-verified bust/no-bust files. Verify code-list review, units, exact point ranges, signs, exclusions and new-copy exports in Windows WebView. See docs/TOPO_ROD_HEIGHT_QC.md. Confirm the supplied logo on the app, installer and shortcuts.
6. Updater consent, close/install/reopen behavior and version display.

The corrected GitHub release workflow is included but has not been pushed or run. Code signing and signed manifests are not configured. Do not promote this candidate to Stable on automated test results alone.
