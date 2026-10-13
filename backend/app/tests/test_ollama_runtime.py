"""ollama_runtime — keep_alive / num_ctx /api/ps sağlık."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.ollama_runtime import (
    apply_ollama_payload,
    check_ollama_health,
    get_keep_alive,
    parse_keep_alive,
)


def test_parse_keep_alive_variants():
    assert parse_keep_alive(None) == -1
    assert parse_keep_alive("") == -1
    assert parse_keep_alive("-1") == -1
    assert parse_keep_alive(0) == 0
    assert parse_keep_alive("0") == 0
    assert parse_keep_alive("300") == 300
    assert parse_keep_alive("10m") == "10m"
    assert parse_keep_alive("24h") == "24h"
    assert parse_keep_alive("omit") is None


def test_apply_payload_keep_alive_and_num_ctx(monkeypatch):
    monkeypatch.setattr(
        "app.services.ollama_runtime.get_keep_alive", lambda **_k: -1
    )
    monkeypatch.setattr(
        "app.services.ollama_runtime.get_num_ctx", lambda **_k: 32768
    )
    out = apply_ollama_payload({"model": "x", "prompt": "hi"}, include_num_ctx=True)
    assert out["keep_alive"] == -1
    assert out["options"]["num_ctx"] == 32768
    assert out["model"] == "x"


def test_apply_payload_preserves_existing_options(monkeypatch):
    monkeypatch.setattr(
        "app.services.ollama_runtime.get_keep_alive", lambda **_k: "10m"
    )
    monkeypatch.setattr(
        "app.services.ollama_runtime.get_num_ctx", lambda **_k: 8192
    )
    out = apply_ollama_payload(
        {"model": "x", "options": {"temperature": 0.2}},
        include_num_ctx=True,
    )
    assert out["keep_alive"] == "10m"
    assert out["options"]["temperature"] == 0.2
    assert out["options"]["num_ctx"] == 8192


def test_apply_payload_embed_no_num_ctx(monkeypatch):
    monkeypatch.setattr(
        "app.services.ollama_runtime.get_keep_alive", lambda **_k: -1
    )
    out = apply_ollama_payload({"model": "e", "prompt": "t"}, include_num_ctx=False)
    assert out["keep_alive"] == -1
    assert "options" not in out


def test_get_num_ctx_clamped(monkeypatch):
    import app.services.ollama_runtime as m

    monkeypatch.setattr(
        "app.services.llm_transport.get_effective_context_tokens",
        lambda **_k: 32768,
    )
    assert m.get_num_ctx() == 32768


def test_check_health_vram_and_ctx_warnings(monkeypatch):
    tags = MagicMock(status_code=200)
    tags.json.return_value = {"models": [{"name": "gpt-oss:20b"}]}
    ps = MagicMock(status_code=200)
    ps.json.return_value = {
        "models": [{
            "name": "gpt-oss:20b",
            "size": 10_000_000_000,
            "size_vram": 5_000_000_000,
            "context_length": 8192,
        }]
    }

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            if url.endswith("/api/tags"):
                return tags
            return ps

    monkeypatch.setattr(
        "app.services.ollama_runtime.get_num_ctx", lambda **_k: 32768
    )
    monkeypatch.setattr(
        "app.services.ollama_runtime.get_keep_alive", lambda **_k: -1
    )
    with patch("app.services.ollama_runtime.httpx.Client", FakeClient):
        with patch("app.core.config.get_active_model", return_value="gpt-oss:20b"):
            with patch("app.core.config.settings") as st:
                st.OLLAMA_URL = "http://127.0.0.1:11434"
                st.OLLAMA_DEFAULT_MODEL = "gpt-oss:20b"
                out = check_ollama_health()

    assert out["ok"] is True
    assert out["reachable"] is True
    assert out["model_loaded"] is True
    assert out["vram_ratio"] == 50.0
    warns = " ".join(out["warnings"])
    assert "CPU" in warns or "VRAM" in warns
    assert "8192" in warns and "32768" in warns


def test_check_health_unreachable_ok_false(monkeypatch):
    import httpx as hx

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            raise hx.ConnectError("refused")

    monkeypatch.setattr(
        "app.services.ollama_runtime.get_num_ctx", lambda **_k: 32768
    )
    monkeypatch.setattr(
        "app.services.ollama_runtime.get_keep_alive", lambda **_k: -1
    )
    with patch("app.services.ollama_runtime.httpx.Client", FakeClient):
        with patch("app.core.config.get_active_model", return_value="m"):
            with patch("app.core.config.settings") as st:
                st.OLLAMA_URL = "http://127.0.0.1:11434"
                st.OLLAMA_DEFAULT_MODEL = "m"
                out = check_ollama_health()

    assert out["ok"] is False
    assert out["reachable"] is False
    assert out["errors"]


def test_get_keep_alive_from_setting(monkeypatch):
    monkeypatch.delenv("OLLAMA_KEEP_ALIVE", raising=False)
    monkeypatch.delenv("OLLAMA_EMBED_KEEP_ALIVE", raising=False)
    with patch(
        "app.services.runtime_settings.get_setting",
        return_value="24h",
    ):
        assert get_keep_alive() == "24h"
