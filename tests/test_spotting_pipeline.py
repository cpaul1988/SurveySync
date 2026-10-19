"""Exercise the real OCR coordinator, cache, and child-process event transport.

The child supplies synthetic native-contract results. It never imports Paddle or
loads weights: these are integration checks, not handwriting/model benchmarks.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from PIL import Image
import pytest

from fieldbook_sync import ocr_local
from fieldbook_sync.models import FieldBookPage
from fieldbook_sync.text_spotting import MODEL_NAME, validate_spotting_model_dir


WORKER = r"""
import argparse, hashlib, json, sys
from pathlib import Path
sys.path.insert(0, REPO_PATH)
from PIL import Image
from fieldbook_sync.text_spotting import normalize_spotting_result, validate_spotting_model_dir

parser = argparse.ArgumentParser()
parser.add_argument('--manifest', required=True)
parser.add_argument('--ocr-mode', default='blocks')
parser.add_argument('--spotting-model-dir')
parser.add_argument('--prefetch-pages')
parser.add_argument('--page-retries')
parser.add_argument('--enable-hpi', action='store_true')
parser.add_argument('--prefer-gpu', action='store_true')
args = parser.parse_args()
root = Path(__file__).parent
scenario = (root / 'scenario.txt').read_text(encoding='utf-8')
paths = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
with (root / 'calls.jsonl').open('a', encoding='utf-8') as log:
    log.write(json.dumps({'argv': sys.argv[1:], 'paths': paths}) + '\n')
digest = validate_spotting_model_dir(args.spotting_model_dir).asset_sha256 if args.ocr_mode == 'spotting' else ''
def emit(event):
    print('FBS_EVENT|' + json.dumps(event), flush=True)
emit({'event': 'ready', 'total': len(paths), 'ocr_mode': args.ocr_mode,
      'model_asset_sha256': 'f' * 64 if scenario == 'ready_hash_mismatch' else digest,
      'device': 'cpu'})
if scenario == 'idle':
    import time
    time.sleep(30)  # Parent cancellation/timeout test must stop this child promptly.
    sys.exit(0)
for number, path in enumerate(paths, 1):
    with Image.open(path) as im:
        width, height = im.size
    image_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    res = {'input_path': path, 'page_index': 0, 'width': width, 'height': height,
           'model_settings': {'use_layout_detection': False, 'use_doc_preprocessor': False},
           'parsing_res_list': [{'block_content': '001A', 'block_bbox': [10, 10, 40, 30], 'block_label': 'text'}],
           'spotting_res': {'rec_texts': ['001A'], 'rec_polys': [[[10, 10], [40, 10], [40, 30], [10, 30]]]}}
    data = {'res': res}
    if args.ocr_mode == 'spotting':
        data = normalize_spotting_result(data, image_path=path, image_sha256=image_hash,
                                        asset_sha256=digest, expected_image_size=(width, height))
        meta = data['res']['spotting_metadata']
        if scenario == 'payload_hash_mismatch':
            meta['model_asset_sha256'] = 'f' * 64
        elif scenario == 'image_hash_mismatch':
            meta['image_sha256'] = 'f' * 64
        elif scenario == 'dimension_mismatch':
            meta['input_image_size'] = [width + 1, height]
        elif scenario == 'missing_spotting':
            data['res'].pop('spotting_res')
    emit({'event': 'page_done', 'index': number, 'total': len(paths), 'attempt': 1, 'result': data})
emit({'event': 'complete', 'total': len(paths)})
"""


@pytest.fixture
def pipeline_case(tmp_path, monkeypatch):
    root = tmp_path / "app"
    root.mkdir()
    repo = str(Path(ocr_local.__file__).parents[1])
    (root / "paddle_bridge.py").write_text(
        WORKER.replace("REPO_PATH", repr(repo)), encoding="utf-8"
    )
    (root / "scenario.txt").write_text("ok", encoding="utf-8")
    assets = tmp_path / "model"
    assets.mkdir()
    (assets / "inference.yml").write_text(
        f"Global:\n  model_name: {MODEL_NAME}\n", encoding="utf-8"
    )
    for name in ("config.json", "preprocessor_config.json", "tokenizer_config.json"):
        (assets / name).write_text("{}", encoding="utf-8")
    for name in ("tokenizer.model", "model.safetensors", "chat_template.jinja"):
        (assets / name).write_bytes(b"synthetic fixture, never loaded")
    original, cleaned = tmp_path / "original.png", tmp_path / "cleaned.png"
    Image.new("RGB", (200, 100), "white").save(original)
    Image.new("RGB", (200, 100), (250, 250, 250)).save(cleaned)
    page = FieldBookPage(
        page_id="p1",
        source_name="synthetic fieldbook",
        page_number=1,
        image_path=str(original),
        enhanced_image_path=str(cleaned),
        mime_type="image/png",
    )
    monkeypatch.setattr(
        ocr_local,
        "paddle_status",
        lambda _: ocr_local.PaddleStatus(
            True,
            sys.executable,
            "synthetic protocol worker",
            verified=True,
            device="cpu",
        ),
    )
    monkeypatch.setattr(
        ocr_local,
        "build_performance_plan",
        lambda _: SimpleNamespace(
            cache_enabled=True,
            prefetch_pages=4,
            enable_hpi=True,
            prefer_gpu=True,
            paddle_cpu_threads=1,
        ),
    )
    return SimpleNamespace(root=root, assets=assets, page=page, cache=tmp_path / "ocr-cache")


def run(case, **kwargs):
    return ocr_local.run_paddle_pages(
        [case.page],
        case.root,
        timeout=15,
        cache_dir=case.cache,
        spotting_model_dir=str(case.assets),
        **kwargs,
    )


def calls(case):
    path = case.root / "calls.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_mode_and_asset_content_separate_real_cache_entries(pipeline_case):
    case = pipeline_case
    flags = []
    run(case, ocr_mode="blocks")
    assert len(calls(case)) == 1
    run(case, ocr_mode="spotting", page_callback=lambda *args: flags.append(args[-1]))
    assert flags == [False]
    assert len(calls(case)) == 2
    flags.clear()
    run(case, ocr_mode="spotting", page_callback=lambda *args: flags.append(args[-1]))
    assert flags == [True]
    assert len(calls(case)) == 2  # The second spotting job never starts a worker.
    (case.assets / "model.safetensors").write_bytes(b"changed synthetic weights")
    flags.clear()
    run(case, ocr_mode="spotting", page_callback=lambda *args: flags.append(args[-1]))
    assert flags == [False]
    assert len(calls(case)) == 3
    assert len(list(case.cache.rglob("*.json.gz"))) == 6  # Two views for each configuration.


def test_explicit_spotting_cli_is_cpu_native_and_manifest_is_local(pipeline_case):
    case = pipeline_case
    run(case, ocr_mode="spotting")
    call = calls(case)[0]
    argv = call["argv"]
    assert argv[argv.index("--ocr-mode") + 1] == "spotting"
    assert argv[argv.index("--spotting-model-dir") + 1] == str(case.assets.resolve())
    assert argv[argv.index("--prefetch-pages") + 1] == "1"
    assert "--enable-hpi" not in argv and "--prefer-gpu" not in argv
    assert call["paths"] == [case.page.image_path, case.page.enhanced_image_path]
    assert not Path(argv[argv.index("--manifest") + 1]).exists()  # Parent cleaned it up.


def test_source_view_provenance_survives_worker_and_cache(pipeline_case):
    case = pipeline_case
    model_hash = validate_spotting_model_dir(case.assets).asset_sha256
    fresh = run(case, ocr_mode="spotting")[0]
    cached = run(case, ocr_mode="spotting")[0]
    assert fresh == cached
    blocks = ocr_local._extract_blocks(cached)
    assert len(blocks) == 2  # Matching text/box from two views still has two sources.
    assert {b["source_view"] for b in blocks} == {"original", "grid_cleaned"}
    expected = {
        "original": hashlib.sha256(Path(case.page.image_path).read_bytes()).hexdigest(),
        "grid_cleaned": hashlib.sha256(
            Path(case.page.enhanced_image_path).read_bytes()
        ).hexdigest(),
    }
    for block in blocks:
        assert block["source_image_sha256"] == expected[block["source_view"]]
        assert block["provenance"]["image_sha256"] == block["source_image_sha256"]
        assert block["provenance"]["model_asset_sha256"] == model_hash
        assert block["block_polygon"] == [[10, 10], [40, 10], [40, 30], [10, 30]]


@pytest.mark.parametrize(
    "scenario",
    [
        "ready_hash_mismatch",
        "payload_hash_mismatch",
        "image_hash_mismatch",
        "dimension_mismatch",
        "missing_spotting",
    ],
)
def test_mismatched_worker_evidence_is_not_published_or_cached(pipeline_case, scenario):
    case = pipeline_case
    (case.root / "scenario.txt").write_text(scenario, encoding="utf-8")
    published = []
    with pytest.raises(RuntimeError):
        run(case, ocr_mode="spotting", page_callback=lambda *args: published.append(args))
    assert published == []
    assert not list(case.cache.rglob("*.json.gz"))


def test_invalid_cached_spotting_is_discarded_before_publication(pipeline_case):
    case = pipeline_case
    run(case, ocr_mode="spotting")
    for path in case.cache.rglob("*.json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            entry = json.load(stream)
        entry["payload"]["res"]["spotting_metadata"]["model_asset_sha256"] = "f" * 64
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump(entry, stream)
    published = []
    # Corrupt cache is an untrusted prior observation and must trigger new work.
    run(case, ocr_mode="spotting", page_callback=lambda *args: published.append(args))
    assert len(calls(case)) == 2
    assert [args[-1] for args in published] == [False]
    valid_hash = validate_spotting_model_dir(case.assets).asset_sha256
    assert all(
        b["provenance"]["model_asset_sha256"] == valid_hash
        for b in ocr_local._extract_blocks(published[0][2])
    )


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_real_spotting_worker_can_be_cancelled_or_timed_out(pipeline_case, monkeypatch, stop):
    case = pipeline_case
    (case.root / "scenario.txt").write_text("idle", encoding="utf-8")
    processes = []
    real_popen = ocr_local.subprocess.Popen

    def spawn(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        processes.append(proc)
        return proc

    monkeypatch.setattr(ocr_local.subprocess, "Popen", spawn)
    cancelled = False

    def progress(_completed, _total, message):
        nonlocal cancelled
        if stop == "cancel" and "model ready" in message:
            cancelled = True

    error = ocr_local.PaddleCancelled if stop == "cancel" else RuntimeError
    with pytest.raises(error, match="cancelled|no progress"):
        ocr_local.run_paddle_pages(
            [case.page],
            case.root,
            timeout=1,
            cache_dir=case.cache,
            ocr_mode="spotting",
            spotting_model_dir=str(case.assets),
            cancel_check=lambda: cancelled,
            progress_callback=progress,
        )
    assert len(processes) == 1
    assert processes[0].poll() is not None
    assert not list(case.cache.rglob("*.json.gz"))


def test_invalid_spotting_folder_is_a_client_error_before_settings_change(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_FIELD_ROOT", str(tmp_path / "field-storage"))
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path / "surveysync-config"))
    from fastapi import HTTPException
    from fieldbook_sync import app
    from fieldbook_sync.api_models import SettingsIn

    previous = (app.runtime.provider, app.runtime.ocr_mode, app.runtime.spotting_model_dir)
    with pytest.raises(HTTPException) as failure:
        app.api_settings(
            SettingsIn(ocr_mode="spotting", spotting_model_dir=str(tmp_path / "missing"))
        )
    assert failure.value.status_code == 400
    assert (app.runtime.provider, app.runtime.ocr_mode, app.runtime.spotting_model_dir) == previous
