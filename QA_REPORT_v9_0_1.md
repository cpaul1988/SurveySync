# SurveySync v9.0.1 QA Report

## Result

**125 passed, 0 failed** in the maintained SurveySync + preserved FieldBookSync regression set after the installer-branding and shared-theme corrections.

Command:

```text
PYTHONPATH=. pytest -q tests legacy_tests/test_core.py legacy_tests/test_v8117_dip_book_statuses.py legacy_tests/test_v6_features.py legacy_tests/test_v8118_feedback_wizard.py
```

Additional checks:

- `python -m compileall -q surveysync fieldbook_sync` passed.
- `node --check surveysync/static/app.js` passed.
- `node --check fieldbook_sync/static/app.js` passed.
- API smoke test confirmed `/api/v9/release-notes` returns v9.0.1 release notes.
- API smoke test confirmed `/api/v9/feedback` saves locally with **no SurveySync project open**.
- FieldBookSync route returns the unified SurveySync ribbon/module navigation.
- FieldBookSync global menubar and module tabs now span the full application width, with the FieldBookSync workflow sidebar beginning below the shared ribbon, matching Home and every other module.
- FieldBookSync legacy startup splash is inert/hidden; SurveySync Home owns the visible What's New experience.
- Installer and FieldBookSync application icon assets now use the navy/gold SurveySync globe mark.
- System / Light / Dark and application-wide theme preferences remain shared across modules.

- Inno Setup now references `branding/SurveySync.ico` and the regenerated `wizard_large.bmp` / `wizard_small.bmp`; all three show the SurveySync globe artwork rather than the legacy FieldBook mark.
- The main SurveySync shell now consumes the same full theme surface tokens as FieldBookSync, including background, panels, sidebar, inputs, hover states, text, lines, accents, and System/Light/Dark appearance.
- Theme/appearance changes persist through `/api/v9/config/ui`, so navigating between FieldBookSync and any other module retains the same application-wide theme.
- Manual Field Book Entry uses the audited result-edit path and marks reviewer changes as `EDITED`.
- Feedback remains local-first; remote HTTP/network failures stay `PENDING` rather than deleting or losing the report.
- Feedback attachment submission retains the metadata-only recovery path after HTTP 500/413/429/502/503/504 while original support files remain local.
- Gemini, OpenAI, and Anthropic Claude remain selectable explicit cloud backups; Automatic remains local-only.
- Hybrid Local full-book AI fallback does not create authoritative PointID evidence without an independent exact OCR match.
- Automatic AI now prefers the document-specialized PaddleOCR-VL 1.6 + hardware-sized Qwen3-VL pipeline when both are ready; Windows AI + Foundry Local remain free local fallbacks.

## Historical-suite note

The complete archived `legacy_tests/` collection is not directly runnable from the v9 source package because several historical tests intentionally reference retired build-only files that are no longer shipped (for example `installer/FieldBookSync.iss`, `installer/setup_ui.ps1`, `paddle_bridge.py`, and the old bootstrapper sources). The selected preserved regression set above is the maintained compatibility suite for the v9 package.

## Windows runtime note

This build environment is Linux, so the actual Windows App SDK / PyWinRT and Foundry Local runtime calls cannot be executed here. The Windows AI path remains dependency-optional and fallback-safe and should be smoke-tested on the real Windows 11 target before publishing v9.0.1.

- One-button `/api/v9/update/check-and-install` path is covered by regression tests.
- FieldBookSync compatibility update source/check routes are verified to resolve to the SurveySync manifest rather than the retired FieldBookSync release channel.
- Version normalization, deterministic aliases, `Height` elevation detection, shared point-range gap logic, and current export provenance have direct regression coverage.
- A full raw `legacy_tests/` collection run is intentionally not claimed: archived tests that require retired v8 build-only files fail during collection because those files are no longer shipped. The maintained v9 compatibility selection above passed.
