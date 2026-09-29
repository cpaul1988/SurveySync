# SurveySync 9.4.8-beta.1 — reviewed level-loop rechecks

ControlSync now shows each setup's backsight/foresight points, middle-wire checks, distance balance, elevation and overall closure for the active level revision. Choose a suspect setup, specify the job's closure tolerance and crew instructions, then download a two-sight recheck template. The return is staged as immutable source evidence and the entire loop is previewed with Ron's original three-wire math and the saved calculation policy.

Approval requires the returned loop to pass the closure tolerance and all sight QC flags. A reviewed approval saves only the requested BS/FS sight overlays, preserves all original level observations, and activates a new solution revision with source provenance. This also handles station-row turning points where a single row carries the previous setup's FS and the next setup's BS. A rejected return leaves the active solution untouched. The accepted ZIP contains before/after closure and review evidence. Ron's workbook profile continues to default to no closure adjustment.

Opening an existing project upgrades its database schema to version 7 after a migration backup. The candidate is based on 9.4.7 Stable. Windows installer and representative field-book acceptance remain required before promotion.
