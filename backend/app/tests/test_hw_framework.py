"""Donanım sağlayıcı çerçevesi (Dell OME + HPE OneView/OVGD): opsiyonellik, salt-okunur allowlist, hesap kilitlenme
koruması, contract (doküman alanları), eşleştirme, bulgular, RBAC, DEMO kapısı ve sohbet aracı.

Ağa ÇIKMAZ (sahte HTTP oturumu); DB testleri İZOLE geçici DB'de çalışır.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.services.hw import auth_guard, endpoints as ep
from app.services.hw.constants import KIND_DELL, KIND_HPE
from app.services.hw.dell_ome import DellOmeProvider, norm_alert, norm_device, norm_warranty, support_for
from app.services.hw.http import HwApiError
from app.services.hw.oneview import HpeProvider, support_for_api, support_for_version
from app.tests import hw_fakes as F


@pytest.fixture()
def db(isolated_db):
    return isolated_db


# ═══ 1) Salt-okunur allowlist ════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("product,path", [
    ("ome", "/api/GroupService/Groups"), ("ome", "/api/GroupService/Groups(1)/AllLeafDeviceSummaries"),
    ("ome", "/api/AlertService/Alerts"), ("ome", "/api/WarrantyService/Warranties"),
    ("ome", "/api/ApplicationService/Info"),
    ("oneview", "/rest/server-hardware"), ("oneview", "/rest/enclosures"), ("oneview", "/rest/alerts"),
    ("ovgd", "/rest/appliances"), ("ovgd", "/rest/resource-alerts"),
])
def test_get_allowed(product, path):
    assert ep.allowed(product, "GET", path)


@pytest.mark.parametrize("product,path", [
    ("ome", "/api/DeviceService/Devices(1)/VirtualSession"),
    ("ome", "/api/DeviceService/Devices(1)/BlinkStatus"),
    ("ome", "/api/DeviceService/Actions/DeviceService.RemoveDevices"),
    ("ome", "/api/UserService/Users"),
    ("oneview", "/rest/server-hardware/1/remoteConsoleUrl"),
    ("oneview", "/rest/server-hardware/1/iloSsoUrl"),
    ("oneview", "/rest/server-hardware/1/powerState"),
    ("oneview", "/rest/server-hardware/1/mpSessionKey"),
    ("ovgd", "/rest/appliances/1/sso"),
    ("ovgd", "/rest/enclosures/1/oaSsoUrl"),
])
def test_forbidden_paths_rejected(product, path):
    assert not ep.allowed(product, "GET", path)


@pytest.mark.parametrize("product", ["ome", "oneview", "ovgd"])
@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "POST"])
def test_write_methods_rejected_outside_session(product, method):
    for path in ("/api/DeviceService/Devices", "/rest/server-hardware", "/rest/server-hardware/1/powerState",
                 "/rest/appliances"):
        assert not ep.allowed(product, method, path)


def test_login_logout_only():
    assert ep.allowed("ome", "POST", "/api/SessionService/Sessions")
    assert ep.allowed("ome", "DELETE", "/api/SessionService/Sessions('0f7d-ab12')")
    assert ep.allowed("oneview", "POST", "/rest/login-sessions")
    assert ep.allowed("oneview", "DELETE", "/rest/login-sessions")
    assert ep.allowed("ovgd", "POST", "/rest/login-sessions/")
    assert not ep.allowed("ome", "DELETE", "/api/UserService/Users(1)")


def test_http_client_blocks_before_network():
    http, sess = F.http_for(F.ome_router(), "https://ome.example", "ome")
    with pytest.raises(HwApiError) as ei:
        http.get("/api/DeviceService/Devices(1)/VirtualSession")
    assert ei.value.kind == "readonly"
    assert sess.calls == []                      # ağ isteği hiç yapılmadı


def test_endpoints_match_api_sources_doc():
    """Koddaki her endpoint kalıbı docs/plans/hw-api-sources.md'de kayıtlı olmalı."""
    doc = Path(__file__).resolve().parents[3] / "docs" / "plans" / "hw-api-sources.md"
    if not doc.exists():                         # dağıtım paketinde docs yok → atlama değil, repo'da zorunlu
        pytest.skip("docs/plans yok (yalnız repo kökünde çalışır)")
    text = doc.read_text(encoding="utf-8")
    missing = []
    for pat in ep.all_documented_paths():
        s = pat.strip("^$").replace("\\(\\d+\\)", "|")
        s = s.replace("\\('deviceSoftware'\\)", "|deviceSoftware").replace("\\('deviceLocation'\\)", "|deviceLocation")
        for frag in [f for f in s.split("|") if f]:
            if frag.strip("/") not in text:
                missing.append((pat, frag))
    assert not missing, f"hw-api-sources.md'de kaydı olmayan uçlar: {missing}"


# ═══ 2) Dell OME contract ════════════════════════════════════════════════════════════════════════════════════════

def test_ome_normalizers():
    s = norm_device(F.OME_SERVER)
    assert s.provider_ref == "10073" and s.vendor == "dell" and s.serial == "ABC1234"
    assert s.bmc_ip == "10.20.30.41" and s.bmc_type == "iDRAC" and s.bmc_version == "4.40.00.00"
    assert s.form_factor == "blade" and s.enclosure_name == "MX7000-A" and s.bay == "Sled-3"
    assert s.health == "ok" and s.power_state == "on" and s.connected is True
    r = norm_device(F.OME_RACK)
    assert r.form_factor == "standalone" and r.health == "critical" and r.enclosure_name is None
    assert norm_device(F.OME_CHASSIS) is None                       # şasi sunucu değildir
    a = norm_alert(F.OME_ALERT)
    assert a.severity == "critical" and a.server_ref == "10074" and a.occurred_at is not None
    w = norm_warranty(F.OME_WARRANTY)
    assert w.server_ref == "10074" and w.end_date.year == 2026
    assert norm_warranty({**F.OME_WARRANTY, "EndDate": "0001-01-01 00:00:00.000"}).end_date is None


def test_ome_support_levels():
    assert support_for("4.7.0") == "verified"
    assert support_for("4.8.1") == "compatible"
    assert support_for("2.9.0") == "unsupported"
    assert support_for(None) == "compatible"


def test_ome_collect_via_provider(db):
    row = F.make_row(db)
    http, sess = F.http_for(F.ome_router(), "https://ome.example", "ome")
    snap = DellOmeProvider(row, http=http).collect(["inventory", "alerts", "warranty"])
    assert {s.provider_ref for s in snap.servers} == {"10073", "10074"}
    assert [e.name for e in snap.enclosures] == ["MX7000-A"]
    assert [a.provider_ref for a in snap.alerts] == ["5001"]        # yalnız Warning/Critical saklanır
    assert len(snap.warranties) == 1
    assert sess.count("POST") == 1                                   # tek oturum açma
    assert sess.count("DELETE") == 1                                 # oturum kapatıldı
    assert all(m in ("GET", "POST", "DELETE") for m, _, _ in sess.calls)


def test_ome_alert_run_does_not_list_devices(db):
    row = F.make_row(db)
    http, sess = F.http_for(F.ome_router(), "https://ome.example", "ome")
    DellOmeProvider(row, http=http).collect(["alerts"])
    assert sess.count("GET", "/api/GroupService") == 0               # 15 dk'lık tur yalnız alarm okur


# ═══ 3) Hesap kilitlenme koruması ════════════════════════════════════════════════════════════════════════════════

def test_ome_bad_password_exactly_one_request_and_halt(db):
    from app.services.hw import sync
    row = F.make_row(db, password="wrong")
    http, sess = F.http_for(F.ome_router(login_status=401), "https://ome.example", "ome")
    res = sync.sync_instance(db, row, force=True, provider=DellOmeProvider(row, http=http))
    assert res["ok"] is False and res.get("auth_halted") is True
    assert sess.count() == 1 and sess.count("POST") == 1             # YALNIZ bir oturum açma isteği
    db.refresh(row)
    assert row.last_status == "auth_failed" and auth_guard.is_halted(row)
    # sonraki senkronlar (force dahil) HİÇ istek yapmaz
    http2, sess2 = F.http_for(F.ome_router(), "https://ome.example", "ome")
    for force in (False, True):
        r2 = sync.sync_instance(db, row, force=force, provider=DellOmeProvider(row, http=http2))
        assert r2.get("skipped") == "auth_halted"
    assert sess2.calls == []
    # zamanlayıcı da atlar
    assert sync.run_all_due(db)["synced"] == 0 and sess2.calls == []


def test_forbidden_403_also_halts(db):
    from app.services.hw import sync
    row = F.make_row(db)
    http, sess = F.http_for(F.ome_router(login_status=403), "https://ome.example", "ome")
    res = sync.sync_instance(db, row, force=True, provider=DellOmeProvider(row, http=http))
    assert res.get("auth_halted") is True and res.get("kind") == "forbidden" and sess.count() == 1


def test_mid_session_401_does_not_relogin(db):
    from app.services.hw import sync
    row = F.make_row(db)
    http, sess = F.http_for(F.ome_router(mid_status=401), "https://ome.example", "ome")
    res = sync.sync_instance(db, row, force=True, provider=DellOmeProvider(row, http=http))
    assert res.get("auth_halted") is True
    assert http.login_attempts == 1 and sess.count("POST") == 1


def test_network_errors_retry_bounded_not_halting(db):
    from app.services.hw import sync
    row = F.make_row(db)
    http, sess = F.http_for(lambda *a: (503, {}, {}), "https://ome.example", "ome")
    res = sync.sync_instance(db, row, force=True, provider=DellOmeProvider(row, http=http))
    assert res["ok"] is False and not res.get("auth_halted")
    db.refresh(row)
    assert not auth_guard.is_halted(row)


def test_saving_credentials_does_not_resume_and_test_success_clears(db):
    row = F.make_row(db)
    auth_guard.halt(db, row, kind="auth", message="x", where="t")
    db.refresh(row)
    assert auth_guard.is_halted(row)
    # yalnız clear() (başarılı test yolu) sürdürür
    auth_guard.clear(db, row)
    db.refresh(row)
    assert not auth_guard.is_halted(row)


def test_test_button_cooldown():
    key = "pytest-cooldown-key"
    auth_guard.reset_test_slot(key)
    assert auth_guard.acquire_test_slot(key, cooldown_sec=30) == 0
    assert auth_guard.acquire_test_slot(key, cooldown_sec=30) > 0
    auth_guard.reset_test_slot(key)


def test_attempt_lock_is_exclusive():
    with auth_guard.attempt_lock(987654) as a:
        assert a is True
        with auth_guard.attempt_lock(987654) as b:
            assert b is False                                        # ikinci eşzamanlı deneme reddedilir


def test_oneview_24_appliances_shared_account_stops_at_first_failure(db):
    hosts = [f"ov{i:02d}.example" for i in range(24)]
    row = F.make_row(db, kind=KIND_HPE, endpoint=hosts[0],
                     meta={"mode": "oneview", "appliances": hosts[1:]}, password="wrong")
    log = []
    sessions = {}

    def factory(base, product):
        http, sess = F.http_for(F.oneview_router(login_status=401, calls_log=log), base, product)
        sessions[base] = sess
        return http

    from app.services.hw import sync
    res = sync.sync_instance(db, row, force=True, provider=HpeProvider(row, http_factory=factory))
    assert res.get("auth_halted") is True
    logins = [c for c in log if c[0] == "POST"]
    assert len(logins) == 1                                          # 24 appliance'ın yalnız İLKİ denendi
    assert len(sessions) == 1


def test_oneview_network_error_on_one_appliance_does_not_halt(db):
    row = F.make_row(db, kind=KIND_HPE, endpoint="ov-a.example",
                     meta={"mode": "oneview", "appliances": ["ov-b.example"]})

    def factory(base, product):
        if base.startswith("https://ov-a"):
            return F.http_for(lambda *a: (503, {}, {}), base, product)[0]
        return F.http_for(F.oneview_router(), base, product)[0]

    snap = HpeProvider(row, http_factory=factory).collect(["inventory", "alerts"])
    statuses = {m.key: m.status for m in snap.managers}
    assert statuses["ov-a.example"] == "error" and statuses["ov-b.example"] == "ok"
    assert len(snap.servers) == 2


# ═══ 4) HPE OneView contract ═════════════════════════════════════════════════════════════════════════════════════

def test_oneview_support_levels():
    assert support_for_api(9000) == "verified" and support_for_api(7600) == "verified"
    assert support_for_api(3800) == "compatible"
    assert support_for_api(2000) == "unsupported"
    assert support_for_version("11.40.00-0520695") == "verified"
    assert support_for_version("6.60.04-0476963") in ("compatible", "verified")
    assert support_for_version("5.00.00") == "unsupported"


def test_oneview_collect_and_alert_server_link(db):
    row = F.make_row(db, kind=KIND_HPE, endpoint="ov.example", meta={"mode": "oneview"})
    http_by = {}

    def factory(base, product):
        h, s = F.http_for(F.oneview_router(), base, product)
        http_by[base] = s
        return h

    snap = HpeProvider(row, http_factory=factory).collect(["inventory", "alerts", "warranty"])
    blade = next(s for s in snap.servers if s.serial == "MXQ1234ABC")
    rack = next(s for s in snap.servers if s.serial == "CZ12345678")
    assert blade.form_factor == "blade" and blade.enclosure_name == "Encl-1" and blade.bay == "3"
    assert blade.bmc_ip == "10.9.9.3" and blade.bmc_type == "iLO5" and blade.memory_gb == 256.0
    assert rack.form_factor == "rack" and rack.health == "critical"
    assert len(snap.alerts) == 1 and snap.alerts[0].server_ref == rack.provider_ref   # alarm↔sunucu aynı anahtar
    assert any("Garanti" in n for n in snap.not_measurable)                           # HPE'de garanti ölçülemez
    sess = next(iter(http_by.values()))
    assert sess.count("POST") == 1
    assert all(m in ("GET", "POST", "DELETE") for m, _, _ in sess.calls)


# ═══ 5) Eşleştirme ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_matching_order_and_ambiguity():
    from app.services.hw.matching import HwItem, Target, match_core
    hw = [HwItem(1, serial="ABC1234", names=["esx-blade-01.kfs.local"]),
          HwItem(2, uuid="37333036-3831-4D32-3234-303930344D31"),
          HwItem(3, names=["web01"]),
          HwItem(4, serial="DUP0001"), HwItem(5, serial="DUP0001")]
    targets = [Target("esxi", 10, serial="ABC1234", names=["esx-blade-01"]),
               Target("server", 20, uuid="37333036-3831-4D32-3234-303930344D31"),
               Target("server", 30, names=["WEB01.kfs.local"]),
               Target("server", 40, serial="DUP0001")]
    r = match_core(hw, targets)
    links = {(h, k, t): (m, c) for h, k, t, m, c in r.links}
    assert links[(1, "esxi", 10)] == ("serial", "exact")
    assert links[(2, "server", 20)][0] == "uuid"
    assert links[(3, "server", 30)] == ("hostname", "low")           # kısa ad yalnız düşük güven
    assert 4 not in {h for h, *_ in r.links} and 5 not in {h for h, *_ in r.links}
    assert any(a["hw_id"] in (4, 5) for a in r.ambiguous)             # aynı seri iki kayıt → eşleşmez, listelenir


def test_uuid_mixed_endian_variant_matches():
    from app.services.hw.matching import HwItem, Target, match_core
    a = "33303637-3138-324D-3234-303930344D31"                       # SMBIOS karışık-endian karşılığı
    b = "37363033-3831-4D32-3234-303930344D31"
    r = match_core([HwItem(1, uuid=a)], [Target("server", 1, uuid=b)])
    assert len(r.links) == 1 and r.links[0][3] == "uuid"


# ═══ 6) Opsiyonellik ═════════════════════════════════════════════════════════════════════════════════════════════

def test_no_instance_means_no_capability_no_job_and_empty_endpoints(db, monkeypatch):
    from app.api import hw as hw_api
    from app.services.capabilities import capabilities_payload, get_capabilities, invalidate_capabilities
    from app.services.hw import sync
    from app.services.hw.registry_util import has_enabled_hw_instance
    monkeypatch.delenv("HW_DEMO_ENABLED", raising=False)
    invalidate_capabilities()
    caps = get_capabilities(force_refresh=True)
    assert not {"hw", "hw.dell", "hw.hpe", "hw_demo"} & set(caps)
    p = capabilities_payload()
    assert p["has_hw"] is False and p["hw_demo_active"] is False
    assert has_enabled_hw_instance() is False
    assert sync.run_all_due(db)["instances"] == 0
    assert hw_api.summary(db=db, _u=None)["enabled"] is False
    out = hw_api.list_servers(q="", health="", vendor="", matched="", form_factor="", limit=50, offset=0, db=db, _u=None)
    assert out.get("enabled") is False and out["servers"] == []


def test_veeam_real_does_not_suppress_hw_and_vice_versa(db, monkeypatch):
    """Capability has_real kategori bazlıdır: gerçek yedek sağlayıcısı HW demo'yu bastırmaz."""
    from app.models.integration_instance import IntegrationInstance
    from app.services.capabilities import capabilities_payload, invalidate_capabilities
    monkeypatch.setenv("HW_DEMO_ENABLED", "true")
    db.add(IntegrationInstance(category="backup", kind="veeam_vbr", label="v", endpoint="x", enabled=True,
                               last_status="ok", sync_interval_sec=3600))
    db.add(IntegrationInstance(category="hardware", kind="hw_demo", label="d", endpoint="demo", enabled=True,
                               last_status="ok", sync_interval_sec=900))
    db.commit()
    invalidate_capabilities()
    p = capabilities_payload()
    assert p["has_backup"] is True and p["hw_demo_active"] is True and p["has_hw"] is False


def test_demo_flag_off_is_inert(db, monkeypatch):
    from app.models.integration_instance import IntegrationInstance
    from app.services.capabilities import capabilities_payload, invalidate_capabilities
    from app.services.hw import sync
    from app.services.hw.demo_gate import hw_mode
    monkeypatch.delenv("HW_DEMO_ENABLED", raising=False)
    row = IntegrationInstance(category="hardware", kind="hw_demo", label="d", endpoint="demo", enabled=True,
                              last_status="never", sync_interval_sec=900)
    db.add(row)
    db.commit()
    invalidate_capabilities()
    assert hw_mode(db) == "none"
    assert capabilities_payload()["hw_demo_active"] is False
    assert sync.sync_instance(db, row, force=True).get("skipped") == "demo_disabled"


# ═══ 7) Senkron → DB → bulgular ═════════════════════════════════════════════════════════════════════════════════

def _real_sync(db):
    from app.services.hw import sync
    row = F.make_row(db)
    http, _ = F.http_for(F.ome_router(), "https://ome.example", "ome")
    res = sync.sync_instance(db, row, force=True, provider=DellOmeProvider(row, http=http))
    assert res["ok"] is True, res
    return row


def test_sync_persists_and_matches_and_findings(db):
    from app.models.hw import HwAlert, HwHostLink, HwServer, HwWarranty
    from app.models.server import Server
    from app.services.hw.findings_engine import hw_findings
    srv = Server(name="lin-db-02", hostname="lin-db-02", ip_address="10.0.0.2", hw_serial="XYZ9876")
    db.add(srv)
    db.commit()
    row = _real_sync(db)
    assert db.query(HwServer).filter(HwServer.instance_id == row.id).count() == 2
    assert db.query(HwAlert).count() == 1 and db.query(HwWarranty).count() == 1
    link = db.query(HwHostLink).one()
    assert link.target_kind == "server" and link.target_id == srv.id and link.method == "serial"
    ids = {d.check_id for d in hw_findings(db)}
    assert "hw.server.health_critical" in ids                        # OME_RACK Status=4000 → critical
    assert "hw.warranty.expired_prod" not in ids                     # eşleşen sunucu production değil
    # ikinci senkron idempotent
    from app.services.hw import sync
    http, _ = F.http_for(F.ome_router(), "https://ome.example", "ome")
    assert sync.sync_instance(db, row, force=True, provider=DellOmeProvider(row, http=http))["ok"]
    assert db.query(HwServer).count() == 2 and db.query(HwAlert).count() == 1


def test_demo_data_never_produces_findings(db, monkeypatch):
    from app.models.hw import HwServer
    from app.models.integration_instance import IntegrationInstance
    from app.services.capabilities import invalidate_capabilities
    from app.services.hw.findings_engine import hw_findings
    monkeypatch.setenv("HW_DEMO_ENABLED", "true")
    row = IntegrationInstance(category="hardware", kind="hw_demo", label="d", endpoint="demo", enabled=True,
                              last_status="ok", sync_interval_sec=900)
    db.add(row)
    db.commit()
    db.add(HwServer(instance_id=row.id, provider_ref="d1", vendor="dell", name="demo-1", health="critical"))
    db.commit()
    invalidate_capabilities()
    assert hw_findings(db) == []


# ═══ 8) RBAC ═════════════════════════════════════════════════════════════════════════════════════════════════════

def test_hw_routes_require_hardware_module():
    from app.core.module_policy import decide
    for p in ("/api/v1/hw/summary", "/api/v1/hw/servers", "/api/v1/hw/servers/by-target"):
        assert not decide(role="operator", modules=("linux", "windows", "integrations"), method="GET", path=p, query={}).allowed
        assert decide(role="operator", modules=("hardware",), method="GET", path=p, query={}).allowed
        assert decide(role="admin", modules=(), method="GET", path=p, query={}).allowed


def test_hardware_module_is_default_registered():
    from app.models.module import DEFAULT_MODULES
    assert any((m.get("id") if isinstance(m, dict) else m[0]) == "hardware" for m in DEFAULT_MODULES)


def test_servers_api_never_exposes_bmc_or_serial():
    from app.schemas.server import ServerResponse
    fields = set(ServerResponse.model_fields)
    assert not {f for f in fields if f.startswith("hw_") or "bmc" in f or "serial" in f}


def test_hw_integrations_router_is_admin_only():
    from app.api import hw_integrations
    assert hw_integrations.router.routes
    for r in hw_integrations.router.routes:
        calls = [d.call for d in r.dependant.dependencies]
        assert hw_integrations._admin in calls, r.path


# ═══ 9) Sohbet araçları ══════════════════════════════════════════════════════════════════════════════════════════

def test_chat_tools_hidden_without_capability(db, monkeypatch):
    from app.services.agent import tools as T
    from app.services.capabilities import invalidate_capabilities
    monkeypatch.delenv("HW_DEMO_ENABLED", raising=False)
    invalidate_capabilities()
    names = {s["function"]["name"] for s in T.tool_specs_read_only(None)}
    assert "hw_server_status" not in names and "hw_alerts_summary" not in names
    out = T.TOOLS["hw_server_status"].direct_handler(db, {}, {"hw_allowed": True})
    assert out["ok"] is False


def test_chat_tools_respect_module_and_leak_no_bmc(db):
    from app.services.agent import tools as T
    from app.services.agent.tools_hw import LLM_EGRESS_FIELDS
    _real_sync(db)
    tool = T.TOOLS["hw_server_status"]
    denied = tool.direct_handler(db, {}, {"hw_allowed": False})
    assert denied["ok"] is False and "servers" not in denied
    ok = tool.direct_handler(db, {}, {"hw_allowed": True})
    assert ok["ok"] is True and ok["total"] == 2
    blob = json.dumps(ok)
    for secret in ("10.20.30.41", "10.20.30.42", "ABC1234", "XYZ9876", "4.40.00.00", "X-Auth", "tok"):
        assert secret not in blob
    assert all(set(r) <= set(LLM_EGRESS_FIELDS) for r in ok["servers"])
    al = T.TOOLS["hw_alerts_summary"].direct_handler(db, {"hours": 24 * 365}, {"hw_allowed": True})
    assert al["ok"] is True and "10.20.30" not in json.dumps(al) and "Drive 3 failed" not in json.dumps(al)


def test_hw_intent_keywords():
    from app.services.agent.tools_hw import hw_intent
    assert hw_intent("iDRAC uyarısı olan sunucular") and hw_intent("garantisi biten blade'ler")
    assert not hw_intent("disk doluluk oranı nedir")


# ═══ 10) HTTP seviyesi (yapılandırma API + veri API) ═════════════════════════════════════════════════════════════

def _http_client(db, role="admin"):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import hw as hw_api, hw_integrations
    from app.core.auth import get_current_user
    from app.core.database import get_db
    app = FastAPI()
    app.include_router(hw_integrations.router, prefix="/integrations/hardware")
    app.include_router(hw_api.router, prefix="/hw")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=role, id=1, username="t")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_http_config_requires_admin(db):
    r = _http_client(db, "operator").get("/integrations/hardware/instances")
    assert r.status_code == 403


def test_http_create_never_returns_password_and_test_has_cooldown(db, monkeypatch):
    from app.services.hw import auth_guard as ag
    from app.services.hw.dell_ome import DellOmeProvider
    from app.services.integrations import registry as reg
    c = _http_client(db)
    body = {"kind": "dell_ome", "label": "ome-a", "endpoint": "ome.example", "username": "viewer", "password": "S3cret!x"}
    r = c.post("/integrations/hardware/instances", json=body)
    assert r.status_code == 200 and "S3cret!x" not in r.text and r.json()["has_credentials"] is True
    lst = c.get("/integrations/hardware/instances")
    assert "S3cret!x" not in lst.text and lst.json()["test_cooldown_sec"] == 30
    iid = r.json()["id"]

    calls = {"n": 0}

    class _P(DellOmeProvider):
        def _client(self):
            calls["n"] += 1
            http, _ = F.http_for(F.ome_router(), "https://ome.example", "ome")
            from app.services.hw.dell_ome import OmeClient
            from app.services.hw.creds import load_credentials
            u, p = load_credentials(self.row)
            return OmeClient(http, u, p)

    monkeypatch.setitem(reg._FACTORIES, "dell_ome", lambda inst: _P(inst))
    ag.reset_test_slot(f"i{iid}")
    t1 = c.post("/integrations/hardware/test", json={**body, "password": None, "instance_id": iid})
    assert t1.status_code == 200 and t1.json()["ok"] is True
    t2 = c.post("/integrations/hardware/test", json={**body, "password": None, "instance_id": iid})
    assert t2.status_code == 429                                      # 30 sn bekleme: ardışık deneme hesap kilitlemesin
    assert calls["n"] == 1
    ag.reset_test_slot(f"i{iid}")


def test_http_credential_change_halts_until_successful_test(db):
    c = _http_client(db)
    body = {"kind": "dell_ome", "label": "ome-b", "endpoint": "ome.example", "username": "viewer", "password": "pw1"}
    iid = c.post("/integrations/hardware/instances", json=body).json()["id"]
    r = c.put(f"/integrations/hardware/instances/{iid}", json={**body, "password": "pw2-typo"})
    j = r.json()
    assert j["auth_halted"] is True and j["auth_halt"]["kind"] == "changed"
    e = c.post(f"/integrations/hardware/instances/{iid}/enable", json={"enabled": True})
    assert e.status_code == 409                                       # kaydetmek tek başına sürdürmez; etkinleştirme de reddedilir
    s = c.post(f"/integrations/hardware/instances/{iid}/sync")
    assert s.status_code in (400, 409)


def test_http_data_api_after_sync(db):
    from app.models.server import Server
    srv = Server(name="lin-db-02", hostname="lin-db-02", ip_address="10.0.0.2", hw_serial="XYZ9876", server_type="PHYSICAL")
    db.add(srv)
    db.commit()
    _real_sync(db)
    c = _http_client(db)
    s = c.get("/hw/summary").json()
    assert s["enabled"] is True and s["total"] == 2 and s["matched"] == 1 and s["by_health"]["critical"] == 1
    t = c.get(f"/hw/servers/by-target?kind=server&id={srv.id}").json()
    assert t["available"] is True and t["server"]["bmc_ip"] == "10.20.30.42" and t["server"]["health"] == "critical"
    assert c.get("/hw/servers/by-target?kind=server&id=9999").json()["available"] is False
    assert c.get("/hw/servers?matched=no").json()["total"] == 1
    assert c.get("/hw/enclosures").json()["enclosures"][0]["name"] == "MX7000-A"
    g = c.get("/hw/alerts").json()["groups"]
    assert len(g) == 1 and g[0]["severity"] == "critical"
    assert c.get("/hw/unmatched").json()["enabled"] is True
    # GET dışındaki her yöntem veri API'sinde yok
    assert c.post("/hw/servers").status_code in (404, 405)
    assert c.delete("/hw/servers/1").status_code in (404, 405)
