from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from PIL import Image
import pytest

import paddle_bridge
from fieldbook_sync.text_spotting import (
    MODEL_NAME,
    SOURCE,
    SpottingCapabilityError,
    SpottingError,
    ViewTransform,
    map_polygon_to_page,
    normalize_spotting_result,
    require_spotting_api,
    validate_spotting_model_dir,
)


@pytest.fixture
def model_dir(tmp_path):
    directory = tmp_path / "local-vl"
    directory.mkdir()
    (directory / "inference.yml").write_text(
        f"Global:\n  model_name: {MODEL_NAME}\n", encoding="utf-8"
    )
    for name in ("config.json", "preprocessor_config.json", "tokenizer_config.json"):
        (directory / name).write_text("{}", encoding="utf-8")
    (directory / "tokenizer.model").write_bytes(b"synthetic tokenizer, never loaded")
    (directory / "chat_template.jinja").write_text("{{ messages }}", encoding="utf-8")
    (directory / "model.safetensors").write_bytes(b"synthetic weights, never loaded")
    return directory


@pytest.fixture
def image_path(tmp_path):
    path = tmp_path / "page.png"
    Image.new("RGB", (200, 100), "white").save(path)
    return path


def payload(image_path, *, width=200, height=100, polygon=None):
    return {
        "res": {
            "input_path": str(image_path),
            "page_index": 0,
            "width": width,
            "height": height,
            "model_settings": {"use_layout_detection": False, "use_doc_preprocessor": False},
            "parsing_res_list": [
                {
                    "block_content": "PT 00417",
                    "block_label": "spotting",
                    "block_bbox": [0, 0, width, height],
                }
            ],
            "spotting_res": {
                "rec_texts": ["PT 00417"],
                "rec_polys": [polygon or [[10, 20], [80, 20], [80, 40], [10, 40]]],
            },
        }
    }


def normalize(data, image_path, **kwargs):
    return normalize_spotting_result(
        data,
        image_path=image_path,
        image_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
        **kwargs,
    )


def test_local_asset_digest_tracks_contents_not_location(model_dir, tmp_path):
    import shutil

    first = validate_spotting_model_dir(model_dir)
    moved = tmp_path / "same-assets"
    shutil.copytree(model_dir, moved)
    assert first.directory == model_dir.resolve()
    assert len(first.asset_sha256) == 64
    assert validate_spotting_model_dir(moved).asset_sha256 == first.asset_sha256
    (moved / "model.safetensors").write_bytes(b"different synthetic weights")
    assert validate_spotting_model_dir(moved).asset_sha256 != first.asset_sha256
    (model_dir / "generation_config.json").write_text('{"max_new_tokens": 17}', encoding="utf-8")
    assert validate_spotting_model_dir(model_dir).asset_sha256 != first.asset_sha256


@pytest.mark.parametrize(
    "name,content",
    [
        ("inference.yml", "Global:\n  model_name: PaddleOCR-VL-1.5-0.9B\n"),
        ("inference.yml", "Global: []\n"),
        ("inference.yml", "Global: [\n"),
        ("config.json", "{"),
        ("preprocessor_config.json", "[]"),
        ("tokenizer.model", ""),
    ],
)
def test_invalid_local_export_fails_without_model_import(model_dir, name, content):
    (model_dir / name).write_text(content, encoding="utf-8")
    with pytest.raises(SpottingCapabilityError):
        validate_spotting_model_dir(model_dir)


def test_missing_weight_or_processor_is_explicit(model_dir):
    (model_dir / "model.safetensors").unlink()
    with pytest.raises(SpottingCapabilityError, match="No assets were downloaded"):
        validate_spotting_model_dir(model_dir)
    (model_dir / "model_state.pdparams").write_bytes(b"synthetic")
    (model_dir / "chat_template.jinja").unlink()
    with pytest.raises(SpottingCapabilityError, match="chat_template"):
        validate_spotting_model_dir(model_dir)


@pytest.mark.parametrize(
    "value",
    ["", "https://example.invalid/model", "hf://repo/model", "//server/share", r"\\server\share"],
)
def test_remote_model_sources_are_rejected(value):
    with pytest.raises(SpottingCapabilityError):
        validate_spotting_model_dir(value)


class PublicPipeline:
    def __init__(
        self,
        pipeline_version=None,
        vl_rec_model_name=None,
        vl_rec_model_dir=None,
        vl_rec_backend=None,
        use_layout_detection=None,
        use_doc_orientation_classify=None,
        use_doc_unwarping=None,
        use_queues=None,
        **kwargs,
    ):
        self.options = {
            "pipeline_version": pipeline_version,
            "vl_rec_model_name": vl_rec_model_name,
            "vl_rec_model_dir": vl_rec_model_dir,
            "vl_rec_backend": vl_rec_backend,
            "use_layout_detection": use_layout_detection,
            "use_doc_orientation_classify": use_doc_orientation_classify,
            "use_doc_unwarping": use_doc_unwarping,
            "use_queues": use_queues,
            **kwargs,
        }

    def predict(
        self,
        image,
        *,
        prompt_label=None,
        use_layout_detection=None,
        use_doc_orientation_classify=None,
        use_doc_unwarping=None,
        use_queues=None,
    ):
        return []


def test_api_check_rejects_silent_kwargs_support():
    class OldPipeline:
        def __init__(self, **kwargs):
            pass

        def predict(self, image, **kwargs):
            return []

    require_spotting_api(PublicPipeline)
    with pytest.raises(SpottingCapabilityError, match="Block OCR|block OCR"):
        require_spotting_api(OldPipeline)


def test_pipeline_uses_explicit_local_native_assets(monkeypatch, model_dir):
    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PaddleOCRVL=PublicPipeline))
    model = validate_spotting_model_dir(model_dir)
    pipeline, hpi = paddle_bridge._create_pipeline(False, "cpu", "spotting", model)
    assert hpi is False
    assert pipeline.options == {
        "pipeline_version": "v1.6",
        "vl_rec_model_name": MODEL_NAME,
        "vl_rec_model_dir": str(model_dir.resolve()),
        "vl_rec_backend": "native",
        "use_layout_detection": False,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_queues": False,
        "device": "cpu",
    }
    with pytest.raises(SpottingCapabilityError):
        paddle_bridge._create_pipeline(False, "cpu", "spotting")


def test_pixel_contract_preserves_text_polygon_and_provenance(image_path):
    polygon = [[1000, 200], [1200, 200], [1200, 400], [1000, 400]]
    data = payload(image_path, width=4000, height=2000, polygon=polygon)
    original = copy.deepcopy(data)
    result = normalize(data, image_path, asset_sha256="a" * 64)
    block = result["res"]["parsing_res_list"][0]
    assert block["block_bbox"] == [1000, 200, 1200, 400]  # Pixels, not 0--1000 units.
    assert block["block_polygon"] == polygon
    assert block["block_content"] == "PT 00417"
    assert block["confidence"] is None
    assert block["source"] == SOURCE
    assert block["provenance"]["image_path"] == str(image_path.resolve())
    assert block["provenance"]["input_polygon"] == polygon
    assert block["provenance"]["model_asset_sha256"] == "a" * 64
    assert result["res"]["spotting_res"] == original["res"]["spotting_res"]
    assert data == original  # Caller-owned native result is unchanged.


@pytest.mark.parametrize(
    "rotation,size,polygon",
    [
        (0, (400, 200), [[20, 30], [100, 30], [100, 60], [20, 60]]),
        (90, (200, 400), [[170, 20], [170, 100], [140, 100], [140, 20]]),
        (180, (400, 200), [[380, 170], [300, 170], [300, 140], [380, 140]]),
        (270, (200, 400), [[30, 380], [30, 300], [60, 300], [60, 380]]),
        (90, (400, 800), [[340, 40], [340, 200], [280, 200], [280, 40]]),
    ],
)
def test_crop_quarter_turn_and_resize_return_to_original_page(rotation, size, polygon):
    transform = ViewTransform(1000, 800, (100, 200, 500, 400), rotation)
    result = map_polygon_to_page(
        polygon, image_width=size[0], image_height=size[1], transform=transform
    )
    assert result == [[120, 230], [200, 230], [200, 260], [120, 260]]


def test_normalization_retains_native_coordinates_for_transformed_view(image_path):
    polygon = [[170, 20], [170, 100], [140, 100], [140, 20]]
    result = normalize(
        payload(image_path, width=200, height=400, polygon=polygon),
        image_path,
        transform=ViewTransform(1000, 800, (100, 200, 500, 400), 90),
    )
    res = result["res"]
    assert (res["width"], res["height"]) == (1000, 800)
    assert res["parsing_res_list"][0]["block_bbox"] == [120, 230, 200, 260]
    assert res["spotting_res"]["rec_polys"][0] == polygon
    assert res["spotting_metadata"]["input_image_size"] == [200, 400]
    assert res["spotting_metadata"]["native_coordinate_space"] == "input_image_pixels"


@pytest.mark.parametrize(
    "polygon",
    [
        [[-1, 0], [20, 0], [20, 20], [0, 20]],
        [[0, 0], [201, 0], [200, 20], [0, 20]],
        [[0, 0], [20, 20], [0, 20], [20, 0]],
        [[0, 0], [20, 0], [20, 0], [0, 0]],
        [[0, 0], [20, 0], [20, 20]],
        [[False, 0], [20, 0], [20, 20], [0, 20]],
        [[float("nan"), 0], [20, 0], [20, 20], [0, 20]],
        [[float("inf"), 0], [20, 0], [20, 20], [0, 20]],
        [[10**500, 0], [20, 0], [20, 20], [0, 20]],
    ],
)
def test_malformed_geometry_is_rejected_instead_of_clamped(image_path, polygon):
    with pytest.raises(SpottingError):
        normalize(payload(image_path, polygon=polygon), image_path)


@pytest.mark.parametrize(
    "transform",
    [
        ViewTransform(1000, 800, rotation_cw=45),
        ViewTransform(1000, 800, rotation_cw=True),
        ViewTransform(1000, 800, (-1, 0, 100, 100)),
        ViewTransform(1000, 800, (100, 100, 100, 200)),
        ViewTransform(1000, 800, (0, 0, 1001, 800)),
    ],
)
def test_unknown_or_invalid_view_transform_is_rejected(image_path, transform):
    with pytest.raises(SpottingError):
        normalize(payload(image_path), image_path, transform=transform)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["spotting_res"].update(rec_polys=[]),
        lambda r: r["spotting_res"].update(rec_texts=[None]),
        lambda r: r["spotting_res"].update(rec_texts=[" "]),
        lambda r: r.update(width=True),
        lambda r: r.update(height=0),
        lambda r: r.update(input_path="another-image.png"),
        lambda r: r.update(input_path={"bad": "path"}),
        lambda r: r["model_settings"].update(use_doc_preprocessor=True),
        lambda r: r["model_settings"].update(use_layout_detection=True),
    ],
)
def test_malformed_response_is_not_spatial_evidence(image_path, mutation):
    data = payload(image_path)
    mutation(data["res"])
    with pytest.raises(SpottingError):
        normalize(data, image_path)


def test_empty_spotting_is_empty_evidence_and_missing_spotting_is_capability_failure(image_path):
    data = payload(image_path)
    data["res"]["spotting_res"] = {"rec_texts": [], "rec_polys": []}
    assert normalize(data, image_path)["res"]["parsing_res_list"] == []
    data["res"].pop("spotting_res")
    with pytest.raises(SpottingCapabilityError, match="did not return spotting_res"):
        normalize(data, image_path)


def test_dimension_mismatch_or_unhashed_image_is_rejected(image_path):
    with pytest.raises(SpottingError, match="dimensions"):
        normalize(payload(image_path), image_path, expected_image_size=(400, 200))
    with pytest.raises(SpottingError, match="SHA-256"):
        normalize_spotting_result(payload(image_path), image_path=image_path, image_sha256="")


def test_predict_uses_spotting_controls_and_block_default_is_unchanged(image_path, model_dir):
    class Fake:
        def predict(self, path, **kwargs):
            self.kwargs = kwargs
            return [SimpleNamespace(json=payload(path))]

    pipeline = Fake()
    model = validate_spotting_model_dir(model_dir)
    result = paddle_bridge._predict_result(pipeline, str(image_path), "spotting", model)
    assert pipeline.kwargs == {
        "prompt_label": "spotting",
        "use_layout_detection": False,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_queues": False,
    }
    assert result["res"]["ocr_mode"] == "spotting"
    result = paddle_bridge._predict_result(pipeline, str(image_path), "blocks", None)
    assert pipeline.kwargs == {}
    assert result == payload(str(image_path))
    assert paddle_bridge._parse_args(["paddle_bridge.py", str(image_path)])[5:] == ("blocks", None)


def test_explicit_spotting_requires_local_directory_before_runtime_import(image_path):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(paddle_bridge.__file__)),
            "--ocr-mode",
            "spotting",
            str(image_path),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    event = json.loads(result.stdout.split(paddle_bridge.PREFIX)[1])
    assert event["event"] == "fatal"
    assert event["code"] == "spotting_unavailable"
    assert "--spotting-model-dir" in event["error"]


def test_spotting_installs_offline_flags_and_network_audit_guard():
    code = """
import os, sys
from paddle_bridge import _configure_spotting_offline
from fieldbook_sync.text_spotting import SpottingCapabilityError
_configure_spotting_offline()
assert os.environ['HF_HUB_OFFLINE'] == '1'
assert os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] == 'True'
try:
    # Emit CPython's connection audit event without constructing a socket: the
    # test runner may prohibit socket creation before Python's connect guard.
    sys.audit('socket.connect', None, ('127.0.0.1', 9))
except SpottingCapabilityError:
    print('blocked before connect')
else:
    raise AssertionError('network guard did not block')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(paddle_bridge.__file__).parent,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "blocked before connect" in result.stdout


def test_missing_runtime_capability_is_fatal_and_never_relabelled_as_blocks(
    monkeypatch, image_path, model_dir
):
    class MissingSpotting:
        def predict(self, path, **kwargs):
            data = payload(path)
            data["res"].pop("spotting_res")
            return [SimpleNamespace(json=data)]

    events = []
    monkeypatch.setattr(paddle_bridge, "emit", events.append)
    monkeypatch.setattr(paddle_bridge, "_configure_spotting_offline", lambda: None)
    monkeypatch.setattr(paddle_bridge, "_choose_device", lambda _: ("cpu", False, "synthetic"))
    monkeypatch.setattr(paddle_bridge, "_create_pipeline", lambda *args: (MissingSpotting(), False))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "paddle_bridge.py",
            "--ocr-mode",
            "spotting",
            "--spotting-model-dir",
            str(model_dir),
            str(image_path),
        ],
    )
    assert paddle_bridge.main() == 1
    assert events[-1]["event"] == "fatal"
    assert events[-1]["code"] == "spotting_unavailable"
    assert not any(e["event"] in ("page_done", "page_retry", "complete") for e in events)
