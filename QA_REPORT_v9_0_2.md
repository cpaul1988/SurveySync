# SurveySync v9.0.2 QA Report

This report covers the evidence-first FieldBookSync source candidate including reviewed PointID reassignment.

## Automated release-gate checks

- Python source compilation: **PASS** (`python -m compileall -q surveysync fieldbook_sync`)
- Maintained SurveySync pytest suite: **55 passed, 0 failed**
- SurveySync JavaScript syntax check: **PASS** (`node --check surveysync/static/app.js`)
- FieldBookSync JavaScript syntax check: **PASS** (`node --check fieldbook_sync/static/app.js`)
- Windows launcher x64 cross-build: **PASS**
- Windows updater x64 cross-build: **PASS**

## Evidence-first checks

- Utility, level-loop, and control page-type classification
- Provider-independent OCR text flattening
- High-quality independent evidence scoring and AUTO_ACCEPT routing
- Model-disagreement downgrade to review
- AI-only evidence remains manual review without exact independent OCR
- Automatic plan uses Windows AI + PaddleOCR-VL + Qwen3-VL when all are locally ready

## PointID correction checks

- Reviewer can reassign a result to another imported Survey PointID
- Target retains its authoritative survey coordinates/code/category
- Original `point_id_raw` OCR evidence is preserved
- Reviewed evidence association changes to the corrected PointID
- Source point is reset without deleting its survey identity
- Reassignment creates one multi-record audit event
- Undo restores both source and target atomically
- Redo reapplies both records atomically
- Reassignment is blocked when the target already contains evidence or reviewed edits
- Review UI contains the imported-PointID selector and explicit reassignment confirmation

## Historical test note

The archived `legacy_tests/` directory contains tests that intentionally assert standalone FieldBook Sync v8 filenames, version strings, updater URLs, installer files, and retired root-level Paddle bridge files. Running that entire historical directory against SurveySync v9 therefore produces expected collection/assertion failures and is not used as the v9 release gate. The maintained `tests/` suite is the active SurveySync regression gate.

## Platform limitation

This Linux build environment cannot execute Windows App SDK TextRecognizer, Foundry Local, or the final Inno Setup installer. Those Windows runtime paths must still be smoke-tested on the Windows 11 target before Stable publication.


## Paddle bridge packaging hotfix validation

A real Windows test exposed `OCR-001` because `paddle_bridge.py` was omitted from the v9.0.2 source/install payload even though `fieldbook_sync/ocr_local.py` still requires it. The bridge has been restored and packaging/readiness regression coverage was added.

- Maintained combined suite: **138 passed, 0 failed**
- Targeted historical Paddle bridge contract tests: **4 passed, 0 failed**
- Python compileall: passed
- SurveySync shell JavaScript syntax: passed
- FieldBookSync JavaScript syntax: passed
- Packaged bridge SHA-256: `a4ebf05e56f05d9bf1654c16cb1624d23a06a69bf665b4813b3e4de682bea03d`

Automatic mode now treats Paddle as unavailable if either the isolated Paddle environment or the packaged bridge is missing, allowing another ready local engine to be selected instead of starting an analysis that must fail.

## Crew point-range finder validation

A real workflow example established the intended behavior: review all occupied PointIDs and return practical crew-allocation blocks rather than every tiny numerical hole.

- Canonical recommendation engine: passed
- Clean next-thousand open-ended recommendation: passed
- Internal ranges ranked by capacity: passed
- Existing PointIDs excluded from every recommendation: passed
- Sub-100-point gap omission/reporting: passed
- FieldBookSync table/CSV output: syntax and regression checks passed
- ReportSync table/CSV output: syntax and regression checks passed
- Screenshot-shaped synthetic fixture produced: `12000 and above`, `4435 - 4999` (565), `10665 - 10999` (335), `6091 - 6214` (124)
- Maintained + selected historical regression gate after this change: **139 passed, 0 failed**
