"""Donanım → SystemEvent → Incident, iki seviyeli yetki, etki alanı, elle eşleştirme, garanti raporu.

Ağa ÇIKMAZ; DB testleri İZOLE geçici DB'de çalışır (canlı veriye dokunmaz).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.models.infrastructure_report  # noqa: F401  (business_service_map tablosu metadata'ya kayıtlansın)
from app.models.event import Incident, SystemEvent
from app.models.hw import HwAlert, HwHostLink, HwServer
from app.models.server import Server
from app.services.hw import events as E
from app.services.hw.dell_ome import DellOmeProvider
from app.tests import hw_fakes as F


@pytest.fixture()
def db(isolated_db):
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()
    yield isolated_db
    invalidate_capabilities()


def _caps(db=None, row=None):
    from app.services.capabilities import invalidate_capabilities
    if row is not None:
        row.last_status = "ok"          # hiç başarılı senkron yoksa capability açılmaz
        db.commit()
    invalidate_capabilities()


def _real_sync(db, **kw):
    from app.services.hw import sync
    row = F.make_row(db)
    http, _ = F.http_for(F.ome_router(**kw), "https://ome.example", "ome")
    res = sync.sync_instance(db, row, force=True, provider=DellOmeProvider(row, http=http))
    assert res["ok"] is True, res
    return row


def _linux_srv(db, name="lin-db-02"):
    s = Server(name=name, hostname=name, ip_address="10.0.0.2", hw_serial="XYZ9876", server_type="PHYSICAL", os_type="linux")
    db.add(s)
    db.commit()
    return s


def _hw_events(db):
    return db.query(SystemEvent).filter(SystemEvent.event_type.in_(E.HW_EVENT_TYPES)).order_by(SystemEvent.id).all()


# ═══ 1) Olay + incident ══════════════════════════════════════════════════════════════════════════════════════════

def test_sync_creates_events_and_one_incident_per_server(db):
    srv = _linux_srv(db)
    _real_sync(db)
    evs = _hw_events(db)
    assert {e.event_type for e in evs} == {E.ET_HEALTH, E.ET_ALERT}
    assert all(e.source == E.SOURCE_REAL and e.severity == "critical" and e.server_id == srv.id for e in evs)
    assert all((e.raw_data or {}).get("platform") == "linux" for e in evs)       # Linux olay listesine düşer
    inc = db.query(Incident).all()
    assert len(inc) == 1 and set(inc[0].related_events) == {e.id for e in evs}   # sağlık + alarm TEK incident
    assert inc[0].severity == "critical" and srv.id in inc[0].affected_servers


def test_events_do_not_leak_bmc_ip_serial_or_url(db):
    _linux_srv(db)
    _real_sync(db)
    blob = " ".join(f"{e.title} {e.description} {e.raw_data}" for e in _hw_events(db))
    inc = " ".join(f"{i.title} {i.description}" for i in db.query(Incident).all())
    for secret in ("10.20.30.42", "XYZ9876", "xyz9876", "https://", "bmc_ip", "web_url"):
        assert secret not in blob and secret not in inc


def test_sync_is_idempotent_and_dedupes(db):
    from app.services.hw import sync
    _linux_srv(db)
    row = _real_sync(db)
    n_ev, n_inc = len(_hw_events(db)), db.query(Incident).count()
    http, _ = F.http_for(F.ome_router(), "https://ome.example", "ome")
    for _i in range(3):
        sync.sync_instance(db, row, force=True, provider=DellOmeProvider(row, http=http))
    assert len(_hw_events(db)) == n_ev and db.query(Incident).count() == n_inc


def test_condition_clears_resolves_event_and_reopens(db):
    srv = _linux_srv(db)
    _real_sync(db)
    hw = db.query(HwServer).filter(HwServer.serial == "XYZ9876").one()
    hw.health = "ok"
    for a in db.query(HwAlert).all():
        a.state = "cleared"
    db.commit()
    st = E.sync_hw_events(db)
    assert st["resolved"] == 2 and all(e.resolved for e in _hw_events(db))
    hw.health = "critical"
    db.commit()
    st = E.sync_hw_events(db)
    assert st["reopened"] == 1
    ev = [e for e in _hw_events(db) if e.event_type == E.ET_HEALTH][0]
    assert ev.resolved is False and ev.occurrence_count == 2
    assert db.query(Incident).count() == 1                                      # açık incident'a bağlandı
    assert srv.id in db.query(Incident).one().affected_servers


def test_recurring_warning_creates_warning_event_without_incident(db):
    row = F.make_row(db)
    hw = HwServer(instance_id=row.id, provider_ref="r1", vendor="dell", name="rack-9", serial="WARN111", health="warning")
    db.add(hw)
    db.flush()
    now = datetime.now(timezone.utc)
    for i in range(3):
        db.add(HwAlert(instance_id=row.id, provider_ref=f"a{i}", server_ref="r1", severity="warning", state="active",
                       message="Fan speed degraded", fingerprint="fp-fan", occurred_at=now - timedelta(hours=i)))
    db.commit()
    st = E.sync_hw_events(db)
    ev = _hw_events(db)
    assert st["created"] == 1 and ev[0].event_type == E.ET_RECUR and ev[0].severity == "warning"
    assert ev[0].server_id is None and "platform" not in (ev[0].raw_data or {})   # eşleşmemiş: platformsuz
    assert db.query(Incident).count() == 0                                     # warning incident açmaz
    # iki uyarı eşiğin altı → olay yok
    db.query(HwAlert).filter(HwAlert.provider_ref == "a0").delete()
    db.commit()
    assert E.sync_hw_events(db)["resolved"] == 1


def test_two_servers_with_similar_names_get_separate_incidents(db):
    row = F.make_row(db)
    for i in (1, 2):
        db.add(HwServer(instance_id=row.id, provider_ref=f"r{i}", vendor="hpe", name=f"srv0{i}", health="critical"))
    db.commit()
    E.sync_hw_events(db)
    assert db.query(Incident).count() == 2                                      # srv01/srv02 sayı normalizasyonuyla birleşmez


def test_no_provider_or_demo_never_emits_events(db, monkeypatch):
    assert E.sync_hw_events(db)["created"] == 0                                 # sağlayıcı yok
    monkeypatch.setenv("HW_DEMO_ENABLED", "true")
    row = F.make_row(db, kind="hw_demo", endpoint="demo")
    db.add(HwServer(instance_id=row.id, provider_ref="d1", vendor="dell", name="demo-1", health="critical"))
    db.commit()
    assert E.sync_hw_events(db)["created"] == 0 and db.query(SystemEvent).count() == 0   # DEMO: bulgu/olay üretmez


def test_demo_events_are_opt_in_labelled_and_fully_removable(db, monkeypatch):
    monkeypatch.setenv("HW_DEMO_ENABLED", "true")
    row = F.make_row(db, kind="hw_demo", endpoint="demo")
    db.add(HwServer(instance_id=row.id, provider_ref="d1", vendor="dell", name="demo-1", health="critical"))
    db.commit()
    st = E.sync_hw_events(db, allow_demo=True)
    ev = _hw_events(db)
    assert st["created"] == 1 and ev[0].source == E.SOURCE_DEMO and ev[0].title.startswith("[DEMO]")
    assert ev[0].raw_data["demo"] is True and db.query(Incident).count() == 1
    assert E.delete_demo_events(db) == 1
    assert db.query(SystemEvent).count() == 0 and db.query(Incident).count() == 0


def test_cleanup_keeps_real_incidents(db, monkeypatch):
    monkeypatch.setenv("HW_DEMO_ENABLED", "true")
    db.add(Incident(title="gerçek", severity="critical", status="open", source="auto_cpu_high", related_events=[999999]))
    db.commit()
    E.delete_demo_events(db)
    assert db.query(Incident).count() == 1


def test_sanitize_text_masks_ip_and_identifiers():
    s = HwServer(serial="ABC1234", uuid="37333036-3831-4D32", bmc_ip="10.1.1.5")
    out = E.sanitize_text("PSU fail on abc1234 (10.1.1.5) host 192.168.0.7 uuid 37333036-3831-4D32", s)
    assert "ABC1234" not in out.upper() and "10.1.1.5" not in out and "192.168.0.7" not in out and "37333036" not in out


# ═══ 2) ESXi etki alanı ══════════════════════════════════════════════════════════════════════════════════════════

def _esxi_fixture(db):
    from app.models.hypervisor import Hypervisor, HypervisorType
    from app.models.hypervisor_inventory import HypervisorHostInventory
    from app.models.infrastructure_report import BusinessServiceMap
    from app.services.hw.matching import run_matching
    hv = Hypervisor(name="vc01", hypervisor_type=HypervisorType.VMWARE, hostname="vc01.x", ip_address="10.0.0.1", connection_config={})
    db.add(hv)
    db.flush()
    inv = HypervisorHostInventory(hypervisor_id=hv.id, host_ref="host-1", host_name="esx01.corp", serial_number="ESX0001",
                                  cluster_name="PROD")
    inv2 = HypervisorHostInventory(hypervisor_id=hv.id, host_ref="host-2", host_name="esx02.corp", serial_number="ESX0002",
                                   cluster_name="PROD")
    db.add_all([inv, inv2])
    vms = []
    for i in range(3):
        v = Server(name=f"vm{i}", hostname=f"vm{i}", ip_address=f"10.1.0.{i + 1}", hypervisor_id=hv.id, server_type="VIRTUAL",
                   vm_name=f"vm{i}", vm_host_ref="host-1", vm_host_name="esx01.corp", vm_power_state="poweredOn" if i < 2 else "poweredOff")
        vms.append(v)
    other = Server(name="vm-other", hostname="vmo", ip_address="10.1.0.9", hypervisor_id=hv.id, server_type="VIRTUAL",
                   vm_name="vm-other", vm_host_ref="host-2", vm_host_name="esx02.corp", vm_power_state="poweredOn")
    db.add_all(vms + [other])
    db.flush()
    db.add(BusinessServiceMap(service_name="ERP", service_tier="critical", server_id=vms[0].id))
    db.add(BusinessServiceMap(service_name="ERP", service_tier="critical", server_id=vms[1].id))
    db.add(BusinessServiceMap(service_name="Intranet", service_tier="low", server_id=vms[2].id))
    db.add(BusinessServiceMap(service_name="Other", service_tier="high", server_id=other.id))
    row = F.make_row(db)
    h1 = HwServer(instance_id=row.id, provider_ref="h1", vendor="dell", name="esx01-hw", serial="ESX0001", health="critical")
    h2 = HwServer(instance_id=row.id, provider_ref="h2", vendor="dell", name="esx02-hw", serial="ESX0002", health="ok")
    db.add_all([h1, h2])
    db.commit()
    run_matching(db)
    return hv, inv, h1, h2


def test_esxi_critical_event_carries_blast_radius_and_goes_to_virtualization(db):
    _hv, _inv, h1, _h2 = _esxi_fixture(db)
    st = E.sync_hw_events(db)
    assert st["created"] == 1 and st["incidents"] == 1
    ev = _hw_events(db)[0]
    assert ev.server_id is None and ev.raw_data["platform"] == "virt" and ev.raw_data["host_name"] == "esx01.corp"
    imp = ev.raw_data["impact"]
    assert imp["vm_count"] == 3 and imp["vm_powered_on"] == 2
    assert [s["name"] for s in imp["services"]] == ["ERP", "Intranet"]          # kritik katman önce
    assert imp["critical_services"] == 1
    assert imp["cluster"]["hosts"] == 2 and imp["cluster"]["hw_critical_hosts"] == 1 and imp["cluster"]["ha_risk"] is True
    assert "Etkilenen VM: 3" in ev.description
    # diğer host (ok) etkilenmez
    assert db.query(Incident).count() == 1


def test_incident_hardware_card_data(db):
    from app.services.hw.incident_view import hardware_for_incident
    _esxi_fixture(db)
    E.sync_hw_events(db)
    inc = db.query(Incident).one()
    out = hardware_for_incident(db, inc)
    assert out["enabled"] is True and len(out["items"]) == 1
    it = out["items"][0]
    assert it["health"] == "critical" and it["via"] == "event" and it["impact"]["vm_count"] == 3
    assert not ({"serial", "bmc_ip", "uuid", "web_url"} & set(it))


def test_incident_card_via_affected_server_only_when_hw_unhealthy(db):
    from app.services.hw.incident_view import hardware_for_incident
    srv = _linux_srv(db)
    _real_sync(db)
    manual = Incident(title="cpu", severity="critical", status="open", source="auto_cpu_high", affected_servers=[srv.id],
                      related_events=[])
    db.add(manual)
    db.commit()
    out = hardware_for_incident(db, manual)
    assert len(out["items"]) == 1 and out["items"][0]["via"] == "affected_server"
    for h in db.query(HwServer).all():
        h.health = "ok"
    db.commit()
    assert hardware_for_incident(db, manual)["items"] == []                      # sağlıklıysa gürültü yok


# ═══ 3) İki seviyeli yetki + HTTP ════════════════════════════════════════════════════════════════════════════════

def _client(db, role="operator", uid=7):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import hw as hw_api
    from app.core.auth import get_current_user
    from app.core.database import get_db
    app = FastAPI()
    app.include_router(hw_api.router, prefix="/hw")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=role, id=uid, username="u")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _grant(db, uid, module):
    from app.models.module import UserModule
    db.add(UserModule(user_id=uid, module_id=module))
    db.commit()


@pytest.fixture()
def users(db):
    from app.models.user import User
    from app.models.module import Module
    ids = {}
    for name in ("platform_u", "hw_u"):
        u = User(username=name, email=f"{name}@x", hashed_password="x", role="operator", is_active=True)
        db.add(u)
        db.flush()
        ids[name] = u.id
    for mid in ("linux", "hardware"):
        if not db.query(Module).filter(Module.id == mid).first():
            db.add(Module(id=mid, name=mid, description="", icon="Server", color="blue", sort_order=1, is_active=True))
    db.commit()
    _grant(db, ids["platform_u"], "linux")
    _grant(db, ids["hw_u"], "hardware")
    return ids


def test_platform_user_sees_summary_without_bmc_serial_console(db, users):
    srv = _linux_srv(db)
    _real_sync(db)
    j = _client(db, uid=users["platform_u"]).get(f"/hw/servers/by-target?kind=server&id={srv.id}").json()
    s = j["server"]
    assert j["available"] is True and j["restricted"] is True and s["restricted"] is True
    assert s["health"] == "critical" and s["model"] and s["warranty"] is not None
    for k in ("serial", "uuid", "bmc_ip", "bmc_type", "bmc_version", "web_url", "virtual_serial"):
        assert k not in s
    assert "10.20.30.42" not in str(j) and "XYZ9876" not in str(j)


def test_hardware_module_user_gets_full_detail(db, users):
    srv = _linux_srv(db)
    _real_sync(db)
    j = _client(db, uid=users["hw_u"]).get(f"/hw/servers/by-target?kind=server&id={srv.id}").json()
    assert j["restricted"] is False and j["server"]["bmc_ip"] == "10.20.30.42" and j["server"]["serial"] == "XYZ9876"


def test_targets_health_map_is_sanitized(db, users):
    srv = _linux_srv(db)
    _real_sync(db)
    j = _client(db, uid=users["platform_u"]).get("/hw/targets-health?kind=server").json()
    it = j["items"][str(srv.id)]
    assert it["health"] == "critical" and it["critical_alerts"] == 1
    assert "10.20.30.42" not in str(j) and "XYZ9876" not in str(j)
    assert _client(db).get("/hw/targets-health?kind=esxi").json()["items"] == {}


def test_policy_platform_modules_get_only_summary_endpoints():
    from app.core.module_policy import decide
    for mod in ("linux", "windows", "virtualization"):
        for p in ("/api/v1/hw/servers/by-target", "/api/v1/hw/targets-health"):
            assert decide(role="operator", modules=(mod,), method="GET", path=p, query={}).allowed
        for p in ("/api/v1/hw/servers", "/api/v1/hw/summary", "/api/v1/hw/alerts", "/api/v1/hw/warranty-report",
                  "/api/v1/hw/unmatched"):
            assert not decide(role="operator", modules=(mod,), method="GET", path=p, query={}).allowed
    assert not decide(role="operator", modules=("linux",), method="POST", path="/api/v1/hw/links", query={}).allowed
    assert decide(role="operator", modules=("hardware",), method="POST", path="/api/v1/hw/links", query={}).allowed
    assert not decide(role="viewer", modules=("hardware",), method="POST", path="/api/v1/hw/links", query={}).allowed


# ═══ 4) Elle eşleştirme, öneri, rapor, geçmiş ═══════════════════════════════════════════════════════════════════

def test_manual_link_survives_automatic_rematch_and_unlink(db, users):
    from app.services.hw.matching import run_matching
    row = F.make_row(db)
    _caps(db, row)
    hw = HwServer(instance_id=row.id, provider_ref="m1", vendor="hpe", name="blade-x", serial=None, health="ok")
    srv = Server(name="app-weird-name", hostname="weird", ip_address="10.0.0.5", server_type="PHYSICAL")
    db.add_all([hw, srv])
    db.commit()
    c = _client(db, uid=users["hw_u"])
    un = c.get("/hw/unmatched").json()
    assert un["hw"][0]["id"] == hw.id
    r = c.post("/hw/links", json={"hw_server_id": hw.id, "target_kind": "server", "target_id": srv.id})
    assert r.status_code == 200
    run_matching(db)
    run_matching(db)
    l = db.query(HwHostLink).one()
    assert (l.hw_server_id, l.target_id, l.method, l.confidence) == (hw.id, srv.id, "manual", "exact")
    assert c.get("/hw/unmatched").json()["hw"] == []
    # aynı hedefe ikinci donanım bağlanamaz
    hw2 = HwServer(instance_id=row.id, provider_ref="m2", vendor="hpe", name="blade-y", health="ok")
    db.add(hw2)
    db.commit()
    assert c.post("/hw/links", json={"hw_server_id": hw2.id, "target_kind": "server", "target_id": srv.id}).status_code == 409
    assert c.post("/hw/links", json={"hw_server_id": hw2.id, "target_kind": "vm", "target_id": 1}).status_code == 400
    assert c.post("/hw/links", json={"hw_server_id": hw2.id, "target_kind": "server", "target_id": 99999}).status_code == 404
    assert c.delete(f"/hw/links/{hw.id}").json()["removed"] == 1
    run_matching(db)
    assert db.query(HwHostLink).count() == 0


def test_unmatched_suggests_candidates_by_name(db, users):
    row = F.make_row(db)
    _caps(db, row)
    db.add(HwServer(instance_id=row.id, provider_ref="u1", vendor="dell", name="ora-prod-db01.corp", health="ok"))
    db.add(Server(name="ora-prod-db01", hostname="ora-prod-db01", ip_address="10.0.0.6", server_type="PHYSICAL"))
    db.add(Server(name="totally-different", hostname="zzz", ip_address="10.0.0.7", server_type="PHYSICAL"))
    db.commit()
    from app.services.hw.matching import run_matching
    run_matching(db)                                   # hostname eşleşmesi low-confidence bağlar → sil, öneriyi sına
    db.query(HwHostLink).delete()
    db.commit()
    cand = _client(db, uid=users["hw_u"]).get("/hw/unmatched").json()["hw"][0]["candidates"]
    assert cand and cand[0]["name"] == "ora-prod-db01" and cand[0]["score"] >= 0.9
    assert all(c["name"] != "totally-different" for c in cand)


def test_warranty_report_and_history(db, users):
    from app.models.hw import HwWarranty
    srv = _linux_srv(db)
    row = _real_sync(db)
    hw = db.query(HwServer).filter(HwServer.serial == "XYZ9876").one()
    now = datetime.now(timezone.utc)
    ok_hw = HwServer(instance_id=row.id, provider_ref="w2", vendor="dell", name="fresh", health="ok")
    db.add(ok_hw)
    db.flush()
    db.add(HwWarranty(instance_id=row.id, provider_ref="w2", server_ref="w2", service_level="ProSupport",
                      start_date=now - timedelta(days=10), end_date=now + timedelta(days=900)))
    db.commit()
    c = _client(db, uid=users["hw_u"])
    j = c.get("/hw/warranty-report?days=180").json()
    assert j["enabled"] is True and j["expired"] >= 1
    names = [i["name"] for i in j["items"]]
    assert "lin-db-02" in names and "fresh" not in names                        # 900 gün sonra bitecek → pencere dışı
    assert "fresh" in [i["name"] for i in c.get("/hw/warranty-report?days=180&include_ok=true").json()["items"]]
    # geçmiş: donanım olayları (açılış/çözülme) detayda
    d = c.get(f"/hw/servers/{hw.id}").json()["server"]
    assert {h["type"] for h in d["history"]} == {E.ET_HEALTH, E.ET_ALERT} and all(not h["resolved"] for h in d["history"])
    assert srv.id is not None


def test_event_grouping_keys_distinguish_hw_servers():
    from app.services.event_grouping import event_problem_key
    a = SimpleNamespace(event_type=E.ET_ALERT, source=E.SOURCE_REAL, server_id=None, title="Donanım alarmı: srv01 — x",
                        raw_data={"hw_server_key": "1:a", "fingerprint": "f"})
    b = SimpleNamespace(event_type=E.ET_ALERT, source=E.SOURCE_REAL, server_id=None, title="Donanım alarmı: srv02 — x",
                        raw_data={"hw_server_key": "1:b", "fingerprint": "f"})
    assert event_problem_key(a) != event_problem_key(b)


# ═══ 4) Dashboard: sıralama, sorunlu donanım kartları, host → VM ═════════════════════════════════════════════════

def _more_hw(db, row):
    now = datetime.now(timezone.utc)
    from app.models.hw import HwWarranty
    for ref, name, vendor, model, bmc, health, enc, bay, wend in (
        ("a1", "node-10", "hpe", "DL380 Gen10", "10.10.0.1", "ok", "Enc-B", 2, 400),
        ("a2", "node-2", "dell", "R740", "10.2.0.9", "warning", "Enc-A", 11, 30),
        ("a3", "node-1", "dell", "R640", None, "unknown", None, None, None),
    ):
        db.add(HwServer(instance_id=row.id, provider_ref=ref, vendor=vendor, name=name, model=model, bmc_ip=bmc,
                        health=health, enclosure_name=enc, bay=bay, serial=f"SN-{ref}"))
        if wend is not None:
            db.add(HwWarranty(instance_id=row.id, provider_ref=ref, server_ref=ref, service_level="PS",
                              start_date=now - timedelta(days=5), end_date=now + timedelta(days=wend)))
    db.commit()


def _names(c, qs):
    return [s["name"] for s in c.get(f"/hw/servers?{qs}").json()["servers"]]


def test_servers_sort_natural_ip_health_and_empty_last(db, users):
    row = _real_sync(db)
    _more_hw(db, row)
    c = _client(db, uid=users["hw_u"])
    base = _names(c, "")
    assert len(base) == 5 and {"node-1", "node-2", "node-10"} <= set(base)
    n = _names(c, "sort_by=name&sort_dir=asc")
    assert n.index("node-2") < n.index("node-10")                                # doğal sıra (2 < 10)
    assert _names(c, "sort_by=name&sort_dir=desc")[0] == "node-10"
    ip = _names(c, "sort_by=bmc_ip&sort_dir=asc")
    assert ip.index("node-2") < ip.index("node-10") and ip[-1] == "node-1"        # 10.2.0.9 < 10.10.0.1; boş sona
    ipd = _names(c, "sort_by=bmc_ip&sort_dir=desc")
    assert ipd[-1] == "node-1" and ipd.index("node-10") < ipd.index("node-2")     # boş yönden bağımsız sonda
    h = _names(c, "sort_by=health&sort_dir=asc")
    hl = {x["name"]: x["health"] for x in c.get("/hw/servers").json()["servers"]}
    assert [hl[n] for n in h] == sorted((hl[n] for n in h), key=["critical", "warning", "unknown", "ok"].index)  # critical → … → ok
    assert h[-1] == "node-10" and h.index("node-2") < h.index("node-1")
    w = _names(c, "sort_by=warranty&sort_dir=asc")
    assert w.index("node-2") < w.index("node-10") < w.index("node-1")            # yakın bitiş önce; garantisiz sonda
    enc = _names(c, "sort_by=enclosure&sort_dir=asc")
    assert enc.index("node-2") < enc.index("node-10") < enc.index("node-1")       # Enc-A < Enc-B < boş
    ven = c.get("/hw/servers?sort_by=vendor&sort_dir=asc").json()["servers"]
    assert [x["vendor"] for x in ven] == sorted(x["vendor"] for x in ven)
    page = c.get("/hw/servers?sort_by=name&sort_dir=asc&limit=2&offset=2").json()
    assert page["total"] == 5 and len(page["servers"]) == 2                       # sıralama TÜM kayıtlarda, dilim sonra
    assert c.get("/hw/servers?sort_by=password").status_code == 422
    assert c.get("/hw/servers?sort_by=name&sort_dir=up").status_code == 422


def test_servers_sort_by_bmc_and_bios_version_numeric_empty_last(db, users):
    row = _real_sync(db)
    for ref, name, bmc, bios in (("v1", "ver-a", "2.10", "1.9.0"), ("v2", "ver-b", "2.9", "1.10.0"), ("v3", "ver-c", None, None)):
        db.add(HwServer(instance_id=row.id, provider_ref=ref, vendor="hpe", name=name, bmc_version=bmc, bios_version=bios,
                        serial=f"SN-{ref}"))
    db.commit()
    c = _client(db, uid=users["hw_u"])
    b = [n for n in _names(c, "sort_by=bmc_version&sort_dir=asc") if n.startswith("ver-")]
    assert b == ["ver-b", "ver-a", "ver-c"]                                   # 2.9 < 2.10 (metinsel değil); boş sonda
    bd = [n for n in _names(c, "sort_by=bmc_version&sort_dir=desc") if n.startswith("ver-")]
    assert bd == ["ver-a", "ver-b", "ver-c"]                                  # boş yönden bağımsız sonda
    o = [n for n in _names(c, "sort_by=bios_version&sort_dir=asc") if n.startswith("ver-")]
    assert o == ["ver-a", "ver-b", "ver-c"]                                   # 1.9.0 < 1.10.0
    row_ = next(x for x in c.get("/hw/servers").json()["servers"] if x["name"] == "ver-a")
    assert row_["bmc_version"] == "2.10" and row_["bios_version"] == "1.9.0"  # listede sütun verisi var


def test_servers_sort_by_match_name(db, users):
    srv = _linux_srv(db, "aaa-linux")
    _real_sync(db)
    c = _client(db, uid=users["hw_u"])
    got = c.get("/hw/servers?sort_by=match&sort_dir=asc").json()["servers"]
    assert got[0]["link"] and got[0]["link"]["name"] == "aaa-linux"
    assert srv.id is not None


def test_problem_servers_only_unhealthy_sorted_and_sanitized(db, users):
    row = _real_sync(db)
    _more_hw(db, row)
    c = _client(db, uid=users["hw_u"])
    j = c.get("/hw/problem-servers").json()
    names = [i["name"] for i in j["items"]]
    assert j["enabled"] is True and "lin-db-02" in names and "node-2" in names and names.index("node-2") > names.index("lin-db-02")
    assert "node-10" not in names and "node-1" not in names                        # sağlıklı / unknown+bağlı → yok
    top = j["items"][0]
    assert top["critical_alerts"] >= 1 and top["top_alert"]
    blob = str(j)
    assert "10.20.30.42" not in blob and "XYZ9876" not in blob                     # BMC/seri maskeli


def test_problem_servers_requires_hardware_module_and_no_integration(db, users):
    from app.core.module_policy import decide
    for mod in ("linux", "windows", "virtualization"):
        assert not decide(role="operator", modules=(mod,), method="GET", path="/api/v1/hw/problem-servers", query={}).allowed
    assert decide(role="operator", modules=("hardware",), method="GET", path="/api/v1/hw/problem-servers", query={}).allowed
    j = _client(db, uid=users["hw_u"]).get("/hw/problem-servers").json()
    assert j["enabled"] is False and j["items"] == []                              # entegrasyon yok → boş


def _virt_fixture(db):
    from app.models.hypervisor import Hypervisor, HypervisorType
    hv = Hypervisor(name="vc1", hypervisor_type=HypervisorType.VMWARE, hostname="vc1", ip_address="10.0.0.1")
    db.add(hv)
    db.flush()
    for n, ref, hn, pw in (("vm-a", "host-1", "esx1.lab", "poweredOn"), ("vm-b", "host-1", "esx1.lab", "poweredOff"),
                           ("vm-c", "host-2", "esx2.lab", "POWERED_ON"), ("vm-d", "", "ESX1.LAB", "poweredOn")):
        db.add(Server(name=n, hostname=n, ip_address="10.1.0.9", server_type="VM", os_type="linux", hypervisor_id=hv.id,
                      vm_host_ref=ref, vm_host_name=hn, vm_power_state=pw, vm_name=n))
    db.commit()
    return hv


def _hv_client(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import hypervisors as hv_api
    from app.core.database import get_db
    app = FastAPI()
    app.include_router(hv_api.router, prefix="/hypervisors")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_host_vms_returns_only_that_host(db):
    hv = _virt_fixture(db)
    c = _hv_client(db)
    j = c.get(f"/hypervisors/{hv.id}/host-vms?host_ref=host-1&host_name=esx1.lab").json()
    assert sorted(v["name"] for v in j["vms"]) == ["vm-a", "vm-b", "vm-d"]          # ref VEYA ad (büyük/küçük harf duyarsız)
    assert j["total"] == 3 and j["running"] == 2
    j2 = c.get(f"/hypervisors/{hv.id}/host-vms?host_ref=host-2").json()
    assert [v["name"] for v in j2["vms"]] == ["vm-c"] and j2["running"] == 1       # oVirt/OCP «POWERED_ON» da açık sayılır
    assert j2["unmapped"] == 0
    assert c.get(f"/hypervisors/{hv.id}/host-vms").json()["vms"] == []              # kimlik yoksa tüm VM'ler ASLA dönmez
    assert c.get("/hypervisors/9999/host-vms?host_ref=x").status_code == 404


# ═══ 5) Host sınıfı (Hardware sayfası gruplaması) ════════════════════════════════════════════════════════════════

def test_host_class_summary_filter_and_precedence(db, users):
    from app.models.hypervisor import Hypervisor, HypervisorType
    from app.models.hypervisor_inventory import HypervisorHostInventory
    row = _real_sync(db)
    _more_hw(db, row)                                   # node-10 (hpe, Enc-B), node-2 (dell, Enc-A), node-1 (standalone)
    ids = {s.name: s for s in db.query(HwServer).filter(HwServer.instance_id == row.id).all()}

    def inv(htype, ref):
        hv = Hypervisor(name=f"hv-{ref}", hypervisor_type=htype, hostname=f"{ref}.x", ip_address="10.9.0.1",
                        username="ro", connection_config={})
        db.add(hv)
        db.flush()
        i = HypervisorHostInventory(hypervisor_id=hv.id, host_ref=ref, host_name=ref)
        db.add(i)
        db.flush()
        return i

    # node-10 (şasi içinde ama ESXi'ye eşleşmiş) → esxi; node-2 → OpenShift; node-1 → OLVM/KVM
    for name, htype, ref in (("node-10", HypervisorType.VMWARE, "h1"), ("node-2", HypervisorType.OPENSHIFT_VIRT, "h2"),
                             ("node-1", HypervisorType.KVM, "h3")):
        i = inv(htype, ref)
        db.add(HwHostLink(hw_server_id=ids[name].id, target_kind="esxi", target_id=i.id, method="serial", confidence="exact"))
    db.commit()
    c = _client(db, uid=users["hw_u"])
    by = c.get("/hw/summary").json()["by_class"]
    total = c.get("/hw/summary").json()["total"]
    assert by["esxi"] == 1 and by["ocp"] == 1 and by["olvm"] == 1
    assert sum(by.values()) == total                                    # her kayıt tek sınıf
    assert _names(c, "host_class=esxi") == ["node-10"]                  # şasi'de olsa da hypervisor sınıfı önce
    assert _names(c, "host_class=ocp") == ["node-2"] and _names(c, "host_class=olvm") == ["node-1"]
    rows = c.get("/hw/servers").json()["servers"]
    assert all(r["host_class"] in ("esxi", "ocp", "olvm", "hv_other", "chassis", "physical") for r in rows)
    assert c.get("/hw/servers?host_class=nope").status_code == 422
    assert len(_names(c, "host_class=physical")) + len(_names(c, "host_class=chassis")) == total - 3


def test_host_class_linux_server_and_unmatched_rack_are_physical(db, users):
    row = _real_sync(db)
    _more_hw(db, row)
    srv = _linux_srv(db)
    node1 = db.query(HwServer).filter(HwServer.instance_id == row.id, HwServer.name == "node-1").first()
    db.add(HwHostLink(hw_server_id=node1.id, target_kind="server", target_id=srv.id, method="serial", confidence="exact"))
    db.commit()
    c = _client(db, uid=users["hw_u"])
    assert "node-1" in _names(c, "host_class=physical")                 # Linux sunucuya eşleşmiş
    assert "node-10" in _names(c, "host_class=chassis")                 # eşleşmemiş blade/şasi → chassis
