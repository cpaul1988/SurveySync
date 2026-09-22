import json
from pathlib import Path

from PIL import Image

import fieldbook_sync.ai_reader as ai_reader
from fieldbook_sync.app import _recommend_ollama_model, _ollama_warning_for_model
from fieldbook_sync.errors import classify_exception
from fieldbook_sync.models import FieldBookPage

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "fieldbook_sync/app.py").read_text(encoding="utf-8")
JS = (ROOT / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
HTML = (ROOT / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")


def test_auto_recommends_compact_vision_model_on_4gb_gpu():
    models = ["qwen3-vl:8b-instruct", "qwen3-vl:4b-instruct", "qwen3-vl:2b-instruct"]
    model, reason = _recommend_ollama_model(models, profile="auto", selected="qwen3-vl:8b-instruct", vram_bytes=4 * 1024**3)
    assert model == "qwen3-vl:2b-instruct"
    assert "4.0 GB" in reason


def test_maximum_profile_keeps_large_model_and_warns_on_low_vram():
    models = ["qwen3-vl:8b-instruct", "qwen3-vl:4b-instruct", "qwen3-vl:2b-instruct"]
    model, _ = _recommend_ollama_model(models, profile="maximum", selected="qwen3-vl:4b-instruct", vram_bytes=4 * 1024**3)
    assert model == "qwen3-vl:8b-instruct"
    assert "spill" in _ollama_warning_for_model(model, 4 * 1024**3)


def test_qwen_errors_are_classified_specifically():
    assert classify_exception(RuntimeError("Ollama service is unavailable"), component="qwen").code == "QWN-SVC-001"
    assert classify_exception(RuntimeError("Ollama inference timed out"), component="qwen").code == "QWN-TIMEOUT-001"
    assert classify_exception(RuntimeError("Ollama ran out of memory"), component="qwen").code == "QWN-OOM-001"
    assert classify_exception(RuntimeError("Ollama model 'x' is not installed"), component="qwen").code == "QWN-MODEL-001"


def test_ollama_ps_runtime_split(monkeypatch):
    class FakeResponse:
        status_code = 200
        def json(self):
            return {"models": [{"name": "qwen2.5vl:3b", "size": 1000, "size_vram": 430, "context_length": 4096}]}
    monkeypatch.setattr(ai_reader.requests, "get", lambda *a, **k: FakeResponse())
    running = ai_reader.ollama_running_models()
    assert running[0]["gpu_percent"] == 43.0
    assert running[0]["cpu_percent"] == 57.0


def test_ollama_streaming_reports_progress(tmp_path, monkeypatch):
    image_path = tmp_path / "page.jpg"
    Image.new("RGB", (80, 80), "white").save(image_path)
    page = FieldBookPage(page_id="p1", source_name="book.pdf", page_number=1, image_path=str(image_path), mime_type="image/jpeg")
    output = json.dumps({"entries": [], "unmatched": []})

    class FakeResponse:
        status_code = 200
        text = ""
        def iter_lines(self, decode_unicode=True):
            yield json.dumps({"message": {"content": output[:10]}, "done": False})
            yield json.dumps({"message": {"content": output[10:]}, "done": False})
            yield json.dumps({"message": {"content": ""}, "done": True, "prompt_eval_count": 20, "eval_count": 8})

    monkeypatch.setattr(ai_reader.requests, "post", lambda *a, **k: FakeResponse())
    progress = []
    ev, un, usage = ai_reader.read_pages_ollama(
        pages=[page], target_point_ids=["5000"], model="qwen2.5vl:3b", progress_callback=progress.append
    )
    assert ev == [] and un == []
    assert usage.total_tokens == 28
    assert any(x.get("state") == "generating" for x in progress)
    assert progress[-1]["state"] == "complete"


def test_ui_and_backend_expose_v818_runtime_features():
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == "8.1.21"
    assert 'id="ollamaProfile"' in HTML
    assert 'qwen3-vl:4b-instruct' in HTML
    assert 'Test &amp; Warm Model' in HTML
    assert '@app.post("/api/ollama/warmup")' in APP
    assert '_start_analysis_heartbeat(job_id)' in APP
    assert 'progress_callback=_qwen_progress' in APP
    assert 'Qwen ${job.qwen_state}' in JS
