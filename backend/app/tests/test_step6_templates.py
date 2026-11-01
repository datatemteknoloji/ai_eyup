"""Adım 6b — zaman ifadeli sayım şablonu + evet/hayır VM durumu (saf; DB/saat sahte)."""
from datetime import datetime

import pytest

from app.services.chat_quality import clock
from app.services.chat_quality import count_rules as cr
from app.services.chat_quality import vm_yesno as yn
from app.services.chat_quality.count_scope import HV, ScopeCatalog

FROZEN = datetime(2026, 10, 14, 10, 30)


def _cat() -> ScopeCatalog:
    c = ScopeCatalog()
    c.hypervisors = [HV(1, "office", "VMWARE"), HV(2, "Datatem OLVM", "KVM")]
    c.ocp_clusters = [(2, "oVirt")]
    return c


CAT = _cat()


@pytest.fixture(autouse=True)
def _frozen(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: FROZEN)
    monkeypatch.setattr(cr, "answer", lambda plan, cat, db: f"**Toplam {plan.topic.upper()}: 42**")

    class _S:
        def close(self):
            pass
    import app.core.database as dbm
    monkeypatch.setattr(dbm, "ThreadSessionLocal", lambda: _S())


def ts(q, platform="unified", allowed=None):
    return cr._time_scoped(q, CAT, platform=platform, allowed_modules=allowed)


def resp(q):
    r = ts(q)
    assert r is not None, q
    return cr._time_scoped_response(*r, CAT)


# ── zaman ifadeli sayım (≥ 10) ────────────────────────────────────────────────────

@pytest.mark.parametrize("q,mode", [
    ("2030 Ocak'ta kaç VM vardı?", "future"),
    ("2030 Ocak ayında kaç VM vardı?", "future"),
    ("2031 yılında kaç VM olacak?", "future"),
    ("Geçen ay kaç VM vardı?", "past"),
    ("Geçen yıl kaç host vardı?", "past"),
    ("Geçen hafta kaç Linux sunucu vardı?", "past"),
    ("01.01.2025 tarihinde kaç VM vardı?", "past"),
    ("Dün kaç VM vardı?", "past"),
    ("Bugün kaç VM var?", "current"),
    ("Bu yıl kaç node var?", "current"),
    ("Bu ay kaç kapalı VM var?", "current"),
])
def test_time_scoped_modes(q, mode):
    t = resp(q)
    if mode == "future":
        assert "henüz yaşanmadı" in t and "veri yok" in t
        assert "güncel" in t
    elif mode == "past":
        assert "Geçmişe dönük envanter sayımı" in t and "veri yok" in t
        assert "güncel" in t
    else:
        assert "şu anı kapsıyor" in t
    # sayı yalnız güncel sorgudan gelir (uydurma yok)
    assert "42" in t


@pytest.mark.parametrize("q", [
    "Dün kaç VM kapandı?", "Son 3 günde kaç VM restart oldu?", "Bu ay kaç VM oluşturuldu?", "Dün kaç alarm vardı?",
    "Geçen hafta kaç VM silindi?", "Kaç VM var?", "2030 ve 2031'de kaç VM vardı?", "Dün ve bugün kaç VM vardı?",
])
def test_time_scoped_not_applicable(q):
    assert ts(q) is None, q


def test_time_scoped_respects_rbac():
    assert ts("Geçen ay kaç VM vardı?", "unified", {"openshift"}) is None
    assert ts("Geçen ay kaç node vardı?", "unified", {"openshift"}) is not None


def test_time_scoped_sets_followup_context():
    from app.services.chat_quality import count_followup as cf
    cf.set_context(None)
    resp("Geçen ay kaç VM vardı?")
    ctx = cf.pop_context()
    assert ctx and ctx["items"][0]["topic"] == "vm"


# ── evet/hayır VM durumu ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("q,want", [
    ("Harvester VM'i çalışıyor mu?", ("harvester", "on")),
    ("Harvester VM'i çalışıyor mu", ("harvester", "on")),
    ("dttadvance açık mı?", ("dttadvance", "on")),
    ("Harvester kapalı mı?", ("harvester", "off")),
    ("datatemengine sanal makinesi açık mı?", ("datatemengine", "on")),
    ("web-01 askıda mı?", ("web-01", "suspended")),
    ("Harvester şu an ayakta mı?", ("harvester", "on")),
])
def test_parse_yes_no(q, want):
    assert yn.parse(q) == want


@pytest.mark.parametrize("q", [
    "Hangi VM çalışıyor mu?", "nginx servisi çalışıyor mu?", "Kaç VM çalışıyor?", "Harvester ne zaman kapandı?",
    "VM'ler çalışıyor mu?", "Harvester ve dttadvance açık mı?", "Disk dolu mu?", "Harvester'ın CPU'su yüksek mi?",
    "Merhaba", "Tüm VM'ler açık mı?",
])
def test_parse_not_yes_no(q):
    assert yn.parse(q) is None, q


def _rec(name, hv, power, host="h1"):
    return {"name": name, "hv": hv, "power": power, "host": host, "cluster": "c1", "ts": None}


HVN = {1: ("office", "VMWARE"), 2: ("Datatem OLVM", "KVM")}


def test_render_single_no():
    t = yn.render([_rec("Harvester", 1, "POWERED_OFF")], "on", HVN)
    assert t.startswith("**Hayır** — Harvester kapalı (POWERED_OFF)")
    assert "office (VMware vCenter)" in t


def test_render_single_yes_and_inverse():
    assert yn.render([_rec("x", 1, "POWERED_ON")], "on", HVN).startswith("**Evet**")
    assert yn.render([_rec("x", 1, "POWERED_OFF")], "off", HVN).startswith("**Evet**")
    assert yn.render([_rec("x", 1, "Running")], "off", HVN).startswith("**Hayır**")


def test_render_unknown_state():
    assert yn.render([_rec("x", 1, "Migrating")], "on", HVN).startswith("**Belirsiz**")


def test_render_multi():
    t = yn.render([_rec("d", 1, "POWERED_OFF"), _rec("d", 2, "POWERED_ON")], "on", HVN)
    assert t.startswith("**Kayda göre değişiyor**") and "2 kayıt" in t
    assert "| office |" in t and "| Datatem OLVM |" in t


def test_yesno_rbac(monkeypatch):
    monkeypatch.setattr(cr, "get_catalog", lambda: CAT)
    monkeypatch.setattr(yn, "fetch", lambda db, n: [_rec("Harvester", 1, "POWERED_OFF")])
    assert yn.respond("Harvester çalışıyor mu?", platform="virt") is not None
    assert yn.respond("Harvester çalışıyor mu?", platform="unified", allowed_modules={"linux"}) is None
    assert yn.respond("Harvester çalışıyor mu?", platform="openshift") is None
    assert yn.respond("Harvester çalışıyor mu?", platform="linux") is None
