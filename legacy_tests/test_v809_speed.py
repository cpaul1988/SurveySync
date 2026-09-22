from __future__ import annotations

from pathlib import Path

from PIL import Image

from fieldbook_sync.ai_reader import ProviderUsage
from fieldbook_sync.interpret_cache import (
    clear_interpretation_cache,
    interpretation_cache_key,
    interpretation_cache_stats,
    load_interpretation_cache,
    save_interpretation_cache,
)
from fieldbook_sync.models import DipStatus, EvidenceBasis, FieldBookPage, PageEvidence
from fieldbook_sync.ocr_local import locate_target_ids
from fieldbook_sync.performance import HardwareProfile, build_performance_plan

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "fieldbook_sync" / "app.py").read_text(encoding="utf-8")
BRIDGE = (ROOT / "paddle_bridge.py").read_text(encoding="utf-8")
INDEX = (ROOT / "fieldbook_sync" / "static" / "index.html").read_text(encoding="utf-8")
APPJS = (ROOT / "fieldbook_sync" / "static" / "app.js").read_text(encoding="utf-8")
GPU_BAT = (ROOT / "Install_PaddleOCR_GPU_Optional.bat").read_text(encoding="utf-8")
CPU_BAT = (ROOT / "install_paddleocr_local.bat").read_text(encoding="utf-8")


def test_v809_accuracy_first_plan_can_consider_safe_overlap_on_gpu_workstation():
    hw = HardwareProfile(
        logical_cores=20,
        physical_cores=10,
        total_ram_bytes=32 * 1024**3,
        available_ram_bytes=20 * 1024**3,
        platform="Windows 11",
        nvidia_gpu=True,
        nvidia_gpu_name="RTX Workstation",
        nvidia_vram_bytes=8 * 1024**3,
        nvidia_compute_capability=8.6,
        nvidia_driver_cuda=12.6,
    )
    plan = build_performance_plan("auto", hw)
    assert plan.accuracy_first is True
    assert plan.enable_hpi is True
    assert plan.prefer_gpu is True
    assert plan.interpretation_cache_enabled is True
    assert plan.near_match_routing is True
    assert plan.pipeline_overlap is True
    assert plan.qwen_workers == 1


def test_v809_safe_mode_does_not_force_hpi():
    hw = HardwareProfile(
        logical_cores=4,
        physical_cores=2,
        total_ram_bytes=8 * 1024**3,
        available_ram_bytes=4 * 1024**3,
        platform="Windows",
    )
    plan = build_performance_plan("safe", hw)
    assert plan.accuracy_first is True
    assert plan.enable_hpi is False
    assert plan.pipeline_overlap is False


def test_v809_qwen_interpretation_cache_round_trip(tmp_path: Path):
    image = tmp_path / "crop.jpg"
    Image.new("RGB", (160, 100), "white").save(image)
    cache = tmp_path / "qcache"
    key = interpretation_cache_key(image, point_id="12345", model="qwen3.8:27b")
    ev = PageEvidence(
        matched_point_id="12345",
        basis=EvidenceBasis.MEASUREMENT,
        source_name="book.pdf",
        page_number=7,
        page_id="p7",
        point_id_raw="12345",
        point_id_confidence=.98,
        dipped=DipStatus.YES,
        dipped_confidence=.94,
        evidence="visible dip",
    )
    save_interpretation_cache(cache, key, [ev], [], ProviderUsage(requests=1, total_tokens=42))
    loaded = load_interpretation_cache(cache, key)
    assert loaded is not None
    evidence, unmatched, usage = loaded
    assert evidence[0].matched_point_id == "12345"
    assert unmatched == []
    assert usage.requests == 1
    assert interpretation_cache_stats(cache)["entries"] == 1
    clear_interpretation_cache(cache)
    assert interpretation_cache_stats(cache)["entries"] == 0


def test_v809_near_match_is_routing_hint_only(tmp_path: Path):
    image = tmp_path / "page.jpg"
    Image.new("RGB", (1000, 1000), "white").save(image)
    page = FieldBookPage(page_id="p1", source_name="book.pdf", page_number=1, image_path=str(image), mime_type="image/jpeg")
    payload = {"parsing_res_list": [{"block_content": "Structure 1234S dip 4.2", "block_bbox": [100, 100, 400, 300]}]}
    assert locate_target_ids(page, payload, ["12345"]) == []
    hints = locate_target_ids(page, payload, ["12345"], include_near_matches=True)
    assert len(hints) == 1
    assert hints[0].point_id == "12345"
    assert hints[0].exact_match is False
    assert hints[0].confidence < .98


def test_v809_ambiguous_near_match_is_not_routed(tmp_path: Path):
    image = tmp_path / "page.jpg"
    Image.new("RGB", (1000, 1000), "white").save(image)
    page = FieldBookPage(page_id="p1", source_name="book.pdf", page_number=1, image_path=str(image), mime_type="image/jpeg")
    payload = {"parsing_res_list": [{"block_content": "1234S", "block_bbox": [100, 100, 400, 300]}]}
    hints = locate_target_ids(page, payload, ["12345", "12346"], include_near_matches=True)
    assert hints == []


def test_v809_bridge_has_gpu_hpi_with_safe_fallback():
    assert "--enable-hpi" in BRIDGE
    assert "--prefer-gpu" in BRIDGE
    assert 'device="gpu:0"' not in BRIDGE  # runtime selection, not hard-coded
    assert 'return "gpu:0"' in BRIDGE
    assert "HPI unavailable; using standard inference" in BRIDGE


def test_v809_hybrid_pipeline_keeps_full_accuracy_fallback_and_qwen_cache():
    assert "load_interpretation_cache" in APP
    assert "save_interpretation_cache" in APP
    assert "pipeline_overlap" in APP
    assert "near-match suggested" in APP
    assert "Accuracy-first full-book fallback" in APP
    assert "confirmed_fuzzy_keys" in APP


def test_v809_gpu_and_cache_controls_are_visible():
    assert "PERFORMANCE ENGINE V2" in INDEX
    assert 'id="gpuPerformanceSummary"' in INDEX
    assert 'id="clearAnalysisCacheBtn"' in INDEX
    assert "interpretation_cache" in APPJS
    assert "/api/analysis-cache/clear" in APPJS


def test_v809_installers_are_logged_and_gpu_installer_verifies_cuda():
    assert "PaddleOCR_Install.log" in CPU_BAT
    assert "The prior .paddleenv was NOT replaced" in CPU_BAT
    assert "PaddleOCR_GPU_Install.log" in GPU_BAT
    assert "paddlepaddle-gpu==!GPU_PADDLE_VERSION!" in GPU_BAT
    assert "paddle.device.is_compiled_with_cuda" in GPU_BAT
    assert "paddle.set_device('gpu:0')" in GPU_BAT
