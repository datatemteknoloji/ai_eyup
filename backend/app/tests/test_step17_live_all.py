"""Adım 17 — canlı akış kapsamı: ortak yardımcı (`chat_live_final`), Windows / Linux·OpenShift / Sanallaştırma sözleşmeleri."""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

from app.services import chat_live_final as lf

APP = Path(__file__).resolve().parents[1]
FRONT = APP.parents[1] / "frontend" / "src"


def _src(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")


def _payloads(raws):
    return [json.loads(r[len("data: "):]) for r in raws]


class _U:
    def __init__(self, role):
        self.role = role


# ── rol / sağlayıcı kapısı ───────────────────────────────────────────────────

@pytest.mark.parametrize("mode,role,provider,expect", [
    ("admin", "admin", "ollama", True),
    ("admin", "superadmin", "ollama", True),
    ("admin", "operator", "ollama", False),
    ("all", "operator", "ollama", True),
    ("off", "admin", "ollama", False),
    ("all", "admin", "groq", False),
])
def test_thinking_allowed_gate(monkeypatch, mode, role, provider, expect):
    monkeypatch.setattr(lf.runtime_settings_mod, "get_setting", lambda k: mode if k == "chat_stream_thinking" else "")
    assert lf.thinking_allowed(_U(role), provider) is expect


def test_live_loop_kwargs_flags(monkeypatch):
    monkeypatch.setattr(lf.runtime_settings_mod, "get_bool", lambda k: True)
    monkeypatch.setattr(lf.runtime_settings_mod, "get_setting", lambda k: "admin")
    kw = lf.live_loop_kwargs(_U("admin"), "ollama")
    assert kw == {"stream_final": True, "forward_thinking": True, "final_reminder": lf.SINGLE_PASS_RULES}
    kw = lf.live_loop_kwargs(_U("operator"), "openai")
    assert kw == {"stream_final": False, "forward_thinking": False, "final_reminder": None}
    monkeypatch.setattr(lf.runtime_settings_mod, "get_bool", lambda k: False)
    assert lf.live_loop_kwargs(_U("admin"), "ollama")["stream_final"] is False


# ── LiveFinal durum makinesi ─────────────────────────────────────────────────

class _T:
    n = 0

    def note_ttft(self):
        _T.n += 1


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def _settle(l):
    return [r async for r in l.settle()]


def test_livefinal_single_pass_keeps_live_text():
    _T.n = 0
    l = lf.LiveFinal(timing=_T())
    out = []
    for it in [
        {"type": "thinking", "text": "düşünüyor"},
        {"type": "answer_start"},
        {"type": "token", "text": "Merhaba "},
        {"type": "token", "text": "dünya."},
        {"type": "final", "final_text": "Merhaba dünya.", "final_streamed": True, "final_done_reason": "stop"},
    ]:
        out += l.on_item(it)
    p = _payloads(out)
    assert p[0] == {"type": "thinking", "text": "düşünüyor"} and p[1] == {"phase": "answering"}
    assert [x.get("token") for x in p[2:]] == ["Merhaba ", "dünya."]
    assert _T.n == 1                                   # TTFT yalnız bir kez
    assert _run(_settle(l)) == [] and l.use_loop_final is True


def test_livefinal_length_falls_back_and_clears_screen():
    l = lf.LiveFinal()
    for it in [
        {"type": "token", "text": "yarım cev"},
        {"type": "final", "final_text": "yarım cev", "final_streamed": True, "final_done_reason": "length"},
    ]:
        l.on_item(it)
    raw = _run(_settle(l))
    assert l.use_loop_final is False
    assert _payloads(raw) == [{"replace_answer": True}] and l.live_text == ""


def test_livefinal_stream_error_and_not_streamed():
    l = lf.LiveFinal()
    l.on_item({"type": "final", "final_text": "x", "final_streamed": False, "final_done_reason": "stop"})
    assert _run(_settle(l)) == [] and l.use_loop_final is False
    l2 = lf.LiveFinal()
    l2.on_item({"type": "final", "final_text": "x", "final_streamed": True, "final_done_reason": "stream_error"})
    assert _run(_settle(l2)) == [] and l2.use_loop_final is False


def test_livefinal_answer_reset_and_corrected_final(monkeypatch):
    async def _no_sleep(_d):
        return None
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    l = lf.LiveFinal()
    out = l.on_item({"type": "token", "text": "sızıntı"})
    out += l.on_item({"type": "answer_reset"})
    assert _payloads(out)[-1] == {"replace_answer": True} and l.live_text == ""
    # reset sonrası ikinci deneme ekranda farklıysa düzeltilir
    l.on_item({"type": "token", "text": "ilk"})
    l.on_item({"type": "final", "final_text": "düzeltilmiş cevap", "final_streamed": True, "final_done_reason": "stop"})
    p = _payloads(_run(_settle(l)))
    assert p[0] == {"replace_answer": True}
    assert "".join(x.get("token", "") for x in p[1:]) == "düzeltilmiş cevap"


def test_livefinal_ignores_empty_events():
    l = lf.LiveFinal()
    assert l.on_item({"type": "thinking", "text": ""}) == []
    assert l.on_item({"type": "token", "text": ""}) == []
    assert l.on_item({"type": "answer_reset"}) == []          # ekranda bir şey yokken sessiz


# ── LiveSink ─────────────────────────────────────────────────────────────────

def test_sink_drain_order_and_role_gate():
    s = lf.LiveSink(allow_thinking=False)
    s.thinking("gizli")
    s.event({"type": "tool_call", "tool": "t", "label": "L"})
    s.token("a")
    s.token("b")
    p = _payloads(s.drain())
    assert p == [{"type": "tool_call", "tool": "t", "label": "L"}, {"phase": "answering"}, {"token": "a"}, {"token": "b"}]
    assert s.live_text == "ab"
    s.reset()
    assert _payloads(s.drain()) == [{"replace_answer": True}] and s.live_text == "" and s.token_started is False
    s2 = lf.LiveSink(allow_thinking=True)
    s2.thinking("düşünce")
    assert _payloads(s2.drain()) == [{"type": "thinking", "text": "düşünce"}]


def test_sink_is_thread_safe():
    s = lf.LiveSink(allow_thinking=True)
    t = threading.Thread(target=lambda: [s.token("x") for _ in range(200)])
    t.start(); t.join()
    assert sum(1 for x in _payloads(s.drain()) if "token" in x) == 200


# ── generate_live_sync ───────────────────────────────────────────────────────

def _patch_stream(monkeypatch, events, blocking=None):
    from app.services import llm_gateway
    monkeypatch.setattr("app.services.llm_external.resolve_external_chat_target", lambda m: None)
    monkeypatch.setattr(llm_gateway, "chat_stream_iter", lambda *a, **k: iter(events))
    calls = []

    def _gen(**kw):
        calls.append(kw)
        return blocking or {"response": "BLOK", "done": True}
    monkeypatch.setattr(llm_gateway, "generate_sync", _gen)
    return calls


def test_generate_live_sync_no_sink_is_blocking(monkeypatch):
    calls = _patch_stream(monkeypatch, [])
    r = lf.generate_live_sync(model="m", prompt="p", sink=None)
    assert r["response"] == "BLOK" and len(calls) == 1


def test_generate_live_sync_streams_tokens_and_thinking(monkeypatch):
    ans = "Toplam 12 VM çalışıyor; 3 tanesi kapalı durumda ve incelenmeli. " * 2
    events = [{"type": "thinking", "text": "a" * 50}] + [
        {"type": "content", "text": ans[i:i + 10]} for i in range(0, len(ans), 10)
    ] + [{"type": "done", "data": {}}]
    calls = _patch_stream(monkeypatch, events)
    sink = lf.LiveSink(allow_thinking=True)
    r = lf.generate_live_sync(model="m", prompt="p", sink=sink)
    assert r["response"] == ans.strip() and calls == []
    p = _payloads(sink.drain())
    assert p[0]["type"] == "thinking" and any("token" in x for x in p)
    assert "".join(x.get("token", "") for x in p) == ans and sink.live_text == ans


def test_generate_live_sync_short_answer_flushes_held_lead(monkeypatch):
    calls = _patch_stream(monkeypatch, [{"type": "content", "text": "Evet."}, {"type": "done", "data": {}}])
    sink = lf.LiveSink(allow_thinking=False)
    r = lf.generate_live_sync(model="m", prompt="p", sink=sink)
    assert r["response"] == "Evet." and sink.live_text == "Evet." and calls == []


def test_generate_live_sync_leak_falls_back_to_blocking(monkeypatch):
    leak = "The user asks: how many VMs? We need to answer in Turkish. Let me think about this. " * 2
    calls = _patch_stream(monkeypatch, [{"type": "content", "text": leak}, {"type": "done", "data": {}}])
    sink = lf.LiveSink(allow_thinking=True)
    r = lf.generate_live_sync(model="m", prompt="p", sink=sink)
    assert r["response"] == "BLOK" and len(calls) == 1 and sink.live_text == ""


def test_generate_live_sync_error_before_tokens_falls_back(monkeypatch):
    calls = _patch_stream(monkeypatch, [{"type": "error", "status": 500, "text": "boom"}])
    sink = lf.LiveSink(allow_thinking=False)
    r = lf.generate_live_sync(model="m", prompt="p", sink=sink)
    assert r["response"] == "BLOK" and len(calls) == 1


def test_generate_live_sync_error_after_tokens_keeps_partial(monkeypatch):
    ans = "Birinci cümle tamam ve yeterince uzun bir cevap başlangıcı yazıyoruz burada, sunucuda 12 VM var. "
    calls = _patch_stream(monkeypatch, [
        {"type": "content", "text": ans}, {"type": "error", "status": 500, "text": "boom"},
    ])
    sink = lf.LiveSink(allow_thinking=False)
    r = lf.generate_live_sync(model="m", prompt="p", sink=sink)
    assert r["response"] == ans.strip() and r.get("error") and calls == []


# ── kaynak sözleşmeleri ──────────────────────────────────────────────────────

def test_windows_and_linux_contracts():
    for rel, tag in (("api/windows_chat.py", "WindowsChat"), ("api/chat.py", "LinuxChat")):
        s = _src(rel)
        assert "**_live_loop_kwargs(_auth_user, provider)" in s, rel
        assert "_lf.on_item(item)" in s and "async for _raw in _lf.settle()" in s, rel
        assert "if not _lf.use_loop_final:" in s and "full_response = _lf.loop_text" in s, rel
        assert "think=_final_think_level(model)" in s and "_thinking_allowed(_auth_user, provider)" in s, rel
        assert 'chunk.get("thinking")' in s and 'yield _sse({"type": "thinking"' in s, rel


def test_virt_contracts():
    h = _src("api/hypervisors.py")
    assert "live_sink_var.set(sink)" in h and "sink.drain()" in h and "paced_chunks(answer)" in h
    assert "thinking_allowed(_auth_user, _prov)" in h
    # tek patlama yok: eski 8'lik token döngüsü kalmamalı
    assert 'for i in range(0, len(answer), 8):' not in h.split("async def ask_hypervisor_stream")[1].split("quick-stats")[0]
    hi = _src("services/hypervisor_intelligence.py")
    assert hi.count("_generate_live_sync(model=active_model, prompt=prompt, timeout=120)") == 3
    assert "_sk.reset()" in hi
    g = _src("services/chat_source_graph.py")
    assert "current_sink" in g and "forward_thinking=" in g and "_sink.thinking(" in g


def test_unified_still_uses_shared_helpers():
    from app.api import unified_chat as uc
    assert uc._SINGLE_PASS_RULES is lf.SINGLE_PASS_RULES and uc.paced_plan is lf.paced_plan
    assert uc.thinking_allowed is lf.thinking_allowed and uc.final_think_level is lf.final_think_level


def test_frontend_pages_render_thinking_trace():
    if not (FRONT / "pages").exists():
        pytest.skip("frontend kaynağı bu ortamda yok (konteyner)")
    for rel in ("pages/Chat.tsx", "pages/WindowsChat.tsx", "pages/HypervisorChat.tsx"):
        t = (FRONT / rel).read_text(encoding="utf-8")
        assert "import ThinkingTrace" in t and "<ThinkingTrace" in t and "thinkingText" in t, rel
    hv = (FRONT / "pages/HypervisorChat.tsx").read_text(encoding="utf-8")
    assert "streamingText={stream.streamingText}" in hv      # virt canlı cevap balonu
