# SurveySync v9.1.2 Release Notes

## Beta candidate — trainable field-note profiles

SurveySync 9.1.2 adds a user-trainable **Field Note Profile** system to FieldBookSync. The goal is to let different clients, crews and job types use different field-note layouts without hard-coding every new format into the application.

### Field Note Profile Trainer

- Added **FieldBookSync → Field Note Trainer**.
- Create custom profiles with a name, client/company, job type, description, detection cues, vocabulary, expected fields and extraction/association rules.
- The existing BRT structure-note grammar is now a locked built-in profile named **BRT_STANDARD** rather than being treated as the universal field-note format.
- Added a conservative built-in **GENERIC_SURVEY_NOTES** fallback for pages that do not confidently match a named format.
- **Auto-detect per page** is the default analysis mode. A reviewer can also select one active profile or override an individual page.
- One field book may therefore contain different page/profile types without forcing every page through the same grammar.

### Visual teaching from real field-book pages

- The trainer displays imported field-book pages and lets a reviewer draw normalized annotation boxes.
- Supported teaching labels include structure/manhole, structure PointID, north arrow, pipe/connection leader, dip/depth, diameter, material, written azimuth, destination PointID, structure note, pipe note and other evidence.
- Pipe-specific annotations can be assigned to a pipe number so the example preserves which notes belong to which connection.
- Saved examples retain the local page image, annotation geometry and profile association for QA/regression and future model-tuning workflows.

### Teach from review corrections

- The normal Structure Review window now includes **Teach this profile**.
- SurveySync saves the review correction first, then captures the linked field-book evidence and corrected result as a labeled training example.
- The example preserves available structure/PointID/leader evidence without overwriting original OCR/AI evidence or audit history.

### Learned grammar during analysis

Saved examples are not just an archive. SurveySync now derives bounded, privacy-preserving structural hints from a profile's labeled examples—annotation types, pipe associations and coarse normalized layout tendencies—and provides those hints to the profile-aware interpretation stage.

Raw PointIDs, source names, handwritten values and accepted-result contents from previous projects are deliberately excluded from this learned prompt summary. This prevents a reusable profile from leaking another project's values when a user explicitly selects an opt-in cloud vision provider.

The current implementation is **profile/example learning**, not neural-network weight training. SurveySync does not claim to fine-tune PaddleOCR or Qwen inside the app. A future model-training workflow can use the accumulated labeled examples after separate validation.

### Reusable `.fnp` profile bundles

- Custom and built-in profiles can be exported as `.fnp` bundles with their labeled examples.
- `.fnp` files can be imported on another project/workstation.
- Import is path-safe and size-bounded; imported copies of locked built-in profiles are assigned a non-destructive custom ID rather than replacing the built-in definition.

### BRT behavior preserved

The user-taught BRT grammar remains intact: structure circle, north orientation, structure PointID, individual leaders, leader-associated dip/diameter/material/azimuth/notes, visual leader direction and explicit `to PointID` topology. Survey coordinates and written/visual directions remain independent QC evidence, and disagreements still route to review rather than being silently corrected.

### Preserved v9.1.1 workflows

- FBR-0009 Point Range fix: Current Project Points plus Browse / Select Point File.
- Low-to-high / high-to-low / capacity point-range sorting and CSV/TXT/XLSX output.
- Direct Trimble Access `.job` selection through the supported Trimble conversion layer plus direct JXL/JobXML intake.
- Ronald's validated three-point control math with QC + FINAL/RESHOOT deliverables.
- Project Manager, native GUI launcher, evidence-first OCR/vision pipeline, local-first feedback, global themes and unified updater.

### Feedback gate

The shared Intake tracker was checked before this build and the raw Form Responses tab was also checked for unprocessed submissions. **FBR-0009 remained the newest Intake item; no FBR-0010 or later item and no unprocessed raw form response was present at build time.**

### Beta release gates

Before Stable promotion, run a real Windows v9.1.1 → v9.1.2 update, annotate/train at least one additional non-BRT field-note format, verify that a mixed-format book can use page-level overrides, rerun the supplied BRT field book, smoke-test installed PaddleOCR/Qwen, and exercise `.fnp` export/import on a second project or workstation.
