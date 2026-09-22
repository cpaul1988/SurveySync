from __future__ import annotations

from pathlib import Path

from PIL import Image

from fieldbook_sync.image_processing import ensure_enhanced_pages_parallel
from fieldbook_sync.models import FieldBookPage
from fieldbook_sync.ocr_local import (
    _load_cached_payload,
    _ocr_cache_key,
    _save_cached_payload,
    clear_ocr_cache,
    ocr_cache_stats,
)
from fieldbook_sync.performance import HardwareProfile, build_performance_plan

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "fieldbook_sync" / "static" / "index.html").read_text(encoding="utf-8")
APPJS = (ROOT / "fieldbook_sync" / "static" / "app.js").read_text(encoding="utf-8")
BRIDGE = (ROOT / "paddle_bridge.py").read_text(encoding="utf-8")


def test_v807_auto_performance_plan_uses_multicore_and_bounded_prefetch():
    hw = HardwareProfile(
        logical_cores=16,
        physical_cores=8,
        total_ram_bytes=32 * 1024**3,
        available_ram_bytes=24 * 1024**3,
        platform="Windows",
    )
    plan = build_performance_plan("auto", hw)
    assert plan.effective_mode == "high"
    assert 2 <= plan.enhancement_workers <= 8
    assert 6 <= plan.paddle_cpu_threads <= 16
    assert 2 <= plan.prefetch_pages <= 12


def test_v807_safe_plan_stays_conservative():
    hw = HardwareProfile(
        logical_cores=4,
        physical_cores=2,
        total_ram_bytes=4 * 1024**3,
        available_ram_bytes=3 * 1024**3,
        platform="Windows",
    )
    plan = build_performance_plan("safe", hw)
    assert plan.enhancement_workers == 1
    assert plan.paddle_cpu_threads <= 4
    assert plan.prefetch_pages <= 2


def test_v807_ocr_cache_round_trip_and_clear(tmp_path: Path):
    image = tmp_path / "page.jpg"
    Image.new("RGB", (80, 60), "white").save(image)
    cache = tmp_path / "cache"
    key = _ocr_cache_key(image)
    payload = {"parsing_res_list": [{"block_content": "区 café Ω", "block_bbox": [1, 2, 3, 4]}]}
    _save_cached_payload(cache, key, payload)
    assert _load_cached_payload(cache, key) == payload
    stats = ocr_cache_stats(cache)
    assert stats["entries"] == 1
    assert stats["size_bytes"] > 0
    clear_ocr_cache(cache)
    assert ocr_cache_stats(cache)["entries"] == 0


def test_v807_cache_is_content_addressed(tmp_path: Path):
    image = tmp_path / "page.jpg"
    Image.new("RGB", (20, 20), "white").save(image)
    before = _ocr_cache_key(image)
    Image.new("RGB", (20, 20), "black").save(image)
    after = _ocr_cache_key(image)
    assert before != after


def test_v807_parallel_page_enhancement(tmp_path: Path):
    pages = []
    for i in range(4):
        src = tmp_path / f"p{i}.jpg"
        Image.new("RGB", (120, 100), "white").save(src)
        pages.append(FieldBookPage(page_id=f"p{i}", source_name="book.pdf", page_number=i + 1, image_path=str(src), mime_type="image/jpeg"))
    progress = []
    count = ensure_enhanced_pages_parallel(
        pages,
        tmp_path / "enhanced",
        max_workers=3,
        progress_callback=lambda done, total: progress.append((done, total)),
    )
    assert count == 4
    assert progress[-1] == (4, 4)
    assert all(p.enhanced_image_path and Path(p.enhanced_image_path).exists() for p in pages)


def test_v807_performance_ui_and_cache_controls_present():
    assert 'id="performanceMode"' in INDEX
    assert 'id="performanceSummary"' in INDEX
    assert 'id="clearAnalysisCacheBtn"' in INDEX
    assert "performance_mode" in APPJS
    assert "/api/analysis-cache/clear" in APPJS


def test_v807_bridge_has_bounded_ram_prefetch():
    assert "--prefetch-pages" in BRIDGE
    assert "ThreadPoolExecutor(max_workers=1" in BRIDGE
    assert "Path(path).read_bytes()" in BRIDGE
