"""Adım 6b — LLM kullanım optimizasyonu: politika, sonuç küçültme, stream son tur,
prompt ön eki, etkinlik kaydı."""
from __future__ import annotations

import json
import time

import pytest

from app.services import chat_request_metrics as crm
from app.services import llm_activity
from app.services import llm_chat_policy as lcp
from app.services import unified_tool_chat as utc
from app.services.agent import llm as agent_llm
from app.services.agent.policy import RiskLevel
from app.services.chat_llm_context import ToolResultCompactor, compact_result


# ── madde 2/3: soru derinliği + think + num_predict ─────────────────────────

@pytest.mark.parametrize("q,expected", [
    ("JOBS.DWH.SYNC.01 en son ne zaman çalıştı?", "simple"),
    ("Şu an kaç iş çalışıyor?", "simple"),
    ("Hangi job'lar hata verdi?", "simple"),
    ("BATCH/OPS kullanıcısı dün kaç iş çalıştırdı?", "simple"),
    ("Dün gece hata veren job'ları agent'a göre grupla", "simple"),
    ("BATCH/OPS kullanıcısının hatalı işleri", "simple"),
    ("Son 7 günde en uzun süren 5 job", "simple"),
    ("JOBS.DWH.SYNC.01 neden hata verdi?", "analysis"),
    ("En çok hata veren 5 job ve ortak noktaları", "analysis"),
    ("Bu hafta geçen haftaya göre ne değişti?", "analysis"),
    ("Merhaba", "default"),
])
def test_question_depth(q, expected):
    assert lcp.classify_question_depth(q) == expected


def test_think_levels_defaults_and_sticky(monkeypatch):
    vals = {"llm_think_sticky": True}
    monkeypatch.setattr(lcp, "_setting", lambda k, d: vals.get(k, d))
    assert lcp.think_level("simple", tool_selection=False) == "low"
    assert lcp.think_level("analysis", tool_selection=False) == "medium"
    assert lcp.think_level("default", tool_selection=False) == "medium"  # emin değil → medium
    # sticky: araç seçim turu cevap seviyesini kullanır (prefix cache)
    assert lcp.think_level("analysis", tool_selection=True) == "medium"
    vals["llm_think_sticky"] = False
    assert lcp.think_level("analysis", tool_selection=True) == "low"
    vals["llm_think_simple"] = "high"
    assert lcp.think_level("simple", tool_selection=False) == "high"
    vals["llm_think_simple"] = "bogus"
    assert lcp.think_level("simple", tool_selection=False) == "low"


def test_num_predict_and_bump(monkeypatch):
    monkeypatch.setattr(lcp, "_setting", lambda k, d: d)
    assert lcp.num_predict_for("low") == 1536
    assert lcp.num_predict_for("medium") == 3072
    assert lcp.bumped_num_predict(1536) == 3072
    assert lcp.bumped_num_predict(10000) == 12288  # üst sınır


def test_think_only_for_gpt_oss():
    assert lcp.supports_think_level("gpt-oss:20b")
    assert not lcp.supports_think_level("llama3.2:3b")


# ── madde 4: araç sonucu küçültme ───────────────────────────────────────────

def _active_result(n=50):
    rows = [{
        "run_id": i, "object_name": f"JOBS.X.{i}", "status": "ACTIVE", "user_idnr": 5,
        "snapshot_at": "2026-10-10T10:00:00.123456+00:00",
        "start_time": "2026-10-10T09:00:00.987654+00:00", "empty": None, "ert_calc": 2,
    } for i in range(n)]
    return {"ok": True, "system_id": 1, "total": n, "items": rows, "over_p95": list(rows)}


def test_compact_result_rows_dedupe_columns_and_note():
    notes: list = []
    out = compact_result(_active_result(), max_rows=20, notes=notes)
    assert out["total"] == 50                       # skaler özet önce
    assert list(out.keys())[0] in ("ok", "total")
    items = out["items"]
    assert items["_note"] == "toplam 50 kayıt, ilk 20 gösteriliyor"
    assert len(items["rows"]) == 20
    assert "user_idnr" not in items["rows"][0] and "empty" not in items["rows"][0]
    assert items["rows"][0]["start_time"] == "2026-10-10 09:00:00+00:00"  # mikrosaniye atıldı
    assert isinstance(out["over_p95"], str) and "items" in out["over_p95"]  # tekrar listesi tekilleşti
    assert "system_id" not in out


def test_compact_result_adds_full_distribution_for_truncated_lists():
    rows = [{"run_id": i, "state": ("running" if i % 3 else "blocked"), "agent": f"A{i % 2}"} for i in range(30)]
    out = compact_result({"ok": True, "total": 30, "items": rows}, max_rows=5)
    dist = out["items"]["_dagilim_tum_kayitlar"]
    assert dist["state"] == {"running": 20, "blocked": 10}   # tüm 30 satır üzerinden
    assert dist["agent"] == {"A0": 15, "A1": 15}
    assert len(out["items"]["rows"]) == 5
    small = compact_result({"items": rows[:3]}, max_rows=5)
    assert isinstance(small["items"], list)                   # sınırın altında ek alan yok


def test_answer_length_hint_by_depth():
    assert "KISA" in lcp.answer_length_hint("simple")
    assert "ORTA" in lcp.answer_length_hint("analysis")
    assert lcp.answer_length_hint("zzz") == lcp.answer_length_hint("default")


def test_compactor_token_cap_and_ui_data_untouched():
    result = _active_result(200)
    before = json.dumps(result, sort_keys=True)
    c = ToolResultCompactor()
    text = c("automic_active", result)
    assert json.dumps(result, sort_keys=True) == before  # UI/structured tam veri değişmez
    assert len(c.log) == 1 and c.log[0]["llm_tokens"] <= c.max_tokens_each
    assert c.log[0]["llm_tokens"] < c.log[0]["raw_tokens"] / 3
    assert "toplam 200 kayıt" in text


def test_compactor_masks_before_llm():
    c = ToolResultCompactor(mask_fn=lambda r: json.loads(json.dumps(r).replace("secret", "***")))
    text = c("t", {"ok": True, "items": [{"note": "secret-token"}]})
    assert "secret" not in text and "***" in text


def test_compactor_total_budget():
    c = ToolResultCompactor()
    c.max_tokens_total = 1500
    c.max_tokens_each = 1000
    for _ in range(3):
        c("t", _active_result(100))
    assert c.total_tokens <= 1500 + 400  # taban pay (400) dahil


# ── madde 1: tool loop son turu stream ──────────────────────────────────────

class _FakeTool:
    risk_level = RiskLevel.READ_ONLY
    domains = frozenset({"automic"})

    def preview(self, db, args, ctx):
        return "fake"

    def execute(self, db, args, ctx):
        return _active_result(50)


@pytest.fixture
def _loop_env(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent.tools.tool_specs_read_only",
        lambda domains=None: [{"type": "function", "function": {"name": "automic_active"}}],
    )
    monkeypatch.setattr("app.services.agent.tools.get_tool", lambda name: _FakeTool())
    monkeypatch.setattr("app.services.agent.tools.resolve_server", lambda db, args, ctx: None)
    monkeypatch.setattr("app.services.chat_tool_policy.should_use_db_first", lambda **kw: False)


def _run_loop(policy, model="gpt-oss:20b"):
    return list(utc.run_read_only_tool_loop(
        db=None, model=model, user_message="Şu an kaç iş çalışıyor?",
        context_str="", server_summary="", max_steps=4,
        domains=frozenset({"automic"}), platform="automic", llm_policy=policy,
    ))


def test_loop_streams_last_turn_without_extra_llm_call(monkeypatch, _loop_env):
    calls = {"plain": [], "stream": []}

    def fake_plain(model, messages, tools, timeout=90, **kw):
        calls["plain"].append(kw)
        return {"content": "", "error": None,
                "tool_calls": [{"id": "c1", "name": "automic_active", "arguments": {}}]}

    def fake_stream(model, messages, tools, timeout=90, **kw):
        calls["stream"].append((kw, messages))
        yield {"type": "token", "text": "**50 iş "}
        yield {"type": "token", "text": "çalışıyor.**"}
        yield {"type": "result", "content": "**50 iş çalışıyor.**", "tool_calls": [],
               "error": None, "streamed_chars": 22, "done_reason": "stop"}

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools", fake_plain)
    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", fake_stream)
    seen = []
    policy = {
        "depth": "simple", "stream_final": True,
        "result_transform": lambda name, r: (seen.append(name) or ToolResultCompactor()(name, r)),
        "runtime_context": "## 11. Çalışma zamanı bağlamı\n- Şu an: X",
    }
    events = _run_loop(policy)
    kinds = [e["type"] for e in events]
    assert kinds.index("answer_start") < kinds.index("token") < kinds.index("final")
    assert "".join(e["text"] for e in events if e["type"] == "token") == "**50 iş çalışıyor.**"
    final = events[-1]
    assert final["final_streamed"] is True and final["final_text"].startswith("**50")
    assert final["final_done_reason"] == "stop"
    # tam yapısal sonuç (UI) küçültülmemiş
    assert len(final["structured_results"][0]["result"]["items"]) == 50
    # LLM'e giden araç metni küçültülmüş
    assert "toplam 50 kayıt, ilk 20 gösteriliyor" in final["tool_text"]
    assert seen == ["automic_active"]
    # 1 akışsız (araç seçimi) + 1 stream (son tur) = toplam 2 LLM turu; ayrı final yok
    assert len(calls["plain"]) == 1 and len(calls["stream"]) == 1
    # think seviyesi gpt-oss için gönderildi (simple → low) ve num_predict tavanı
    assert calls["plain"][0]["think"] == "low" and calls["plain"][0]["num_predict"] == 1536
    kw, msgs = calls["stream"][0]
    assert kw["think"] == "low"
    # çalışma zamanı bağlamı sistem mesajının EN SONUNDA
    sys_msg = msgs[0]["content"]
    assert sys_msg.rstrip().endswith("- Şu an: X")


def test_loop_without_policy_is_unchanged(monkeypatch, _loop_env):
    calls = []

    def fake_plain(model, messages, tools, timeout=90):  # think/num_predict kabul ETMEZ
        calls.append(1)
        if len(calls) == 1:
            return {"content": "", "error": None,
                    "tool_calls": [{"id": "c1", "name": "automic_active", "arguments": {}}]}
        return {"content": "bitti", "tool_calls": [], "error": None}

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools", fake_plain)
    events = _run_loop(None)
    final = events[-1]
    assert final["type"] == "final" and "final_text" not in final
    assert not any(e["type"] in ("token", "answer_start") for e in events)


def test_loop_non_gpt_oss_gets_no_think(monkeypatch, _loop_env):
    seen = []

    def fake_plain(model, messages, tools, timeout=90, **kw):
        seen.append(kw)
        if len(seen) == 1:
            return {"content": "", "error": None,
                    "tool_calls": [{"id": "c1", "name": "automic_active", "arguments": {}}]}
        return {"content": "ok", "tool_calls": [], "error": None}

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools", fake_plain)
    _run_loop({"depth": "simple", "stream_final": False}, model="llama3.2:3b")
    assert all(kw.get("think") is None and kw.get("num_predict") is None for kw in seen)


def test_loop_no_live_stream_without_tools(monkeypatch, _loop_env):
    """Araç çağrılmadıysa (kanıt nudge / yedek plan olasılığı) cevap canlı akıtılmaz."""
    def fake_plain(model, messages, tools, timeout=90, **kw):
        return {"content": "genel cevap", "tool_calls": [], "error": None}

    def boom(*a, **k):
        raise AssertionError("stream çağrılmamalı")

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools", fake_plain)
    monkeypatch.setattr("app.services.agent.llm.chat_with_tools_stream", boom)
    monkeypatch.setattr(utc, "_needs_tool_evidence", lambda: False, raising=False)
    events = _run_loop({"depth": "simple", "stream_final": True})
    final = events[-1]
    assert final["type"] == "final" and final["final_streamed"] is False
    assert final["final_text"] == "genel cevap"


# ── madde 1/3/7: agent.llm.chat_with_tools_stream ───────────────────────────

class _GW:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = []

    def chat_stream_iter(self, model, messages, **kw):
        self.calls.append(kw)
        yield from self.scripts.pop(0)


def _patch_gw(monkeypatch, scripts):
    gw = _GW(scripts)
    monkeypatch.setattr("app.services.llm_gateway.chat_stream_iter", gw.chat_stream_iter)
    return gw


def _collect(gen):
    toks, result = [], None
    for ev in gen:
        if ev["type"] == "token":
            toks.append(ev["text"])
        else:
            result = ev
    return toks, result


def test_stream_holds_short_preamble_when_tool_call_follows(monkeypatch):
    _patch_gw(monkeypatch, [[
        {"type": "thinking", "text": "düşünüyor"},
        {"type": "content", "text": "Bakayım."},
        {"type": "tool_calls", "calls": [{"function": {"name": "automic_active", "arguments": {}}}]},
        {"type": "done", "data": {"done_reason": "stop", "eval_count": 5}},
    ]])
    toks, res = _collect(agent_llm.chat_with_tools_stream("gpt-oss:20b", [], [{"x": 1}], think="low", num_predict=1536))
    assert toks == []                      # ön söz kullanıcıya sızmadı
    assert res["tool_calls"][0]["name"] == "automic_active"
    assert res["streamed_chars"] == 0


def test_stream_releases_after_hold_threshold_and_flushes_short(monkeypatch):
    long_txt = "A" * 90
    _patch_gw(monkeypatch, [[
        {"type": "content", "text": long_txt}, {"type": "content", "text": "tail"},
        {"type": "done", "data": {"done_reason": "stop"}},
    ]])
    toks, res = _collect(agent_llm.chat_with_tools_stream("gpt-oss:20b", [], None))
    assert "".join(toks) == long_txt + "tail" and res["streamed_chars"] == 94
    _patch_gw(monkeypatch, [[
        {"type": "content", "text": "kısa"}, {"type": "done", "data": {"done_reason": "stop"}},
    ]])
    toks, res = _collect(agent_llm.chat_with_tools_stream("gpt-oss:20b", [], None))
    assert toks == ["kısa"] and res["content"] == "kısa"


def test_stream_length_empty_retries_once_with_higher_cap(monkeypatch, caplog):
    gw = _patch_gw(monkeypatch, [
        [{"type": "thinking", "text": "x" * 3000}, {"type": "done", "data": {"done_reason": "length", "eval_count": 1536}}],
        [{"type": "content", "text": "Cevap geldi."}, {"type": "done", "data": {"done_reason": "stop"}}],
    ])
    with caplog.at_level("WARNING"):
        toks, res = _collect(agent_llm.chat_with_tools_stream(
            "gpt-oss:20b", [], None, think="low", num_predict=1536))
    assert res["content"] == "Cevap geldi."
    assert [c["options"]["num_predict"] for c in gw.calls] == [1536, 3072]
    assert any("done_reason=length" in r.message for r in caplog.records)


def test_stream_error_falls_back_to_non_stream(monkeypatch):
    _patch_gw(monkeypatch, [[{"type": "error", "status": 500, "text": "boom"}]])
    monkeypatch.setattr(agent_llm, "chat_with_tools",
                        lambda *a, **k: {"content": "yedek", "tool_calls": [], "error": None})
    toks, res = _collect(agent_llm.chat_with_tools_stream("gpt-oss:20b", [], None))
    assert res["content"] == "yedek" and res["streamed_chars"] == 0


# ── madde 5: prompt ön eki ──────────────────────────────────────────────────

def test_prompt_static_prefix_has_no_placeholders_and_runtime_is_last():
    from app.services.automic import prompt as p
    assert "{{" not in p.SYSTEM_PROMPT_STATIC
    assert "{{" in p.SYSTEM_PROMPT_RUNTIME
    assert p.SYSTEM_PROMPT_TEMPLATE.startswith(p.SYSTEM_PROMPT_STATIC)
    assert p.SYSTEM_PROMPT_TEMPLATE.endswith(p.SYSTEM_PROMPT_NOW)
    assert "{{CURRENT_TIME}}" not in p.SYSTEM_PROMPT_RUNTIME and "{{CURRENT_TIME}}" in p.SYSTEM_PROMPT_NOW
    assert "Kısa tut" in p.SYSTEM_PROMPT_STATIC
    rows = p.prompt_variable_field_report()
    assert rows and all(r["prefix_cache_safe"] == "yes" for r in rows)


def test_tool_specs_order_is_deterministic():
    from app.services.agent import tools as tm
    a = json.dumps(tm.tool_specs_read_only(domains=frozenset({"automic"})), ensure_ascii=False)
    b = json.dumps(tm.tool_specs_read_only(domains=frozenset({"automic"})), ensure_ascii=False)
    assert a == b


# ── madde 6/7: metrik + etkinlik kaydı ──────────────────────────────────────

def test_queue_time_and_unaccounted_and_empty_reason():
    m = crm.start("automic", "q")
    try:
        crm.begin_llm_turn("tool_selection", think="low", num_predict=1536, streamed=True)
        time.sleep(0.05)
        crm.record_ollama_stats({
            "prompt_eval_count": 100, "prompt_eval_duration": 10_000_000,
            "eval_count": 1536, "eval_duration": 20_000_000, "total_duration": 30_000_000,
            "load_duration": 0, "done_reason": "length",
        })
        crm.mark_empty_turn()
        crm.note_visible_token()
        crm.set_final_turn_reason("test")
        time.sleep(0.02)
        payload = crm.finish(m)
    finally:
        pass
    t = payload["llm_turns"][0]
    assert t["done_reason"] == "length" and t["think"] == "low" and t["num_predict"] == 1536
    assert t["queue_ms"] >= 15            # duvar süresi − motor süresi (30 ms)
    assert "done_reason=length" in t["empty_reason"]
    assert payload["queue_ms_total"] >= 15
    assert payload["unaccounted_ms"] > 0
    assert payload["first_visible_token_ms"] is not None
    assert payload["final_turn_reason"] == "test"


def test_llm_activity_overlap_and_caller(monkeypatch):
    monkeypatch.setattr(llm_activity, "_redis", lambda: None)  # test kaydı gerçek Redis'e yazılmasın
    t0 = time.time()
    with llm_activity.track("chat_sync", "gpt-oss:20b"):
        time.sleep(0.02)
    ov = llm_activity.overlapping(t0 - 1, time.time() + 1)
    assert any(x["kind"] == "chat_sync" and x["model"] == "gpt-oss:20b" for x in ov)
    ov2 = llm_activity.overlapping(time.time() + 10, time.time() + 11)
    assert ov2 == []
    ex = llm_activity.overlapping(t0 - 1, time.time() + 1, exclude_request_id="nope")
    assert ex


def test_leak_guard_drops_inline_monologue_before_bold_lead():
    from app.services.automic.chat_support import AnswerLeakGuard

    g = AnswerLeakGuard()
    out = ""
    for tok in ["We have total 11724 runs. Need count. Provide number.", "**BATCH/OPS dün 11 724 iş çalıştırdı.**", "\n\nYorum: ok"]:
        out += g.feed(tok)
    out += g.flush()
    assert out.startswith("**BATCH/OPS dün")
    assert "Need count" not in out
