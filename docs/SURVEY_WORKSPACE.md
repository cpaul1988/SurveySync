# SurveySync 9.5.0 shared workspace candidate

The first upgrade tranche builds the integration inventory and shared UI components
inside Visual Survey QA. It retains the local project coordinate canvas; drawing,
snapping, geographic basemaps, new CAD geometry, GNSS processing and live instruments
are later phases, not capabilities of this candidate.

## Review workflow

- Sources on the left control visibility in the map and point table.
- Identify selects the closest visible record within 12 screen pixels. Pan is an
  explicit tool. Box select uses a dragged rectangle without Ctrl. Add to selection
  retains previous records; point-table checkboxes also toggle records individually.
- Selection is keyed by UUID, including duplicate PointIDs. The selected count may
  include hidden/unplottable records. The active record drives the evidence pane and
  the existing single-record correction preview. Multi-selection never bulk-applies
  an offset. Refresh, project/view changes and changed thresholds clear selection.
- All, flagged, selected and visible table scopes combine with existing search,
  issue/state filters and source visibility. The viewport scope does not refit the map.
  Fit points fits matching visible sources; Fit selected fits selected visible records.
- Coordinate, description, source and flag columns can be hidden in the current
  session. Paging remains 100 records and 50 issues.
- Control Review, Boundary Drafting and Topo QA are layout presets. They do not
  enable new survey tools. Drag the splitters or focus one and use arrow keys,
  Home or End. Save layout stores pane sizes on this device. Narrow windows stack
  the panes; source records, layouts and selections are never written to project data.
- Original source inspection, audited review decisions, stale-project refusal,
  correction-copy confirmation and full-scope PDF/CSV reports remain in place.

## Integration foundation

`GET /api/v9/integrations/status` reads installed distribution versions and explicit
adapter descriptors. A planned adapter stays planned even if its package happens to
be installed. Missing optional packages do not affect native DXF or app startup.
Metadata errors appear in the inventory instead of activating a fallback.

The endpoint does not import optional packages, start subprocesses, probe devices,
install software, or call a network. Inventory is an availability hint, not a
successful import/operation guarantee. Real operation diagnostics remain authoritative.
Exact bundled versions are pinned in the existing requirements locks; no package was
added by this tranche. PyMuPDF's existing AGPL/commercial licensing is recorded in the
notices and must be addressed in any commercial distribution license review.

Future adapter jobs must preserve source hashes, project UUID, input settings,
backend version, progress and cancellation state; return bounded structured errors;
create staged outputs before explicit approval; and check project context before any
commit. This contract is documented here but no new generic job runner is introduced.

## Validation

Run the full release gate and `scripts/verify_visual_qa.py`. The latter exercises real
controls, duplicate UUID selection, source visibility, viewport filtering, splitter
keyboard/pointer operation, saved layout restoration, table columns and existing
review/export/project guards against a disposable project. Windows Repair Acceptance
must pass on the exact candidate installer before any publication or promotion.
