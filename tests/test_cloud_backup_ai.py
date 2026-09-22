from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

import fieldbook_sync.ai_reader as ai_reader
from surveysync.config import ConfigStore


def test_shared_config_accepts_explicit_cloud_backups(tmp_path):
    store = ConfigStore(tmp_path)
    cfg = store.load()
    for provider in ("gemini", "openai", "anthropic"):
        cfg.ai_provider = provider
        store.save(cfg)
        assert store.load().ai_provider == provider


def test_anthropic_vision_reader_keeps_exact_target_gate(tmp_path, monkeypatch):
    image_path = tmp_path / "page.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)
    returned = {
        "entries": [
            {
                "point_id": "2437",
                "point_id_raw": "2437",
                "point_id_confidence": 0.98,
                "dipped": "YES",
                "dipped_confidence": 0.92,
                "basis": "MEASUREMENT",
                "evidence": "DIP 4.62",
                "structure_label": "MH",
                "pipes": [],
                "bbox": [10, 10, 50, 30],
                "notes": "",
            },
            {
                "point_id": "9999",
                "point_id_raw": "9999",
                "point_id_confidence": 0.99,
                "dipped": "YES",
                "dipped_confidence": 0.99,
                "basis": "MEASUREMENT",
                "evidence": "DIP 1.0",
                "structure_label": "MH",
                "pipes": [],
                "bbox": [20, 20, 60, 40],
                "notes": "",
            },
        ],
        "unmatched": [],
    }

    class Response:
        status_code = 200
        text = ""
        def json(self):
            return {
                "content": [{"type": "text", "text": json.dumps(returned)}],
                "usage": {"input_tokens": 120, "output_tokens": 80},
            }

    captured = {}
    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        return Response()

    monkeypatch.setattr(ai_reader.requests, "post", fake_post)
    evidence, unmatched, usage = ai_reader.read_page_anthropic(
        image_path=str(image_path),
        mime_type="image/jpeg",
        source_name="book.pdf",
        page_number=1,
        page_id="p1",
        target_point_ids=["2437"],
        api_key="test-key",
        model="claude-sonnet-5",
    )
    assert captured["url"] == ai_reader.ANTHROPIC_MESSAGES_URL
    assert captured["headers"]["x-api-key"] == "test-key"
    assert len(evidence) == 1 and evidence[0].matched_point_id == "2437"
    assert any(x.point_id_raw == "9999" for x in unmatched)
    assert usage.requests == 1 and usage.total_tokens == 200


def test_fieldbook_ui_exposes_all_cloud_backups_but_auto_is_local_only():
    root = Path(__file__).resolve().parents[1]
    html = (root / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
    js = (root / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    for provider in ("gemini", "openai", "anthropic"):
        assert f'data-provider="{provider}"' in html
    assert 'id="geminiKey"' in html
    assert 'id="openaiKey"' in html
    assert 'id="anthropicKey"' in html
    assert "Automatic never" in html or "Automatic" in html
    assert "Local-only; no paid cloud fallback" in js
