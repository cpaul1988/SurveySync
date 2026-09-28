# Visual Survey QA — 9.4.3-beta.1

Open a project, import canonical survey points, then choose **Home or QASync → Visual Survey QA**. Refresh evidence after changing jump/gap thresholds or project data. Processing stays local; the canvas needs no tile server, remote library or cloud service.

The plan, searchable/paged point table and filtered issue list share record-UUID selection. Duplicate PointIDs remain separate records. Select an issue to highlight all participating records and inspect its explanation. Select an individual record to see its coordinates, units, revision, retained source filename and SHA-256. Load original source observations verifies the retained file hash and shows all matching exact-ID rows for delimited point files up to 30 MiB; duplicate source rows are not guessed into one-to-one matches. Selected correction source hashes are checked again before export. Missing/incompatible coordinates stay available in the table and evidence view. Drag to pan, scroll or use buttons to zoom, and Fit points to reset. The table provides keyboard-accessible equivalents to canvas selection.

## Findings and boundaries

- Duplicate PointIDs are grouped by exact stored text; leading zeros and case are preserved.
- Missing/nonfinite northing, easting or elevation is reported without guessing values.
- CRS/unit mismatches are explicit; incompatible horizontal contexts are not overlaid. No coordinate transformation is performed. An unset but consistent project CRS is displayed as a local coordinate view.
- Elevation-jump screening compares consecutive retained records with the same source and exact description. Both units and CRS must match the project. Absolute elevation change must meet the selected vertical threshold, and horizontal separation must be within the selected gap. Thresholds use the displayed project units. These are screening flags, not terrain models, nearest-neighbor results, proof of acquisition order or automatic rod-bust diagnoses.
- Up to 50 most recent saved project TopoSync analyses are inspected. Only PROBABLE candidates are linked, requiring an exact source hash, matching coordinate units, exact PointID and unchanged northing/easting/elevation. Suppressed candidates are not promoted to findings. The heuristic score is never labeled a statistical probability. No fresh rod analysis is run automatically; partial record matches are identified by their linked-record count.
- Maximum 20,000 canonical points; larger projects fail explicitly instead of silently sampling. The table pages by 100 records and issues by 50. All loaded, compatible points remain in the plan view.

## Review and correction workflow

Save **needs review**, **confirmed finding**, or **dismissed** with an independent reason. Decisions append to the hash-chained audit trail and do not suppress the original finding. The latest decision for the exact evidence snapshot is displayed. Any point/registered-source-metadata/context/settings/rod-run change invalidates the snapshot and makes previous decisions historical; this conservative rule may require re-reviewing otherwise unaffected findings.

For corrections, select an individual record and enter an explicit signed elevation offset in that record's vertical units. Add records to the preview, inspect before/after values and signs, enter the supporting reason and confirm the checkbox. **Approve & download corrected copy** returns a ZIP with all project records in CSV and exact JSON evidence (original selected records, offsets, corrected values, project/source identities and review reason). It does not apply corrections to canonical points, replace source files, change previous reports or silently approve other issues. No correction is inferred from a detector score. Text starting with potential spreadsheet-formula prefixes is escaped in CSV only; exact IDs/text remain available in JSON.

Server endpoints require the active project header, validate a fresh snapshot inside a serialized database transaction, reject unknown/duplicate correction UUIDs, missing elevations, nonfinite offsets, unrecognized vertical units, blank reasons and missing confirmation. Requests from stale project panels are rejected. UI responses from old navigation are ignored. The audit records copy generation, not proof that a browser saved the download.

## API

`GET /api/v9/visual-qa/snapshot?jump=2&distance=50` returns points, issues, sources, context and evidence token. `POST /review` and `POST /export` use the same prefix and require token, settings and reason. All endpoints require `X-SurveySync-Project`. Reviews additionally require issue ID/decision; exports require explicit confirmation and UUID/offset pairs.

## Verification

`tests/test_visual_qa.py` checks actual database/API safety and source preservation. `scripts/verify_visual_qa.py` exercises real browser controls, linked canvas/table/issue selection, review persistence, correction preview/download, dark/light layouts and stale-project rejection on synthetic projects. Release acceptance remains tied to the exact candidate source and installer; this document alone is not a passing release record.
