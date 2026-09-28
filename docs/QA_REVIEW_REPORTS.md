# QA review reports

In Home or QASync, open Visual Survey QA and refresh the project evidence. Save finding decisions with an independent-check reason. To document elevation changes, explicitly approve and export a reviewed copy first. Unsaved correction previews are not reportable saved actions.

At the bottom of the workspace, enter a report title and optional prepared-by label, then choose **Export PDF + CSV review package**. The prepared-by label is user-entered and is not an authenticated signature. The report includes all current findings regardless of search, issue-type, or review-state filters. Saved decisions are read again during export.

## Package

- `QA_Review.pdf`: project, CRS and units, screening settings, summary counts, all findings and affected UUID records, decisions/reasons/timestamps, separate correction exports, registered source references, and interpretation notes.
- `findings.csv`: one row per finding and affected record. A point with multiple findings appears more than once. Duplicate PointIDs remain separate by UUID.
- `corrections.csv`: one row per record per previously generated correction export, with event ID, timestamp, reason, before elevation, signed offset, exported elevation, vertical units, and source ID. Separate exports are never added together.
- `review_evidence.json`: exact snapshot evidence and full source metadata. Missing numeric values remain null.
- `SHA256SUMS.txt`: integrity hashes for the other four files; these are not digital signatures.

Desktop exports save uniquely named ZIP files in the project's `Exports/VisualQA/Reports` folder and reveal the folder. Browser sessions download the ZIP. A failed audit write removes only the new output. Existing reports are never overwritten.

## Scope and boundaries

The project and point/settings snapshot must still match the open workspace. Only reviews and correction-export events matching that snapshot are included; older correction exports are counted as excluded. The report does not modify coordinates, original files, or prior reports. A confirmed finding is not an approved correction or professional certification.

Source hashes are the registered import hashes. Report generation does not reread or rehash source files and does not claim fresh source verification. Original observations can be checked separately using the workspace source preview. PDF text wraps and paginates; CSV formula-like text is apostrophe-prefixed, while JSON retains exact identifiers. CSV consumers should import PointID as text to preserve leading zeros.

Reports fail explicitly rather than silently truncate beyond 50,000 finding/record plus correction detail rows or 2,000 PDF pages. The workspace's existing 20,000-point cap remains. Full-project screening is advisory, and rod evidence scores remain heuristic rather than calibrated probabilities.
