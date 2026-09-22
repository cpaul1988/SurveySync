# SurveySync v9.1.3 Release Notes

## Field-book profile workflow completion (FBR-0010)

SurveySync 9.1.3 connects the v9.1.2 Field Note Profile Trainer directly to normal field-book import. After a field book is imported, FieldBookSync now exposes a **Field Note Profile** panel on the project dashboard. The operator can leave the book on **Auto-detect per page**, assign any installed profile to that specific field book, preview representative pages, or open **Train this field book** without re-importing the PDF.

For projects with more than one imported field book, the dashboard profile control is book-specific. The selected profile, profile version, selection mode, training-page IDs, and assignment reason are saved with the project. Page-level overrides remain independent, so one PDF can still contain mixed note formats.

## Training from the imported book

**Preview first pages** shows up to five representative pages from the selected book. When page classification is already available, cover/index/blank pages are deprioritized; before classification, source order is preserved. **Train this field book** opens the existing trainer already filtered to that book and shows a quick strip of representative pages.

Saving a labeled training example from this workflow marks the chosen profile as trained for that field book and keeps the normal `.fnp` sharing/export system. Training remains profile/example learning; SurveySync does not claim that PaddleOCR or Qwen model weights are retrained in-app.

## Profile precedence and mixed-format safety

Field-note profile precedence is now explicit:

1. page-specific profile override;
2. field-book default profile;
3. project/global Field Note Profile setting;
4. Auto detection / generic fallback.

Changing a field-book default does not erase an existing page-specific override. Raw OCR/vision evidence remains preserved and profile rules remain advisory to the deterministic QA/QC layer.

## Release engineering and documentation

The release process now treats developer documentation as a release gate. SurveySync ships architecture, feature matrix, data-flow, FieldBookSync, project-system, API, decision, known-issues, test-coverage, and release-history documents plus `IMPLEMENTATION_INDEX.json`. `scripts/validate_release_docs.py` verifies the current version and required documentation before the Windows build proceeds.

The Windows build helper retains the v9.1.2 fixes for `httpx2`, portable Trimble converter tests, and per-user Inno Setup discovery. The GitHub release workflow now references the v9.1.3 release notes.

## Feedback incorporated

- **FBR-0010** — Field Note Trainer: profile selection and training are now available directly after field-book import, with representative-page preview and book-specific persistence.
- FBR-0002 / FBR-0006 / FBR-0009 Point Range behavior remains preserved.
- FBR-0003 Ron control final/reshoot deliverables remain preserved.

## Beta validation targets

Before Stable promotion, test a real BRT field book and at least one non-BRT field book on Windows. Verify the dashboard profile selector, first-page preview, Train This Field Book handoff, saved training example, mixed page override, project close/reopen persistence, `.fnp` export/import, and full re-analysis using the assigned profile. Also smoke-test Point Range, direct Trimble JOB intake, Ron control outputs, feedback submission, and the one-button updater.
