# SurveySync 9.4.9-beta.1 — survey calculation and review safeguards

Populated ControlSync and level-loop rows without a PointID now stop import with a source row number. Level files are parsed before source registration, so a rejected file does not create an orphan source record.

Control network adjustment refuses to return coordinates when its iteration limit is reached without convergence. Robust level-network adjustment also refuses a nonconverged result and solves the final reported weights. Both network tools cap runs at 100 points and 1,000 observations. Their redundancy diagnostics use observation-wise calculations instead of square observation matrices to reduce memory use. These limits protect interactive work; larger networks need a dedicated sparse/batch solver.

Reviewed level recheck state is now held in project SQLite metadata. Existing 9.4.8 JSON requests are imported once, preserving the original file. Approval, active sight overlays, revision creation and review status commit in one database transaction. Ordinary level solve/activate routes share the recheck project lock. Truncated crew returns now receive a row-specific validation error.

This is an unpublished beta candidate based on 9.4.8 Stable. The original three-wire observations remain unchanged. Representative field-book and installed Windows acceptance are still required before publication or promotion.
