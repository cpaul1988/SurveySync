# TopoSync rod-height range review — 9.3.0

Open **TopoSync → Rod Height Bust QC**. This standalone workflow accepts UTF-8 CSV/TXT/TSV/PNEZD/ASC exports and does not need a field-book PDF, AI engine or FieldBook profile. The original FieldBook isolated-point check remains available separately.

## Workflow

1. Load the file and inspect the preview. Set header handling and map PointID, Northing, Easting, Elevation and Code. IDs, including leading zeros, are strings. Duplicate IDs, non-finite coordinates and inconsistent rows fail visibly instead of being dropped.
2. Review the supplied default classifications or import CSV/TXT/TSV/XLSX with `code,description,role`. Role is optional; description-based suggestions are conservative and require review. Save classifications for the current project or standalone workspace. Import replaces the default list. Explicit entries override range fallbacks, including 604 and 607 within 600–639. Unknown codes remain unknown.
3. Confirm horizontal/elevation units and acquisition chronology. File order is the default; numeric PointID sorting is available but is not evidence of chronology. Every tolerance labeled ft is in international feet and is converted to the selected source units.
4. Analyze and inspect candidate ranges, exact affected IDs, offset, scatter, score components, neighboring unaffected points, chain boundaries and exclusion evidence. Changing analysis inputs invalidates displayed results.
5. Export a CSV summary or JSON evidence record. Select eligible ranges, enter the review reason and explicitly confirm the correction before exporting a separate copy. Desktop exports are new uniquely named files in the workspace's TopoSync/RodHeightQC/exports directory (opened in Explorer); browser exports download files. Exports never overwrite a source or project elevation.

## Detection and limits

Stable features are split into geometric chains by base code and explicit string ID, BS/ES markers, coincident XY observations and excessive horizontal gaps. PC/PT remain curve markers. BS does not mean a backsight and earns no setup score. Local least-squares elevation models use horizontal chainage and at least three unaffected points. A candidate must exceed the minimum offset; long projections and inconsistent offsets stop its evidence interval. Independently verified recovery uses unaffected context on both sides. Setup boundaries end a run but do not alone verify a correction endpoint.

Events correlate only when their starts are close in acquisition order, nearby in plan, and have matching offsets. Multiple observations of the same feature class do not count as multiple classes. The score is a heuristic **0–100 evidence score, not a calibrated probability**: up to 40 for distinct classes (8 each), 25 for constant offset, 15 for a nearby setup/control code, 10 for surface observations, and 10 for independent chains. Terrain penalties follow the submitted proposal. Nearby mapped walls/discontinuities, ditches, creeks and structures suppress correction regardless of score. Exclusions use plan distance, even when the object was observed at another time; this is intentionally conservative.

A recommendation requires score >80, constant offset, verified recovery, no unsupported surface observations inside the inferred interval, no unknown codes in it, and confirmed units/order/classifications. An uncertain end or interrupted setup is shown as REVIEW. Sparse data, curved grades, separate unmarked strings and missing codes can prevent detection. Real common grade changes can mimic rod errors; independent field evidence is still needed. Spot-object codes do not provide primary confidence. A range includes only explicitly listed source IDs between the observed boundaries; no missing integer IDs are invented. Exact start/end chronology between sparse feature observations cannot be inferred without field records.

`estimated_rod_bust = observed − expected`; `recommended_correction = −estimated_rod_bust`. A −1.83 ft shift therefore recommends +1.83 ft. Blocked candidates have a null recommendation. Original uploaded bytes (base64), SHA-256, mappings, rules, units/settings, evidence and review-export audits are retained in separate immutable JSON records. Corrected CSV includes OriginalElevation, AppliedCorrection and SourceRow. It is a normalized point export and does not round-trip unrelated extra source columns.

## Reproducible example

`examples/topo/rod_bust_demo.csv` is synthetic, in international feet. Select international feet for both units and confirm the review checkboxes. Expected result: points **36138–36157**, observed offset **−1.83 ft**, recommended correction **+1.83 ft**, score **85/100**, five supporting classes. It demonstrates behavior; it is not field acceptance data. `code_list_template.csv` contains editable defaults.

Validate against Ron's actual known bust, no-bust roads, walls/curbs, drainage crossings, multiple setups, mixed units and sparse/end-of-file runs before release. No measured detection sensitivity, false-positive rate or 92% probability is claimed.

## v9.3.1 reviewed-production workflow

Version 9.3.1 adds reusable QC profiles, run history, explicit per-candidate review decisions, and an advisory review-calibration summary. A reviewer may record `confirmed_bust`, `not_bust`, or `needs_review` with a reason. These decisions are stored as separate immutable review records; project-backed reviews also write the project audit trail.

Confirmed-review scatter can be summarized into a suggested consistency tolerance, but SurveySync never applies the suggestion automatically. The detector remains evidence-based/advisory and corrected-copy export still requires explicit confirmation. Original point files and stored source evidence are never rewritten by the review/calibration workflow.

