from PIL import Image, ImageDraw
import numpy as np
import pytest

from fieldbook_sync.image_processing import enhance_fieldbook_image
from fieldbook_sync.spatial_preprocessing import structure_context_bbox, suppress_grid


def test_grid_cleanup_preserves_dark_geometry_and_isolated_colored_notes():
    im = Image.new("RGB", (300, 200), "white")
    draw = ImageDraw.Draw(im)
    draw.line((0, 100, 299, 100), fill=(100, 170, 235), width=2)
    draw.line((120, 0, 120, 199), fill=(235, 130, 130), width=2)
    draw.ellipse((110, 80, 150, 120), outline=(30, 30, 30), width=2)
    draw.rectangle((20, 20, 30, 25), fill=(100, 170, 235))
    before = np.array(im)
    result = np.array(suppress_grid(im))
    dark = before.max(axis=2) < 90
    assert np.array_equal(result[dark], before[dark])
    assert tuple(result[100, 50]) == (255, 255, 255)
    assert tuple(result[22, 25]) == (100, 170, 235)
    assert np.array_equal(np.array(im), before)


def test_derivative_keeps_dimensions_and_source_bytes(tmp_path):
    source = tmp_path / "page.png"
    output = tmp_path / "ocr.jpg"
    Image.new("RGB", (321, 231), "white").save(source)
    original = source.read_bytes()
    enhance_fieldbook_image(source, output)
    with Image.open(output) as result:
        assert result.size == (321, 231)
    assert source.read_bytes() == original
    with pytest.raises(ValueError):
        enhance_fieldbook_image(source, source)
    assert source.read_bytes() == original


@pytest.mark.parametrize("box", [[1, 2, 15, 12], [970, 980, 1000, 1000], [450, 400, 490, 420]])
def test_context_contains_id_and_nearby_notes_without_leaving_page(box):
    out = structure_context_bbox(box)
    assert 0 <= out[0] <= box[0] < box[2] <= out[2] <= 1000
    assert 0 <= out[1] <= box[1] < box[3] <= out[3] <= 1000
    assert out[2] - out[0] >= 440
    assert out[3] - out[1] >= 360


def test_dual_view_ocr_keeps_original_evidence_and_page_identity(tmp_path, monkeypatch):
    from fieldbook_sync import ocr_local
    from fieldbook_sync.models import FieldBookPage

    source, cleaned = tmp_path / "original.png", tmp_path / "cleaned.png"
    Image.new("RGB", (200, 100), "white").save(source)
    Image.new("RGB", (200, 100), "white").save(cleaned)
    page = FieldBookPage(page_id="p1", source_name="book", page_number=1,
                         image_path=str(source), enhanced_image_path=str(cleaned), mime_type="image/png")
    callbacks = []

    def worker(pages, root, timeout, **kwargs):
        assert len(pages) == 2
        assert pages[0].enhanced_image_path is None
        assert pages[1].enhanced_image_path == str(cleaned)
        for i, target in enumerate(pages):
            kwargs["page_callback"](i + 1, target, {"parsing_res_list": [{
                "block_content": "001A" if i == 0 else "001B", "block_bbox": [10, 10, 40, 30]
            }]}, False)

    monkeypatch.setattr(ocr_local, "_run_paddle_views", worker)
    result = ocr_local.run_paddle_pages([page], tmp_path, page_callback=lambda *args: callbacks.append(args))
    assert len(result) == len(callbacks) == 1
    assert callbacks[0][1].page_id == "p1"
    assert {c.point_id for c in ocr_local.locate_target_ids(page, result[0], ["001A", "001B"])} == {"001A", "001B"}


def test_four_gb_gpu_reserves_memory_for_vision():
    from fieldbook_sync.performance import HardwareProfile, build_performance_plan
    hw = HardwareProfile(logical_cores=12, physical_cores=6, total_ram_bytes=32 * 1024**3,
                         available_ram_bytes=20 * 1024**3, platform="Windows",
                         nvidia_gpu=True, nvidia_vram_bytes=4 * 1024**3)
    assert build_performance_plan("auto", hw).prefer_gpu is False


def test_profile_change_invalidates_interpretation_cache(tmp_path):
    from fieldbook_sync.interpret_cache import interpretation_cache_key
    path = tmp_path / "same.png"
    Image.new("RGB", (20, 20), "white").save(path)
    args = dict(point_id="001A", model="local")
    assert interpretation_cache_key(path, profile_context="old rules", **args) != interpretation_cache_key(path, profile_context="new rules", **args)
