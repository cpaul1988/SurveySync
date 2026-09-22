# SurveySync v9.0.1 Release Notes

## Application-wide themes and appearance

- Theme profile now follows the user across every SurveySync module, including FieldBookSync.
- Added shared **System / Light / Dark** appearance modes. System tracks the Windows appearance preference and updates live.
- Added a persistent appearance switcher to the main SurveySync menubar plus direct View/Options commands.
- Added global Theme, Accent, and Appearance controls to SurveySync Settings.
- FieldBookSync now reads and writes the same SurveySync theme preferences while retaining backwards compatibility with its v8 preference keys.
- Replaced the temporary `S` orbit mark at the top-left of the SurveySync shell with the navy/gold SurveySync globe mark.


## Automatic free local AI on Windows

- Added **Automatic — Free Local AI** as the default AI provider for SurveySync and FieldBookSync.
- Automatic mode probes the workstation and prefers the **PaddleOCR-VL + Qwen3-VL** document pipeline when ready.
- Windows AI OCR + Microsoft Foundry Local remain free on-device fallbacks when the document-specialized stack is unavailable.
- Lower-memory systems can use smaller hardware-selected Qwen3-VL variants while stronger GPUs can use larger variants for accuracy.
- Automatic mode **never silently switches to Gemini, OpenAI, or another paid/cloud provider**.
- Added shared **AI & OCR** status/settings in the main SurveySync Settings page and the FieldBookSync Engine page. The UI shows which local provider Automatic actually selected.
- Windows AI components and Foundry Local models are **not downloaded silently**. The user must explicitly approve **Enable Windows AI OCR** or **Enable Foundry Local Vision** when a supported component needs a one-time download.
- Added optional Windows installer packages for PyWinRT Windows AI bindings and `foundry-local-sdk-winml`. Failure to install these optional integrations does not block SurveySync installation; the existing local engines remain available.
- Added the same Automatic provider resolution to queued/batch FieldBookSync work so setting Automatic cannot produce an unsupported batch-provider error.
- Preserved the review-first PointID safety rule: Microsoft/Windows vision can interpret only a crop tied to an **independent exact OCR PointID hit**; it cannot invent or substitute the authoritative survey PointID.
- Kept **Gemini, OpenAI, and Anthropic Claude** as explicitly selectable cloud backup providers. Automatic never selects a cloud provider; cloud processing requires the user to choose it and enter a session API key.
- Added Anthropic Claude vision support using the same exact-target PointID gate as the other cloud providers. OpenAI and Anthropic model names remain editable so the user can move to another supported model without a SurveySync rebuild.

## Compatibility

- FieldBookSync processing engine remains v8.1.22-compatible.
- Existing SurveySync projects and FieldBookSync migration data are unchanged.
- Existing FieldBookSync theme preferences are migrated automatically when no SurveySync-wide preference exists.
- This is a normal update from SurveySync 9.0.0 and should be published as **9.0.1**, not by replacing the already released 9.0.0 installer.

## Ron field-test fixes folded into 9.0.1

- Feedback is now explicitly **local-first and retry-safe**. A temporary HTTP 500 from the shared Google Apps Script Intake endpoint no longer implies the report was lost: the report stays in the local append-only log, background sync retries automatically, and a failed remote sync remains `PENDING` for later retry.
- Feedback errors now preserve the HTTP status/body summary in the local report so support can diagnose the remote endpoint without losing the submission.
- Added a second-stage HTTP 500/413/429/502/503/504 recovery path for feedback reports with attachments: SurveySync retries the tracker submission once as metadata-only, while keeping the original screenshots/diagnostics safely in the local feedback log. This avoids losing the report when the Google Apps Script/Drive attachment path is the failing part.
- Added a **Manual Field Book Entry** wizard on the Review screen. Reviewers can choose an authoritative survey PointID, set primary/dip status, add notes and pipe/dip measurements, and save the record as an audited manual edit.
- Tightened the Hybrid Local PointID safety gate. **AI-only full-book matches and near-match routing are now review suggestions, not authoritative found PointIDs.** Only exact OCR-confirmed PointIDs can create automatic matched evidence in the default hybrid workflow.
- Updated Review wording to make the product explicitly review-first: automated extraction assists the reviewer; it does not silently invent a PointID.

## Planned follow-up from the same field test

- Level-loop book extraction will be added as a dedicated review/data-entry workflow. A representative real level-loop field book is needed to tune the parser and arithmetic/QC rules against the way the crews actually record BS/FS/HI/elevations before enabling automatic entry.

## Shell, branding, startup, and feedback consistency
- Retired the legacy FieldBookSync 8.1.22 startup splash. SurveySync Home now owns the application-wide What's New experience.
- Added an always-visible What's New card on SurveySync Home and an in-shell first-launch release-notes dialog after an update.
- Replaced remaining FieldBookSync/installer legacy icon surfaces with the SurveySync globe mark.
- Standardized the global ribbon in FieldBookSync to the same File / Home / Edit / View / Data / Tools / Options / Help structure and module-tab styling used by the rest of SurveySync.
- Restored the full Feedback Wizard from the main SurveySync shell. It can be opened without a project; local-first reporting remains available before project creation.

## Installer branding and true global-theme hotfix

- Rebuilt the Inno Setup application icon from the SurveySync navy/gold globe artwork.
- Rebuilt both Inno Setup wizard images (`wizard_large.bmp` and `wizard_small.bmp`) so the installer no longer displays the legacy FieldBook Sync logo.
- Updated SurveySync and FieldBookSync favicons/classic app marks to the same SurveySync globe identity.
- Moved theme persistence to the shared SurveySync configuration endpoint and expanded the main shell to consume the full theme palette instead of only the FieldBookSync module.
- System / Light / Dark, product theme, and accent now survive module navigation and application restart across the entire SurveySync shell.

- FieldBookSync now uses the same full-width SurveySync environment strip, application menubar, and module ribbon as every other module; its left workflow sidebar starts below the global ribbon.


### Adaptive Local AI
- Automatic local AI now prefers **PaddleOCR-VL 1.6 + Qwen3-VL** when both are ready.
- PaddleOCR-VL remains the independent PointID/document evidence gate; Qwen3-VL is used only on localized crops for interpretation.
- Qwen model size remains hardware-aware (2B / 4B / 8B) so low-memory PCs favor speed while capable GPUs can favor accuracy.
- Windows AI OCR + Foundry Local remain free, on-device fallbacks when the document-specialized stack is unavailable.
- Automatic still never switches to Gemini, OpenAI, or Anthropic without explicit user selection.

## Unified updater + code-review fixes

- Replaced the two-step Check / Stage workflow with one **Check & Update** button across the main SurveySync shell and FieldBookSync.
- FieldBookSync no longer checks or configures the old `cpaul1988/FieldBookSync` update channel. All module update actions use the SurveySync manifest, channel, staging directory, pending handoff, and native updater helper.
- Kept legacy `/api/update/*` routes only as safe compatibility proxies to the SurveySync updater so old UI calls cannot write a handoff into the wrong `%LOCALAPPDATA%` tree.
- Normalized version comparison (`9.1 == 9.1.0`) and fixed cleanup of oversized partial installer downloads.
- Replaced ReportSync's integer-by-integer point-range scan with the shared gap-walk algorithm used by FieldBookSync, preventing huge-range hangs and producing a clear error when empty input lacks explicit bounds.
- Made control/survey header alias precedence deterministic and added `Height` as an elevation alias.
- Replaced stale `FieldBook Sync v8.0.0` export provenance with the current SurveySync/FieldBookSync engine versions.
