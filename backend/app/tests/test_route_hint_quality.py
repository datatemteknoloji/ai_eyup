"""Adım 3 / Parça 2C: routing ipucu kalitesi — şablonda hazır örnek yok, birleştirme güvenliği, görünürlük."""
import itertools
import re
import uuid
from types import SimpleNamespace

import pytest

from app.services import llm_activity, llm_gateway
from app.services import route_llm_hint as rh
from app.services.module_orchestrator import ALL_MODULES, ModulePlan, plan_modules


@pytest.fixture(autouse=True)
def _izole(monkeypatch):
    monkeypatch.setattr(llm_activity, "_redis", lambda: None)
    monkeypatch.setattr(llm_activity, "_is_test_rec", lambda x: False)
    with llm_activity._lock:
        llm_activity._recent.clear()
        llm_activity._hint_notes.clear()
    rh.clear_cache()
    yield
    rh.clear_cache()
    with llm_activity._lock:
        llm_activity._recent.clear()
        llm_activity._hint_notes.clear()


def _plan(modules=(), reason="no_module_signal", conf=0.70):
    return ModulePlan(mode="knowledge", modules=tuple(modules), domains=frozenset({"infra"}),
                      confidence=conf, reason=reason)


# ── şablon: hazır modül listesi örneği YOK ─────────────────────────────────

_MODS = "|".join(ALL_MODULES + ("vcenter",))


def test_sablonda_hazir_modul_listesi_ornegi_yok():
    """Eski şablondaki {"modules":["virt","linux"]} örneği model tarafından kopyalanıyordu."""
    system, user = rh.build_hint_prompt("Winserver01 çalışıyor mu?", _plan())
    text = system + "\n" + user + "\n" + rh._SYSTEM + "\n" + rh._USER_TMPL
    # JSON modules anahtarından sonra gerçek modül adı içeren dizi olmamalı
    assert not re.search(r'"modules"\s*:\s*\[\s*"(?:%s)"' % _MODS, text, re.I), "hazır modül örneği var"
    # köşeli parantez içinde iki gerçek modül adı yan yana (örn. ["virt","linux"]) olmamalı
    assert not re.search(r'\[\s*"(?:%s)"\s*,\s*"(?:%s)"' % (_MODS, _MODS), text, re.I)
    assert "<modül>" in user                      # şema yer tutucuyla verilir


def test_istem_soru_ve_keyword_plani_icerir():
    system, user = rh.build_hint_prompt("IIS durdu mu?", _plan(("linux",), "single:linux", 0.6))
    assert "IIS durdu mu?" in user
    assert "modules=['linux']" in user and "single:linux" in user
    # Windows/Linux ayrımı ve boş liste kuralı sistem isteminde
    assert "windows" in system.lower() and "boş liste" in system
    assert "birden fazla yaz" not in system         # bulanıklaştıran eski kural kalktı


# ── birleştirme güvenliği: ipucu yalnız EKLER / modülsüz-düşük güvende doldurur ───────

def test_yuksek_guvenli_plan_icin_ipucu_sorulmaz(monkeypatch):
    monkeypatch.setattr("app.services.runtime_settings.get_bool", lambda *_a, **_k: True)
    monkeypatch.setattr("app.core.config.remote_llm_enabled", lambda: False)
    called = []
    monkeypatch.setattr(rh, "_call_hint_llm", lambda *a, **k: called.append(1) or ("windows",))
    for q in ("vcenter datastore kapasitesi", "IIS servisi neden durdu event log", "openshift pod crashloop"):
        plan = plan_modules(q)
        assert plan.confidence > rh.HINT_CONF_MAX, q
        assert rh.apply_route_llm_hint(q, plan) is plan
    assert called == []


_REASONS = ["single:virt", "single:linux", "multi:virt+linux", "auto_explore:virt+linux",
            "esnaf_live_resource:virt+linux", "no_module_signal", "planning_scope:mtv"]


@pytest.mark.parametrize("reason", _REASONS)
def test_ipucu_mevcut_modulleri_silmez(reason):
    """Tüm modül kombinasyonlarında birleşim ⊇ keyword modülleri (auto_multi_tie alt küme seçimi hariç)."""
    mods = [m for m in ALL_MODULES if m != "automic"]
    for n in (0, 1, 2):
        for orig in itertools.combinations(mods, n):
            for k in (1, 2):
                for hinted in itertools.combinations(mods, k):
                    plan = _plan(orig, reason, 0.6)
                    out = rh.merge_route_hint(plan, hinted, "soru")
                    assert set(orig) <= set(out.modules), (reason, orig, hinted, out.modules)


def test_multi_tie_alt_kume_secimi_dusuk_guvende_kalir():
    plan = _plan(("virt", "linux"), "auto_multi_tie:virt+linux", 0.6)
    assert rh.merge_route_hint(plan, ("linux",), "x").modules == ("linux",)
    # kümeyi aşan ipucu ekleme yapar, daraltmaz
    out = rh.merge_route_hint(plan, ("windows",), "x")
    assert set(out.modules) == {"virt", "linux", "windows"}


def test_auto_explore_ve_esnaf_daralmaz():
    for reason in ("auto_explore:virt+linux", "esnaf_live_resource:virt+linux"):
        out = rh.merge_route_hint(_plan(("virt", "linux"), reason, 0.6), ("linux",), "x")
        assert out.modules == ("virt", "linux")


def test_modulsuz_plan_ipucuyla_dolar_ve_bos_ipucu_plani_korur():
    out = rh.merge_route_hint(_plan(), ("windows",), "Winserver01 çalışıyor mu?")
    assert out.modules == ("windows",) and out.reason.endswith("+llm")
    plan = _plan()
    assert rh.merge_route_hint(plan, (), "x") is plan          # boş ipucu = plan aynen


def test_ipucu_guven_tavani_076():
    out = rh.merge_route_hint(_plan(), ("windows",), "x")
    assert out.confidence <= 0.76


# ── görünürlük: ham çıktı ve trace_id ──────────────────────────────────────

def _fake_generate(raw, **extra):
    def _g(**kw):
        return {"response": raw, "done": True, **extra}
    return _g


def _ask(monkeypatch, tid, raw, **extra):
    monkeypatch.setattr("app.services.runtime_settings.get_bool", lambda *_a, **_k: True)
    monkeypatch.setattr("app.core.config.remote_llm_enabled", lambda: False)
    monkeypatch.setattr(llm_gateway, "generate_sync", _fake_generate(raw, **extra))
    with llm_activity.trace_scope(tid):
        return rh.apply_route_llm_hint("Winserver01 çalışıyor mu?", _plan())


def test_ham_cikti_trace_ozetine_yazilir(monkeypatch):
    tid = str(uuid.uuid4())
    out = _ask(monkeypatch, tid, '{"modules":["windows"],"reason":"Windows sunucusu"}')
    assert out.modules == ("windows",)
    s = llm_activity.summary_for_trace(tid)
    assert s and s["route_hint"], s
    n = s["route_hint"][0]
    assert n["source"] == "llm"
    assert n["raw"].startswith('{"modules":["windows"]')
    assert n["hinted"] == ["windows"] and n["merged_modules"] == ["windows"]
    assert n["kw_reason"] == "no_module_signal" and n["plan_changed"] is True


def test_ham_cikti_300_karakterle_sinirli_ve_maskeli(monkeypatch):
    tid = str(uuid.uuid4())
    raw = '{"modules":["linux"],"reason":"' + ("x" * 900) + '"} password=Sup3rSecret!'
    _ask(monkeypatch, tid, raw)
    n = llm_activity.summary_for_trace(tid)["route_hint"][0]
    assert len(n["raw"]) <= 300
    assert "Sup3rSecret" not in n["raw"]


def test_bos_ve_hata_kaynaklari_ayirt_edilir(monkeypatch):
    t1, t2 = str(uuid.uuid4()), str(uuid.uuid4())
    _ask(monkeypatch, t1, '{"modules":[],"reason":"genel"}')
    rh.clear_cache()
    monkeypatch.setattr(llm_gateway, "generate_sync", _fake_generate("", error="ReadTimeout: x"))
    with llm_activity.trace_scope(t2):
        rh.apply_route_llm_hint("m2", _plan())
    assert llm_activity.summary_for_trace(t1)["route_hint"][0]["source"] == "empty"
    n2 = llm_activity.summary_for_trace(t2)["route_hint"][0]
    assert n2["source"] == "error" and "ReadTimeout" in n2["raw"]


def test_onbellek_isabeti_not_edilir_ama_ilk_kayit_korunur(monkeypatch):
    tid = str(uuid.uuid4())
    _ask(monkeypatch, tid, '{"modules":["windows"],"reason":"a"}')
    with llm_activity.trace_scope(tid):
        rh.apply_route_llm_hint("Winserver01 çalışıyor mu?", _plan())      # aynı tur: önbellek
    srcs = [x["source"] for x in llm_activity.summary_for_trace(tid)["route_hint"]]
    assert srcs == ["llm", "cache"]


def test_trace_yoksa_not_tutulmaz(monkeypatch):
    monkeypatch.setattr("app.services.runtime_settings.get_bool", lambda *_a, **_k: True)
    monkeypatch.setattr("app.core.config.remote_llm_enabled", lambda: False)
    monkeypatch.setattr(llm_gateway, "generate_sync", _fake_generate('{"modules":["linux"]}'))
    rh.apply_route_llm_hint("sunucu neden ağır", _plan())
    assert llm_activity._hint_notes == {}


def test_activity_kaydina_trace_id_yazilir_trace_scope_ile():
    tid = str(uuid.uuid4())
    with llm_activity.trace_scope(tid):
        with llm_activity.track("generate_sync", "m", label="route_hint"):
            pass
        llm_activity.note_skipped("generate_sync", "slot_busy", label="route_hint")
    recs = [r for r in llm_activity.recent(limit=10) if r.get("tclass") == "route_hint"]
    assert len(recs) == 2 and all(r.get("trace_id") == tid for r in recs)
    # kapsam dışında trace_id yok
    with llm_activity.track("generate_sync", "m", label="route_hint"):
        pass
    assert llm_activity.recent(limit=1)[0].get("trace_id") is None


def test_create_turn_plan_sources_tur_kimligiyle_calisir(monkeypatch):
    """create_turn: plan_sources (ipucu LLM'i) tur izi bağlanmadan önce çalışır; kimlik trace_scope'tan gelmeli."""
    from app.services.chat_orchestrator import service as svc

    seen = {}

    def _fake_plan(message, **kw):
        seen["tid"] = llm_activity._current_trace_id()
        return SimpleNamespace(to_dict=lambda: {"sources": ["db"]})

    monkeypatch.setattr(svc, "plan_sources", _fake_plan)
    monkeypatch.setattr(svc.events, "publish_event", lambda *a, **k: None)
    monkeypatch.setattr(svc.events, "enqueue_job", lambda *a, **k: None)
    monkeypatch.setattr(svc.ai_gate, "queue_position", lambda: 0)
    db = SimpleNamespace(add=lambda x: None, commit=lambda: None, refresh=lambda x: None)
    turn = svc.create_turn(db, platform="unified", message="Winserver01 çalışıyor mu?", payload={})
    assert seen["tid"] == turn.id
    assert llm_activity._current_trace_id() is None            # kapsam dışına sızmaz
