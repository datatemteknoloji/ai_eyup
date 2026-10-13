"""Adım 6c — cevap kalitesi, kapsam bilgisi, ince taban prompt, sızıntı, semafor/öncelik, ilerleme olayları."""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid

import pytest

from app.services import chat_request_metrics as crm
from app.services import llm_activity, llm_scheduler as sched
from app.services import unified_tool_chat as utc
from app.services.agent.policy import RiskLevel
from app.services.automic.chat_support import AnswerLeakGuard


# ── semafor + öncelik ───────────────────────────────────────────────────────

@pytest.fixture
def local_sched(monkeypatch):
    """Redis'siz, temiz süreç-içi semafor (cap=1)."""
    monkeypatch.setattr(sched, "_redis", lambda: None)
    monkeypatch.setattr(sched, "_local", sched._LocalBackend())
    vals = {"llm_max_concurrent": 1, "llm_sched_bg_max_wait_sec": 5, "llm_sched_max_wait_sec": 10}
    monkeypatch.setattr(sched, "_setting", lambda k, d: vals.get(k, d))
    return vals


def _run(order, name, prio, hold_s, start_delay=0.0):
    def _t():
        time.sleep(start_delay)
        with sched.priority(prio):
            with sched.slot(name):
                order.append(("start", name))
                time.sleep(hold_s)
                order.append(("end", name))
    th = threading.Thread(target=_t)
    th.start()
    return th


def test_semaphore_serializes_calls(local_sched):
    order = []
    ts = [_run(order, f"c{i}", sched.CHAT, 0.15) for i in range(3)]
    [t.join() for t in ts]
    # hiçbir an iki çağrı birlikte çalışmadı: start/end ardışık
    active = 0
    for kind, _ in order:
        active += 1 if kind == "start" else -1
        assert active <= 1


def test_chat_has_priority_over_background_and_background_does_not_start_while_chat_waits(local_sched):
    order = []
    holder = _run(order, "holder", sched.CHAT, 0.4)
    time.sleep(0.05)
    bg = _run(order, "bg", sched.BACKGROUND, 0.05, 0.0)       # önce sıraya girer
    time.sleep(0.05)
    chat = _run(order, "chat", sched.CHAT, 0.05, 0.0)         # sonra gelir ama öncelikli
    for t in (holder, bg, chat):
        t.join()
    starts = [n for k, n in order if k == "start"]
    assert starts == ["holder", "chat", "bg"]


def test_background_bypasses_after_max_wait(local_sched, monkeypatch):
    import threading
    local_sched["llm_sched_bg_max_wait_sec"] = 1
    res = {}

    def bg():   # ayrı bağlam (iç içe slot yeniden-girişli sayılmasın)
        with sched.priority(sched.BACKGROUND):
            with sched.slot("bg") as lease:
                res["lease"] = lease
                res["t"] = time.perf_counter() - res["t0"]

    with sched.priority(sched.CHAT):
        with sched.slot("holder"):
            sched._try_acquire("waiter", sched.CHAT, 1)   # bekleyen sohbet kaydı
            res["t0"] = time.perf_counter()
            th = threading.Thread(target=bg)
            th.start()
            th.join(10)
    assert res["lease"].bypassed and 0.9 <= res["t"] < 4.0


def test_reentrant_and_disabled(local_sched):
    with sched.slot("outer") as a:
        with sched.slot("inner") as b:      # aynı bağlamda iç içe çağrı kilitlenmez
            assert b.bypassed and b.reason == "reentrant"
        assert not a.bypassed
    local_sched["llm_max_concurrent"] = 0
    with sched.slot("x") as c:
        assert c.bypassed and c.reason == "disabled"


def test_current_priority_follows_chat_metrics(local_sched):
    assert sched.current_priority() == sched.BACKGROUND
    m = crm.start("automic", "q")
    try:
        assert sched.current_priority() == sched.CHAT
        sched.set_priority("background")      # benchmark / toplu işler açıkça arka plan olabilir
        assert sched.current_priority() == sched.BACKGROUND
    finally:
        sched.set_priority(None)
        crm.finish(m)


def test_wait_is_recorded_in_turn_metrics_and_activity(local_sched, monkeypatch):
    monkeypatch.setattr(llm_activity, "_redis", lambda: None)
    m = crm.start("automic", "q")
    try:
        crm.begin_llm_turn("tool_selection")
        holder = _run([], "holder", sched.CHAT, 0.3)
        time.sleep(0.05)
        with sched.slot("chat_sync") as lease, llm_activity.track("chat_sync", "gpt-oss:20b", lease=lease) as rec:
            pass
        holder.join()
        assert lease.wait_ms >= 150
        assert rec["priority"] == sched.CHAT and rec["sched_wait_ms"] >= 150
        assert m.llm_turns[-1].sched_wait_ms >= 150 and m.llm_turns[-1].sched_priority == sched.CHAT
        perf = crm.finish(m)
        assert perf["sched_wait_ms_total"] >= 150
        # semafor beklemesi queue_ms_total'in alt kümesi; Ollama tarafı ayrıca
        assert perf["ollama_queue_ms_total"] <= perf["queue_ms_total"]
    finally:
        sched.set_priority(None)


def test_async_slot_waits_without_blocking_loop(local_sched):
    async def main():
        ticks = []

        async def ticker():
            for _ in range(8):
                ticks.append(time.perf_counter())
                await asyncio.sleep(0.03)

        async def use(name, hold):
            async with sched.aslot(name) as lease:
                await asyncio.sleep(hold)
                return lease.wait_ms

        t = asyncio.create_task(ticker())
        w1, w2 = await asyncio.gather(use("a", 0.2), use("b", 0.05))
        await t
        return ticks, max(w1, w2)

    ticks, waited = asyncio.run(main())
    assert waited >= 100                                   # ikincisi kuyrukta bekledi
    assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.15   # olay döngüsü bloklanmadı


def _real_redis():
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        r.ping()
        return r
    except Exception:
        return None


def test_redis_semaphore_cross_process_semantics(monkeypatch):
    r = _real_redis()
    if r is None:
        pytest.skip("Redis yok")
    suffix = uuid.uuid4().hex[:8]
    monkeypatch.setattr(sched, "_ACTIVE_KEY", f"test:llm:sem:active:{suffix}")
    monkeypatch.setattr(sched, "_WAIT_KEY", f"test:llm:sem:wait:{suffix}")
    try:
        assert sched._try_acquire("t1", sched.CHAT, 1) is True
        assert sched._try_acquire("t2", sched.CHAT, 1) is False       # dolu; t2 sohbet bekleyen olarak kayıtlı
        assert sched._try_acquire("bg1", sched.BACKGROUND, 1) is False
        sched._release("t1")
        assert sched._try_acquire("bg1", sched.BACKGROUND, 1) is False  # sohbet (t2) bekliyor → arka plan başlamaz
        assert sched._try_acquire("t2", sched.CHAT, 1) is True
        sched._release("t2")
        assert sched._try_acquire("bg1", sched.BACKGROUND, 1) is True   # bekleyen sohbet kalmadı
        assert sched._try_acquire("bg2", sched.BACKGROUND, 2) is True   # cap=2 → ikinci yuva
    finally:
        r.delete(sched._ACTIVE_KEY, sched._WAIT_KEY)


def test_redis_lease_expires_for_crashed_holder(monkeypatch):
    r = _real_redis()
    if r is None:
        pytest.skip("Redis yok")
    suffix = uuid.uuid4().hex[:8]
    monkeypatch.setattr(sched, "_ACTIVE_KEY", f"test:llm:sem:active:{suffix}")
    monkeypatch.setattr(sched, "_WAIT_KEY", f"test:llm:sem:wait:{suffix}")
    monkeypatch.setattr(sched, "_LEASE_TTL_SEC", -1)   # anında süresi dolmuş lease (çökmüş sahip)
    try:
        assert sched._try_acquire("dead", sched.CHAT, 1) is True
        monkeypatch.setattr(sched, "_LEASE_TTL_SEC", 900)
        assert sched._try_acquire("alive", sched.CHAT, 1) is True
    finally:
        r.delete(sched._ACTIVE_KEY, sched._WAIT_KEY)


# ── sızıntı koruması ───────────────────────────────────────────────────────

def test_leak_guard_fast_release_for_normal_answer():
    g = AnswerLeakGuard()
    # 7g/7h: çıplak `**` ile hızlı akıtma YOK (planlama sızıntısı `**` ile başlayabilir); kalın cümle KAPANINCA akıtılır
    assert g.feed("**Şu an ") == ""
    assert g.feed("24 iş çalışıyor.**") == "**Şu an 24 iş çalışıyor.**"
    assert g.feed(" Devam.") == " Devam."              # sonrası doğrudan akar
    assert g.dropped == 0


def test_leak_guard_holds_monologue_and_records_dropped_text():
    g = AnswerLeakGuard()
    out = ""
    for tok in ["We have total 11724 runs. ", "Need answer.", "\n**BATCH/OPS dün 11 724 iş çalıştırdı.**\n", "Yorum"]:
        out += g.feed(tok)
    assert out.startswith("**BATCH/OPS dün") and "Need answer" not in out
    assert g.dropped > 20 and g.dropped_text.startswith("We have total")


def test_leak_guard_unwraps_markdown_fence_and_keeps_meta():
    g = AnswerLeakGuard()
    out = g.feed("```markdown\n") + g.feed("**Sonuç.**\n") + g.feed("```\n```ainew-meta\n{}\n```")
    assert out.startswith("**Sonuç.**")
    assert "```ainew-meta" in g.clean_full(out)


def test_leak_head_detection_in_metrics():
    m = crm.start("automic", "q")
    try:
        crm.begin_llm_turn("final_answer")
        crm.note_stream_text(content_chars=80, content_head="We have total 5 runs. Need count.")
        t = m.llm_turns[-1]
        assert t.leak_suspect is True and t.content_head.startswith("We have")
        crm.begin_llm_turn("final_answer")
        crm.note_stream_text(content_chars=20, content_head="**Şu an 24 iş çalışıyor.**")
        assert m.llm_turns[-1].leak_suspect is False
        crm.note_leak(42, "We have")
        assert crm.finish(m)["leak_dropped_chars"] == 42
    finally:
        pass


# ── ince taban prompt + veriye dayalılık kuralı ───────────────────────────────

def test_automic_base_prompt_is_thin_and_other_modules_unchanged():
    from app.services.automic.prompt import AUTOMIC_BASE_PROMPT
    assert len(AUTOMIC_BASE_PROMPT) < len(utc.SYSTEM_PROMPT) / 4   # Adım 7: davranış kuralları eklendi (hâlâ ince)
    for word in ("OpenShift", "vCenter", "KubeVirt", "ESXi"):
        assert word not in AUTOMIC_BASE_PROMPT.replace("Linux/Windows/vCenter/OpenShift araçları", "")
    assert "automic_*" in AUTOMIC_BASE_PROMPT


class _FakeTool:
    risk_level = RiskLevel.READ_ONLY
    domains = frozenset({"automic"})

    def preview(self, db, args, ctx):
        return "fake"

    def execute(self, db, args, ctx):
        return {"ok": True, "total": 3, "items": [{"object_name": "JOBS.A.B.01"}]}


@pytest.fixture
def _loop_env(monkeypatch):
    monkeypatch.setattr("app.services.agent.tools.tool_specs_read_only",
                        lambda domains=None: [{"type": "function", "function": {"name": "automic_active"}}])
    monkeypatch.setattr("app.services.agent.tools.get_tool", lambda name: _FakeTool())
    monkeypatch.setattr("app.services.agent.tools.resolve_server", lambda db, args, ctx: None)
    monkeypatch.setattr("app.services.chat_tool_policy.should_use_db_first", lambda **kw: False)


def _capture_system_message(monkeypatch, policy, platform="automic"):
    seen = {}

    def fake_plain(model, messages, tools, timeout=90, **kw):
        seen["sys"] = messages[0]["content"]
        return {"content": "**ok**", "tool_calls": [], "error": None}

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools", fake_plain)
    list(utc.run_read_only_tool_loop(
        db=None, model="gpt-oss:20b", user_message="Şu an kaç iş çalışıyor?", context_str="", server_summary="",
        max_steps=2, domains=frozenset({"automic"}), platform=platform, llm_policy=policy))
    return seen["sys"]


def test_loop_uses_base_prompt_only_when_given(monkeypatch, _loop_env):
    from app.services.automic.prompt import AUTOMIC_BASE_PROMPT
    thin = _capture_system_message(monkeypatch, {"depth": "simple", "stream_final": False,
                                                 "base_prompt": AUTOMIC_BASE_PROMPT,
                                                 "runtime_context": "## 11. runtime\n- Şu an: X"})
    assert thin.startswith(AUTOMIC_BASE_PROMPT)
    assert "OpenShift pod/namespace" not in thin and "KubeVirt" not in thin
    assert thin.rstrip().endswith("- Şu an: X")
    # diğer modüller / politikasız çağrılar: genel prompt aynen korunur
    generic = _capture_system_message(monkeypatch, None)
    assert generic.startswith(utc.SYSTEM_PROMPT)
    generic_pol = _capture_system_message(monkeypatch, {"depth": "simple", "stream_final": False})
    assert generic_pol.startswith(utc.SYSTEM_PROMPT)


def test_static_prompt_has_grounding_rules():
    from app.services.automic.prompt import SYSTEM_PROMPT_STATIC as P
    for must in ("Veriye dayalılık", "Genel bilgi:", "Değerlendirme:", "period_compare", "kapsam dışı",
                 "İşlem yoktu", "kat artış", "return_code_note", "known_error_codes"):
        assert must in P, must
    # sabit ön ekte dinamik yer tutucu yok (prefix cache)
    assert "{{" not in P


# ── kapsam bilgisi + dönem karşılaştırma (salt okunur, DEV-FAKE) ────────────────

def _adb_system():
    from app.services.automic import database as adb_mod
    from app.services.automic.service import resolve_system
    try:
        adb_mod.ensure_schema()
        adb = adb_mod._session_factory()
        system = resolve_system(adb, None)
    except Exception:
        pytest.skip("Automic modül DB okunamıyor")
    if system is None:
        adb.close()
        pytest.skip("Automic sistemi yok")
    return adb, system


def test_history_results_carry_coverage_and_trend_totals_match():
    from app.services.automic import queries as q
    adb, system = _adb_system()
    try:
        res = q.run_history(adb, system, "failure_trend", {"range": "7d"})
        cov = res["coverage"]
        assert {"data_first_at", "data_last_at", "records_in_range", "records_total", "range_days"} <= set(cov)
        # kova toplamı = kapsamdaki kayıt sayısı (model sayıyı kovadan da, kapsamdan da doğrulayabilir)
        assert sum(r["total"] for r in res["rows"]) == cov["records_in_range"]
        if cov["records_in_range"] == 0:
            assert "İşlem yoktu" in cov["note"] or "kayıt yok" in cov["note"]
    finally:
        adb.close()


def test_period_compare_never_computes_ratio_against_missing_period():
    from app.services.automic import queries as q
    adb, system = _adb_system()
    try:
        res = q.run_history(adb, system, "period_compare", {"range": "7d"})
        assert res["ok"] and res["template_id"] == "period_compare"
        cur, prev = res["rows"]
        assert cur["label"] == "bu dönem" and prev["label"] == "önceki dönem"
        assert cur["from"] > prev["from"] and prev["to"] == cur["from"]      # bitişik, aynı uzunlukta dönemler
        assert "coverage" in res
        if cur["data_available"] and prev["data_available"]:
            assert res["comparison_possible"] is True
            d = res["deltas"]
            assert d["total"]["abs"] == cur["total"] - prev["total"]
            assert d["failed"]["abs"] == cur["failed"] - prev["failed"]
            assert cur["failure_rate_pct"] is not None and cur["success_rate_pct"] is not None
        else:
            assert res["comparison_possible"] is False
            assert "deltas" not in res                       # 0'a bölme / 'kat artış' üretilemez
            assert "HESAPLANAMAZ" in res["note"] and "işlem yoktu" in res["note"].lower()
    finally:
        adb.close()


def test_period_compare_deltas_with_synthetic_data(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.services.automic import queries as q

    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(q, "parse_range", lambda rng, f, t: (now - timedelta(days=7), now))
    monkeypatch.setattr(q, "_clients", lambda system, c: [100])
    mk = lambda total, failed, ok, canc: {  # noqa: E731
        "from": "", "to": "", "data_available": total > 0, "total": total, "failed": failed, "ok": ok,
        "cancelled": canc, "failure_rate_pct": round(100 * failed / total, 2) if total else None,
        "success_rate_pct": None, "cancel_rate_pct": None, "first_record_at": None, "last_record_at": None,
        "top_failed_objects": []}
    seq = [mk(1000, 50, 940, 10), mk(800, 20, 770, 10)]
    monkeypatch.setattr(q, "_period_stats", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(q, "data_coverage", lambda *a, **k: {"data_first_at": "x", "data_last_at": "y",
                                                             "records_in_range": 1800})

    class S:  # minimal system
        name = "T"
        id = 1
        clients = [100]
    res = q._period_compare(None, S, {"range": "7d"})
    assert res["comparison_possible"] is True
    assert res["deltas"]["total"] == {"abs": 200, "pct": 25.0}
    assert res["deltas"]["failed"] == {"abs": 30, "pct": 150.0}
    assert res["deltas"]["failure_rate_pp"] == 2.5

    seq[:] = [mk(1000, 50, 940, 10), mk(0, 0, 0, 0)]
    res = q._period_compare(None, S, {"range": "7d"})
    assert res["comparison_possible"] is False and "deltas" not in res


def test_progress_count_hint():
    assert utc._record_count({"coverage": {"records_in_range": 52515}, "total": 3}) == 52515
    assert utc._record_count({"total": 28, "items": [1, 2]}) == 28
    assert utc._record_count({"items": [1, 2, 3]}) == 3
    assert utc._record_count({"ok": True}) is None
    assert utc._record_count("x") is None


def test_progress_events_are_status_only_and_record_first_progress():
    from app.api import automation as au
    m = crm.start("automic", "q")
    try:
        ev = json.loads(au._progress("thinking", "Düşünüyor")[len("data: "):])
        assert ev == {"type": "progress", "step": "thinking", "text": "Düşünüyor"}
        assert "first_progress" in m.phase_ms
        ev2 = json.loads(au._progress("found", "25 kayıt bulundu", tool="automic_active", count=25)[len("data: "):])
        assert ev2["count"] == 25 and ev2["tool"] == "automic_active"
        assert au._tool_label("automic_history") == "Analiz"
    finally:
        crm.finish(m)


def test_debug_trace_only_admin_payload_shape():
    from app.api import automation as au
    tr = au._tool_trace([{"tool": "automic_active", "args": {"limit": 3}, "result": {"ok": True, "total": 28}}])
    assert tr[0]["tool"] == "automic_active" and json.loads(tr[0]["result_json"])["total"] == 28
    assert tr[0]["truncated"] is False


# ── Adım 6c (kalite): araç sonucu dönüşümleri, sort normalizasyonu, devre kesici ──────────────

def test_fmt_duration_and_text_fields():
    from app.services.chat_llm_context import fmt_duration, _slim_row
    assert fmt_duration(45) == "45sn"
    assert fmt_duration(2185) == "36dk 25sn"
    assert fmt_duration(4985) == "1sa 23dk 05sn"
    row = _slim_row({"duration_sec": 2185.0, "run_time_sec": 2185.0, "ert_sec": 89, "avg_sec": 117.4})
    assert row["duration_text"] == "36dk 25sn" and "run_time_sec" not in row
    assert row["ert_text"] == "1dk 29sn" and row["avg_text"] == "1dk 57sn"


def test_compactor_converts_timestamps_to_user_tz():
    from app.services.chat_llm_context import ToolResultCompactor
    c = ToolResultCompactor(tz_name="Europe/Istanbul")
    out = c("t", {"total": 1, "items": [{"end_time": "2026-10-09T23:11:11+00:00"}]})
    assert "2026-10-10 02:11:11+03:00" in out


def test_sort_normalization():
    from app.services.automic.queries import _norm_sort
    assert _norm_sort("end_desc") == ("end_desc", None)
    assert _norm_sort("")[0] == "end_desc"
    assert _norm_sort("latest")[0] == "end_desc"
    s, note = _norm_sort("-run_time_sec")
    assert s == "duration_desc" and note
    assert _norm_sort("end_time_asc")[0] == "end_asc"
    assert _norm_sort("saçma")[0] == "end_desc"


def test_count_summary_has_exact_numbers():
    from app.services.automic.queries import _count_summary
    assert _count_summary({"ok": 11586, "failed": 198, "cancelled": 37}) == \
        "Toplam 11821 çalışma (başarılı 11586, hatalı 198, iptal 37)"


def test_tool_parse_500_does_not_trip_circuit(monkeypatch):
    from app.services import llm_availability, llm_gateway
    calls = []
    monkeypatch.setattr(llm_availability, "record_failure", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(llm_availability, "record_success", lambda *a, **k: None)
    llm_gateway._note_remote_status(500, '{"error":"error parsing tool call: raw=\'{...}\'"}')
    assert not calls
    llm_gateway._note_remote_status(500, "internal error")
    assert calls


def test_return_code_note_added_once_next_to_data():
    from app.services.chat_llm_context import ToolResultCompactor
    c = ToolResultCompactor()
    out = c("t", {"total": 2, "items": [{"return_code": 8}, {"return_code": 8}]})
    assert out.count("return_code_note") == 1
    ok = c("t", {"total": 1, "items": [{"return_code": 0}]})
    assert "return_code_note" not in ok
