"""llm_gateway uzak yol davranışı — gerçek bir HTTP sunucusuna karşı.

Kapsam: token usage yakalama, `stream_options` desteklemeyen gateway için geri
dönüş, hata durumunda devre kesici + kibar mesaj ve "yerel modele sessizce
düşme yok" kuralı.
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from app.core.config import settings
from app.services import llm_availability as la
from app.services import llm_gateway, llm_usage

STATE = {"mode": "ok", "requests": []}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw or b"{}")
        STATE["requests"].append(body)
        return body

    def do_POST(self):
        body = self._read_body()
        mode = STATE["mode"]

        if mode == "server_error":
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "upstream down"}')
            return

        if mode == "no_stream_options" and "stream_options" in body:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": {"message": "unsupported field stream_options"}}')
            return

        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for token in ("Mer", "haba"):
                chunk = {"choices": [{"delta": {"content": token}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            usage_chunk = {
                "choices": [],
                "usage": {"prompt_tokens": 321, "completion_tokens": 12},
            }
            self.wfile.write(f"data: {json.dumps(usage_chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        payload = {
            "choices": [{"message": {"content": "cevap"}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 5},
        }
        self.wfile.write(json.dumps(payload).encode())


@pytest.fixture
def remote_server(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    STATE["mode"] = "ok"
    STATE["requests"] = []
    monkeypatch.setattr(la, "_redis", lambda: None)
    monkeypatch.setattr(llm_gateway, "_stream_usage_supported", True)
    monkeypatch.setattr(settings, "REMOTE_LLM_ENABLED", True)
    monkeypatch.setattr(settings, "REMOTE_LLM_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setattr(settings, "REMOTE_LLM_MODEL", "test-model")
    monkeypatch.setattr(settings, "REMOTE_LLM_API_KEY", "")
    monkeypatch.setattr(settings, "REMOTE_LLM_VIRTUAL_KEY", "")
    la.reset()
    try:
        yield STATE
    finally:
        la.reset()
        server.shutdown()
        server.server_close()


def _stream_all(prompt="selam"):
    async def run():
        out = []
        async with httpx.AsyncClient() as client:
            async for chunk in llm_gateway.stream_generate(client, model="m", prompt=prompt):
                out.append(chunk)
        return out

    return asyncio.run(run())


def test_stream_collects_tokens_and_usage(remote_server):
    token = llm_usage.start()
    try:
        chunks = _stream_all()
        snap = llm_usage.snapshot()
    finally:
        llm_usage.stop(token)

    assert "".join(c.get("response", "") for c in chunks) == "Merhaba"
    assert chunks[-1]["done"] is True
    assert snap["prompt_tokens"] == 321
    assert snap["completion_tokens"] == 12
    assert snap["total_tokens"] == 333


def test_stream_options_fallback_for_older_gateways(remote_server):
    remote_server["mode"] = "no_stream_options"
    chunks = _stream_all()

    assert "".join(c.get("response", "") for c in chunks) == "Merhaba"
    # İlk istek stream_options ile, ikincisi onsuz gitmiş olmalı
    assert "stream_options" in remote_server["requests"][0]
    assert "stream_options" not in remote_server["requests"][1]

    # Karar hatırlanır: sonraki sohbetler boşa 400 almaz
    remote_server["requests"].clear()
    _stream_all()
    assert "stream_options" not in remote_server["requests"][0]
    assert len(remote_server["requests"]) == 1


def test_chat_sync_records_usage(remote_server):
    token = llm_usage.start()
    try:
        resp = llm_gateway.chat_sync("m", [{"role": "user", "content": "selam"}], timeout=10)
        snap = llm_usage.snapshot()
    finally:
        llm_usage.stop(token)

    assert resp.status_code == 200
    assert resp.json()["message"]["content"] == "cevap"
    assert snap["total_tokens"] == 45


def test_server_error_opens_circuit_and_never_falls_back_to_ollama(remote_server, monkeypatch):
    remote_server["mode"] = "server_error"

    def _boom(*_a, **_kw):  # yerel Ollama'ya gizli düşüş olmadığının kanıtı
        raise AssertionError("yerel Ollama'ya düşülmemeli")

    monkeypatch.setattr(llm_gateway.requests, "post", _boom, raising=True)

    for _ in range(la.FAILURE_THRESHOLD):
        chunks = _stream_all()
        assert chunks[-1].get("error")

    assert la.is_open() is True

    # Devre açıkken istek ağa hiç çıkmaz, kibar mesajla döner
    before = len(remote_server["requests"])
    chunks = _stream_all()
    assert len(remote_server["requests"]) == before
    assert chunks[-1]["remote_unavailable"] is True
    assert la.UNAVAILABLE_MESSAGE in chunks[-1]["error"]


def test_recovery_after_success(remote_server):
    remote_server["mode"] = "server_error"
    for _ in range(la.FAILURE_THRESHOLD):
        _stream_all()
    assert la.is_open() is True

    remote_server["mode"] = "ok"
    la.reset()  # devre süresi dolduğunda yapılan ilk deneme
    chunks = _stream_all()

    assert "".join(c.get("response", "") for c in chunks) == "Merhaba"
    assert la.is_open() is False
