# ControlSync reshoot workflow

1. Load control observations and run the best-three Control QC with the intended tolerance, field metadata policy and coordinate context.
2. In **Control Reshoots**, choose a RESHOOT control, enter crew and field instructions, and download the request ZIP. It contains `Request.json` and a return CSV template with reserved PointIDs. Only one open request per control is allowed.
3. The crew can return the completed CSV or a supported Trimble source. Stage its file in the same project. Exactly one shot per reserved PointID must belong to the requested control; unrelated points in the file are ignored and listed for review. The source is retained immutably. Staging previews QC in a disposable database without importing the returned shots or changing active solutions.
4. Compare the stored before result with the previewed residuals, selected shots and field QC. Enter reviewer and reason; reject the return or approve it. Approval requires PASS with at least one returned shot in the chosen triplet and verifies unchanged project observations, grouping, coordinate context and source hash. A changed project requires a new request and review. Approval imports all three returned shots and reruns QC for this control only.
5. Download the approved ZIP for an accepted control CSV and `Review.json`. The deliverable is registered once with SHA-256 verification; source evidence and all request/review actions are audited in the project.

Existing ControlSync exports and Ron's three-wire leveling workbook remain separate workflows. Treat the QC preview as decision support and check source metadata and residuals before approving.
