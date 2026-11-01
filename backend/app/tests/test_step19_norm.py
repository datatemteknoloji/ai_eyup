"""Adım 19 — kopyalanan kırılmaz tire (U+2011) normalizasyonu + kanıt guard'ı yeniden üretimi (canlı + bildirim)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.services.chat_text_norm import normalize_dashes, normalize_hyphens, normalize_user_text

APP = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")


NB = "zz\u2011fake\u2011vm\u20110862"


def test_normalize_dashes_all_variants():
    for ch in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d":
        assert normalize_dashes(f"a{ch}b") == "a-b"
    assert normalize_dashes(NB) == "zz-fake-vm-0862"
    assert normalize_dashes("") == "" and normalize_dashes(None) == ""
    assert len(normalize_dashes(NB)) == len(NB)             # tek karakter → tek karakter


def test_output_normalization_keeps_en_em_dash():
    # model çıktısında yalnız tire-benzeri karakterler düzelir; en/em çizgi tipografisi korunur
    assert normalize_hyphens(NB) == "zz-fake-vm-0862"
    assert normalize_hyphens("a\u2212b") == "a-b"
    assert normalize_hyphens("Özet \u2014 durum, 10\u201320 arası") == "Özet \u2014 durum, 10\u201320 arası"
    assert normalize_hyphens("") == "" and normalize_hyphens(None) == ""


def test_normalize_user_text_spaces_and_zero_width():
    assert normalize_user_text("a\u00a0b\u202fc") == "a b c"
    assert normalize_user_text("v\u200bm\ufeff") == "vm"
    assert normalize_user_text(f"{NB} {NB} grafik") == "zz-fake-vm-0862 zz-fake-vm-0862 grafik"
    assert normalize_user_text("düz metin – 5 VM") == "düz metin - 5 VM"


def test_request_models_normalize_input():
    from app.api.chat import ChatRequest as LinuxReq
    from app.api.windows_chat import ChatRequest as WinReq
    from app.api.unified_chat import UnifiedChatRequest
    from app.api.hypervisors import HypervisorAskRequest
    assert LinuxReq(message=NB).message == "zz-fake-vm-0862"
    assert WinReq(message=NB).message == "zz-fake-vm-0862"
    assert UnifiedChatRequest(message=NB).message == "zz-fake-vm-0862"
    assert HypervisorAskRequest(question=NB).question == "zz-fake-vm-0862"


def test_automic_models_untouched():
    for rel in ("api/automation.py",):
        p = APP / rel
        if p.exists():
            assert "chat_text_norm" not in p.read_text(encoding="utf-8")


def test_sanitize_normalizes_model_output():
    from app.services.answer_sanitize import sanitize_llm_answer
    assert sanitize_llm_answer(f"VM {NB} yüksek") == "VM zz-fake-vm-0862 yüksek"
    assert sanitize_llm_answer("Özet \u2014 durum") == "Özet \u2014 durum"        # em çizgi korunur


def test_live_final_tokens_and_final_match_without_replace():
    from app.services.chat_live_final import LiveFinal
    l = LiveFinal()
    for t in ("VM zz\u2011fake", "\u2011vm\u20110862 yüksek."):
        l.on_item({"type": "token", "text": t})
    l.on_item({"type": "final", "final_text": "VM zz\u2011fake\u2011vm\u20110862 yüksek.",
               "final_streamed": True, "final_done_reason": "stop"})

    async def _s():
        return [r async for r in l.settle()]
    out = asyncio.new_event_loop().run_until_complete(_s())
    assert out == [] and l.use_loop_final and l.live_text == l.loop_text == "VM zz-fake-vm-0862 yüksek."


def test_sink_token_normalized_and_progress_event_passthrough():
    from app.services.chat_live_final import LiveSink
    s = LiveSink(allow_thinking=False)
    s.token("a\u2011b")
    s.reset()
    s.event({"type": "progress", "step": "evidence_retry", "text": "yeniden üretiliyor…", "elapsed_s": 0})
    s.token("x")
    p = [json.loads(r[len("data: "):]) for r in s.drain()]
    assert p[0] == {"phase": "answering"} and p[1] == {"token": "a-b"}
    assert p[2] == {"replace_answer": True}
    assert p[3]["type"] == "progress" and p[3]["step"] == "evidence_retry"
    assert s.live_text == "x"


def test_chart_intent_same_for_copied_name():
    """Kopyalanan (U+2011) ad, normal tireyle aynı grafik niyetini verir (DB gerektirmez: niyet ayrıştırma)."""
    from app.services.chat_charts import parse_chart_intent
    q = "{n} {n} bu iki vm'in son 12 saatlik cpu ve memory grafiklerini getirir misin?"
    a = parse_chart_intent(normalize_user_text(q.format(n=NB)), explicit=False)
    b = parse_chart_intent(q.format(n="zz-fake-vm-0862"), explicit=False)
    assert a and b and a["hours"] == b["hours"] == 12.0 and a["groups"] == b["groups"]


def test_guard_contracts():
    h = _src("services/hypervisor_intelligence.py")
    assert "neden=%s" in h and "ilk_cevap=%r" in h                      # C: neden + ilk cevap logu
    assert '"step": "evidence_retry"' in h and "yeniden üretiliyor" in h   # A: ret bildirimi
    guard = h.split("kanıt varken cevap reddedildi")[1]
    assert "_generate_live_sync(" in guard.split("retry_answer")[0]       # A: yeniden üretim canlı akar
    assert guard.count("_sk.reset()") >= 1 and "yeniden üretilen cevap da reddedildi" in guard


def test_guard_flow_rejects_live_answer_then_streams_retry(monkeypatch):
    """Sahte LLM: ilk (kanıtı yok sayan) cevap canlı akar → silinir → bildirim → yeniden üretim canlı akar → ekran == cevap."""
    try:
        from app.core.database import SessionLocal
        db = SessionLocal()
        db.execute(__import__("sqlalchemy").text("select 1"))
    except Exception:
        pytest.skip("DB yok")
    from app.services import hypervisor_intelligence as hi, qa_cache
    from app.services.chat_live_final import LiveSink, live_sink_var
    monkeypatch.setattr(qa_cache, "get_cached_answer", lambda *a, **k: None)
    monkeypatch.setattr(qa_cache, "set_cached_answer", lambda *a, **k: None)
    calls = []

    def fake_live(*, model, prompt, timeout=120, think=None, sink=None):
        sk = live_sink_var.get()
        n = len(calls)
        calls.append(1)
        text = ("Canlı sorguda bu alan dönmedi, veri yok; ayrıntı alınamadı. " * 3) if n == 0 else \
            "En yüksek CPU: fake-esx-101.invalid %91, fake-esx-102.invalid %88; bellek fake-esx-101.invalid %80."
        for i in range(0, len(text), 12):
            sk.token(text[i:i + 12])
        return {"response": text, "done": True}

    monkeypatch.setattr(hi, "_generate_live_sync", fake_live)
    ev = "host fake-esx-101.invalid cpu_pct=91 mem_pct=80; host fake-esx-102.invalid cpu_pct=88 mem_pct=70; host fake-esx-103.invalid cpu_pct=40"
    q = "en yüksek cpu hostlar?\n\n[CANLI ARAÇ SONUÇLARI — yanıtında bunları esas al]\n" + ev
    sink = LiveSink(allow_thinking=False)
    tok = live_sink_var.set(sink)
    try:
        r = hi.answer_hypervisor_question(db, q, model="m", skip_deterministic=True, user_question="en yüksek cpu hostlar?")
    finally:
        live_sink_var.reset(tok)
        db.rollback()
        db.close()
    evs = [json.loads(x[6:]) for x in sink.drain()]
    seq = ["token" if "token" in e else ("replace" if e.get("replace_answer") else (e.get("type") or list(e)[0])) for e in evs]
    assert len(calls) == 2
    assert "replace" in seq and "progress" in seq and seq.index("replace") < seq.index("progress")
    assert seq.index("progress") < len(seq) - 1 and seq[-1] == "token"        # yeniden üretim canlı akıyor
    assert sink.live_text.strip() == r["answer"].strip() and "fake-esx-101.invalid" in r["answer"]
