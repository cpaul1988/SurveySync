# FieldBook relationship evidence pilot

This development feature adds reviewable links between independently located OCR
text, measured ink paths, closed structure boundaries, and exact imported
PointIDs. It also separates agreement on individual numbers from agreement on
pipe records. **Every extracted pipe still requires human review**, including a
pipe whose relationship is marked `supported`.

The feature has synthetic geometry, adapter, integration, benchmark, and review
UI coverage. It has not established recognition or association accuracy on
private field books, real Paddle model operation, or acceptable performance on
Windows with a 4 GB GTX 1650. The [existing Defender incident and release
decision](../SECURITY_INCIDENT_953.md) remain unchanged.

## PointID results and source evidence

With the default `status_rule="POINT_ID_FOUND"`, an exact matched field-book
PointID keeps the primary result `YES`; a point without an exact match keeps
`NO`. Pipe interpretation, disputed values, and missing relationship evidence
remain in `dip_status`, `qa_needs_review`, and the review decision. Primary
`YES` does not certify any extracted depth, diameter, destination, or connection.
The separate advanced `CONFIRMED_DIP` rule remains available.

Imported survey points and original field-book sources are preserved. OCR
observations, model interpretations, deterministic proposals, and reviewer
edits remain distinguishable. PointIDs retain their exact spelling, including
case and leading zeros. Neither geometric proximity nor a likely measurement
value creates an exact PointID match.

## What each stage contributes

| Stage | Implemented evidence | Limit |
| --- | --- | --- |
| Text localization | Original and grid-cleaned OCR observations retain their source view and original-page location. Identical text and boxes merge while retaining both provenance records. | Different readings or shifted boxes remain alternatives; a large paragraph box is weak localization. |
| PointID anchor | A localized, independently read token must exactly equal an imported PointID. | A model-supplied identity or paragraph-sized context region cannot serve as the geometry core's independent anchor. |
| Structure boundary | The CPU core finds a bounded class of closed, circle-like ink loops and checks the enclosed anchor. | Open circles, other structure shapes, and overlapping identities can remain unresolved. Profile semantics alone do not prove a boundary. |
| Leader path | Connected original-image ink is traced between text and a measured boundary, retaining endpoints and path points. Scaled candidates need an original-resolution connectivity check. | Crossings, branches, competing endpoints, gaps, and exhausted budgets prevent a supported association. Arrowhead direction is not classified. |
| Pipe comparison | Explicit OCR records are compared with model observations for dip, diameter, material, and azimuth. | Matching a page-wide collection of numbers cannot establish that each pipe has the right tuple. Destination PointID text is retained separately and is outside this four-field comparison. |
| Review decision | The page, alternatives, text snippets, and individual pipe proposals can be inspected together. | `supported` is a proposal for review; this pilot cannot automatically accept a pipe. |

### Agreement is separate from geometry

`PageEvidence.numerical_agreement` records the existing value comparison.
`pipe_record_agreement` checks explicit records without pooling fields from
different pipes and preserves repeated-record multiplicity. `model_agreement`
combines the available text checks. Each may be `true`, `false`, or `null`;
`null` means insufficient evidence, not agreement.

For example, the numbers from `DIP 4.2, 8 in PVC` and `DIP 6.1, 12 in RCP` may
all occur in a page while a model swaps their diameters. A number-only match is
insufficient; the record comparison can expose the mismatch. Swapping both
complete tuples between fixed leader regions needs the separate geometry check
or review against the original image.

The local comparison uses the existing tolerances of 0.08 for dip in its raw
source unit, 0.75 inches for diameter, and 3 degrees for circular azimuth
comparison. Material comparison ignores case. These tolerances are consistency
rules, not a measured recognition error bound. A text block with multiple
candidate values for one field is not treated as one clear pipe record. The
private benchmark uses exact numeric comparison, a deliberately different task.

### Original-page geometry and conservative proposals

The public core entry point is
`fieldbook_sync.spatial_association.associate_page_geometry`. It uses Pillow and
NumPy on the CPU, with bounded image, component, path, iteration, and time
budgets. It does not load a model or require a GPU. See the [spatial core
contract](fieldbook_spatial_core.md) for inputs, algorithms, exact limits, and
synthetic cases.

All retained boxes and `paths[].points` are in **original-page coordinates
normalized to 0..1000**, after display EXIF orientation. Physical distances are
computed on pixels with the page's actual aspect ratio. Model crop coordinates
are mapped back through the actual padded crop once. A large vision context
crop and a model's proposed `leader_bbox` remain model observations; neither is
measured line evidence.

A supported text-to-structure proposal requires one intact path, one text
observation, one measured structure, and one independent exact PointID, with
text and structure at opposite path ends. Nearest text or nearest structure
alone is insufficient. Ambiguous alternatives remain in the graph. An
interrupted analysis raises cancellation; an exhausted geometry budget yields
an explicit partial graph and demotes all its associations.

Binding a model pipe to this graph requires a unique matching OCR record in the
four compared fields and verified original-ink path evidence. If its proposed
leader region conflicts with the matched measured path, the relationship is
`conflict`; a region covering competing paths is `ambiguous`. A missing model
leader box remains missing, even when the values select a review proposal.
Filling that box from a value-selected path would contaminate independent
benchmark pairing.

| Relationship status | Meaning for review |
| --- | --- |
| `supported` | The bounded checks support a specific proposal; verify the handwriting and connection before accepting. |
| `ambiguous` | Competing text, paths, structures, or model regions remain. |
| `conflict` | The matched ink/text proposal contradicts the proposed structure identity or model leader region. |
| `unverified` | No complete supported relationship is available. |

The acceptance gate is derived in `evidence_pipeline.py`, not accepted from a
model's JSON. Any evidence with pipes, or measurement evidence missing pipe
records, receives `PIPE_BINDING_REVIEW_REQUIRED` and cannot become `AUTO_ACCEPT`.
Existing acceptance checks for nonmeasurement evidence without pipes remain
separate. Model-supplied relationship statuses, measured-path IDs, derived
connection scores, and acceptance metadata are discarded during interpretation.

## Stored graph and review workflow

The integration stores one canonical page graph in `AppState.spatial_graphs`,
addressed by a page ID and content digest. Each `PageEvidence` retains
`spatial_evidence_key`; each pipe retains its associated text/path IDs, status,
and flags. The in-memory graph is shared while processing. The persisted form
does not duplicate the full graph for every structure on the page.

Canonical graph serialization has a 2,000,000-byte UTF-8 budget. Oversized graphs
become explicitly partial and lose supported status; the implementation does
not silently remove competing paths to make one proposal look unique. A graph
has separate source fields for its original-raster file SHA-256 (`image_sha256`)
and decoded, oriented pixel SHA-256 (`pixel_sha256`). These are different
identities, with the pixel hash recipe documented in the core contract. A
budget failure before pixel hashing leaves that digest unknown.

1. Open a structure's Review dialog and select the evidence page.
2. Use **Original** and the evidence overlay to inspect OCR regions, independent
   PointIDs, measured structure boundaries, paths, and endpoints. The enhanced
   image remains a reading aid; original-page relationship overlays are shown
   on the original view.
3. Select an individual pipe to inspect its text and path proposals. Compare
   the separate Numbers, Pipe records, and Relationship verdicts. Retain
   unresolved alternatives when the original is unclear.
4. Correct observed pipe fields or explicitly reassign to another imported
   PointID through the existing audited review flow, then Save or Accept.

`GET /api/fieldbook-spatial/{graph_key}` retrieves the selected graph. The server
rechecks the original-raster file hash before returning geometry. A missing or
changed image returns an unavailable result with empty geometry, so an old
overlay cannot silently appear on different source bytes. See the [API
reference](../API_REFERENCE.md) for the data fields and endpoint behavior.

## Default Blocks and explicit local Spotting

`ocr_mode="blocks"` remains the default for the Paddle OCR path. An explicit
`ocr_mode="spotting"` selection additionally requires `spotting_model_dir` to
identify an existing local native `PaddleOCR-VL-1.6-0.9B` export. The settings
handler validates the directory and hashes its inference assets; no model is
downloaded as part of this selection. The installed public API and the returned
spotting contract must also pass checks at runtime. Capability failure reports
an error rather than substituting block output labelled as spotting.

The spotting worker requests localized text without layout detection, document
orientation classification, or unwarping, and uses CPU inference. Upstream
`spotting_res.rec_polys` are already in input-image pixels. The adapter maps and
checks those polygons, preserves source/model hashes, and does not invent OCR
confidence. Caches distinguish OCR mode, image bytes, and model asset identity.
Changing this setting does not convert a Windows OCR or vision-only provider
into Paddle spotting. See [local spotting setup and limits](fieldbook_spotting.md).

## Batch projects

Each batch project snapshots its current engine settings when analysis starts.
Hybrid and Paddle-only batch jobs honor `blocks`/`spotting`, the selected local
model directory and performance mode. Explicit spotting reports a capability
error if Paddle is unavailable. Hybrid and Windows local interpretation use
original-page context crops and the same reverse coordinate mapping and manual
pipe review gate. Their independent OCR graphs, and the Paddle-only batch index
graphs, are stored once per page before aggregation. Direct vision and fallback
results also pass the review gate.

Batch exports retain the run's source hashes, model/mode, elapsed time and
actually observed Paddle receipt hashes. A Windows or direct-vision run does not
invent Paddle asset provenance. This does not add a new batch cancellation,
queueing or shutdown mechanism; existing job handling remains in use.

## Private comparison of real runs

Create independently reviewed gold labels from original pages, including fixed
leader boxes and exact PointIDs. Keep development and holdout pages separate
by book or job where possible. Freeze the labels and the matching policy before
comparing modes. Private pages, labels, raw exports, and reports belong in the
ignored `.fieldbook-benchmark/` directory or another private local directory.

Analyze the same pages in the selected local mode, then use the Engine panel's
benchmark download after the run has finished. The corresponding
`GET /api/fieldbook-benchmark/export` returns raw evidence, canonical graphs,
OCR candidates, original-page hashes, and analysis-time metadata. Save each
download before rerunning. It contains project data and is not a redacted
support report.

For completed Paddle/Hybrid runs whose metadata modes are `blocks` and
`spotting`, save the downloads under those names and score them from the
repository root:

```sh
python scripts/benchmark_fieldbook.py --gold .fieldbook-benchmark/gold.jsonl --run blocks=.fieldbook-benchmark/blocks.json --run spotting=.fieldbook-benchmark/spotting.json --output .fieldbook-benchmark/comparison.json
```

Use `--run blocks=...`, including the final **s**: the CLI run name must match
the export's `benchmark_metadata.mode`. Other providers record their provider
name; older exports may use `unknown`. Do not relabel metadata to make an export
pass. The scorer opens saved local JSON/JSONL or supported export ZIPs, performs
no inference or uploads, and does not open the referenced images.

The scorer pairs pipes by mutual, unique leader-box overlap before comparing
their values. Values and list order never choose a pair. Missing labels,
unverified page hashes, abstentions, review decisions, and unknown denominators
remain visible. Accuracy is scored from raw `PageEvidence`, not corrected
aggregated pipes. See the [private benchmark schema and protocol](../FIELDBOOK_BENCHMARK.md)
for exact PointID, complete pipe/structure, false-acceptance, and field metrics.

Exported wall time describes the run. Review-dialog elapsed time includes
reading and idle time and is labelled accordingly. Peak RAM/VRAM, page latency,
cancellation latency, and out-of-memory outcomes need actual workstation
measurements; synthetic fixtures do not provide them.

## Validation boundary and implementation map

Synthetic tests cover adjacent and crossing leaders, ambiguous targets, wrong
nearest neighbors, gaps lost by resizing, budgets/cancellation, source identity,
crop remapping, model-metadata stripping, record swaps, and canonical graph
persistence. Adapter tests use synthetic worker results rather than real model
weights. The review UI harness renders synthetic pages and intercepted API
responses; it is separate from a physical desktop acceptance run.

Relevant implementation and tests:

- [`spatial_association.py`](../../fieldbook_sync/spatial_association.py) and
  [`test_spatial_association.py`](../../tests/test_spatial_association.py): measured ink proposals.
- [`relationship_evidence.py`](../../fieldbook_sync/relationship_evidence.py) and
  [`test_relationship_pipeline.py`](../../tests/test_relationship_pipeline.py): provenance, conservative consumers, crop coordinates, storage, and acceptance gates.
- [`measurement_comparison.py`](../../fieldbook_sync/measurement_comparison.py) and
  [`test_pipe_measurement_comparison.py`](../../tests/test_pipe_measurement_comparison.py): record-aware OCR checks.
- [`text_spotting.py`](../../fieldbook_sync/text_spotting.py),
  [`test_text_spotting.py`](../../tests/test_text_spotting.py), and
  [`test_spotting_pipeline.py`](../../tests/test_spotting_pipeline.py): optional local spotting contract and cache transport.
- [`export_routes.py`](../../fieldbook_sync/export_routes.py),
  [`benchmark_export.py`](../../fieldbook_sync/benchmark_export.py), and the
  [benchmark guide](../FIELDBOOK_BENCHMARK.md): private exports, scorer, and UI verification.

Remaining acceptance includes difficult real handwriting, rotated annotations,
intersecting and incomplete leaders, realistic grid lines and scan noise, and
actual correction effort on the target workstation. A generic document OCR or
diagram benchmark cannot establish those outcomes for survey field books.

## Upstream design and API references

The spatial implementation is original SurveySync code. The endpoint/graph
design was informed by Azure's P&ID work; the local implementation does not
import its application, cloud services, graph code, or models. No code, model
weights, or datasets from circuit-recognition research repositories were copied
or bundled. In particular, research availability without a code license was
not treated as permission to import an implementation.

- [Azure graph construction design, commit c51302e3](https://github.com/Azure-Samples/digitization-of-piping-and-instrument-diagrams/blob/c51302e3ec34147c676ef6eedbdd7551ea908b05/docs/graph-construction-design.md)
- [Azure endpoint connection candidates at the same commit](https://github.com/Azure-Samples/digitization-of-piping-and-instrument-diagrams/blob/c51302e3ec34147c676ef6eedbdd7551ea908b05/src/app/services/graph_construction/create_line_connection_candidates.py)
- [Zhang and Suen, 1984, thinning algorithm](https://doi.org/10.1145/357994.358023): algorithmic reference for the original bounded thinning implementation.
- [Arrow R-CNN paper](https://doi.org/10.1007/s10032-020-00361-1): background on the distinction between recognizing symbols and recovering diagram relations; no detector or trained weights are included.
- [PaddleOCR public wrapper, commit dab3fe35](https://github.com/PaddlePaddle/PaddleOCR/blob/dab3fe35379033fdcb2d0e9572fac0b36c9a9ebf/paddleocr/_pipelines/paddleocr_vl.py)
- [PaddleX spotting coordinate conversion, commit ffb64904](https://github.com/PaddlePaddle/PaddleX/blob/ffb64904d23708863ff5b8da312a5cbd52a7f462/paddlex/inference/pipelines/paddleocr_vl/uilts.py)
- [PaddleX native loading at the same commit](https://github.com/PaddlePaddle/PaddleX/blob/ffb64904d23708863ff5b8da312a5cbd52a7f462/paddlex/inference/models/doc_vlm/predictor.py)

See [third-party notices](../../THIRD_PARTY_NOTICES.md) for source-reference and
runtime license boundaries. Upstream API references identify the reviewed
contract; they are not a claim that a specific local installation has passed
model or distribution acceptance.
