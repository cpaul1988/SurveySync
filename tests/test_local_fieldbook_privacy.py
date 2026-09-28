import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from surveysync.local_inference import local_request, loopback_url, require_local_ollama_model


@pytest.mark.parametrize("url", [
    "https://example.com", "http://192.168.1.1:11434", "http://0.0.0.0",
    "http://127.0.0.1.evil.test", "http://user:pass@127.0.0.1",
    "http://127.0.0.1?host=example.com", "http://[::ffff:192.168.1.1]",
    "file:///tmp/model", "http://127.0.0.1:0", "http://127.0.0.1/proxy",
])
def test_reject_remote_or_ambiguous_endpoints(url):
    with pytest.raises(ValueError):
        loopback_url(url, base=True)


def test_localhost_is_pinned_without_dns():
    assert loopback_url("http://localhost:11434/", base=True) == "http://127.0.0.1:11434"
    assert loopback_url("http://[::1]:11434", base=True) == "http://[::1]:11434"


def test_real_transport_ignores_proxy_and_rejects_redirect(monkeypatch):
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            paths.append(self.path)
            self.send_response(302 if self.path == "/redirect" else 200)
            self.send_header("Location", "/should-not-follow")
            self.end_headers()
            self.wfile.write(b"local")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    root = f"http://127.0.0.1:{server.server_port}"
    try:
        with local_request("GET", root + "/ok", timeout=2) as response:
            assert response.text == "local"
        with pytest.raises(ValueError, match="redirects"):
            local_request("GET", root + "/redirect", timeout=2)
        assert paths == ["/ok", "/redirect"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("reader,kwargs", [
    ("read_page_openai", {"image_path": "missing", "mime_type": "image/jpeg", "source_name": "test", "page_number": 1, "page_id": "p1", "target_point_ids": [], "api_key": "unused"}),
    ("read_page_anthropic", {"image_path": "missing", "mime_type": "image/jpeg", "source_name": "test", "page_number": 1, "page_id": "p1", "target_point_ids": [], "api_key": "unused"}),
    ("read_pages_gemini", {"pages": [], "target_point_ids": [], "api_key": "unused"}),
])
def test_cloud_blocked_before_images_or_network(reader, kwargs, monkeypatch):
    from fieldbook_sync import ai_reader

    def forbidden(*args, **kwargs):
        pytest.fail("Cloud request attempted")

    monkeypatch.setattr(ai_reader.requests, "post", forbidden)
    with pytest.raises(ValueError, match="locked"):
        getattr(ai_reader, reader)(**kwargs)


@pytest.mark.parametrize("metadata", [
    {"remote_host": "https://ollama.com", "remote_model": "other"},
    {"details": {"format": "gguf"}}, {}, [],
])
def test_cloud_alias_or_unverified_weights_blocked(metadata, monkeypatch):
    import surveysync.local_inference as local

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def json(self): return metadata

    monkeypatch.setattr(local, "local_request", lambda *a, **k: Response())
    with pytest.raises(ValueError):
        require_local_ollama_model("http://127.0.0.1:11434", "my-local-alias")


def test_settings_rejection_is_atomic(monkeypatch):
    from fieldbook_sync import app
    from fieldbook_sync.api_models import SettingsIn
    from fastapi import HTTPException

    monkeypatch.setattr(app.runtime, "provider", "manual")
    for payload in (SettingsIn(provider="gemini"), SettingsIn(ollama_base_url="http://example.com")):
        with pytest.raises(HTTPException):
            app.api_settings(payload)
        assert app.runtime.provider == "manual"


@pytest.mark.parametrize("cancel,incomplete", [(True, False), (False, True), (False, False)])
def test_stream_cleanup_and_no_partial_results(tmp_path, monkeypatch, cancel, incomplete):
    import json
    from PIL import Image
    from fieldbook_sync import ai_reader
    from fieldbook_sync.models import FieldBookPage

    path = tmp_path / "page.png"
    Image.new("RGB", (20, 20), "white").save(path)
    page = FieldBookPage(page_id="p", source_name="synthetic", page_number=1,
                         image_path=str(path), mime_type="image/png")
    cancelled = [False]

    class Response:
        status_code = 200
        closed = False
        def iter_lines(self, **kwargs):
            cancelled[0] = cancel
            yield json.dumps({"message": {"content": '{"entries":[],"unmatched":[]}'}, "done": not incomplete})
        def close(self): self.closed = True

    response = Response()
    monkeypatch.setattr(ai_reader, "require_local_ollama_model", lambda *a: None)
    monkeypatch.setattr(ai_reader, "local_request", lambda *a, **k: response)
    args = dict(pages=[page], target_point_ids=["001A"], cancel_check=lambda: cancelled[0])
    if cancel or incomplete:
        with pytest.raises(RuntimeError, match="cancelled|before completion"):
            ai_reader.read_pages_ollama(**args)
    else:
        evidence, unmatched, _ = ai_reader.read_pages_ollama(**args)
        assert evidence == unmatched == []
    assert response.closed
