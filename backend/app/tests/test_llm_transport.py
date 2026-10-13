"""llm_transport: Ollama algılama, taşıma modu, etkin bütçe."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from app.core.config import settings
from app.services import llm_gateway, llm_transport as tr


@pytest.fixture(autouse=True)
def _clear_caches():
    tr.clear_transport_caches()
    yield
    tr.clear_transport_caches()


class _OllamaHandler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/version"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"version":"0.9.0"}')
            return
        if self.path.startswith("/api/ps"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = {
                "models": [{
                    "name": "test-model",
                    "size": 1000,
                    "size_vram": 1000,
                    "context_length": 8192,
                }],
            }
            self.wfile.write(json.dumps(body).encode())
            return
        if self.path.startswith("/api/tags"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"models":[{"name":"test-model"}]}')
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw or b"{}")
        self.server.last_body = body  # type: ignore[attr-defined]
        self.server.last_path = self.path  # type: ignore[attr-defined]

        if self.path.startswith("/api/show"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "model_info": {"llama.context_length": 8192},
            }).encode())
            return

        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            self.wfile.write(json.dumps({"response": "Mer", "done": False}).encode() + b"\n")
            self.wfile.write(json.dumps({
                "response": "haba", "done": True, "prompt_eval_count": 10, "eval_count": 2,
            }).encode() + b"\n")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"response": "cevap", "done": True}).encode())


@pytest.fixture
def ollama_remote(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _OllamaHandler)
    server.last_body = None  # type: ignore[attr-defined]
    server.last_path = None  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"

    from app.services import llm_availability as la

    monkeypatch.setattr(settings, "REMOTE_LLM_ENABLED", True)
    monkeypatch.setattr(settings, "REMOTE_LLM_URL", base)
    monkeypatch.setattr(settings, "REMOTE_LLM_MODEL", "test-model")
    monkeypatch.setattr(settings, "REMOTE_LLM_API_KEY", "")
    monkeypatch.setattr(settings, "REMOTE_LLM_VIRTUAL_KEY", "")
    monkeypatch.setattr(tr, "get_transport_mode", lambda **_k: "auto")
    monkeypatch.setattr(la, "_redis", lambda: None)
    la.reset()
    tr.clear_transport_caches()
    try:
        yield server
    finally:
        la.reset()
        server.shutdown()
        server.server_close()
        tr.clear_transport_caches()


def test_probe_ollama_version(ollama_remote):
    info = tr.probe_ollama_version(settings.REMOTE_LLM_URL)
    assert info and info.get("version") == "0.9.0"
    assert tr.is_remote_ollama() is True


def test_transport_mode_openai_forces_openai(ollama_remote, monkeypatch):
    monkeypatch.setattr(tr, "get_transport_mode", lambda **_k: "openai")
    tr.clear_transport_caches()
    assert tr.is_remote_ollama() is False


def test_transport_mode_ollama_forces_native(ollama_remote, monkeypatch):
    monkeypatch.setattr(tr, "get_transport_mode", lambda **_k: "ollama")
    tr.clear_transport_caches()
    assert tr.is_remote_ollama() is True


def test_effective_budget_min_of_setting_and_discovered(ollama_remote, monkeypatch):
    import app.services.llm_context_budget as budget

    monkeypatch.setattr(budget, "get_context_token_budget", lambda **_k: 32768)
    monkeypatch.setattr(budget, "get_gateway_hard_cap_tokens", lambda **_k: 65536)
    eff = tr.get_effective_context_tokens(model="test-model", allow_discover=True)
    assert eff == 8192


def test_stream_generate_uses_native_api_with_keep_alive(ollama_remote, monkeypatch):
    import app.services.ollama_runtime as ort

    monkeypatch.setattr(ort, "get_keep_alive", lambda **_k: -1)
    monkeypatch.setattr(ort, "get_num_ctx", lambda **_k: 4096)

    async def run():
        out = []
        async with httpx.AsyncClient() as client:
            async for chunk in llm_gateway.stream_generate(
                client, model="test-model", prompt="selam", timeout=10.0,
            ):
                out.append(chunk)
        return out

    import asyncio
    chunks = asyncio.run(run())
    assert "".join(c.get("response", "") for c in chunks) == "Merhaba"
    assert ollama_remote.last_path == "/api/generate"  # type: ignore[attr-defined]
    body = ollama_remote.last_body  # type: ignore[attr-defined]
    assert body.get("keep_alive") == -1
    assert (body.get("options") or {}).get("num_ctx") == 4096


def test_generate_sync_native(ollama_remote, monkeypatch):
    import app.services.ollama_runtime as ort

    monkeypatch.setattr(ort, "get_keep_alive", lambda **_k: "10m")
    monkeypatch.setattr(ort, "get_num_ctx", lambda **_k: 2048)
    data = llm_gateway.generate_sync(model="test-model", prompt="x", timeout=10.0)
    assert data.get("response") == "cevap"
    assert ollama_remote.last_path == "/api/generate"  # type: ignore[attr-defined]
    assert ollama_remote.last_body.get("keep_alive") == "10m"  # type: ignore[attr-defined]


def test_build_llm_health_includes_effective(ollama_remote):
    h = tr.build_llm_health(model="test-model")
    assert h.get("transport") == "ollama"
    assert h.get("effective_num_ctx") == 8192
    assert h.get("discovered_context_length") == 8192
    assert h.get("ok") is True
