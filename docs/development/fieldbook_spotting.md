# Local PaddleOCR-VL 1.6 text spotting

FieldBook Sync can request localized text from the existing PaddleOCR-VL 1.6
family. Select **spotting** as the OCR mode and provide an existing local native
model folder. **Blocks** remains the default. Spotting is an explicit capability:
missing assets, an incompatible installed API, or a result without the spotting
contract produces an error instead of a result labelled as successful spotting.

This feature supplies recognized text and its location. It does not establish
that a handwritten digit is correct, connect a note to a pipe by itself, or make
an OCR match a verified surveying observation. Review the original image and the
separate spatial evidence before accepting an interpretation.

## Existing model folder

Use the model's own directory, not its parent cache directory or a model name.
For example, a manually selected local folder might be
`C:\Models\PaddleOCR-VL-1.6-0.9B`. No home-directory search or asset download runs
when selecting this mode.

The native export must contain:

| File | Check |
| --- | --- |
| `inference.yml` | `Global.model_name` must be `PaddleOCR-VL-1.6-0.9B`. |
| `config.json` | Nonempty file containing a JSON object. |
| `preprocessor_config.json` | Nonempty file containing a JSON object. |
| `tokenizer_config.json` | Nonempty file containing a JSON object. |
| `tokenizer.model` | Existing, nonempty local tokenizer. |
| `chat_template.jinja` | Existing, nonempty local chat template. |
| Native weights | At least one of `model.safetensors`, `model_state.pdparams`, or `inference.pdparams`. |

The validator also includes any existing `special_tokens_map.json`,
`added_tokens.json`, `generation_config.json`, and `tokenizer.json`. It hashes the
contents of these inference assets, including the weights. The resulting
`asset_sha256` identifies the local selection for provenance and cache keys;
checking it requires reading the weight files. It is a consistency check, not a
verification of the model publisher's signature or a proof that arbitrary files
are valid weights. The native loader must still initialize successfully.

An incomplete Hugging Face cache, a sharded-only export, or a folder containing
another model version is not accepted by this adapter. Repair the local
environment explicitly if necessary. Spotting does not run an installer, obtain
weights, or switch to a remote inference backend.

## Actual API and coordinate contract

The isolated worker uses the public `PaddleOCRVL` wrapper:

```python
pipeline = PaddleOCRVL(
    pipeline_version="v1.6",
    vl_rec_model_name="PaddleOCR-VL-1.6-0.9B",
    vl_rec_model_dir=existing_local_directory,
    vl_rec_backend="native",
    use_layout_detection=False,
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_queues=False,
    device="cpu",
)
results = pipeline.predict(
    image_path,
    prompt_label="spotting",
    use_layout_detection=False,
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_queues=False,
)
```

The installed wrapper must explicitly expose these controls. A permissive
`**kwargs` signature is not enough to establish support. The checked upstream
implementation returns `result.json["res"]["spotting_res"]` with parallel
`rec_texts` and `rec_polys` arrays. Each polygon contains four `[x, y]` points in
**input-image pixels**. PaddleX already converts the model's normalized 0–1000
location tokens back into pixels and compensates for its internal enlargement.
Do not divide these returned coordinates by 1000 a second time.

`fieldbook_sync.text_spotting.normalize_spotting_result` produces one
`parsing_res_list` block per text. Each block includes `block_content`,
`block_bbox`, `block_polygon`, source name, and provenance. Confidence is `None`:
this API does not supply a calibrated recognition probability. The native
`spotting_res` is retained and its input-image coordinate space is labelled.

Provenance records the exact input image path and SHA-256, model asset SHA-256,
input and page dimensions, crop rectangle, rotation, and native polygon. The
adapter rejects mismatched array lengths, invalid text, nonfinite or out-of-image
coordinates, degenerate/crossed quadrilaterals, and unexpected preprocessing.

The parent currently submits full-page original and grid-cleaned views with the
same geometry, after EXIF orientation has been applied. Both observations retain
their source role and hash. The helper also supports a documented crop followed
by a clockwise 0/90/180/270-degree rotation and resizing through `ViewTransform`
and `map_polygon_to_page`. Those transforms map the polygon back to original-page
pixels. The current parent requires the full-page identity transform; it does
not silently infer a crop, deskew, or unwarping transform from an image.

## Worker, cache, and resource limits

The app passes `--ocr-mode spotting --spotting-model-dir <local-directory>` to the
existing isolated worker. The app's spotting path uses CPU inference, one-page
prefetch, and no HPI or preferred-GPU flag, leaving the small GPU available for
the local vision model. Existing process cancellation, timeouts, and streamed
page reporting remain in use. This does not establish a speed or RAM guarantee
for a particular Windows computer or GTX 1650.

Before importing OCR dependencies, the spotting worker sets
`PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK`, `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`,
and `HF_HUB_DISABLE_TELEMETRY`. It uses an explicit native model directory and a
process-local audit hook that rejects Python DNS/connect/sendto operations. The
hook is not an operating-system sandbox for arbitrary native dependency code.

OCR cache keys separate block versus spotting mode, input-image contents, and
the selected model asset digest. The parent validates incoming and cached
spotting metadata against the current input image, dimensions, and selected
model. A corrupt cached observation is recomputed. Inconsistent fresh evidence
is rejected before publication and cache writing. Switching modes does not
reinterpret a block-mode cache entry as spotted text.

## Verification and remaining acceptance work

Run the focused suite from the repository with its development environment:

```text
python -m pytest -q tests/test_text_spotting.py tests/test_spotting_pipeline.py tests/test_paddle_bridge_packaging.py tests/test_spatial_fieldbook_preprocessing.py
python -m ruff check --select F paddle_bridge.py fieldbook_sync/text_spotting.py tests/test_text_spotting.py tests/test_spotting_pipeline.py
```

The adapter fixtures cover the upstream pixel schema, all quarter-turns, crop and
resize reversal, malformed geometry, local asset identity/hash changes, and
explicit capability failure. The integration tests run the real coordinator,
gzip cache, and event transport with an actual synthetic child process. They
check CLI arguments, cache reuse/separation, source-view provenance, and rejection
of mismatched worker/cache evidence. No synthetic test loads Paddle weights or
measures handwriting recognition.

A real local Paddle runtime and model were unavailable in the development test
environment. Windows model initialization, performance, and field-book accuracy
remain acceptance work. Measure exact PointID/digit transcription and spatial
association separately on held-out field-book pages, retaining the original
image for review. Generic document benchmarks do not establish either outcome.

## Primary implementation references

- [Public PaddleOCR wrapper and prediction arguments](https://github.com/PaddlePaddle/PaddleOCR/blob/dab3fe35379033fdcb2d0e9572fac0b36c9a9ebf/paddleocr/_pipelines/paddleocr_vl.py)
- [PaddleX spotting execution and input-image dimensions](https://github.com/PaddlePaddle/PaddleX/blob/ffb64904d23708863ff5b8da312a5cbd52a7f462/paddlex/inference/pipelines/paddleocr_vl/pipeline.py)
- [PaddleX spotting token-to-pixel conversion](https://github.com/PaddlePaddle/PaddleX/blob/ffb64904d23708863ff5b8da312a5cbd52a7f462/paddlex/inference/pipelines/paddleocr_vl/uilts.py)
- [Native tokenizer, processor, and model loading](https://github.com/PaddlePaddle/PaddleX/blob/ffb64904d23708863ff5b8da312a5cbd52a7f462/paddlex/inference/models/doc_vlm/predictor.py)
- [Native model-file resolution](https://github.com/PaddlePaddle/PaddleX/blob/ffb64904d23708863ff5b8da312a5cbd52a7f462/paddlex/inference/models/utils/model_paths.py)
