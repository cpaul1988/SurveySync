# SurveySync 9.5.1 CAD Drawing & Geometry QA

Open BoundarySync → CAD Drawing & Geometry QA. Import a DXF (modelspace only), select its actual units, and explicitly confirm that origin, axes and coordinate reference system match the active project. DXF does not reliably identify a survey CRS. A unit conversion is applied to a derived review representation, never to original bytes. No geographic-coordinate overlay or automatic CRS transformation is offered. Header `$INSUNITS` is reported for comparison, not silently trusted.

## Review

Lines, 2D/3D polylines, bulges, arcs, circles, ellipses, points, TEXT/MTEXT, attributes and supported nested block references are represented in WCS. Block transforms are applied, layer 0 inherits its insertion layer, and source handles/block paths remain visible. Unsupported entities, recursive blocks, XREFs, block extension/clipping data and curve-fit polylines are reported. Paperspace is excluded and counted. Text is an anchor and plain-text label preview, not faithful CAD typography. Layer visibility initially respects off/frozen layers.

Entity table, findings and plan selection share entity identities. Survey points can be identified in the plan; the overlay uses only points matching the project CRS and horizontal units. Excluded points are counted. Identify, pan, zoom, layer visibility, searchable/paged entity tables and paged findings keep drawing review usable. Reports include findings from all imported layers, regardless of display filters.

## Geometry and closure

- Exact duplicate straight segments compare XYZ, including reverse direction. Partial overlaps and curved inter-entity overlaps are not tested.
- Exact repeated vertices/zero-length straight segments are reported. Nonplanar linework is excluded from planar checks and flagged.
- Shapely screens self-intersections and crossings in XY. Inter-entity crossing checks cover straight segments. Grade-separated or intentional crossings are possible; findings are advisory.
- Curves use ezdxf path approximations for display and self-intersection screening. Display chord target is 0.001 international ft; this is not a certification of engineering curve accuracy. Closure uses original entity endpoints, not a forced closing chord.
- Endpoint proximity uses a configurable 0.10–10 ft search radius. Nearby endpoints may be unrelated. Gaps beyond that search radius are not listed.
- Append open entities to an explicit ordered boundary chain, reverse directions or move entries as required, then Check closure. The report shows every internal join and the last-to-first gap. Any gap over 0.10 ft in the project’s US survey/international foot definition (metric projects: 0.03048 m) requires investigation. A within-tolerance result still requires review. Closed DXF entities are refused for survey misclosure because their closing edge is already encoded. No traversal order is inferred.
- No tool in this candidate edits, snaps, closes, repairs or adjusts source geometry or canonical project points.

## Evidence, performance and limits

A unique project CADReview package retains the original DXF, SHA-256, explicit unit settings, library versions, project context, point snapshot, supported geometry, omissions and findings. Import/report actions are audited. The review package and original source hash are checked on reopen, closure and report export. Changed project context or points require reimport. Reports download a ZIP containing a printable HTML report, CSV findings and closure tables, JSON provenance/ordered closure, and a scope note. CSV cells are protected against formula injection.

Limits are 32 MiB DXF, 10,000 expanded entities, 150,000 display vertices, 5,000 findings, 200,000 candidate proximity/intersection pairs, 20,000 project points and 1,000 ordered closure entries. Exceeding an analysis limit rejects the import; no partial QA result is presented as complete. Parsing/QA runs in a disposable subprocess with a 40-second timeout and one concurrent import. The project lock is released during parsing and reacquired with identity/context checks before retention. Partial packages are removed if retention/audit fails. Large or complex drawings should be split in CAD first.

## Validation and dependencies

Pinned runtime: ezdxf 1.4.4 (MIT), Shapely 2.1.2 (BSD-3-Clause; bundled GEOS LGPL). Dependencies and transitives are included in hash-locked runtime/dev requirements. `tests/test_cad_review.py` checks transformations, OCS, bulges, unsupported content, known geometry failures, closure order/direction, units, limits, retained-source tampering, route guards and report export. `scripts/verify_cad_review.py` exercises actual browser controls and source preservation. Windows installer/runtime/update acceptance is required before publication.

Threshold classification permits a floating-point roundoff margin based on coordinate precision; reported gaps and original coordinates are not adjusted.

## 9.5.2 — decisions and revised drawings

Select a finding, choose Needs review / Confirmed finding / Dismissed with reason, enter your reviewer name and evidence, and Save decision. Confirmation means the finding exists, not that geometry was repaired. Saved history remains visible when reopening this import. To revise a decision, save another entry; earlier entries remain in the project audit chain. Names are self-entered.

Import the revised DXF with its actual units and verified alignment. With the revised drawing open, choose the earlier retained import under Compare a revised drawing and press Compare drawings. Select a change to view its evidence and dashed-red before / solid-green after overlay. The comparison lists supported representations only. Same top-level handles are candidate matches, not proof of entity identity; expanded block children are always unmatched. An unchanged sampled curve or text anchor does not prove the native CAD entity is identical. Unsupported content from both imports remains in the comparison evidence.

Download review report includes all findings and saved decisions, regardless of hidden layers, plus decision history and the currently computed comparison. Changing the earlier-drawing selector clears that comparison until Compare is run again. The ZIP contains CAD_Decisions.csv and CAD_Workflow.json as well as the original CAD review report files. A stale decision token requires reopening the review. Altered DXF bytes, project context or overlay points block comparison/export; reimport against the current context. Original geometry and canonical points are never modified.

Acceptance: use a representative real project DXF and matching points to confirm known control alignment, one known defect, one deliberately revised entity, unsupported-content reporting, decision retention after restart and agreement between visible decisions and exported reports. Synthetic tests do not substitute for this field acceptance.
