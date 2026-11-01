"""Adım 14 — canlı akış: tek geçiş (stream_final), düşünme akışı, aralıklı gönderim, kaynak sözleşmeleri."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import unified_tool_chat as utc
from app.services.agent.policy import RiskLevel

APP = Path(__file__).resolve().parents[1]


class _FakeTool:
    risk_level = RiskLevel.READ_ONLY
    domains = frozenset({"automic"})

    def preview(self, db, args, ctx):
        return "fake"

    def execute(self, db, args, ctx):
        return {"ok": True, "total": 1, "items": [{"x": 1}]}


@pytest.fixture
def _env(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent.tools.tool_specs_read_only",
        lambda domains=None: [{"type": "function", "function": {"name": "automic_active"}}],
    )
    monkeypatch.setattr("app.services.agent.tools.get_tool", lambda name: _FakeTool())
    monkeypatch.setattr("app.services.agent.tools.resolve_server", lambda db, args, ctx: None)
    monkeypatch.setattr("app.services.chat_tool_policy.should_use_db_first", lambda **kw: False)
    monkeypatch.setattr(utc, "_needs_tool_evidence", lambda: False, raising=False)
    monkeypatch.setattr("app.services.chat_clause_check.uncovered_clause_labels", lambda *a, **k: [])


def _loop(**kw):
    return list(utc.run_read_only_tool_loop(
        db=None, model="gpt-oss:20b", user_message="Şu an kaç iş çalışıyor?",
        context_str="", server_summary="", max_steps=5,
        domains=frozenset({"automic"}), platform="automic", **kw,
    ))


_TOOL_RES = {"type": "result", "content": "", "error": None, "streamed_chars": 0, "done_reason": "stop",
             "tool_calls": [{"id": "c1", "name": "automic_active", "arguments": {}}]}


def _final_res(txt="**1 iş var.**"):
    return {"type": "result", "content": txt, "tool_calls": [], "error": None,
            "streamed_chars": len(txt), "done_reason": "stop"}


def test_stream_final_streams_last_turn_only_and_skips_plain(monkeypatch, _env):
    calls = []

    def fake_stream(model, messages, tools, timeout=90, **kw):
        calls.append(kw)
        if len(calls) == 1:
            # araç seçimi turu: model ön metin akıtsa bile kullanıcıya GİTMEZ
            yield {"type": "token", "text": "Bakayım, sorguluyorum şimdi."}
            yield dict(_TOOL_RES)
        else:
            yield {"type": "token", "text": "**1 iş "}
            yield {"type": "token", "text": "var.**"}
            yield _final_res()

    def boom(*a, **k):
        raise AssertionError("akışsız çağrı yapılmamalı")

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", fake_stream)
    monkeypatch.setattr("app.services.agent.llm.chat_with_tools", boom)
    ev = _loop(stream_final=True)
    toks = "".join(e["text"] for e in ev if e["type"] == "token")
    assert toks == "**1 iş var.**"
    kinds = [e["type"] for e in ev]
    assert kinds.index("answer_start") < kinds.index("token") < kinds.index("final")
    fin = ev[-1]
    assert fin["final_streamed"] is True and fin["final_text"] == "**1 iş var.**"
    assert fin["final_done_reason"] == "stop"
    assert "answer_reset" not in kinds
    assert not any(e["type"] == "thinking" for e in ev)        # forward_thinking kapalı
    assert all("emit_thinking" in kw and kw["emit_thinking"] is False for kw in calls)


def test_flags_off_keep_non_stream_path(monkeypatch, _env):
    n = []

    def fake_plain(model, messages, tools, timeout=90, **kw):
        n.append(1)
        if len(n) == 1:
            return {"content": "", "error": None,
                    "tool_calls": [{"id": "c1", "name": "automic_active", "arguments": {}}]}
        return {"content": "bitti", "tool_calls": [], "error": None}

    def boom(*a, **k):
        raise AssertionError("stream çağrılmamalı")

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools", fake_plain)
    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", boom)
    ev = _loop()
    assert ev[-1]["type"] == "final" and "final_text" not in ev[-1]
    assert not any(e["type"] in ("token", "answer_start", "thinking") for e in ev)


def test_forward_thinking_coalesced_and_not_answer(monkeypatch, _env):
    calls = []

    def fake_stream(model, messages, tools, timeout=90, **kw):
        calls.append(kw)
        for _ in range(30):
            yield {"type": "thinking", "text": "abc "}      # 4 kr × 30 → birleştirilmeli
        if len(calls) == 1:
            yield dict(_TOOL_RES)
        else:
            yield {"type": "token", "text": "cevap metni burada"}
            yield _final_res("cevap metni burada")

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", fake_stream)
    ev = _loop(forward_thinking=True)            # stream_final KAPALI
    th = [e for e in ev if e["type"] == "thinking"]
    assert 2 <= len(th) < 60                      # 60 ham parça → birleştirilmiş
    assert "".join(e["text"] for e in th) == "abc " * 60
    assert not any(e["type"] in ("token", "answer_start") for e in ev)   # cevap akıtılmaz
    assert ev[-1]["type"] == "final" and ev[-1].get("final_streamed") in (None, False)
    assert all(kw["emit_thinking"] is True for kw in calls)


def test_nudge_pending_turn_is_not_live(monkeypatch, _env):
    """Eksik cümle nudge'ı bekleyen araçsız tur kullanıcıya akıtılmaz; nudge sonrası tur akıtılır."""
    n = {"i": 0}
    leaks = {"first": True}

    def fake_stream(model, messages, tools, timeout=90, **kw):
        n["i"] += 1
        if n["i"] == 1:
            yield dict(_TOOL_RES)
        elif n["i"] == 2:
            yield {"type": "token", "text": "EKSİK CEVAP (akıtılmamalı)"}
            yield _final_res("EKSİK CEVAP (akıtılmamalı)")
        else:
            yield {"type": "token", "text": "TAM CEVAP"}
            yield _final_res("TAM CEVAP")

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", fake_stream)
    monkeypatch.setattr("app.services.chat_clause_check.uncovered_clause_labels", lambda *a, **k: ["x"])
    monkeypatch.setattr("app.services.chat_clause_check.sufficiency_nudge", lambda m: "nudge")
    ev = _loop(stream_final=True)
    toks = "".join(e["text"] for e in ev if e["type"] == "token")
    assert toks == "TAM CEVAP"
    assert ev[-1]["final_text"] == "TAM CEVAP" and ev[-1]["final_streamed"] is True


def test_live_text_then_tool_call_emits_answer_reset(monkeypatch, _env):
    n = {"i": 0}

    def fake_stream(model, messages, tools, timeout=90, **kw):
        n["i"] += 1
        if n["i"] == 1:
            yield dict(_TOOL_RES)
        elif n["i"] == 2:
            # araç kullanıldı → canlı; model yine de ön metin + ikinci araç çağrısı yapıyor
            yield {"type": "token", "text": "Önce şuna bakayım ve sonra başka bir kaynağa da göz atacağım, çünkü veri eksik görünüyor."}
            r = dict(_TOOL_RES)
            r["tool_calls"] = [{"id": "c2", "name": "automic_active", "arguments": {"a": 1}}]
            yield r
        else:
            yield {"type": "token", "text": "SON"}
            yield _final_res("SON")

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", fake_stream)
    ev = _loop(stream_final=True)
    kinds = [e["type"] for e in ev]
    assert "answer_reset" in kinds
    assert kinds.index("answer_reset") < len(kinds) - 1
    assert ev[-1]["final_text"] == "SON"


def test_short_preamble_with_tool_call_is_never_shown(monkeypatch, _env):
    """<80 karakterlik ön metin tutulur; ardından araç çağrısı gelirse kullanıcıya hiç gitmez (answer_reset gerekmez)."""
    n = {"i": 0}

    def fake_stream(model, messages, tools, timeout=90, **kw):
        n["i"] += 1
        if n["i"] == 1:
            yield dict(_TOOL_RES)
        elif n["i"] == 2:
            yield {"type": "token", "text": "Bir de şuna bakayım."}
            r = dict(_TOOL_RES)
            r["tool_calls"] = [{"id": "c2", "name": "automic_active", "arguments": {"a": 1}}]
            yield r
        else:
            yield {"type": "token", "text": "SON"}
            yield _final_res("SON")

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", fake_stream)
    ev = _loop(stream_final=True)
    assert "".join(e["text"] for e in ev if e["type"] == "token") == "SON"
    assert "answer_reset" not in [e["type"] for e in ev]


_LEAK = ("User asked: \"Hangi job'lar hata verdi?\" We have data. Need to answer in Turkish. Provide list of job names "
         "that had failures. **Hata veren job'lar** | Nesne | Hata |")


@pytest.mark.parametrize("leak_text", [
    _LEAK,
    "We need to answer in Turkish. The data shows 5 failures.",          # kısa (<80)
    "The user wants a list of failing jobs. Provide top 10 now.",
    "Analysis: need to craft a concise reply with a table.",
])
def test_reasoning_leak_is_never_streamed_and_falls_back(monkeypatch, _env, leak_text):
    n = {"i": 0}

    def fake_stream(model, messages, tools, timeout=90, **kw):
        n["i"] += 1
        if n["i"] == 1:
            yield dict(_TOOL_RES)
        else:
            for i in range(0, len(leak_text), 12):
                yield {"type": "token", "text": leak_text[i:i + 12]}
            yield _final_res(leak_text)

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", fake_stream)
    ev = _loop(stream_final=True)
    assert not any(e["type"] in ("token", "answer_start") for e in ev)       # ekrana HİÇ gitmedi
    fin = ev[-1]
    assert fin["final_streamed"] is False and fin["final_done_reason"] == "reasoning_leak"


def test_reasoning_leak_gets_one_quick_retry_instead_of_second_generation(monkeypatch, _env):
    """İlk final tur sızdırırsa aynı tur bir kez uyarıyla yeniden denenir; temiz cevap canlı akar (ikinci üretim YOK)."""
    n = {"i": 0}
    notes = []
    seen_tools = []

    def fake_stream(model, messages, tools, timeout=90, **kw):
        n["i"] += 1
        seen_tools.append(tools)
        notes.append([m["content"] for m in messages if m.get("role") == "system" and "akıl yürütme" in (m.get("content") or "")])
        if n["i"] == 1:
            yield dict(_TOOL_RES)
        elif n["i"] == 2:
            for i in range(0, len(_LEAK), 10):
                yield {"type": "token", "text": _LEAK[i:i + 10]}
            yield _final_res(_LEAK)
        else:
            good = "**Hata veren job'lar** şunlardır: JOBS.A (24), JOBS.B (22) — toplam 46 hata görüldü."
            yield {"type": "token", "text": good}
            yield _final_res(good)

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", fake_stream)
    ev = _loop(stream_final=True)
    toks = "".join(e["text"] for e in ev if e["type"] == "token")
    assert toks.startswith("**Hata veren") and "User asked" not in toks
    assert ev[-1]["final_streamed"] is True and ev[-1]["final_done_reason"] == "stop"
    assert n["i"] == 3 and notes[2]        # üçüncü çağrıda uyarı notu var
    assert seen_tools[1] and seen_tools[2]            # sızıntıda araçlar korunur


@pytest.mark.parametrize("ok_text", [
    "Şu an **36** iş aktif. Bunların 25 tanesi p95 süresini aşmış durumda ve izlenmeli, ayrıntıyı ister misiniz?",
    "**Hata veren job'lar (son 24 saat)** | Nesne | Hata sayısı | Oran |\n|---|---|---|---|\n| JOBS.A | 24 | %12 |",
    "Toplam 18 iş.",
])
def test_normal_turkish_answer_is_not_flagged(monkeypatch, _env, ok_text):
    n = {"i": 0}

    def fake_stream(model, messages, tools, timeout=90, **kw):
        n["i"] += 1
        if n["i"] == 1:
            yield dict(_TOOL_RES)
        else:
            for i in range(0, len(ok_text), 7):
                yield {"type": "token", "text": ok_text[i:i + 7]}
            yield _final_res(ok_text)

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", fake_stream)
    ev = _loop(stream_final=True)
    assert "".join(e["text"] for e in ev if e["type"] == "token") == ok_text
    assert ev[-1]["final_streamed"] is True


def test_final_reminder_added_once_after_tools_with_tool_names(monkeypatch, _env):
    seen = []
    n = {"i": 0}

    def fake_stream(model, messages, tools, timeout=90, **kw):
        n["i"] += 1
        seen.append([m for m in messages if m.get("role") == "system" and "KURAL-X" in (m.get("content") or "")])
        if n["i"] == 1:
            yield dict(_TOOL_RES)
        else:
            yield {"type": "token", "text": "Bitti."}
            yield _final_res("Bitti.")

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", fake_stream)
    _loop(stream_final=True, final_reminder="KURAL-X")
    assert seen[0] == []                                   # araç çalışmadan önce yok
    assert len(seen[1]) == 1 and "automic_active" in seen[1][0]["content"]


def test_stream_error_mid_answer_reports_done_reason(monkeypatch, _env):
    """Akış yarıda koparsa (done_reason=stream_error) `final` bunu bildirir → çağıran ikinci üretime düşer."""
    n = {"i": 0}

    def fake_stream(model, messages, tools, timeout=90, **kw):
        n["i"] += 1
        if n["i"] == 1:
            yield dict(_TOOL_RES)
        else:
            yield {"type": "token", "text": "yarım cevap burada, kesil"}
            r = _final_res("yarım cevap burada, kesil")
            r["done_reason"] = "stream_error"
            yield r

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", fake_stream)
    ev = _loop(stream_final=True)
    assert ev[-1]["final_done_reason"] == "stream_error"


# ── agent.llm: thinking olayı yalnız istenince ──────────────────────────────

def _gw(monkeypatch, script):
    monkeypatch.setattr("app.services.llm_gateway.chat_stream_iter",
                        lambda model, messages, **kw: iter(script))


_SCRIPT = [
    {"type": "thinking", "text": "düşünüyorum"},
    {"type": "content", "text": "Bu bir cevap metnidir, yeterince uzun."},
    {"type": "done", "data": {"done_reason": "stop", "eval_count": 5}},
]


def test_llm_stream_emits_thinking_only_when_asked(monkeypatch):
    from app.services.agent import llm as agent_llm
    _gw(monkeypatch, _SCRIPT)
    off = [e["type"] for e in agent_llm.chat_with_tools_stream("m", [], [])]
    assert "thinking" not in off
    _gw(monkeypatch, _SCRIPT)
    on = [e for e in agent_llm.chat_with_tools_stream("m", [], [], emit_thinking=True)]
    assert on[0] == {"type": "thinking", "text": "düşünüyorum"}
    assert on[-1]["type"] == "result"


# ── aralıklı gönderim ───────────────────────────────────────────────────────

@pytest.mark.parametrize("n", [1, 40, 500, 3000, 20000])
def test_paced_plan_bounds(n):
    from app.api.unified_chat import _PACE_MAX_CHUNKS, _PACE_TOTAL_S, paced_plan
    step, delay = paced_plan(n)
    chunks = -(-n // step)
    assert step >= 8 and chunks <= _PACE_MAX_CHUNKS + 1
    assert chunks * delay <= _PACE_TOTAL_S + 1e-6
    assert 0 <= delay <= 0.04


@pytest.mark.asyncio
async def test_paced_chunks_reassemble_and_sleep(monkeypatch):
    import asyncio
    from app.api import unified_chat as uc
    slept = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(uc._asyncio, "sleep", fake_sleep)
    text = "Merhaba dünya. " * 40
    import json
    out = []
    async for raw in uc._paced_chunks(text):
        out.append(json.loads(raw[len("data: "):])["token"])
    assert "".join(out) == text
    assert len(slept) == len(out) - 1 and sum(slept) <= uc._PACE_TOTAL_S + 1e-6


# ── kaynak sözleşmeleri ─────────────────────────────────────────────────────

def _src(rel):
    return (APP / rel).read_text(encoding="utf-8")


def test_unified_chat_contracts():
    s = _src("api/unified_chat.py")
    assert not re.search(r"for i in range\(0, len\(.+\), \d+\):\n\s+yield _sse\(\{\"token\"", s), \
        "hazır cevaplar `_paced_chunks` ile akıtılmalı (tek patlama yok)"
    assert "stream_final=_sf_on" in s and "forward_thinking=_fwd_think" in s
    assert 'runtime_settings.get_bool("chat_unified_stream_final")' in s
    # düşünme akışı rol kapılı
    _lf = _src("services/chat_live_final.py")   # Adım 17: ortak modüle taşındı
    assert '"admin", "superadmin"' in _lf and 'chat_stream_thinking' in _lf
    # ikinci üretim yalnız tek geçiş yoksa
    assert "final_reminder=_SINGLE_PASS_RULES" in s and "stream_final=_sf_on" in s
    assert "if _use_loop_final:" in s and "full_response = _loop_final_text" in s
    assert '"length", "stream_error"' in s
    # düşünme olayı cevap tokenı değil
    assert 'yield _sse({"type": "thinking"' in s


def test_orchestrator_clears_partial_on_replace():
    s = _src("services/chat_orchestrator/service.py")
    assert 'if chunk.get("replace_answer"):' in s and "full.clear()" in s


def test_settings_defaults():
    from app.services import runtime_settings as rs
    assert rs.ADVANCED_SCHEMA["chat_unified_stream_final"]["type"] == "bool"
    assert rs.ADVANCED_SCHEMA["chat_stream_thinking"]["default"] == "admin"
    assert rs.ADVANCED_SCHEMA["chat_stream_thinking"]["choices"] == ["off", "admin", "all"]


def test_progress_rearm_after_replace_answer():
    from app.services.chat_orchestrator import progress as P
    t = [0.0]
    tr = P.ProgressTracker(clock=lambda: t[0])
    tr.on_token()
    assert tr.done and tr.tick() == []                    # ilk token sonrası sessiz
    t[0] = 30.0
    ev = tr.rearm()
    assert ev and ev[0]["type"] == "progress" and "yeniden" in ev[0]["text"] and not tr.done
    t[0] = 36.0
    hb = tr.tick()                                         # sessizlikte kalp atışı yeniden akar
    assert hb and hb[0].get("heartbeat")
    tr.on_token()
    assert tr.done


def test_progress_rearm_respects_disabled():
    from app.services.chat_orchestrator import progress as P
    tr = P.ProgressTracker(enabled=False)
    assert tr.rearm() == []


def test_service_and_second_generation_contracts():
    sv = _src("services/chat_orchestrator/service.py")
    assert "_pw_tracker.rearm()" in sv and 'stop2' in sv
    uc = _src("api/unified_chat.py")
    assert "think=final_think_level(model)" in uc
    assert 'chunk.get("thinking")' in uc and "thinking_allowed(_auth_user, provider)" in uc
    from app.services import runtime_settings as rs
    assert rs.ADVANCED_SCHEMA["chat_final_think"]["default"] == "low"


def test_stream_error_midanswer_retries_without_tools_and_resets_screen(monkeypatch, _env):
    """Akış ortası Ollama 500 ('error parsing tool call'): kısmi metin geri alınır, tur araçsız yeniden denenir."""
    n = {"i": 0}
    seen_tools = []
    good = "**Hata veren job'lar** şunlardır: JOBS.A (24), JOBS.B (22) — toplam 46 hata görüldü, ayrıntı aşağıda."

    def fake_stream(model, messages, tools, timeout=90, **kw):
        n["i"] += 1
        seen_tools.append(tools)
        if n["i"] == 1:
            yield dict(_TOOL_RES)
        elif n["i"] == 2:
            part = "**Hata veren job'lar (son 24 saat)** şunlardır: JOBS.A (24), JOBS.B (22), JOBS.C"
            yield {"type": "token", "text": part}
            yield {"type": "result", "content": part, "tool_calls": [], "error": None,
                   "streamed_chars": len(part), "done_reason": "stream_error"}
        else:
            yield {"type": "token", "text": good}
            yield _final_res(good)

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", fake_stream)
    ev = _loop(stream_final=True)
    types = [e["type"] for e in ev]
    assert "answer_reset" in types
    assert types.index("answer_reset") < max(i for i, t in enumerate(types) if t == "token")
    assert seen_tools[2] == [] and ev[-1]["final_streamed"] is True and ev[-1]["final_done_reason"] == "stop"
