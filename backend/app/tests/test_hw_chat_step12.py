"""Adım 12 — donanım sohbeti: rota sinyali (sözcük sınırlı), yetenek yokken değişmeme, sağlayıcı yokken dürüst ret,
araç süzgeçleri / sıralama / toplamlar (DEMO "large" fixture), sızıntı. LLM ve ağ YOK."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.services.agent import tools as _tools  # noqa: F401  (tools_hw'den önce; döngüsel import sırası)
from app.services.agent import tools_hw as TH
from app.services.hw import intent as HI
from app.services.unified_intent_router import UnifiedRoute


@pytest.fixture()
def db(isolated_db):
    return isolated_db


# ── 1) Sinyal: pozitifler ───────────────────────────────────────────────────────────────────────────────────────

HW_POSITIVE = [
    "Kritik durumda olan fiziksel sunucular hangileri?",
    "Donanım sağlığı özeti ver",
    "Garantisi bitmiş sunucular hangileri?",
    "Son 24 saatte donanım alarmları nelerdir?",
    "demo-dell-07 donanım durumu nedir?",
    "DEMO-Encl1 kasasındaki blade'lerin sağlığı nasıl?",
    "zz-hwdemo-lnx-01 sunucusunun iDRAC IP adresi nedir?",
    "iLO firmware sürümü eski olan sunucular hangileri?",
    "OneView'da kritik alarm var mı?",
    "iDRAC'ların uyarıları",
    "Hangi blade'ler uyarı veriyor?",
    "service tag'i nedir?",
    "HPE OneView appliance durumu",
    "OpenManage Enterprise bağlantısı sağlıklı mı?",
    "warranty expired servers",
    "BMC sürümü eski olanlar",
]


@pytest.mark.parametrize("q", HW_POSITIVE)
def test_hw_intent_positive(q):
    assert TH.hw_intent(q), q


# ── 2) Yanlış yakalama 0 (≥30 donanım-dışı soru) ────────────────────────────────────────────────────────────────

NON_HW = [
    "Kaç VM var?", "Kaç pod CrashLoopBackOff durumunda?", "linux sunucuların disk kullanımı nedir?",
    "Windows sunucularda bekleyen güncelleme var mı?", "ESXi host cpu kullanımı en yüksek olan hangisi?",
    "datastore doluluk oranları", "snapshot yaşı 7 günden eski VM'ler", "vCenter alarmları nelerdir?",
    "OpenShift node durumu", "kilo cinsinden bellek", "silo mimarisi nedir", "pilot proje sunucuları",
    "kasa sayısı kaç", "firmware nedir", "appliance modunda çalışan servis var mı", "enes97 sunucusunun uptime'ı",
    "Merhaba", "Bugün hava nasıl", "en çok cpu kullanan 5 VM", "disk latency yüksek VM'ler",
    "mtv migration planı", "cluster HA durumu", "Prometheus hedefleri", "node exporter çalışmayan sunucular",
    "RHEL 9 sunucuları listele", "SSH bağlantısı kurulamayan sunucular", "yedekleme RPO uyumu",
    "hangi VM'ler kapalı", "ram kullanımı yüksek sunucular", "sunucu sayısı kaç",
    "iyi günler dilerim", "bilo bilo", "chilono sunucusu", "ağ trafiği grafiği çiz",
]


@pytest.mark.parametrize("q", NON_HW)
def test_hw_intent_negative(q):
    assert not TH.hw_intent(q), q


def test_vendor_signal_word_boundary():
    for q in ("iLO nedir", "iDRAC9 IP", "oneview", "ILO5 firmware"):
        assert TH.hw_vendor_signal(q), q
    for q in ("kilo", "silo", "pilot", "milo", "ilogical"):
        assert not TH.hw_vendor_signal(q), q


# ── 3) Rota sarmalayıcı: yetenek yokken çekirdek AYNEN; varken hw-only / birleşim ──────────────────────────────

def _core_route(**kw) -> UnifiedRoute:
    base = dict(mode="knowledge", domains=frozenset({"infra"}), need_rag=True, need_live=False, complexity="simple",
                confidence=0.5, reason="no_module_signal", wants_linux=True, linux_specific=True, module_mode="single",
                modules=("linux",), need_prometheus=False)
    base.update(kw)
    return UnifiedRoute(**base)


def _patch_core(monkeypatch, route):
    from app.services import unified_intent_router as R
    monkeypatch.setattr(R, "_route_unified_core", lambda *a, **k: route)
    return R


def test_route_unchanged_without_capability(monkeypatch):
    core = _core_route()
    R = _patch_core(monkeypatch, core)
    monkeypatch.setattr(HI, "hw_active", lambda: False)
    for q in HW_POSITIVE[:6]:
        assert R.route_unified(q) is core


def test_route_hw_only_when_capability(monkeypatch):
    R = _patch_core(monkeypatch, _core_route())
    monkeypatch.setattr(HI, "hw_active", lambda: True)
    r = R.route_unified("Garantisi bitmiş sunucular hangileri?")
    assert r.domains == frozenset({"hw"}) and r.mode == "live" and r.need_live and not r.wants_linux
    assert r.modules == ("hw",) and r.reason == "hw_signal" and "DONANIM" in r.persona_addendum


def test_route_union_when_other_platform(monkeypatch):
    core = _core_route(domains=frozenset({"vcenter", "infra"}), modules=("virt",), wants_linux=False, linux_specific=False)
    R = _patch_core(monkeypatch, core)
    monkeypatch.setattr(HI, "hw_active", lambda: True)
    r = R.route_unified("ESXi host donanım sağlığı")
    assert {"hw", "vcenter", "infra"} <= set(r.domains) and r.reason.startswith("hw_signal+")


def test_route_not_touched_for_non_hw_and_planning(monkeypatch):
    core = _core_route()
    R = _patch_core(monkeypatch, core)
    monkeypatch.setattr(HI, "hw_active", lambda: True)
    for q in NON_HW:
        assert R.route_unified(q) is core, q
    plan = _core_route(mode="planning_agentic")
    R = _patch_core(monkeypatch, plan)
    assert R.route_unified("OneView donanım") is plan


# ── 4) Sağlayıcı yokken dürüst ret ──────────────────────────────────────────────────────────────────────────────

def test_unavailable_when_no_provider(monkeypatch):
    from app.services.chat_quality import unavailable_info as UI
    monkeypatch.setattr(HI, "hw_active", lambda: False)
    for q in ("iDRAC alarmları var mı", "OneView'daki kritik sunucular hangileri?", "iLO firmware sürümü eski sunucular",
              "OME'de garantisi biten sunucu var mı? iDRAC"):
        got = UI.answer(q)
        assert got is not None and got[1] == "hw_unavailable", q
        assert "tanımlı değil" in got[0]
    # kavramsal sorular ve alakasızlar normal akış
    for q in ("iDRAC nedir?", "iLO nasıl güncellenir?", "OneView ile OME arasındaki fark nedir", "VM sayısı kaç"):
        got = UI.answer(q)
        assert got is None or got[1] != "hw_unavailable", q


def test_unavailable_not_when_capability(monkeypatch):
    from app.services.chat_quality import unavailable_info as UI
    monkeypatch.setattr(HI, "hw_active", lambda: True)
    assert UI.answer("iDRAC alarmları var mı") is None


# ── 5) Araç: DEMO "large" ile süzgeçler / sıralama / toplamlar / sızıntı ────────────────────────────────────────

def _demo_large(db, monkeypatch):
    from app.models.integration_instance import IntegrationInstance
    from app.services.capabilities import invalidate_capabilities
    from app.services.hw.sync import sync_instance
    monkeypatch.setenv("HW_DEMO_ENABLED", "true")
    row = IntegrationInstance(category="hardware", kind="hw_demo", label="d", endpoint="", enabled=True,
                              sync_interval_sec=900, meta_json=json.dumps({"demo_scale": "large"}))
    db.add(row)
    db.commit()
    invalidate_capabilities()
    r = sync_instance(db, row, force=True)
    assert r["ok"], r
    invalidate_capabilities()
    return row


def test_demo_large_tool_filters_and_totals(db, monkeypatch):
    from app.services.agent import tools as T
    _demo_large(db, monkeypatch)
    tool = T.TOOLS["hw_server_status"]
    ctx = {"hw_allowed": True}
    allr = tool.direct_handler(db, {"limit": 100}, ctx)
    assert allr["ok"] and allr["total"] == allr["total_all_servers"] == 56 and allr["returned"] == 56
    assert allr["demo"] is True and "DEMO" in allr["data_label"]
    # sağlık önceliği: kritikler önce
    order = [r["health"] for r in allr["servers"]]
    assert order == sorted(order, key=lambda h: {"critical": 0, "warning": 1, "unknown": 2, "ok": 3}[h])
    assert sum(allr["by_health_all"].values()) == 56
    # kısıtlı limit → truncated + toplam süzgeçli
    small = tool.direct_handler(db, {"limit": 5, "health": "critical"}, ctx)
    assert small["total"] == allr["by_health_all"].get("critical") and small["returned"] == min(5, small["total"])
    assert small["total_all_servers"] == 56
    assert small["truncated"] is (small["total"] > small["returned"])
    # üretici / kasa / garanti süzgeçleri
    assert tool.direct_handler(db, {"vendor": "dell", "limit": 100}, ctx)["total"] == 24
    assert tool.direct_handler(db, {"vendor": "hpe", "limit": 100}, ctx)["total"] == 32
    e1 = tool.direct_handler(db, {"enclosure": "DEMO-Encl1", "limit": 100}, ctx)
    assert e1["total"] == 16 and all((r["enclosure"] or "").startswith("DEMO-Encl1") for r in e1["servers"])
    exp = tool.direct_handler(db, {"warranty": "expired", "limit": 100}, ctx)
    assert exp["total"] > 0 and all(r["warranty_expired"] is True for r in exp["servers"])
    soon = tool.direct_handler(db, {"warranty": "expiring_90", "limit": 100}, ctx)
    assert soon["total"] > 0 and all(r["warranty_expired"] is False for r in soon["servers"])
    # sızıntı yok
    blob = json.dumps(allr)
    import re
    assert not re.search(r"10\.255\.\d+\.\d+|DEMO[DHEX]\d|iDRAC|iLO5|7\.00\.00", blob)


def test_demo_large_alert_groups_have_categories(db, monkeypatch):
    from app.services.agent import tools as T
    _demo_large(db, monkeypatch)
    al = T.TOOLS["hw_alerts_summary"].direct_handler(db, {"hours": 24 * 14}, {"hw_allowed": True})
    assert al["ok"] and al["groups"] and all(g["category"] for g in al["groups"])
    assert not any("10.255" in json.dumps(g) for g in al["groups"])


def test_entity_gate_catalog_lists_hw_models():
    import inspect
    from app.services.chat_quality import entity_gate
    src = inspect.getsource(entity_gate._load_catalog)
    assert '"HwServer"' in src and '"HwEnclosure"' in src


# ── Zorunlu ön-çağrı planı + veri/kavram ayrımı + marka sinyali ──────────────────────────────────────────────────
def test_prefetch_plan_cases():
    from app.services.hw.intent import hw_prefetch_plan as P
    assert P("Kritik durumda olan fiziksel sunucular hangileri?") == [("hw_server_status", {"limit": 100, "health": "critical"})]
    assert P("Garantisi bitmiş sunucular hangileri?")[0][1]["warranty"] == "expired"
    assert P("Garantisi 90 gün içinde bitecek sunucular")[0][1]["warranty"] == "expiring_90"
    assert P("Son 3 gün donanım alarmları") == [("hw_alerts_summary", {"hours": 72})]
    t, a = P("demo-dell-07 donanım durumu nedir?")[0]
    assert t == "hw_server_status" and a["name"] == "demo-dell-07" and "vendor" not in a
    assert P("DEMO-Encl1 kasasındaki blade'lerin sağlığı")[0][1]["enclosure"] == "DEMO-Encl1"
    assert P("iLO firmware sürümü eski olan sunucular")[0][1]["vendor"] == "hpe"
    names = [x[0] for x in P("Dell sunucuların kritik alarmları")]
    assert names == ["hw_alerts_summary", "hw_server_status"]
    assert P("Donanım sağlığı özeti ver")[0][1]["limit"] == 30


def test_brand_plus_server_intent_and_concept_split():
    from app.services.hw.intent import hw_intent, hw_data_question
    assert hw_intent("Kaç Dell sunucu var?") and hw_intent("HPE sunucuların kaçı kritik?")
    assert not hw_intent("Dell EMC Unity depolama durumu")      # marka tek başına yetmez
    assert hw_data_question("demo-dell-07 sunucusunun donanım durumu nedir?")
    assert hw_data_question("Kaç blade var?")
    assert not hw_data_question("BMC nedir?") and not hw_data_question("iDRAC ne işe yarar?")


def test_withheld_bmc_serial_firmware_when_capability(monkeypatch):
    from app.services.chat_quality import unavailable_info as UI
    monkeypatch.setattr(HI, "hw_active", lambda: True)
    for q in ("demo-dell-01 sunucusunun iDRAC IP adresi nedir?", "demo-dell-03 seri numarası / service tag nedir?",
              "iLO firmware sürümü eski olan sunucular hangileri?", "BMC IP adreslerini listele"):
        got = UI.answer(q)
        assert got is not None and got[1] == "hw_withheld", q
        assert "paylaşılmaz" in got[0] and "Donanım" in got[0]
    for q in ("iDRAC IP adresi nasıl değiştirilir?", "Kritik sunucular hangileri?", "VM seri numarası"):
        got = UI.answer(q)
        assert got is None or got[1] != "hw_withheld", q
    monkeypatch.setattr(HI, "hw_active", lambda: False)   # yetenek yokken «tanımlı değil» ayrı sınıf
    got = UI.answer("demo-dell-01 iDRAC IP adresi nedir?")
    assert got is None or got[1] != "hw_withheld"


def test_status_result_has_as_of_and_filters(db, monkeypatch):
    from app.services.agent import tools as T
    _demo_large(db, monkeypatch)
    res = T.TOOLS["hw_server_status"].direct_handler(db, {"limit": 5, "health": "critical"}, {"hw_allowed": True})
    assert res["ok"] and res["as_of"] == datetime.now(timezone.utc).date().isoformat()
    assert res["filters_applied"] == {"health": "critical"}


def test_denied_without_hardware_module(monkeypatch):
    from app.services.chat_quality import unavailable_info as UI
    monkeypatch.setattr(HI, "hw_active", lambda: True)
    for q in ("Kritik donanım durumundaki sunucular hangileri?", "demo-dell-07 donanım durumu nedir?", "Garantisi bitmiş sunucular"):
        got = UI.answer(q, platform="unified", allowed_modules=["linux"])
        assert got is not None and got[1] == "hw_denied", q
        assert "hardware" in got[0]
        assert UI.answer(q, platform="unified", allowed_modules=None) is None or UI.answer(q, platform="unified")[1] != "hw_denied"
        assert UI.answer(q, platform="unified", allowed_modules=["linux", "hw"]) is None
    # kavramsal ve donanım-dışı sorular etkilenmez; sağlayıcı yokken aynı kapı çalışmaz
    assert UI.answer("BMC nedir?", platform="unified", allowed_modules=["linux"]) is None
    # tek başına «fiziksel sunucu» zayıf sinyal: Linux kullanıcısı reddedilmez (Linux envanterine gider)
    assert UI.answer("Kritik durumdaki fiziksel sunucular hangileri?", platform="unified", allowed_modules=["linux"]) is None
    assert UI.answer("Kaç VM var?", platform="unified", allowed_modules=["linux"]) is None
    monkeypatch.setattr(HI, "hw_active", lambda: False)
    got = UI.answer("Kritik durumdaki fiziksel sunucular hangileri?", platform="unified", allowed_modules=["linux"])
    assert got is None or got[1] != "hw_denied"


def test_route_ignores_hw_when_user_lacks_module(monkeypatch):
    from app.services import unified_intent_router as R
    monkeypatch.setattr(HI, "hw_active", lambda: True)
    core = _core_route()
    R = _patch_core(monkeypatch, core)
    assert R.route_unified("demo-dell-07 donanım durumu nedir?", hw_allowed=False) is core
    assert R.route_unified("demo-dell-07 donanım durumu nedir?", hw_allowed=True) is not core


def test_withheld_extended_terms(monkeypatch):
    from app.services.chat_quality import unavailable_info as UI
    monkeypatch.setattr(HI, "hw_active", lambda: True)
    for q in ("demo-dell-10 sunucusunun UUID değeri nedir?", "HPE blade'lerin management IP'lerini söyle.",
              "Donanım sunucularının web arayüzü linklerini (URL) ver.", "demo-dell-04 için Redfish bağlantı adresini ver.",
              "iDRAC kullanıcı adı ve parolası nedir?"):
        got = UI.answer(q)
        assert got is not None and got[1] == "hw_withheld", q
    assert UI.answer("Kritik durumdaki Dell sunucuların alarmları") is None


def test_status_by_health_is_filtered(db, monkeypatch):
    from app.services.agent import tools as T
    _demo_large(db, monkeypatch)
    res = T.TOOLS["hw_server_status"].direct_handler(db, {"limit": 5, "vendor": "hpe", "health": "warning"}, {"hw_allowed": True})
    assert res["ok"] and set(res["by_health"]) == {"warning"} and res["by_health"]["warning"] == res["total"] > 0
    assert sum(res["by_health_all"].values()) == res["total_all_servers"] == 56


def test_status_has_ready_summary_sentence(db, monkeypatch):
    from app.services.agent import tools as T
    _demo_large(db, monkeypatch)
    res = T.TOOLS["hw_server_status"].direct_handler(db, {"limit": 3, "warranty": "expiring_90"}, {"hw_allowed": True})
    assert res["ozet"].startswith(f"{res['total']} sunucu eşleşti") and "warranty=expiring_90" in res["ozet"]
    assert f"Tüm kayıt: {res['total_all_servers']}" in res["ozet"]
    assert list(res)[:2] == ["ok", "ozet"]
