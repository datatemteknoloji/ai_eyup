"""Faz 3b — API: Donanım Logları (şasi alarmı), BMC uç noktaları/profilleri, portal BMC hesabı. Ağa ÇIKMAZ."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.models.infrastructure_report  # noqa: F401
from app.models.hw import HwAlert, HwBmcEndpoint, HwBmcProfile, HwEnclosure, HwHostLink, HwLogEntry, HwServer
from app.models.server import Server
from app.services.hw import bmc_creds as BC
from app.services.hw import bmc_logs
from app.services.hw import host_logs as HL
from app.tests import hw_fakes as F
from app.tests.test_hw_bmc import FakeBmc
from app.tests.test_hw_host_logs import _hv_with_hosts


@pytest.fixture()
def db(isolated_db):
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()
    yield isolated_db
    invalidate_capabilities()


def _now():
    return datetime.now(timezone.utc)


def _client(db, role="admin", uid=1, bmc=False, integ=False):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import hw as hw_api, hw_bmc, hw_integrations
    from app.core.auth import get_current_user
    from app.core.database import get_db
    app = FastAPI()
    app.include_router(hw_api.router, prefix="/hw")
    app.include_router(hw_bmc.router, prefix="/hw/bmc")
    app.include_router(hw_integrations.router, prefix="/integrations/hardware")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=role, id=uid, username="u")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _real_provider(db):
    from app.services.capabilities import invalidate_capabilities
    row = F.make_row(db)
    row.last_status = "ok"
    db.commit()
    invalidate_capabilities()
    return row


def _hw(db, inst, name, ref, **kw):
    h = HwServer(instance_id=inst.id, provider_ref=ref, vendor=kw.pop("vendor", "dell"), name=name, serial=name.upper(), **kw)
    db.add(h)
    db.commit()
    return h


def _alert(db, inst, ref, msg, *, server_ref=None, entity=None, sev="critical", state="active"):
    a = HwAlert(instance_id=inst.id, provider_ref=ref, server_ref=server_ref, entity_name=entity, severity=sev, state=state,
                category="Health", message=msg, fingerprint=ref, occurred_at=_now(), last_seen_at=_now())
    db.add(a)
    db.commit()
    return a


@pytest.fixture()
def users(db):
    from app.models.module import Module, UserModule
    from app.models.user import User
    ids = {}
    for name in ("linux_u", "hw_u"):
        u = User(username=name, email=f"{name}@x", hashed_password="x", role="operator", is_active=True)
        db.add(u)
        db.flush()
        ids[name] = u.id
    for mid in ("linux", "hardware"):
        if not db.query(Module).filter(Module.id == mid).first():
            db.add(Module(id=mid, name=mid, description="", icon="Server", color="blue", sort_order=1, is_active=True))
    db.commit()
    db.add(UserModule(user_id=ids["linux_u"], module_id="linux"))
    db.add(UserModule(user_id=ids["hw_u"], module_id="hardware"))
    db.commit()
    return ids


# ═══ A) Donanım Logları sekmesi + şasi alarmı ═══════════════════════════════════════════════════════════════════

def _seed_chassis(db):
    inst = _real_provider(db)
    encl = HwEnclosure(instance_id=inst.id, provider_ref="2001", name="Chassis-A", model="M1000e", health="warning")
    encl2 = HwEnclosure(instance_id=inst.id, provider_ref="encl-77", name="Frame-7", model="c7000", health="ok")
    db.add_all([encl, encl2])
    srv = _hw(db, inst, "blade1", "1001", form_factor="blade", enclosure_name="Chassis-A")
    db.commit()
    _alert(db, inst, "a1", "Chassis PSU 2 failed", server_ref="2001", entity="Chassis-A")                 # OME: şasi cihazı
    _alert(db, inst, "a2", "Server DIMM failure", server_ref="1001", entity="blade1")                      # OME: sunucu
    _alert(db, inst, "a3", "Enclosure fan degraded", server_ref=None, entity="Frame-7", sev="warning")     # OneView: şasi adı
    _alert(db, inst, "a4", "Enclosure cleared", server_ref=None, entity="Frame-7", state="cleared")        # temizlenmiş → yok
    _alert(db, inst, "a5", "Unknown thing", server_ref=None, entity="Nobody")                              # şasiye ait değil
    return inst, srv


def test_log_overview_requires_hardware_module(db, users):
    c = _client(db, role="operator", uid=users["linux_u"])
    assert c.get("/hw/log-overview").status_code == 403
    assert _client(db, role="operator", uid=users["hw_u"]).get("/hw/log-overview").status_code == 200


def test_chassis_alerts_attributed_to_chassis_not_to_blades(db):
    _seed_chassis(db)
    j = _client(db).get("/hw/log-overview").json()
    msgs = sorted(i["message"] for i in j["items"])
    assert msgs == ["Chassis PSU 2 failed", "Enclosure fan degraded"]            # sunucu/temiz/yabancı alarmı YOK (çift sayım yok)
    assert all(i["host_class"] == "chassis" and i["source"] == "portal_alert" for i in j["items"])
    assert {i["target"]["name"] for i in j["items"]} == {"Chassis-A", "Frame-7"}
    assert j["counts"]["by_class"] == {"chassis": 2} and j["counts"]["by_source"] == {"portal_alert": 2}
    src = {s["key"]: s for s in j["sources"]}
    assert src["portal_alert"]["entries"] == 2 and src["portal_alert"]["hosts"] == 2 and src["portal_alert"]["enabled"] is True


def test_log_overview_mixes_sources_and_filters_by_class_and_source(db, monkeypatch):
    monkeypatch.setattr(HL, "enabled", lambda: True)
    _seed_chassis(db)
    hv, inv = _hv_with_hosts(db)
    srv = Server(name="phys-1", ip_address="10.0.0.9", server_type="PHYSICAL", os_type="linux")
    db.add(srv)
    db.commit()
    now = _now()
    HL.ingest_lines(db, "esxi", inv.id, "esxi_sel", [HL.Item(now, "critical", "power", "PSU 2 failed on 10.20.30.42")], now)
    HL.ingest_lines(db, "server", srv.id, "ipmi_sel", [HL.Item(now, "warning", "memory", "Memory: Correctable ECC (Asserted)")], now)
    HL.ingest_lines(db, "server", srv.id, "ipmi_sel", [HL.Item(now, "info", "platform", "System Boot Initiated: x")], now)
    db.commit()
    c = _client(db)
    j = c.get("/hw/log-overview").json()
    assert j["enabled"] is True and j["available"] is True
    assert {i["source"] for i in j["items"]} == {"portal_alert", "esxi_sel", "ipmi_sel"}
    assert "System Boot Initiated: x" not in {i["message"] for i in j["items"]}        # varsayılan: info yok
    assert j["counts"]["by_class"] == {"chassis": 2, "esxi": 1, "physical": 1}
    esx = next(i for i in j["items"] if i["source"] == "esxi_sel")
    assert "10.20.30.42" not in json.dumps(esx) and esx["host_class"] == "esxi" and esx["target"]["name"] == "esx01.corp"
    only = c.get("/hw/log-overview?host_class=physical").json()
    assert [i["source"] for i in only["items"]] == ["ipmi_sel"] and only["items"][0]["target"]["name"] == "phys-1"
    assert c.get("/hw/log-overview?host_class=ocp").json()["items"] == []
    assert [i["source"] for i in c.get("/hw/log-overview?source=esxi_sel").json()["items"]] == ["esxi_sel"]
    allsev = c.get("/hw/log-overview?severity=all").json()
    assert "System Boot Initiated: x" in {i["message"] for i in allsev["items"]}
    # sıralama: kritik önce
    assert [i["severity"] for i in j["items"]] == sorted((i["severity"] for i in j["items"]), key=lambda s: {"critical": 0, "warning": 1}.get(s, 2))
    assert c.get("/hw/log-overview?host_class=bogus").status_code == 422


def test_log_overview_empty_returns_not_enabled(db, monkeypatch):
    for mod, name in ((HL, "enabled"),):
        monkeypatch.setattr(mod, name, lambda: False)
    from app.services.hw import bmc_logs as BL, ipmi_inband as IP
    monkeypatch.setattr(BL, "enabled", lambda: False)
    monkeypatch.setattr(IP, "enabled", lambda: False)
    j = _client(db).get("/hw/log-overview").json()
    assert j["ok"] and j["enabled"] is False and j["available"] is False and j["items"] == []


def test_host_logs_hw_kind_needs_hardware_module(db, users, monkeypatch):
    monkeypatch.setattr(HL, "enabled", lambda: True)
    inst = _real_provider(db)
    h = _hw(db, inst, "b", "5")
    HL.ingest_lines(db, "hw", h.id, "bmc_redfish", [HL.Item(_now(), "critical", "power", "PSU failed")], _now())
    db.commit()
    assert _client(db, role="operator", uid=users["linux_u"]).get(f"/hw/host-logs?kind=hw&id={h.id}").status_code == 403
    j = _client(db, role="operator", uid=users["hw_u"]).get(f"/hw/host-logs?kind=hw&id={h.id}").json()
    assert j["items"][0]["target"]["name"] == "b" and j["items"][0]["source"] == "bmc_redfish"


# ═══ C) BMC API ═════════════════════════════════════════════════════════════════════════════════════════════════

def test_profile_upsert_never_returns_password_and_overview_hides_it(db):
    c = _client(db)
    r = c.post("/hw/bmc/profiles", json={"scope": "global", "username": "ro", "password": "TOPSECRET-1"})
    assert r.status_code == 200 and "TOPSECRET-1" not in r.text and r.json()["profile"]["has_password"] is True
    # aynı kapsam UPSERT: ikinci profil açılmaz
    c.post("/hw/bmc/profiles", json={"scope": "global", "username": "ro2", "password": "TOPSECRET-2"})
    assert db.query(HwBmcProfile).filter_by(scope="global").count() == 1
    c.post("/hw/bmc/profiles", json={"scope": "vendor", "vendor": "dell", "username": "d", "password": "x"})
    j = c.get("/hw/bmc/overview")
    assert "TOPSECRET" not in j.text and {p["scope"] for p in j.json()["profiles"]} == {"global", "vendor"}
    p = db.query(HwBmcProfile).filter_by(scope="global").one()
    assert BC.load(p) == ("ro2", "TOPSECRET-2") and "TOPSECRET" not in (p.credential_ref or "")
    # parola boş bırakılırsa korunur
    c.post("/hw/bmc/profiles", json={"scope": "global", "username": "ro3", "password": ""})
    db.refresh(p)
    assert BC.load(p) == ("ro3", "TOPSECRET-2")


def test_profile_validation(db):
    c = _client(db)
    assert c.post("/hw/bmc/profiles", json={"scope": "global", "username": "", "password": ""}).status_code == 422
    assert c.post("/hw/bmc/profiles", json={"scope": "vendor", "username": "a", "password": "b"}).status_code == 422
    assert c.post("/hw/bmc/profiles", json={"scope": "instance", "instance_id": 999, "username": "a", "password": "b"}).status_code == 422
    assert c.post("/hw/bmc/profiles", json={"scope": "host", "username": "a", "password": "b"}).status_code == 422   # ad şart
    assert c.post("/hw/bmc/profiles", json={"scope": "bogus", "username": "a", "password": "b"}).status_code == 422


def test_writes_are_admin_only_reads_need_hardware_module(db, users):
    op = _client(db, role="operator", uid=users["hw_u"])
    assert op.get("/hw/bmc/overview").status_code == 200
    assert op.post("/hw/bmc/profiles", json={"scope": "global", "username": "a", "password": "b"}).status_code == 403
    assert op.post("/hw/bmc/endpoints", json={"target_kind": "server", "target_id": 1, "bmc_ip": "1.1.1.1"}).status_code == 403
    assert op.post("/hw/bmc/sync").status_code == 403
    assert _client(db, role="operator", uid=users["linux_u"]).get("/hw/bmc/overview").status_code == 403


def test_endpoint_manual_ip_clear_and_bulk(db):
    inst = _real_provider(db)
    h = _hw(db, inst, "blade9", "9", bmc_ip="10.1.1.9")
    srv = Server(name="phys-9", ip_address="10.0.0.9", server_type="PHYSICAL", os_type="linux")
    db.add(srv)
    db.commit()
    c = _client(db)
    j = c.get("/hw/bmc/overview").json()
    by = {e["target"]["name"]: e for e in j["endpoints"]}
    assert by["blade9"]["bmc_ip"] == "10.1.1.9" and by["blade9"]["ip_source"] == "portal"
    assert by["phys-9"]["bmc_ip"] is None and j["counts"]["no_ip"] == 1
    # elle IP: portal değerinin üstüne yazar ve eşitlemede korunur
    assert c.put(f"/hw/bmc/endpoints/{by['blade9']['id']}", json={"bmc_ip": "172.16.0.9"}).status_code == 200
    j = c.get("/hw/bmc/overview").json()
    e = next(x for x in j["endpoints"] if x["target"]["name"] == "blade9")
    assert (e["bmc_ip"], e["ip_source"]) == ("172.16.0.9", "manual")
    # elle girişi kaldır → portal değerine dön
    c.put(f"/hw/bmc/endpoints/{e['id']}", json={"bmc_ip": ""})
    e = next(x for x in c.get("/hw/bmc/overview").json()["endpoints"] if x["target"]["name"] == "blade9")
    assert (e["bmc_ip"], e["ip_source"]) == ("10.1.1.9", "portal")
    # Linux sunucuya elle IP (POST)
    assert c.post("/hw/bmc/endpoints", json={"target_kind": "server", "target_id": srv.id, "bmc_ip": "192.168.5.5"}).status_code == 200
    # geçersiz adresler
    for bad in ("http://x", "a b", "", "10.0.0.1/24"):
        assert c.post("/hw/bmc/endpoints", json={"target_kind": "server", "target_id": srv.id, "bmc_ip": bad}).status_code == 422
    assert c.post("/hw/bmc/endpoints", json={"target_kind": "server", "target_id": 99999, "bmc_ip": "1.1.1.1"}).status_code == 404
    # toplu profil ataması + temizleme
    pid = c.post("/hw/bmc/profiles", json={"scope": "host", "name": "özel", "username": "u", "password": "p"}).json()["profile"]["id"]
    ids = [x["id"] for x in c.get("/hw/bmc/overview").json()["endpoints"]]
    assert c.post("/hw/bmc/endpoints/bulk", json={"ids": ids, "profile_id": pid}).json()["updated"] == len(ids)
    assert {x["profile_id"] for x in c.get("/hw/bmc/overview").json()["endpoints"]} == {pid}
    assert {x["resolved"]["level"] for x in c.get("/hw/bmc/overview").json()["endpoints"]} == {"host"}
    c.post("/hw/bmc/endpoints/bulk", json={"ids": ids, "profile_id": None})
    assert {x["profile_id"] for x in c.get("/hw/bmc/overview").json()["endpoints"]} == {None}
    assert c.post("/hw/bmc/endpoints/bulk", json={"ids": ids, "profile_id": 9999}).status_code == 422
    # profil silinince bağlar temizlenir
    c.post("/hw/bmc/endpoints/bulk", json={"ids": ids, "profile_id": pid})
    c.delete(f"/hw/bmc/profiles/{pid}")
    assert {x["profile_id"] for x in c.get("/hw/bmc/overview").json()["endpoints"]} == {None}


@contextmanager
def _nolock(_i):
    yield True


def test_endpoint_test_button_single_attempt_cooldown_and_halt(db, monkeypatch):
    from app.services.hw import auth_guard
    inst = _real_provider(db)
    h = _hw(db, inst, "t1", "7", bmc_ip="10.9.9.9")
    c = _client(db)
    c.post("/hw/bmc/profiles", json={"scope": "global", "username": "ro", "password": "WRONG"})
    eid = c.get("/hw/bmc/overview").json()["endpoints"][0]["id"]
    bmc = FakeBmc(user="ro", pw="pw")
    monkeypatch.setattr(bmc_logs, "_default_factory", lambda ip, u, p, v: __import__("app.services.hw.redfish", fromlist=["x"]).RedfishClient(ip, u, p, verify=v, session=bmc))
    slots = {"n": 0}

    def slot(key, **kw):
        slots["n"] += 1
        return 0 if slots["n"] != 2 else 17
    monkeypatch.setattr(auth_guard, "acquire_test_slot", slot)
    monkeypatch.setattr(auth_guard, "attempt_lock", _nolock)
    r = c.post(f"/hw/bmc/endpoints/{eid}/test").json()
    assert r["ok"] is False and r["status"] == "auth_failed"
    assert sum(1 for x in bmc.calls if x[3]) == 1                                    # TEK kimlikli istek
    assert c.post(f"/hw/bmc/endpoints/{eid}/test").status_code == 429                # bekleme süresi
    assert c.get("/hw/bmc/overview").json()["endpoints"][0]["auth_halted"] is True
    # kimlik DÜZELTİLİP kaydedilse de TEK BAŞINA sürdürmez; yalnız başarılı test sürdürür
    c.post("/hw/bmc/profiles", json={"scope": "global", "username": "ro", "password": "pw"})
    assert c.get("/hw/bmc/overview").json()["endpoints"][0]["auth_halted"] is True
    assert c.post(f"/hw/bmc/endpoints/{eid}/test").json()["ok"] is True
    e = c.get("/hw/bmc/overview").json()["endpoints"][0]
    assert e["auth_halted"] is False and e["status"] == "ok"
    assert c.post("/hw/bmc/endpoints/424242/test").status_code == 404


def test_overview_shows_ipmi_status_for_linked_server_on_portal_row(db):
    inst = _real_provider(db)
    h = _hw(db, inst, "rack2", "8", bmc_ip="10.1.1.8")
    srv = Server(name="lin-2", ip_address="10.0.0.2", server_type="PHYSICAL", os_type="linux")
    db.add(srv)
    db.commit()
    db.add(HwHostLink(hw_server_id=h.id, target_kind="server", target_id=srv.id, method="serial", confidence="exact"))
    from app.services.hw import bmc_endpoints as EP
    ep = EP.ensure_endpoint(db, "server", srv.id)
    ep.ipmi_status = "no_sudo"
    db.commit()
    rows = _client(db).get("/hw/bmc/overview").json()["endpoints"]
    assert [r["target"]["name"] for r in rows] == ["rack2"]                       # bağlı Linux sunucu ayrı satır açmaz
    assert rows[0]["ipmi_status"] == "no_sudo"


# ═══ C) Portal entegrasyonunda BMC hesabı ═══════════════════════════════════════════════════════════════════════

_INST = {"kind": "dell_ome", "label": "OME-1", "endpoint": "ome.example", "username": "viewer", "password": "pw"}


def test_portal_integration_bmc_credentials_become_instance_profile(db):
    c = _client(db)
    r = c.post("/integrations/hardware/instances", json={**_INST, "bmc_username": "bmcro", "bmc_password": "BMC-PW-1"})
    assert r.status_code == 200 and "BMC-PW-1" not in r.text
    j = r.json()
    assert j["bmc"] == {"configured": True, "username": "bmcro", "has_password": True, "verify_tls": False}
    p = db.query(HwBmcProfile).filter_by(scope="instance", instance_id=j["id"]).one()
    assert BC.load(p) == ("bmcro", "BMC-PW-1")
    # boş bırakılırsa dokunulmaz; parolasız kullanıcı değişikliği parolayı korur
    r2 = c.put(f"/integrations/hardware/instances/{j['id']}", json={**_INST, "password": None})
    assert r2.json()["bmc"]["configured"] is True and BC.load(p) == ("bmcro", "BMC-PW-1")
    c.put(f"/integrations/hardware/instances/{j['id']}", json={**_INST, "password": None, "bmc_username": "bmcro2"})
    db.refresh(p)
    assert BC.load(p) == ("bmcro2", "BMC-PW-1")
    # temizle
    r3 = c.put(f"/integrations/hardware/instances/{j['id']}", json={**_INST, "password": None, "bmc_clear": True})
    assert r3.json()["bmc"] == {"configured": False}
    assert db.query(HwBmcProfile).filter_by(scope="instance").count() == 0


def test_portal_integration_without_bmc_fields_creates_no_profile_and_partial_is_rejected(db):
    c = _client(db)
    assert c.post("/integrations/hardware/instances", json=_INST).json()["bmc"] == {"configured": False}
    assert db.query(HwBmcProfile).count() == 0
    r = c.post("/integrations/hardware/instances", json={**_INST, "label": "x2", "bmc_username": "only-user"})
    assert r.status_code == 422                                                   # kullanıcı + parola birlikte


def test_deleting_portal_removes_its_bmc_profile(db):
    c = _client(db)
    j = c.post("/integrations/hardware/instances", json={**_INST, "bmc_username": "u", "bmc_password": "p"}).json()
    assert db.query(HwBmcProfile).count() == 1
    c.delete(f"/integrations/hardware/instances/{j['id']}")
    db.expire_all()
    assert db.query(HwBmcProfile).count() == 0                                    # FK ON DELETE CASCADE


# ═══ Makineye ÖZEL BMC hesabı (arkada 1:1 host profili) ══════════════════════════════════════════════════════════

def _phys(db, name="phys-a", ip="10.0.0.20"):
    s = Server(name=name, ip_address=ip, server_type="PHYSICAL", os_type="linux")
    db.add(s)
    db.commit()
    return s


def _ep_row(c, name):
    return next(x for x in c.get("/hw/bmc/overview").json()["endpoints"] if x["target"]["name"] == name)


def test_endpoint_private_account_create_keep_replace_and_never_leak(db):
    _phys(db)
    c = _client(db)
    e = _ep_row(c, "phys-a")
    assert e["account"] is None and e["resolved"] is None
    # yeni hesapta ikisi de zorunlu
    assert c.put(f"/hw/bmc/endpoints/{e['id']}/account", json={"username": "root"}).status_code == 422
    assert c.put(f"/hw/bmc/endpoints/{e['id']}/account", json={"username": "root", "password": "s3cret"}).status_code == 200
    e = _ep_row(c, "phys-a")
    assert e["account"] == {"username": "root", "has_password": True, "verify_tls": False}
    assert e["resolved"]["level"] == "host" and e["resolved"]["private"] is True
    raw = json.dumps(c.get("/hw/bmc/overview").json())
    assert "s3cret" not in raw and "endpoint:" not in json.dumps(c.get("/hw/bmc/overview").json()["profiles"])
    prof_id = e["profile_id"]
    # boş parola: mevcut korunur, aynı profil güncellenir (ikinci profil açılmaz)
    assert c.put(f"/hw/bmc/endpoints/{e['id']}/account", json={"username": "admin2", "password": "", "verify_tls": True}).status_code == 200
    e = _ep_row(c, "phys-a")
    assert e["profile_id"] == prof_id and e["account"]["username"] == "admin2" and e["account"]["verify_tls"] is True
    assert BC.load(db.query(HwBmcProfile).filter_by(id=prof_id).one())[1] == "s3cret"
    assert db.query(HwBmcProfile).filter(HwBmcProfile.name.like("endpoint:%")).count() == 1
    # paylaşılan profil atanınca özel hesap silinir (yetim kalmaz); sonra özel hesap tekrar atanınca paylaşılan profil bozulmaz
    shared = c.post("/hw/bmc/profiles", json={"scope": "host", "name": "ortak", "username": "u", "password": "p"}).json()["profile"]["id"]
    c.put(f"/hw/bmc/endpoints/{e['id']}", json={"profile_id": shared})
    assert db.query(HwBmcProfile).filter(HwBmcProfile.name.like("endpoint:%")).count() == 0
    e = _ep_row(c, "phys-a")
    assert e["account"] is None and e["resolved"]["private"] is False
    c.put(f"/hw/bmc/endpoints/{e['id']}/account", json={"username": "root", "password": "x"})
    assert db.query(HwBmcProfile).filter_by(id=shared).count() == 1
    assert _ep_row(c, "phys-a")["profile_id"] != shared
    # temizle
    assert c.put(f"/hw/bmc/endpoints/{e['id']}/account", json={"clear": True}).status_code == 200
    e = _ep_row(c, "phys-a")
    assert e["account"] is None and e["profile_id"] is None
    assert db.query(HwBmcProfile).filter(HwBmcProfile.name.like("endpoint:%")).count() == 0


def test_private_account_hidden_from_profile_list_and_name_prefix_reserved(db):
    _phys(db)
    c = _client(db)
    e = _ep_row(c, "phys-a")
    c.put(f"/hw/bmc/endpoints/{e['id']}/account", json={"username": "root", "password": "x"})
    assert [p["name"] for p in c.get("/hw/bmc/overview").json()["profiles"]] == []
    assert c.post("/hw/bmc/profiles", json={"scope": "host", "name": "endpoint:7", "username": "u", "password": "p"}).status_code == 422


def test_private_account_is_admin_only(db, users):
    _phys(db)
    e = _ep_row(_client(db), "phys-a")
    c = _client(db, role="operator", uid=users["hw_u"])
    assert c.put(f"/hw/bmc/endpoints/{e['id']}/account", json={"username": "r", "password": "p"}).status_code == 403
    assert c.post("/hw/bmc/server-account", json={"server_id": 1, "bmc_ip": "1.1.1.1"}).status_code == 403


def test_server_account_ip_and_credentials_in_one_call(db):
    s = _phys(db, "phys-b", "10.0.0.30")
    c = _client(db)
    # hepsi boş → hiçbir şey yazılmaz
    assert c.post("/hw/bmc/server-account", json={"server_id": s.id}).json() == {"ok": True, "changed": False}
    assert db.query(HwBmcEndpoint).count() == 0
    j = c.post("/hw/bmc/server-account", json={"server_id": s.id, "bmc_ip": "192.168.9.9", "username": "ADMIN", "password": "pw"}).json()
    assert j["changed"] is True
    e = _ep_row(c, "phys-b")
    assert (e["bmc_ip"], e["ip_source"]) == ("192.168.9.9", "manual")
    assert e["account"]["username"] == "ADMIN" and e["resolved"]["level"] == "host"
    # yalnız IP girilirse hesap oluşmaz; geçersiz IP / olmayan sunucu / yarım hesap reddedilir
    s2 = _phys(db, "phys-c", "10.0.0.31")
    assert c.post("/hw/bmc/server-account", json={"server_id": s2.id, "bmc_ip": "10.9.9.9"}).status_code == 200
    assert _ep_row(c, "phys-c")["account"] is None
    assert c.post("/hw/bmc/server-account", json={"server_id": s2.id, "bmc_ip": "http://x"}).status_code == 422
    assert c.post("/hw/bmc/server-account", json={"server_id": 99999, "bmc_ip": "1.1.1.1"}).status_code == 404
    assert c.post("/hw/bmc/server-account", json={"server_id": s2.id, "username": "only-user"}).status_code == 422


def test_server_account_on_server_linked_to_portal_uses_the_portal_row(db):
    inst = _real_provider(db)
    h = _hw(db, inst, "dl-link", "55")
    s = _phys(db, "lin-link", "10.0.0.40")
    db.add(HwHostLink(hw_server_id=h.id, target_kind="server", target_id=s.id, method="manual", confidence="exact"))
    db.commit()
    c = _client(db)
    assert c.post("/hw/bmc/server-account", json={"server_id": s.id, "bmc_ip": "10.5.5.5", "username": "u", "password": "p"}).status_code == 200
    names = [x["target"]["name"] for x in c.get("/hw/bmc/overview").json()["endpoints"]]
    assert names.count("dl-link") == 1 and "lin-link" not in names          # çift satır yok
    e = _ep_row(c, "dl-link")
    assert e["bmc_ip"] == "10.5.5.5" and e["account"]["username"] == "u"


def test_get_server_account_single_server_view_never_leaks_and_does_not_create(db, users):
    """Düzenleme paneli: tek sunucunun BMC durumu; uç nokta YOKSA oluşturulmaz; parola yok; yalnız admin."""
    s = _phys(db, "phys-get", "10.0.0.60")
    c = _client(db)
    j = c.get(f"/hw/bmc/server-account/{s.id}").json()
    assert j["exists"] is False and j["account"] is None and j["endpoint_id"] is None
    assert db.query(HwBmcEndpoint).count() == 0                       # GET yazmaz
    assert c.post("/hw/bmc/server-account", json={"server_id": s.id, "bmc_ip": "10.7.7.7", "username": "ro", "password": "S3cret!"}).status_code == 200
    r = c.get(f"/hw/bmc/server-account/{s.id}")
    j = r.json()
    assert j["exists"] is True and j["bmc_ip"] == "10.7.7.7" and j["ip_source"] == "manual"
    assert j["account"] == {"username": "ro", "has_password": True, "verify_tls": False}
    assert j["resolved"]["private"] is True and j["endpoint_id"]
    assert "S3cret!" not in r.text and "password" not in {k for k in j["account"]}
    assert c.get("/hw/bmc/server-account/99999").status_code == 404
    op = _client(db, role="operator", uid=users["hw_u"])
    assert op.get(f"/hw/bmc/server-account/{s.id}").status_code == 403


def test_orphan_private_accounts_are_removed_on_sync(db):
    s = _phys(db, "phys-gone", "10.0.0.50")
    c = _client(db)
    e = _ep_row(c, "phys-gone")
    c.put(f"/hw/bmc/endpoints/{e['id']}/account", json={"username": "u", "password": "p"})
    db.query(Server).filter(Server.id == s.id).delete()
    db.commit()
    c.get("/hw/bmc/overview")
    assert db.query(HwBmcEndpoint).count() == 0
    assert db.query(HwBmcProfile).filter(HwBmcProfile.name.like("endpoint:%")).count() == 0
