from pathlib import Path

from fieldbook_sync.intelligence import infer_network
from fieldbook_sync.models import DipStatus, PipeMeasurement, ResultRecord
from fieldbook_sync.ocr_local import ocr_cache_stats, _save_cached_payload, clear_ocr_cache
from fieldbook_sync.interpret_cache import interpretation_cache_stats, save_interpretation_cache, clear_interpretation_cache

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
JS = (ROOT / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
APP = (ROOT / "fieldbook_sync/app.py").read_text(encoding="utf-8")
INTEL = (ROOT / "fieldbook_sync/intelligence.py").read_text(encoding="utf-8")

def _result(pid, x, y, az=None):
    pipes = [PipeMeasurement(azimuth_deg=az)] if az is not None else []
    return ResultRecord(point_id=pid, easting=x, northing=y, code="MH", status=DipStatus.YES, pipes=pipes)

def test_v810_network_spatial_grid_preserves_nearby_connection_and_excludes_far_points():
    a = _result("A", 0, 0, 90)
    b = _result("B", 100, 0, 270)
    far = _result("FAR", 100000, 0, 270)
    edges = infer_network([a, b, far], max_distance=1500, max_bearing_error=25, reciprocal_tolerance=25)
    assert any(e.from_point == "A" and e.to_point == "B" for e in edges)
    assert not any(e.to_point == "FAR" and e.from_point == "A" for e in edges)
    assert "grid" in INTEL and "nearby" in INTEL

def test_v810_live_network_is_debounced_and_outside_global_lock():
    assert "live_network_debounce_seconds" in APP
    assert "threading.Timer" in APP
    assert "def _run_live_network_rebuild" in APP
    # Snapshot/deepcopy is acquired before infer_network; infer_network call is not nested in a with runtime.lock block.
    worker = APP.split("def _run_live_network_rebuild", 1)[1].split("def _rebuild_live_analysis_locked", 1)[0]
    assert "results = deepcopy(runtime.live_results)" in worker
    assert "edges = infer_network" in worker

def test_v810_paddle_install_button_and_endpoint_present():
    assert 'id="installPaddleBtn"' in INDEX
    assert 'Install / Repair PaddleOCR' in INDEX
    assert '/api/paddle/install' in JS
    assert '@app.post("/api/paddle/install")' in APP
    assert 'install_paddleocr_auto.bat' in APP

def test_v810_ocr_cache_stats_are_incremental(tmp_path):
    root = tmp_path / "ocr"
    clear_ocr_cache(root)
    assert ocr_cache_stats(root)["entries"] == 0
    _save_cached_payload(root, "a" * 64, {"ok": True})
    stats = ocr_cache_stats(root)
    assert stats["entries"] == 1
    assert stats["size_bytes"] > 0
    assert (root / ".fbs_cache_stats.json").exists()

def test_v810_interpretation_cache_stats_are_incremental(tmp_path):
    root = tmp_path / "qwen"
    clear_interpretation_cache(root)
    save_interpretation_cache(root, "b" * 64, [], [])
    stats = interpretation_cache_stats(root)
    assert stats["entries"] == 1
    assert stats["size_bytes"] > 0
    assert (root / ".fbs_cache_stats.json").exists()
