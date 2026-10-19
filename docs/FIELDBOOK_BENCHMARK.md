# Private FieldBook benchmark

`scripts/benchmark_fieldbook.py` compares reviewer labels with saved analysis
evidence. It uses only Python's standard library, runs on Windows and Linux, and
does not run OCR, open page images, install a model, or contact a service. Keep real
pages, labels, exports, and reports in `.fieldbook-benchmark/` or another private
local directory. Do not commit real field books or project exports.

The benchmark addresses a specific failure: a page can contain every correct
number while attaching those numbers to the wrong pipes. It first pairs pipes by
their original-page geometry, then checks the fields of each pair. It never uses
matching measurement values or pipe list order to select a pair.

## Save and compare runs

Analyze the same private pages separately in **block** and **spotting** mode. After
each completed analysis, use the Engine panel's benchmark download. The local
`GET /api/fieldbook-benchmark/export` endpoint returns the same JSON snapshot.
Save each download before changing the mode or rerunning analysis. Its metadata
describes the completed analysis, not the settings currently displayed at export.

From the repository root, with Python 3.10 or later:

```sh
python scripts/benchmark_fieldbook.py --gold .fieldbook-benchmark/gold.jsonl --run blocks=.fieldbook-benchmark/blocks.json --run spotting=.fieldbook-benchmark/spotting.json --output .fieldbook-benchmark/comparison.json
```

The script also accepts a normal SurveySync export ZIP containing exactly one
`audit.json`, an extracted audit/project JSON with `results[].evidence_records`,
or per-evidence JSONL described below. ZIP members are read in memory and never
extracted. Older exports may lack run metadata and page hashes; those remain
unknown in the report. Do not substitute the summary CSV, GIS export, or manually
edited `results[].pipes` for raw predictions.

Run names must agree with an export's `benchmark_metadata.mode` when supplied.
For an old export with mode `unknown`, use `--run unknown=...`; relabeling the CLI
argument does not establish which engine actually produced it. An output inside
a Git worktree must be under its ignored `.fieldbook-benchmark/` directory. Git
must be available to verify that rule. Outside a worktree, choose a private local
destination. The script rejects URL/UNC paths, output symlinks/junctions, replacing
an input, and overwriting an existing report unless `--overwrite` is supplied.

The scorer's metrics contain aggregate counts and hashes without copying raw
PointIDs, labels, page names, source paths, or field values. Documented metadata
is retained, including supplied model/hardware descriptions and provenance
warnings, which can mention page identifiers. Keep reports private and inspect
that descriptive metadata before sharing. Original exports contain private
project data.

## Gold JSONL schema, version 1

Each nonblank line describes one original raster page. `page_id` must be the ID
used in the prediction export. Use `source_sha256` for the bytes of that original
page raster, rather than its PDF container, a resized preview, or an enhanced
derivative. A null hash explicitly means image identity has not been verified.

This formatted example is one line when saved as JSONL:

```json
{
  "schema_version": 1,
  "page_id": "synthetic-page",
  "source_sha256": null,
  "structures_complete": true,
  "dip_unit": "ft",
  "structures": [
    {
      "structure_id": "structure-a",
      "point_id": "0001",
      "pipes_complete": true,
      "dip_status": "YES",
      "pipes": [
        {
          "pipe_id": "east-pipe",
          "leader_bbox": [100, 100, 200, 130],
          "fields": {
            "dip": 4.2,
            "diameter_in": 8,
            "material": "PVC",
            "azimuth_deg": 90,
            "connected_point_raw": null
          }
        }
      ]
    }
  ]
}
```

| Label | Required meaning |
| --- | --- |
| `structures_complete` | Every structure on this page is annotated. Set false for a partial page. An empty complete page is a valid negative example. |
| `structure_id` / `pipe_id` | Unique annotation IDs within their parent. These do not need to equal any prediction ID. |
| `point_id` | Exact written identity, preserving case and leading zeros. Null means unreadable/unknown; it does not create a scored identity. |
| `pipes_complete` | All pipes belonging to this structure have been annotated. False prevents extra predictions from being called false merely because labeling is unfinished. |
| `dip_status` | Optional `YES`, `NO`, `CNA`, `CNL`, `NOT_FOUND`, or `REVIEW`. Missing/null means unknown. |
| `leader_bbox` | Required key; null if geometry is unlabelled, otherwise `[x1,y1,x2,y2]` with positive area in original-page coordinates normalized to 0..1000. Use the same pipe/leader extent convention for gold and predictions. |
| `fields` | Object containing any subset of `dip`, `diameter_in`, `material`, `azimuth_deg`, `connected_point_raw`. A missing key means unknown. **An explicit null means the reviewer verified that this field is absent.** |

`image_path` is optional and local-only; it is validated as a path but never
opened. `dip_unit` is optional documentation and performs no conversion. An
optional `structure_bbox` uses the same coordinate convention and is validated;
this version does not use it to repair a wrong PointID.

Numeric labels and predictions must be finite JSON numbers, not strings or
booleans. Diameter is in inches and must be positive; azimuth must be in
`[0,360)`. Dip is compared in the raw unit used by the source and export, without
conversion or rounding tolerance. Numerically equal `4.2` and `4.20` agree.
Material comparison ignores letter case; PointIDs and connected PointID text are
exact. Duplicate labels, duplicate JSON keys, unknown gold keys, invalid boxes,
and conflicting page hashes are rejected instead of silently repaired.

## Matching, metrics, and missing labels

For each exact `(page_id, point_id)`, candidate pipe pairs require leader-box
intersection-over-union (IoU) of at least `--min-iou` (default `0.3`). A pair counts
only when **both** pipes have exactly one candidate. Overlapping alternatives
remain unmatched; one prediction cannot satisfy two gold pipes. The threshold is
an explicit starting policy, not a measured calibration. Freeze it before
comparing a holdout set. Broad boxes, crossing leaders, and inconsistent
annotation extents can reduce assessed binding accuracy even when text is right.

Every rate includes `numerator`, `denominator`, and `value`. A zero denominator
produces null, never an invented 0% or 100% result.

| Metric | Denominator and interpretation |
| --- | --- |
| Exact PointID precision / recall | Unique exact `(page_id, point_id)` groups of raw `PageEvidence` on labeled pages. Precision uses known positives plus unexpected identities on fully labeled pages whose identities are all readable; recall uses all known gold identities. Repeated views count once. These are **not** exhaustive OCR-token detection metrics. |
| Pipe spatial match recall | Gold pipes with known structure identity and a labeled leader box. Missing prediction geometry is a failure; missing gold geometry is unassessed. |
| Labeled pipe binding accuracy | Spatially eligible gold pipes with at least one labeled field. All their known fields must match on the uniquely paired prediction. |
| Complete pipe record accuracy | Eligible gold pipes with all five field keys labeled, including verified nulls. All five must agree. |
| Complete structure record accuracy | Known identity and dip status, complete pipe enumeration, and every gold pipe fully labeled with geometry. Status, pipe count, bindings, and all fields must agree. |
| Field accuracy | Labeled instances of each field on spatially eligible pipes; missing predictions remain in the denominator. |
| False automatic acceptance | Incorrect assessed raw `AUTO_ACCEPT` records divided by all assessed raw `AUTO_ACCEPT` records. A known contradiction is incorrect even with partial gold. A record is correct only when fully labeled. Unknown cases are excluded and counted separately. |
| Review rate | Raw `REVIEW_DETAILS`/`MANUAL_REVIEW` decisions divided by known review plus `AUTO_ACCEPT` decisions on labeled pages. Missing decisions and predictions outside labeled pages are separate counts. |

Unlabeled identities, fields, geometry, incomplete records, unknown decisions,
unverified page hashes, and unassessed auto-accepts are visible in the report.
An extra predicted pipe is a known record error only where `pipes_complete=true`.
The unbound-prediction count is diagnostic: missing gold geometry can also cause
an unbound prediction, so that count alone is not a false-positive rate.

### Repeated original, cleaned, and crop observations

One frozen analysis run can legitimately save multiple observations of the same
page and PointID. The scorer groups them **before consulting gold**. Records that
agree in status, leader geometry, and normalized pipe fields count once for
identity and accuracy; pipe list order does not matter. Case-insensitive material
and numerically equal values use the same normalization as ordinary scoring.

A conflicting group is explicitly ambiguous. Only exact leader geometry shared
by every observation and a status that all observations share are retained. No
pipe field in that group receives accuracy credit, and a fully labeled structure
fails complete-record accuracy. Even small coordinate differences can create a
conflict; this strict policy intentionally does not select a favorable view or
tune geometry against the gold. Unknown gold fields remain unassessed.

The report counts raw observations, unique groups, duplicate observations,
agreeing groups, and conflicting groups separately. Accuracy uses the group
consensus. Review and false-automatic-acceptance rates still count **every raw
decision**, evaluated against that group's conservative verdict; a second view
sent for review cannot conceal the first view's `AUTO_ACCEPT`. Raw exports and
in-memory observations remain unchanged. This can make false automatic acceptance
a conservative estimate when saved views disagree, rather than a measurement of
each individual view's correctness.

Raw evidence determines accuracy even after a reviewer corrects an aggregated
record. Manual `UNREVIEWED`, `ACCEPTED`, `EDITED`, and `REJECTED` states are counted
per raw observation. The spatial pilot's `supported` relation status is a proposal
for human review and is not converted to automatic acceptance.

## Provenance and workstation measurements

Each report hashes the exact gold bytes and each complete prediction file/ZIP.
When both sides supply a page hash, unequal hashes reject the comparison; missing
hashes are counted as unverified. Prediction metadata is supplied provenance,
not reconstructed from the current checkout. The evaluator's own commit, dirty
state, script hash, and Python version are recorded separately.

The preferred export provides `benchmark_metadata` with `schema_version`, `mode`,
`model`, analysis-time `source_commit`/`source_dirty`, `implementation_sha256`,
`generated_at`, `hardware`, and `measurements`. `page_sha256` is a separate mapping
from page ID to original-raster SHA-256. A packaged app without Git can provide an
implementation hash while leaving the commit unknown. A null page-hash entry is
valid and remains unverified; optional `provenance_warnings` preserve the export's
reported limitations.

Optional `ocr_provenance` records the modes and assets observed from completed,
verified OCR worker/cache callbacks. It contains exactly `observed_modes` (unique
`blocks`/`spotting` values), `observed_model_asset_sha256` (unique SHA-256 digests),
and nonnegative integer `observed_page_count` / `observed_view_count`. The scorer
validates and preserves these fields without inferring them from the selected
Engine mode or a configured model path. Empty arrays with zero observations are
valid; missing provenance stays missing. This records supplied evidence of actual
model usage and weight changes, not an independent rerun or verification by the
scorer.

The export records known mode, model, code, page, and observed-asset provenance;
it is not a complete snapshot of prompts, profiles, training examples, or every
analysis setting. Keep the survey target list, field-note profile and training
examples, threshold/status rules, and preprocessing/performance settings fixed
between baseline and challenger runs, and note them privately with the experiment.
Profile or example changes can affect results and confound an engine comparison.

Accepted hardware fields are `os`, `cpu`, `gpu`, `ram_gib`, and `vram_gib`.
Optional measurement fields are `wall_seconds`, `peak_rss_mib`, `peak_vram_mib`,
`correction_seconds`, `cancel_seconds`, `corrected_structures`,
`reviewed_structures`, `oom_count`, and a `page_seconds` array. Supplied page times
produce nearest-rank p50/p95 with a count. Missing measurements stay missing.
This script measures no inference memory, latency, or GPU fit itself.

The UI's `correction_seconds` is accumulated review-dialog elapsed time for timed
records, including reading and idle time; `review_timing_basis` preserves that
qualification. It is not a precise stopwatch measurement of editing effort.
Record page timing, memory, model identity, cancellation, and OOM outcomes on the
actual target workstation if needed. Synthetic fixtures cannot establish that a
model fits or responds acceptably on a 4 GB GPU.

## Private annotation and challenger protocol

Start with a manageable set of representative pages covering multiple structures,
crossing leaders, absent fields, faint handwriting, and partial/negative pages.
Annotate from the originals and verify difficult bindings with a second review.
Separate development and holdout pages by book or job where possible. Keep the
gold fixed across block, spotting, and challenger runs; report every denominator
and unresolved label rather than filling gaps with model guesses.

An offline challenger may save JSONL with one raw evidence object per line:
`schema_version`, `page_id`, `matched_point_id`, `dipped`, `evidence_decision`,
`pipes` (flat pipe fields plus `leader_bbox`), and optional `source_sha256`.
Wrap these records in native-shaped `results[].evidence_records` with top-level
metadata to retain engine and timing provenance. Use `MANUAL_REVIEW` for an
unreviewed challenger proposal; do not invent a production acceptance decision.

Text grounding from a model such as LightOnOCR does not by itself establish which
leader belongs to which structure or pipe. An adapter must preserve the original
coordinate transform and produce separately supported pipe geometry to enter the
binding denominator. Without that geometry, the saved text can still be examined
privately, but the benchmark will not infer a successful binding. This workflow
does not install or run a challenger.

## Synthetic example and verification

The committed `tests/data/fieldbook_benchmark/` files contain two invented pipes,
no images, no real project IDs, and no measured engine output. `correct.json`
matches; `swapped.json` swaps the two dips while preserving the page-wide values.
Their complete-pipe accuracies are respectively 1 and 0. These names deliberately
do not imply that either OCR mode has achieved those results.

```sh
python scripts/benchmark_fieldbook.py --gold tests/data/fieldbook_benchmark/gold.jsonl --run correct=tests/data/fieldbook_benchmark/correct.json --run swapped=tests/data/fieldbook_benchmark/swapped.json --output .fieldbook-benchmark/synthetic-report.json
python -m pytest -q tests/test_fieldbook_benchmark.py
```

This is a development evaluation workflow. It does not establish model accuracy
on private books, authorize automatic pipe acceptance, satisfy physical-hardware
acceptance, or change a release/security hold.

## Review UI verification

`tests/test_relationship_review_ui.py` executes the real JavaScript renderer and
review controller in Node. It checks escaping, original-coordinate bounds, pipe
filters, separate evidence verdicts, malformed graph entries, and delayed page
responses. It needs Node but no browser package or model.

For visual and DOM verification with an existing Node Playwright installation
and Chromium executable:

```sh
python -m pytest -q tests/test_relationship_review_ui.py
python scripts/verify_fieldbook_relationship_ui.py --browser /path/to/existing/chromium
```

Use `--playwright-module /path/to/node_modules/playwright` if the package is not
resolvable from the local environment. The browser harness does not install
dependencies. It renders the actual review HTML, styles, handlers, and embedded
project bridge using two synthetic pages and intercepted API responses. The
startup coordinator is disabled while completed-run fixture state is injected.
It checks image/overlay alignment, original versus enhanced behavior, filtering,
rapid page changes, unsaved review drafts, closing pending requests, and the
project-scoped benchmark download. It neither starts the application backend nor
measures OCR or model performance.

Screenshots and the source-hashed result report are written below
`.fieldbook-benchmark/ui/`. Only synthetic content is used; these results do not
replace integration tests of the backend or a physical-workstation acceptance run.
