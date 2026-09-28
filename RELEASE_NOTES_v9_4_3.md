# SurveySync 9.4.3-beta.1 — Visual Survey QA

Candidate based on Stable 9.4.2. Home and QASync now provide a linked local survey plan, point table and issue list. Select records or findings to inspect source identity and supporting evidence. Filter duplicate IDs, missing coordinates/elevations, mixed coordinate contexts, configurable elevation jumps and exact-source saved rod-height candidates.

Review decisions and independent reasons are saved to the project audit trail. Explicitly previewed, approved elevation offsets produce a separate corrected CSV/JSON evidence ZIP; original observations, canonical project points and historical reports stay unchanged. Desktop exports save a uniquely named ZIP under Exports/VisualQA and reveal its folder; browser use downloads the ZIP. Stale evidence/project requests are rejected.

The local plan does not transform coordinates. Jump screening compares consecutive same-description records within each source, not nearest neighbors or confirmed acquisition order. The workspace supports up to 20,000 points and checks up to 50 recent rod analyses. Heuristic findings require independent survey review.

See docs/VISUAL_SURVEY_QA.md for workflow, units, evidence rules, limits and API behavior. Field-book hardware/accuracy validation, official Trimble conversion, rod-score calibration and production signing limitations from 9.4.2 remain. This candidate is not a Stable promotion; completed CI results and exact installer acceptance must be recorded before distribution.
