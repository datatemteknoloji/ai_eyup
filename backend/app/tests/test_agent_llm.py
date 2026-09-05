"""agent/llm.py — chat_with_tools hata ayrıştırma.

Regresyon: Bifrost/LiteLLM gibi uzak gateway'ler 500 döndüğünde OpenAI-uyumlu
iç içe `{"error": {"message": ..., "type": ..., "code": ...}}` formatı
kullanabiliyor. Eski kod `err_body.get("error", "")`'u doğrudan string kabul
edip `.lower()` çağırıyordu — bu durumda `err_msg` bir dict olduğundan
"'dict' object has no attribute 'lower'" ile patlıyordu (üretim logu, bkz.
[AgentLLM] Hata satırı). Bu, `db-first` agentic tool-loop'unun elindeki
zaten toplanmış tool sonuçlarını (used_tools/tools_used) sessizce kaybetmesine
yol açıyordu.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.agent import llm as agent_llm


class _FakeResp:
    def __init__(self, status_code, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text

    def json(self):
        if self._json_body is None:
            raise ValueError("no json body")
        return self._json_body


def test_nested_dict_error_body_does_not_crash(monkeypatch):
    """Bifrost/LiteLLM tarzı {"error": {"message": ...}} gövdesi — .lower()
    AttributeError'a düşmemeli, iç 'message' string'i çıkarılmalı."""
    resp = _FakeResp(500, json_body={
        "error": {"message": "litellm.BadRequestError: exceeds model's maximum context length",
                  "type": None, "param": None, "code": "400"}
    })
    monkeypatch.setattr(agent_llm, "_ollama_chat", lambda payload, timeout: resp)

    out = agent_llm.chat_with_tools("gpt-oss-120b", [{"role": "user", "content": "hi"}], tools=None)

    assert out["tool_calls"] == []
    assert out["error"] is not None
    assert "dict" not in out["error"]  # AttributeError metni sızmamalı
    assert "exceeds model's maximum context length" in out["error"]


def test_nested_dict_error_with_tools_triggers_retry_without_tools(monkeypatch):
    """Hata mesajı tool-call parse hatasına benziyorsa (nested dict olsa da)
    tools'suz retry hâlâ tetiklenmeli — eski davranış korunmalı."""
    resp1 = _FakeResp(500, json_body={
        "error": {"message": "Error parsing tool call: invalid JSON", "type": "invalid_request_error"}
    })
    resp2 = _FakeResp(200, json_body={"message": {"content": "plain text cevap"}})

    calls = {"n": 0}

    def _fake_ollama_chat(payload, timeout):
        calls["n"] += 1
        return resp1 if calls["n"] == 1 else resp2

    monkeypatch.setattr(agent_llm, "_ollama_chat", _fake_ollama_chat)

    out = agent_llm.chat_with_tools(
        "gpt-oss-120b", [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "x"}}],
    )
    assert calls["n"] == 2
    assert out["error"] is None
    assert out["content"] == "plain text cevap"
    assert out["tool_calls"] == []


def test_plain_string_error_body_still_works(monkeypatch):
    """Eski/basit `{"error": "some string"}` formatı için davranış değişmemeli."""
    resp = _FakeResp(500, json_body={"error": "internal server error"})
    monkeypatch.setattr(agent_llm, "_ollama_chat", lambda payload, timeout: resp)

    out = agent_llm.chat_with_tools("m", [{"role": "user", "content": "hi"}], tools=None)
    assert out["error"] == "LLM HTTP 500: internal server error"


def test_non_dict_json_body_falls_back_to_str(monkeypatch):
    resp = _FakeResp(500, json_body=["unexpected", "list", "body"])
    monkeypatch.setattr(agent_llm, "_ollama_chat", lambda payload, timeout: resp)

    out = agent_llm.chat_with_tools("m", [{"role": "user", "content": "hi"}], tools=None)
    assert out["tool_calls"] == []
    assert out["error"] is not None
