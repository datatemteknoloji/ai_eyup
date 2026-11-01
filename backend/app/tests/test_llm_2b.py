"""Adım 3 / Parça 2B: araç turu bütçesi, öncelik, görünürlük (uyarılar, debug_trace)."""
import threading
import time

import pytest

from app.services import llm_activity, llm_scheduler as sch


@pytest.fixture(autouse=True)
def _izole(monkeypatch):
    """Redis'siz, temiz yerel kayıt (canlı verilerden bağımsız)."""
    monkeypatch.setattr(llm_activity, "_redis", lambda: None)
    monkeypatch.setattr(sch, "_redis", lambda: None)
    with llm_activity._lock:
        llm_activity._recent.clear()
        llm_activity._inflight.clear()
    llm_activity._skipped_local.clear()
    sch._local = sch._LocalBackend()
    sch._held.set(None)
    sch._prio_override.set(None)
    monkeypatch.setattr(sch, "max_concurrent", lambda: 1)
    monkeypatch.setattr(llm_activity, "_is_test_rec", lambda x: False)   # bu testlerin kendi kayıtları sayılsın
    yield
    with llm_activity._lock:
        llm_activity._recent.clear()
    sch._prio_override.set(None)


# ── 2.4 öncelik ───────────────────────────────────────────────────────────

def test_varsayilan_background():
    assert sch.current_priority() == sch.BACKGROUND


def test_chat_priority_atar_ve_geri_alir():
    with sch.chat_priority():
        assert sch.current_priority() == sch.CHAT
    assert sch.current_priority() == sch.BACKGROUND


def test_chat_priority_acik_background_atamasini_korur():
    sch.set_priority("background")           # Automic gibi açık atama
    with sch.chat_priority():
        assert sch.current_priority() == sch.BACKGROUND


def test_mark_chat_yalniz_atanmamissa():
    sch.mark_chat()
    assert sch.current_priority() == sch.CHAT
    sch.set_priority("background")
    sch.mark_chat()
    assert sch.current_priority() == sch.BACKGROUND


def test_chat_priority_thread_a_sizmaz():
    seen = {}

    def _w():
        with sch.chat_priority():
            seen["in"] = sch.current_priority()
        seen["after"] = sch.current_priority()

    t = threading.Thread(target=_w)
    t.start(); t.join()
    assert seen == {"in": sch.CHAT, "after": sch.BACKGROUND}


def test_sohbet_kuyruktayken_arka_plan_baslamaz_sohbet_yokken_calisir():
    """Slot dolu; bir sohbet bekliyor → arka plan alamaz. Sohbet yokken arka plan slotu alır."""
    cap = 1
    assert sch._try_acquire("hold", sch.BACKGROUND, cap)              # slot dolu (arka plan işi)
    assert not sch._try_acquire("chat1", sch.CHAT, cap)               # sohbet bekleme listesine yazıldı
    sch._release("hold")                                              # slot boşaldı
    # sohbet hâlâ bekliyor → arka plan BAŞLAMAZ
    assert not sch._try_acquire("bg1", sch.BACKGROUND, cap)
    # sohbet alır
    assert sch._try_acquire("chat1", sch.CHAT, cap)
    sch._release("chat1")
    # sohbet yok → arka plan çalışır
    assert sch._try_acquire("bg1", sch.BACKGROUND, cap)
    sch._release("bg1")


def test_tool_dongusu_cagrilari_chat_onceligiyle(monkeypatch):
    """Politikasız araç turu: LLM çağrısı CHAT önceliğiyle yapılır; çağrı sonrası bağlam geri alınır."""
    from app.services import unified_tool_chat as utc
    seen = {}

    def _fake(model, messages, specs, timeout=0, **kw):
        seen["prio"] = sch.current_priority()
        seen["timeout"] = timeout
        seen["kw"] = kw
        return {"content": "tamam", "tool_calls": [], "error": None}

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools", _fake)
    out = list(utc.run_read_only_tool_loop(
        None, "gpt-oss:20b", "merhaba", "", "", max_steps=1, platform="unified",
    ))
    assert out, "araç döngüsü sonuç üretmedi"
    assert seen["prio"] == sch.CHAT
    assert sch.current_priority() == sch.BACKGROUND
    assert seen["timeout"] >= 90


def test_automic_politikali_yol_chat_atamasi_yapmaz(monkeypatch):
    from app.services import unified_tool_chat as utc
    seen = {}

    def _fake(model, messages, specs, timeout=0, **kw):
        seen["prio"] = sch.current_priority()
        seen["timeout"] = timeout
        return {"content": "tamam", "tool_calls": [], "error": None}

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools", _fake)
    list(utc.run_read_only_tool_loop(
        None, "gpt-oss:20b", "merhaba", "", "", max_steps=1, platform="automic",
        llm_policy={"depth": "default"},
    ))
    assert seen["prio"] == sch.BACKGROUND      # Automic etkilenmez (varsayılan background)
    assert seen["timeout"] == 90               # eski sabit


# ── 2.2 bütçe ─────────────────────────────────────────────────────────────

def test_arac_turu_butcesi_varsayilan_gpt_oss(monkeypatch):
    from app.services import unified_tool_chat as utc
    think, np = utc._default_tool_budget("gpt-oss:20b")
    assert (think, np) == ("medium", 6144)
    assert utc._default_tool_budget("llama3.2:3b") == (None, 6144)    # think yalnız gpt-oss


def test_arac_turu_butcesi_kapatilabilir(monkeypatch):
    from app.services import unified_tool_chat as utc
    from app.services import runtime_settings as rs
    monkeypatch.setattr(rs, "get_setting", lambda k: 0 if k == "unified_tool_num_predict" else "medium")
    assert utc._default_tool_budget("gpt-oss:20b") == (None, None)    # 0 = sınırsız (eski davranış)


def test_arac_turu_payloadina_think_ve_num_predict_girer(monkeypatch):
    from app.services import unified_tool_chat as utc
    seen = {}

    def _fake(model, messages, specs, timeout=0, **kw):
        seen.update(kw)
        return {"content": "ok", "tool_calls": [], "error": None}

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools", _fake)
    list(utc.run_read_only_tool_loop(None, "gpt-oss:20b", "x", "", "", max_steps=1, platform="unified"))
    assert seen.get("think") == "medium" and seen.get("num_predict") == 6144


def test_length_retry_agent_llm_kalibi_mevcut():
    """done_reason=length + boş çıktı → bir kez daha yüksek tavan (agent/llm.py, mevcut kalıp)."""
    from app.services.llm_chat_policy import bumped_num_predict
    assert bumped_num_predict(6144) == 12288
    import inspect
    from app.services.agent import llm as agent_llm
    src = inspect.getsource(agent_llm._chat_with_tools_once)
    assert 'done_reason") == "length"' in src and "bumped_num_predict" in src


def test_ayarlar_kayitli_2b():
    from app.services.runtime_settings import ADVANCED_SCHEMA as A
    assert A["unified_tool_num_predict"]["default"] == 6144 and A["unified_tool_num_predict"]["min"] == 0
    assert A["unified_tool_think"]["default"] == "medium"
    for k in ("llm_warn_window_sec", "llm_warn_queue_wait_ms", "llm_warn_best_effort_timeouts",
              "llm_warn_hint_skips", "llm_warn_tool_turn_limit"):
        assert A[k]["group"] == "llm_chat"
    assert "OLLAMA_NUM_PARALLEL" in A["llm_max_concurrent"]["help"]


# ── 2.3 llm_activity alanları ─────────────────────────────────────────────

def test_track_sinif_timeout_ve_sinira_dayanma():
    with llm_activity.track("chat_sync", "m", timeout=0.05):
        time.sleep(0.06)                     # sınıra dayandı, yanıt (token) yok
    r = llm_activity.recent(5)[0]
    assert r["tclass"] == "tool_turn" and r["timeout_s"] == 0.05
    assert r["hit_timeout"] is True


def test_track_basarili_cagri_sinira_dayanmis_sayilmaz():
    with llm_activity.track("chat_sync", "m", timeout=0.05) as rec:
        time.sleep(0.06)
        rec["completion_tokens"] = 12         # yanıt geldi
    assert llm_activity.recent(5)[0]["hit_timeout"] is False


def test_note_result_token_ve_done_reason():
    from app.services import llm_usage
    with llm_activity.track("chat_sync", "m", timeout=90):
        llm_usage.record({"prompt_eval_count": 100, "eval_count": 321, "done_reason": "length",
                          "eval_duration": 4_000_000_000})
    r = llm_activity.recent(5)[0]
    assert r["completion_tokens"] == 321 and r["prompt_tokens"] == 100
    assert r["done_reason"] == "length" and r["eval_ms"] == 4000.0
    assert not r.get("hit_timeout")


def test_note_result_openai_finish_reason():
    from app.services import llm_usage
    with llm_activity.track("chat_sync", "m"):
        llm_usage.record({"choices": [{"finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}})
    r = llm_activity.recent(5)[0]
    assert r["completion_tokens"] == 7 and r["done_reason"] == "stop"


def test_classify():
    c = llm_activity.classify
    assert c("generate_sync", "route_hint") == "route_hint"
    assert c("chat_sync") == "tool_turn"
    assert c("stream_generate") == "final_answer"
    assert c("generate_sync") == "background"


def test_skipped_kaydi_sinifli_ve_istatistikte():
    llm_activity.note_skipped("generate_sync", "slot_busy", label="route_hint")
    llm_activity.note_skipped("generate_sync", "slot_busy", label="route_hint")
    st = llm_activity.window_stats(60)
    assert st["skipped"] == {"route_hint:slot_busy": 2}
    assert st["calls"] == 0


# ── 2.3 sağlık uyarıları ──────────────────────────────────────────────────

def _fake_stats(**kw):
    base = {"window_sec": 1800, "calls": 10, "sched_wait_ms_avg": 0.0, "sched_wait_ms_p95": 0.0,
            "by_class": {}, "skipped": {}, "priority": {}}
    base.update(kw)
    return base


def test_uyari_yok_sakin(monkeypatch):
    from app.services import llm_transport as lt
    monkeypatch.setattr(llm_activity, "window_stats", lambda w: _fake_stats())
    assert lt.activity_warnings() == []


def test_uyari_kuyruk_bekleme(monkeypatch):
    from app.services import llm_transport as lt
    monkeypatch.setattr(llm_activity, "window_stats", lambda w: _fake_stats(sched_wait_ms_p95=12000.0))
    w = lt.activity_warnings()
    assert any("Kuyruk bekleme yüksek" in x and "llm_max_concurrent" in x for x in w)


def test_uyari_best_effort_hint_atlama_arac_turu(monkeypatch):
    from app.services import llm_transport as lt
    monkeypatch.setattr(llm_activity, "window_stats", lambda w: _fake_stats(
        by_class={"route_hint": {"calls": 9, "hit_timeout": 4}, "tool_turn": {"calls": 30, "hit_timeout": 3}},
        skipped={"route_hint:slot_busy": 7},
    ))
    w = " | ".join(lt.activity_warnings())
    assert "İsteğe bağlı çağrılar sık zaman aşımına" in w
    assert "ipucu sık atlanıyor" in w
    assert "Araç turu çağrıları zaman aşımı sınırına dayanıyor" in w


def test_uyari_esik_altinda_cikmaz(monkeypatch):
    from app.services import llm_transport as lt
    monkeypatch.setattr(llm_activity, "window_stats", lambda w: _fake_stats(
        by_class={"route_hint": {"calls": 9, "hit_timeout": 1}, "tool_turn": {"calls": 30, "hit_timeout": 1}},
        skipped={"route_hint:slot_busy": 2}, sched_wait_ms_p95=100.0,
    ))
    assert lt.activity_warnings() == []


def test_uyari_hatada_bos_ve_erisimi_engellemez(monkeypatch):
    from app.services import llm_transport as lt

    def _boom(w):
        raise RuntimeError("redis yok")

    monkeypatch.setattr(llm_activity, "window_stats", _boom)
    assert lt.activity_warnings() == []


def test_build_llm_health_uyarilari_ekler_erisim_ayni(monkeypatch):
    from app.services import llm_transport as lt
    monkeypatch.setattr(lt, "activity_warnings", lambda: ["Kuyruk bekleme yüksek (deneme)"])
    monkeypatch.setattr(lt, "resolve_active_transport", lambda ai_source=None: lt.TRANSPORT_OPENAI)
    monkeypatch.setattr(lt, "discover_model_context_length", lambda **kw: 8192)
    monkeypatch.setattr(lt, "get_effective_context_tokens", lambda **kw: 8192)
    h = lt.build_llm_health()
    assert h["ok"] is True and h["reachable"] is True
    assert "Kuyruk bekleme yüksek (deneme)" in h["warnings"]


# ── 2.3 debug_trace ───────────────────────────────────────────────────────

def test_trace_llm_ozeti_yalniz_kayit_varsa():
    from app.services.chat_quality import trace as cq
    tr = cq.TurnTrace(turn_id="T-1", platform="unified", debug_enabled=True)
    assert "llm" not in tr.to_debug_dict()                # kayıt yok → no-op
    tok = cq.bind(tr)
    try:
        with llm_activity.track("chat_sync", "m", timeout=90) as rec:
            rec["sched_wait_ms"] = 1234.0
        llm_activity.note_skipped("generate_sync", "slot_busy", label="route_hint")
    finally:
        cq.unbind(tok)
    d = tr.to_debug_dict()
    assert d["llm"]["calls"] == 1 and d["llm"]["skipped"] == 1
    assert d["llm"]["sched_wait_ms_total"] == 1234.0
    assert d["llm"]["calls_detail"][0]["class"] in ("tool_turn", "route_hint")


def test_trace_baska_turun_kaydi_karismaz():
    from app.services.chat_quality import trace as cq
    tr1 = cq.TurnTrace(turn_id="A", platform="unified")
    tr2 = cq.TurnTrace(turn_id="B", platform="unified")
    tok = cq.bind(tr1)
    try:
        with llm_activity.track("chat_sync", "m"):
            pass
    finally:
        cq.unbind(tok)
    assert "llm" in tr1.to_debug_dict()
    assert "llm" not in tr2.to_debug_dict()


# ── hint önbelleği: RBAC süzmesi hint'ten SONRA ───────────────────────────

def test_hint_onbellegi_kullaniciya_ozel_veri_tutmaz_ve_rbac_sonra():
    """Önbellek anahtarı yalnız mesaj+plan karmasıdır (kullanıcı/rol yok); RBAC süzmesi
    (`_route_denied_modules`) hint sonucunun TÜKETİCİSİNDE, hint'ten sonra uygulanır."""
    import inspect
    from app.services import route_llm_hint as rh
    src = inspect.getsource(rh._cache_key)
    assert "user" not in src.lower() and "role" not in src.lower()
    from app.api import unified_chat as uc
    code = inspect.getsource(uc)
    # rota (hint dahil: route_unified → apply_route_llm_hint) ÖNCE, RBAC süzmesi SONRA
    # Adım 11: route_unified artık event döngüsünü bloklamamak için `await run_chat_io(route_unified, ...)` ile çağrılır
    _call = "_route = await run_chat_io(\n                    route_unified," if "_route = await run_chat_io(" in code else "_route = route_unified("
    assert code.index(_call) < code.index("_denied_mods = _route_denied_modules(_route")
    from app.services import unified_intent_router as uir
    assert "apply_route_llm_hint" in inspect.getsource(uir)


# ── sağlık kartı: model verilmeden çağrı (önceden TypeError → /platform/llm-health 500) ─────

def test_active_model_name_hata_vermez(monkeypatch):
    from app.services import llm_transport as lt
    assert isinstance(lt._active_model_name(), str)
    from app.services import ollama_runtime as orr
    assert isinstance(orr.active_model_name(), str)
    import app.core.config as cfg

    def _boom(db):
        raise RuntimeError("db yok")

    monkeypatch.setattr(cfg, "get_active_model", _boom)
    assert lt._active_model_name() == ""


def test_discover_model_context_length_modelsiz_typeerror_vermez(monkeypatch):
    from app.services import llm_transport as lt
    monkeypatch.setattr(lt, "_active_model_name", lambda: "")
    monkeypatch.setattr(lt, "resolve_active_transport", lambda ai_source=None: "none")
    # TypeError (get_active_model() db'siz) artık oluşmamalı
    lt.discover_model_context_length(model=None, force_refresh=True)


def test_check_ollama_health_modelsiz_typeerror_vermez(monkeypatch):
    """check_ollama_health(model=None) eskiden get_active_model() (db'siz) yüzünden TypeError verirdi."""
    from app.services import ollama_runtime as orr
    import requests

    def _no_net(*a, **k):
        raise requests.ConnectionError("ağ yok")

    monkeypatch.setattr(requests, "get", _no_net)
    out = orr.check_ollama_health(base_url="http://127.0.0.1:9", model=None, timeout=0.2)
    assert out["ok"] is False and out["reachable"] is False
