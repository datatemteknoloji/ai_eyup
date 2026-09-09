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


# ── "boş yanıt" regresyonu: gpt-oss/harmony bazen content boş, thinking dolu
# bırakıp final kanalına hiç geçmiyor. Bu iki senaryoda ekstra bir "nihai
# cevabı şimdi yaz" nudge'ı tetiklenmeli, kullanıcıya çıplak boş metin gitmemeli.

def test_empty_content_no_tool_calls_triggers_final_nudge(monkeypatch):
    """200 OK ama content='' ve tool_calls yok (model 'final' kanalına hiç
    geçmemiş) — bir sonraki çağrıda açık talimatla nihai cevap istenmeli."""
    resp1 = _FakeResp(200, json_body={"message": {"content": "", "thinking": "iç monolog..."}})
    resp2 = _FakeResp(200, json_body={"message": {"content": "İşte nihai cevap."}})
    calls = {"n": 0, "payloads": []}

    def _fake_ollama_chat(payload, timeout):
        calls["n"] += 1
        calls["payloads"].append(payload)
        return resp1 if calls["n"] == 1 else resp2

    monkeypatch.setattr(agent_llm, "_ollama_chat", _fake_ollama_chat)

    out = agent_llm.chat_with_tools("gpt-oss:20b", [{"role": "user", "content": "soru"}], tools=None)

    assert calls["n"] == 2
    assert out["content"] == "İşte nihai cevap."
    assert out["error"] is None
    # nudge çağrısı tools İÇERMEMELİ (final yanıt isteniyor, tool değil)
    assert "tools" not in calls["payloads"][1]


def test_retry_without_tools_still_empty_triggers_final_nudge(monkeypatch):
    """Tool-parse-hatası retry'ı da content='' dönerse (harmony final kanalına
    hâlâ geçmemiş) 3. bir çağrı ile açık nudge denenmeli."""
    resp1 = _FakeResp(500, json_body={
        "error": {"message": "Error parsing tool call: invalid JSON"}
    })
    resp2 = _FakeResp(200, json_body={"message": {"content": "", "thinking": "..."}})
    resp3 = _FakeResp(200, json_body={"message": {"content": "Sonuç: eşleşme yok."}})
    calls = {"n": 0}

    def _fake_ollama_chat(payload, timeout):
        calls["n"] += 1
        return {1: resp1, 2: resp2, 3: resp3}[calls["n"]]

    monkeypatch.setattr(agent_llm, "_ollama_chat", _fake_ollama_chat)

    out = agent_llm.chat_with_tools(
        "gpt-oss:20b", [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "x"}}],
    )

    assert calls["n"] == 3
    assert out["content"] == "Sonuç: eşleşme yok."
    assert out["tool_calls"] == []


def test_transient_connection_error_auto_retries_once(monkeypatch):
    """20 soruluk toplu testte gözlenen ara sıra 'status=error' vakaları — Ollama'ya
    anlık bağlanılamaması gibi geçici hatalar kullanıcıya hemen yansıtılmadan önce
    1 kez otomatik tekrar denenmeli; ikinci deneme başarılıysa normal cevap dönmeli."""
    import requests as _requests

    calls = {"n": 0}

    def _fake_ollama_chat(payload, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _requests.exceptions.ConnectionError("boom")
        return _FakeResp(200, json_body={"message": {"content": "ikinci denemede başarılı"}})

    monkeypatch.setattr(agent_llm, "_ollama_chat", _fake_ollama_chat)

    out = agent_llm.chat_with_tools("m", [{"role": "user", "content": "hi"}], tools=None)

    assert calls["n"] == 2
    assert out["error"] is None
    assert out["content"] == "ikinci denemede başarılı"


def test_persistent_connection_error_still_reported_after_retry(monkeypatch):
    """Hata gerçekten kalıcıysa (2. denemede de aynı hata) sonunda düzgün bir
    hata mesajı dönmeli, sonsuz retry'a girmemeli."""
    import requests as _requests

    calls = {"n": 0}

    def _fake_ollama_chat(payload, timeout):
        calls["n"] += 1
        raise _requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(agent_llm, "_ollama_chat", _fake_ollama_chat)

    out = agent_llm.chat_with_tools("m", [{"role": "user", "content": "hi"}], tools=None)

    assert calls["n"] == 2  # 1 orijinal + 1 retry, daha fazla değil
    assert out["error"] == "Ollama'ya bağlanılamadı."


def test_all_nudges_fail_returns_empty_not_crash(monkeypatch):
    """Nudge da boş dönerse en azından exception fırlatmadan boş content
    dönmeli — çağıran taraf (graph.py) kullanıcıya anlaşılır bir mesaj basar."""
    resp = _FakeResp(200, json_body={"message": {"content": ""}})
    monkeypatch.setattr(agent_llm, "_ollama_chat", lambda payload, timeout: resp)

    out = agent_llm.chat_with_tools("m", [{"role": "user", "content": "hi"}], tools=None)
    assert out["content"] == ""
    assert out["error"] is None
