# SurveySync 9.5.2-beta.1 — CAD review decisions and revision comparison

Candidate based on 9.5.1 Stable; not published or promoted.

- Save Needs review, Confirmed finding, or Dismissed decisions with a required reviewer and reason. Decisions remain tied to the exact imported drawing snapshot. History is stored in the project audit chain; competing stale saves are rejected.
- Compare the open drawing (after) with an earlier retained import (before). Review changed top-level handle candidates, unmatched before/after entities and selected-change overlays. Decisions never transfer automatically.
- Export current finding decisions, full decision history and optional revision comparison in the existing printable HTML/CSV/JSON review ZIP. Original DXF hashes and closure evidence remain included.
- ControlSync uses the label **3-point workbook profile**.

Comparison operates on supported imported representations, not full native CAD semantics. Handles can be reused; block children are conservatively unmatched. Curves are sampled; text is an anchor; unsupported content is listed separately. Confirmed findings are not repairs. No snapping, forced closure, geometry edits or project-point edits are introduced. Reviewer names are self-entered, not authenticated signatures.

Both drawings must be reimported if the project coordinate context or overlay points change. Export rejects stale decision tokens or altered source evidence. Real-job DXF/point validation and Windows installer acceptance are required before Stable promotion.
