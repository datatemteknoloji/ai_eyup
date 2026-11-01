"""Adım 14 — SSE yanıtı gzip ara katmanında TAMPONLANMAZ (tarayıcı token'ları canlı görür)."""
import asyncio

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from starlette.testclient import TestClient

from app.core.gzip_sse import SSEAwareGZipMiddleware


def _app():
    app = FastAPI()
    app.add_middleware(SSEAwareGZipMiddleware, minimum_size=100)

    @app.get("/sse")
    async def sse():
        async def gen():
            for i in range(5):
                yield f"data: {i}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/big")
    async def big():
        return {"x": "a" * 5000}
    return app


def test_event_stream_is_not_gzipped():
    r = TestClient(_app()).get("/sse", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") is None
    assert r.text.count("data:") == 5


def test_regular_json_still_gzipped():
    r = TestClient(_app()).get("/big", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    assert len(r.json()["x"]) == 5000


def test_main_uses_sse_aware_gzip():
    src = open(__import__("app.main", fromlist=["x"]).__file__, encoding="utf-8").read()
    assert "SSEAwareGZipMiddleware" in src
