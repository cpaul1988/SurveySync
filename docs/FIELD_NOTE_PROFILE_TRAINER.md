# SurveySync Field Note Profile Trainer

SurveySync separates handwriting recognition from **field-note grammar**. OCR/vision finds visible evidence; a Field Note Profile describes how a particular client, crew, or job type organizes that evidence.

## Built-in profiles

- `BRT_STANDARD` — BRT utility/structure sketch: structure circle, north marker, structure PointID and one leader per pipe/connection.
- `GENERIC_SURVEY_NOTES` — conservative fallback when no named grammar matches confidently.

Built-in profile rules are locked. A built-in may receive local labeled examples, but duplicate it before changing its grammar.

## Normal v9.1.3 workflow

1. Import a field book normally.
2. The **Field Note Profile** panel appears in the Field Book step.
3. Choose the imported book when the project contains more than one.
4. Leave **Auto-detect per page**, choose an installed profile, or click **Preview first pages**.
5. Click **Train this field book** to open the Trainer already filtered to that book.
6. Create/duplicate/select the profile you want to teach.
7. Use the representative page strip or page selector, draw annotation boxes, and save examples.
8. Saving a training example from the book workflow assigns that profile to the book as `trained`.
9. Individual pages can still override the book profile for mixed-format PDFs.
10. Re-run analysis when you want existing results regenerated with the new profile knowledge.

## Precedence

The interpretation profile is resolved in this order:

`page-specific override > field-book default > global profile selection > Auto/generic fallback`.

The book default and page override are deliberately separate persisted values. Changing a book default therefore does not erase an exceptional page's format.

## What learning means

SurveySync stores labeled examples and derives structural grammar hints from annotation types, pipe associations, and coarse normalized layout. Those hints are used during later profile-aware interpretation. Previous project PointIDs, source names, and raw values are not inserted into reusable AI prompts.

This is not in-app PaddleOCR/Qwen weight fine-tuning. The labeled dataset can support separately validated model tuning later.

## Sharing

Use **Export .fnp** to package a profile plus its labeled examples. Import the `.fnp` in another project/workstation. Built-in IDs are protected from overwrite. Because `.fnp` bundles can contain page imagery, handle them as project/client data.


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.
