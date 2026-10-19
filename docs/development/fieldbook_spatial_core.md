# FieldBook spatial association pilot

## Scope and status

`fieldbook_sync/spatial_association.py` is an original, bounded CPU implementation
using existing Pillow and NumPy dependencies. It makes conservative proposals for
review. It does not transcribe handwriting, interpret pipe measurements, repair
missing strokes, change source images, or authorize automatic acceptance.

The implemented positive case is deliberately narrow: a local text region at one
end of an intact measured ink path, with the other end touching a measured closed,
circle-like structure containing one independently read exact PointID. It is not
a general solution for handwritten surveying pages. Open or broken circles,
arrowhead branches, crossings, crowded annotations, and ambiguous IDs can abstain.
Synthetic tests establish the intended mechanics, not accuracy on real fieldbooks.

The later [confirmed layout conventions](fieldbook_relationships.md#confirmed-note-conventions--2026-10-19)
allow an external structure ID, an internal north arrow, and a variable number
of unboxed connection notes with flow arrowheads. Those are interpretation
conventions, not additional positive geometry cases. This core still requires
an enclosed exact ID and does not classify north or flow arrowheads. The Excel
mockup's rectangular note borders and blank values are illustrative; they are
not required input geometry or labeled measurement truth.

## Public API

```python
from fieldbook_sync.spatial_association import (
    SpatialCancelled, SpatialLimits, associate_page_geometry,
)

graph = associate_page_geometry(
    original_image,  # full original page as a PIL.Image.Image
    page_id="page-1",
    text_regions=[{
        "id": "text-1", "text": "150 PVC", "bbox": [300, 200, 400, 230],
        "source": "ocr",
    }],
    point_anchors=[{
        "id": "anchor-1", "point_id": "001", "raw_text": "001",
        "bbox": [100, 200, 130, 230], "source": "independent_ocr",
        "exact_match": True, "independent": True,
    }],
    structure_hints=[],
    limits=SpatialLimits(),
    cancelled=lambda: False,
)
```

All boxes and path points use **original-page normalized coordinates 0–1000**.
They are not local to a crop. Distances and shape tests use actual image-pixel
aspect ratios; normalizing x and y independently does not stretch physical
geometry. Boxes must contain four finite, ordered coordinates within the page.
Invalid records raise `ValueError`; duplicate record IDs are rejected.

`raw_text` is the independently read exact ID token, not its entire OCR paragraph.
Leading zeros and letter case are retained. An exact-match flag by itself cannot
convert `1` into `001`. Distinct exact IDs inside one structure, or repeated IDs
in separate structures, prevent a unique binding. Duplicate observations of the
same exact ID inside one structure are allowed.

Only tight text and ID boxes are masked from the drawing analysis. Context-sized
boxes are ignored and reported. Hints can be recorded against independently
measured loops, but cannot supply a boundary, leader, PointID, or acceptance.
The API accepts no externally supplied leader polylines. VLM-generated leader
boxes and large interpretation crops are not measured line evidence.

The caller must supply the full original page in the same orientation as the
normalized coordinates. A PIL image alone cannot prove its file provenance; the
integration owns that responsibility. The source image is never modified.

## Output contract

The result contains only JSON-serializable values:

- `schema_version`: `1`.
- `status`: `complete` or `partial`.
- `review_only`: always `true`.
- `truncated`, `flags`, `ignored_inputs`, and the effective `limits`.
- `source`: `page_id`, original `width`/`height`, `pixel_sha256`, and
  `coordinate_space="original_normalized_0_1000"`.
- `analysis`: working dimensions, ink threshold, and measurement methods.
- `structures`: measured closed-loop boxes, exact-ID candidates and anchors,
  identity status/reasons, and source-resolution verification status.
- `paths`: the fields below.
- `associations`: text-to-structure review proposals and competing candidates.

Each path contains:

```json
{
  "id": "path-1",
  "points": [[200.0, 300.0], [400.0, 300.0]],
  "endpoints": [[200.0, 300.0], [400.0, 300.0]],
  "bbox": [200.0, 299.0, 401.0, 302.0],
  "pixel_count": 400,
  "skeleton_pixel_count": 200,
  "branched": false,
  "structure_ids": ["structure-1"],
  "text_ids": ["text-1"],
  "text_endpoint_indices": {"text-1": [1]},
  "structure_endpoint_indices": {"structure-1": [0]},
  "original_resolution_verified": true,
  "evidence": "original_pixels"
}
```

These numbers illustrate the schema, not a test result. `points` is an ordered
ink-centerline polyline with collinear runs compacted; every change in raster
direction is retained. It is not sampled into straight shortcuts. `endpoints`
contains all detected endpoints. Branched components have an empty `points`
list because choosing one branch would invent a unique route. A structure's
small measured-boundary removal halo is excluded from the polyline; the local
terminal check verifies intact ink from the path endpoint to the loop boundary.

An association contains `text_id`, nullable `point_id`/`structure_id`, `path_ids`,
`candidates`, `reasons`, and `status` (`supported`, `ambiguous`, or `unresolved`).
`supported` requires one path, one text region, one structure, a unique exact
independent ID, and text/structure contact at opposite terminals. It is never
an instruction to accept the pipe interpretation. All alternatives remain
available for review.

The source digest is exactly SHA-256 over:

1. ASCII `RGB:{width}x{height}:`, with decimal dimensions;
2. the full RGB image's row-major pixel bytes, without padding.

It identifies the supplied page pixels, not the encoded file bytes. The
integration can additionally retain the original file digest and EXIF/crop/view
transforms. A budget exhausted before hashing leaves `pixel_sha256` as `null`.

Consumers must require `status == "complete"`, `truncated == false`, and matching
page identity before using any supported proposal. A cancelled analysis raises
`SpatialCancelled`; the caller should preserve cancellation, not convert it into
successful evidence.

## Pixel processing and limits

The core thresholds a bounded grayscale view, masks local OCR text, identifies
closed white interiors using connected components, and checks for circle-like
area/aspect characteristics. It binds independent exact ID boxes fully enclosed
by those interiors. It then removes only the measured structure regions,
identifies ink components, thins candidate leaders, and checks their terminals.
Disconnected strokes are not joined; crossings and branches remain ambiguous.

If the bounded working view was resized, a prospective supported association is
checked again in a bounded original-resolution region. That check verifies the
closed ID-containing loop and intact connected ink along the measured path.
Resampling therefore cannot establish support merely by closing a tiny white
gap. A failed native-resolution check abstains. The verification is conservative
when unrelated ink lies within the narrow path corridor.

Defaults bound original pixels, working pixels/side, wall time, input records,
component runs/count, structures, paths, skeleton pixels, thinning iterations,
path vertices/endpoints, and cumulative native-resolution verification pixels.
Cancellation and deadlines are checked throughout substantial loops. A budget
hit returns `partial`, records its reason, and demotes **all** associations and
structure identity statuses. It never presents incomplete topology as supported.
The pilot can legitimately abstain on dense pages rather than exceed its budget.

## Verification

`tests/test_spatial_association.py` covers intact and separated leaders, a closer
but incorrect neighboring structure, crossing leaders, disconnected gaps,
opposite-terminal contact, ambiguous text/IDs, exact leading-zero identity,
duplicate independent observations, context/VLM hint exclusion, coordinate
validation, JSON serialization, source immutability, source-pixel hashing,
resized-page verification, and resource/cancellation behavior.

Real-fieldbook validation is still required, including messy handwriting,
unusual circle styles, oblique leaders, incomplete marks, different paper and
ink, and more than one pipe record beside a structure. The appropriate outcomes
include wrong-binding rate, correct-binding coverage, and explicit abstentions.

## Design references and attribution

No implementation code, model weights, or datasets were copied from the
repositories below. Their concepts informed the research and design review.

- Azure P&ID, inspected tree `c51302e3ec34147c676ef6eedbdd7551ea908b05`:
  [graph design](https://github.com/Azure-Samples/digitization-of-piping-and-instrument-diagrams/blob/c51302e3ec34147c676ef6eedbdd7551ea908b05/docs/graph-construction-design.md)
  and [endpoint candidate matching](https://github.com/Azure-Samples/digitization-of-piping-and-instrument-diagrams/blob/c51302e3ec34147c676ef6eedbdd7551ea908b05/src/app/services/graph_construction/create_line_connection_candidates.py).
  This motivated explicit line-to-text/symbol candidates and traceable graph IDs.
- [Arrow R-CNN paper](https://doi.org/10.1007/s10032-020-00361-1): separating
  arrow endpoints from symbol detection and text recognition. No detector or
  restricted diagram dataset was incorporated.
- [Zhang and Suen, 1984](https://doi.org/10.1145/357994.358023): the published
  two-subiteration skeleton-thinning algorithm, implemented here with bounded
  NumPy operations.
- Hand-drawn circuit parser, inspected tree
  `5e5a957f41bdb60f4835fb7c887452a6dc469520`:
  [connectivity stage](https://github.com/wanghaoyu6661/Hand-Drawn-Circuit-Diagram-Recognition/blob/5e5a957f41bdb60f4835fb7c887452a6dc469520/src/pipeline/build_connections.py).
  Visible ink continuity and explicit endpoint/edge evidence informed the design;
  its circuit-specific models, gap-repair logic, and code were not incorporated.

Upstream accuracy and runtime claims do not transfer to this implementation or
to SurveySync's fieldbook pages.
