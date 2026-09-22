# SurveySync v9.2.0 BetaCandidate Release Notes

## ControlSync active revision management

SurveySync v9.2.0 begins the next feature cycle by turning the existing immutable ControlSync solution history into an operator-controlled revision workflow.

- Every new control solve and saved level solve remains immutable and is automatically marked as the active revision.
- ControlSync shows revision history with an explicit ACTIVE marker instead of assuming that the newest row is always the result the operator intends to report.
- Two stored control revisions can be compared for northing/easting/elevation deltas, horizontal shift, method/settings changes, and QC pass-state changes.
- Two stored level revisions can be compared for closure delta, adjusted ending-elevation delta, method/settings changes, adjustment-state changes, and added/removed QC flags.
- **Restore Selected as Active** switches the active pointer to an earlier stored solution. It does not delete newer solutions, copy the older solution, or rewrite observations.
- ControlSync PDF reports now use the explicitly active control and level revisions. Projects created before v9.2.0 retain backward-compatible latest-revision behavior until an active selection exists.
- Activation and restore actions are recorded in the shared audit trail.

## Data model

A new `solution_selections` table stores one active solution pointer per solution kind/object. The schema is created through the normal SurveySync audit-database initialization path, so existing projects do not require a manual migration step.

## Compatibility

The validated Ron 3-point control calculations and Ron 3-wire level reductions are unchanged. The v9.1.4 updater-confirmation, atomic Save As, diagnostic logging, FieldBookSync review UI, Point Range, Trimble, Field Note Profile Trainer, and existing project format remain preserved.

## Feedback gate

The shared FieldBook Sync Feedback Tracker was checked before this build. The latest Intake item remains **FBR-0012**; there were no newer Intake requests and the legacy `Form Responses 1` tab contained no unprocessed submissions. The tracker did not yet contain an `Error Log` tab at build start.

## Beta validation still required

The source regression suite, documentation gate, Python compile checks, and JavaScript syntax checks are part of the candidate build gate. The Windows-native launchers and Inno Setup installer must still be rebuilt/compiled on Windows and the resulting installer field-tested before Stable promotion.
