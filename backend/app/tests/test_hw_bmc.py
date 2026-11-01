"""Faz 3b — Donanım Logları sekmesi (şasi alarmı), in-band ipmitool, BMC kimlik/uç nokta, Redfish.

Ağa/SSH'a/BMC'ye ÇIKMAZ (sahte oturum / sahte runner); DB testleri izole geçici DB'de. Kapanış kriterleri:
docs/plans/hw-providers.md › Faz 3b.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.models.infrastructure_report  # noqa: F401
from app.models.hw import (
    HwAlert, HwBmcEndpoint, HwBmcProfile, HwEnclosure, HwHostLink, HwLogEntry, HwServer,
)
from app.models.server import Server
from app.services.hw import bmc_creds as BC
from app.services.hw import bmc_endpoints as EP
from app.services.hw import bmc_logs
from app.services.hw import host_logs as HL
from app.services.hw import ipmi_inband as IP
from app.services.hw import redfish as RF
from app.tests import hw_fakes as F


@pytest.fixture()
def db(isolated_db):
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()
    yield isolated_db
    invalidate_capabilities()


def _now():
    return datetime.now(timezone.utc)


def _prof(db, scope="global", user="admin", pw="secret", vendor=None, instance_id=None, name="p", verify=False):
    p = HwBmcProfile(scope=scope, vendor=vendor, instance_id=instance_id, name=name, verify_tls=verify)
    BC.store(p, user, pw)
    db.add(p)
    db.commit()
    return p


# ═══ C) Kimlik çözümü (saf) ═════════════════════════════════════════════════════════════════════════════════════

def _P(id, scope, vendor=None, instance_id=None, cred=True):
    return SimpleNamespace(id=id, scope=scope, vendor=vendor, instance_id=instance_id, credential_ref=("x" if cred else None))


def test_resolve_priority_host_instance_vendor_global():
    g, v, i, h = _P(1, "global"), _P(2, "vendor", vendor="dell"), _P(3, "instance", instance_id=9), _P(4, "host")
    ep = SimpleNamespace(profile_id=4)
    assert BC.resolve(ep, vendor="dell", instance_id=9, profiles=[g, v, i, h]).level == "host"
    ep = SimpleNamespace(profile_id=None)
    assert BC.resolve(ep, vendor="dell", instance_id=9, profiles=[g, v, i, h]) == (i, "instance")
    assert BC.resolve(ep, vendor="dell", instance_id=7, profiles=[g, v, i, h]) == (v, "vendor")
    assert BC.resolve(ep, vendor="hpe", instance_id=7, profiles=[g, v, i, h]) == (g, "global")
    assert BC.resolve(ep, vendor=None, instance_id=None, profiles=[]) == (None, None)


def test_resolve_skips_profiles_without_credentials_and_never_chains():
    empty_inst = _P(3, "instance", instance_id=9, cred=False)
    g = _P(1, "global")
    r = BC.resolve(SimpleNamespace(profile_id=None), vendor="dell", instance_id=9, profiles=[empty_inst, g])
    assert r == (g, "global")                       # kimlik bilgisi boş seviye atlanır
    # çözümleme TEK profil döner: reddedilirse bir sonrakine geçme (zincir) API'si yok
    assert isinstance(BC.resolve(SimpleNamespace(profile_id=None), vendor="dell", instance_id=9, profiles=[g]), tuple)


def test_public_dict_never_contains_password(db):
    p = _prof(db, pw="TOPSECRET")
    d = BC.public_dict(p)
    assert "TOPSECRET" not in json.dumps(d) and d["has_password"] is True and d["username"] == "admin"
    assert "TOPSECRET" not in (p.credential_ref or "")          # şifreli saklanır


def test_store_keeps_password_when_blank(db):
    p = _prof(db, pw="one")
    BC.store(p, "newuser", None)
    assert BC.load(p) == ("newuser", "one")


# ═══ B) ipmitool ayrıştırma (saf) ═══════════════════════════════════════════════════════════════════════════════

SEL = """\
   1 | Pre-Init  |0000011921| Temperature #0x30 | Upper Critical going high | Asserted
   2 | 10/27/2026 | 12:00:00 | Power Supply #0x57 | Failure detected | Asserted
   3 | 10/27/2026 | 12:05:00 | Power Supply #0x57 | Failure detected | Deasserted
   4 | 10/27/2026 | 12:10:00 | Memory #0x01 | Correctable ECC | Asserted
   5 | 10/27/2026 | 12:11:00 | Memory #0x01 | Correctable ECC | Asserted
   6 | 10/27/2026 | 12:20:00 | System Boot Initiated #0x07 | Initiated by power up | Asserted
"""


def test_parse_sel_skips_preinit_and_reads_direction():
    recs = IP.parse_sel_elist(SEL)
    assert [r.rec_id for r in recs] == ["2", "3", "4", "5", "6"]
    assert recs[0].sensor == "Power Supply #0x57" and recs[0].direction == "Asserted"
    assert recs[1].direction == "Deasserted"


def test_items_deasserted_is_info_and_asserted_failure_is_critical():
    host_utc = datetime(2026, 10, 27, 12, 30, tzinfo=timezone.utc)
    bmc_now = datetime(2026, 10, 27, 12, 30, 5)
    items, reliable = IP.items_from_sel_text(SEL, bmc_now, host_utc, now=host_utc)
    assert reliable is True
    by = {i.message: i for i in items}
    assert by["Power Supply #0x57: Failure detected (Asserted)"].severity == "critical"
    assert by["Power Supply #0x57: Failure detected (Asserted)"].category == "power"
    assert by["Power Supply #0x57: Failure detected (Deasserted)"].severity == "info"      # düzeldi
    assert by["Memory #0x01: Correctable ECC (Asserted)"].severity == "warning"


@pytest.mark.parametrize("skew_min,expected_min", [(0, 0), (5, 0), (-12, 0), (180, 180), (183, 180), (-300, -300), (45, None), (40000, None)])
def test_clock_offset(skew_min, expected_min):
    host = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    off = IP.clock_offset(host.replace(tzinfo=None) + timedelta(minutes=skew_min), host)
    assert (None if off is None else int(off.total_seconds() // 60)) == expected_min
    assert IP.clock_offset(None, host) is None and IP.clock_offset(host.replace(tzinfo=None), None) is None


def test_timezone_offset_converts_to_utc():
    host_utc = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)
    bmc_now = datetime(2026, 10, 27, 12, 0, 0)                 # BMC yerel saat UTC+3
    text = "   2 | 10/27/2026 | 11:00:00 | Power Supply #0x57 | Failure detected | Asserted\n"
    items, reliable = IP.items_from_sel_text(text, bmc_now, host_utc, now=host_utc)
    assert reliable and items[0].ts == datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)


def test_unreliable_clock_caps_records_and_drops_timestamps():
    lines = "\n".join(f"{i:4d} | 01/01/2020 | 00:00:{i % 60:02d} | Fan #0x0{i % 9} | Failure detected | Asserted" for i in range(1, 60))
    items, reliable = IP.items_from_sel_text(lines, datetime(2020, 1, 1), datetime(2026, 10, 27, tzinfo=timezone.utc))
    assert reliable is False and len(items) <= IP.UNRELIABLE_CLOCK_MAX and all(i.ts is None for i in items)


def test_old_sel_records_beyond_retention_are_skipped():
    host_utc = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    text = ("   1 | 01/01/2024 | 00:00:00 | Power Supply #0x57 | Failure detected | Asserted\n"
            "   2 | 10/27/2026 | 11:00:00 | Fan #0x02 | Failure detected | Asserted\n")
    items, _ = IP.items_from_sel_text(text, datetime(2026, 10, 27, 12, 0, 1), host_utc, now=host_utc)
    assert [i.category for i in items] == ["thermal"]


def test_parse_mc_info_and_lan():
    assert IP.parse_mc_info("Manufacturer Name : Dell Inc.\n").vendor == "dell"
    assert IP.parse_mc_info("Manufacturer Name : Hewlett Packard Enterprise\n").vendor == "hpe"
    assert IP.parse_mc_info("Manufacturer Name : Supermicro\n").vendor == "other"
    assert IP.parse_mc_info("garbage") == (None, None)
    ok = "IP Address Source       : Static Address\nIP Address              : 10.20.30.40\n"
    assert IP.parse_lan(ok) == {"ip": "10.20.30.40", "source": "Static Address"}
    for bad in ("IP Address : 0.0.0.0", "IP Address : 255.255.255.255", "IP Address : 127.0.0.1", "IP Address : 300.1.1.1", "x"):
        assert IP.parse_lan(bad) is None


def test_device_state_detection():
    assert IP.device_state({"STATE": "no_ipmitool"}) == "no_ipmitool"
    assert IP.device_state({"MC": "Could not open device at /dev/ipmi0", "HOSTUTC": "1"}) == "no_device"
    assert IP.device_state({"MC": "sudo: a password is required", "HOSTUTC": "1"}) == "no_sudo"
    assert IP.device_state({"MC": "Manufacturer Name : Dell", "SEL": "", "HOSTUTC": "1"}) == "ok"


def test_script_uses_only_allowlisted_readonly_ipmitool_commands():
    for want_lan in (False, True):
        script = IP.build_script(want_lan)
        found = {tuple(m) for m in re.findall(r"ipmitool\s+(\w+)\s+(\w+)", script)}
        assert found and found <= IP.ALLOWED, found
        low = script.lower()
        for bad in IP.FORBIDDEN_WORDS:
            assert bad not in low, bad
        assert "sudo -n" in script and "sudo -S" not in script         # parola sorulmaz
    assert "lan print" not in IP.build_script(False) and "lan print" in IP.build_script(True)


# ═══ B) in-band toplama (DB) ════════════════════════════════════════════════════════════════════════════════════

def _linux(db, name, ip, *, physical=True, os_type="linux", ai=True):
    s = Server(name=name, hostname=name, ip_address=ip, server_type="PHYSICAL" if physical else "VIRTUAL", os_type=os_type,
               ai_ready=ai, connection_config={"username": "root", "password": "pw"})
    db.add(s)
    db.commit()
    return s


def _runner_text(host_utc, with_lan=True, vendor="Dell Inc."):
    now = _now()
    d = now.strftime("%m/%d/%Y")
    t1 = (now - timedelta(minutes=30)).strftime("%H:%M:%S")
    parts = [f"##HOSTUTC={int(host_utc.timestamp())}", "##MC", f"Manufacturer Name : {vendor}",
             "##SELTIME", now.strftime("%m/%d/%Y %H:%M:%S"),
             "##SEL", f"   1 | {d} | {t1} | Power Supply #0x57 | Failure detected | Asserted"]
    if with_lan:
        parts += ["##LAN 1", "IP Address Source : Static Address", "IP Address : 10.9.8.7"]
    return "\n".join(parts) + "\n##END"


def test_inband_ingests_sel_and_discovers_ip(db):
    s = _linux(db, "phys-1", "10.0.0.11")
    now = _now()
    out = IP.collect_inband(db, now, runner=lambda creds, script: (True, _runner_text(now)))
    assert out["ok"] == 1 and out["entries"] == 1 and out["ips"] == 1
    row = db.query(HwLogEntry).filter(HwLogEntry.source == "ipmi_sel").one()
    assert (row.target_kind, row.target_id, row.severity, row.category) == ("server", s.id, "critical", "power")
    ep = db.query(HwBmcEndpoint).filter(HwBmcEndpoint.target_kind == "server", HwBmcEndpoint.target_id == s.id).one()
    assert (ep.bmc_ip, ep.ip_source, ep.ipmi_status, ep.vendor) == ("10.9.8.7", "discovered", "ok", "dell")
    # ikinci tur: satır sayısı değişmez (tekilleştirme)
    IP.collect_inband(db, now, runner=lambda creds, script: (True, _runner_text(now)))
    assert db.query(HwLogEntry).filter(HwLogEntry.source == "ipmi_sel").count() == 1


def test_inband_never_overrides_manual_ip_and_skips_lan_probe(db):
    s = _linux(db, "phys-2", "10.0.0.12")
    ep = EP.ensure_endpoint(db, "server", s.id)
    ep.bmc_ip, ep.ip_source = "192.168.1.5", "manual"
    db.commit()
    scripts = []

    def run(creds, script):
        scripts.append(script)
        return True, _runner_text(_now())
    IP.collect_inband(db, _now(), runner=run)
    db.refresh(ep)
    assert (ep.bmc_ip, ep.ip_source) == ("192.168.1.5", "manual")
    assert "lan print" not in scripts[0]                 # manuel IP varken lan print çalıştırılmaz


def test_inband_states_are_not_errors_and_virtual_windows_skipped(db):
    a = _linux(db, "no-tool", "10.0.0.21")
    _linux(db, "vm-1", "10.0.0.22", physical=False)
    _linux(db, "win-1", "10.0.0.23", os_type="windows")
    out = IP.collect_inband(db, _now(), runner=lambda c, s: (True, "##STATE=no_ipmitool\n"))
    assert out["hosts"] == 1 and out["errors"] == [] and out["skipped_state"] == {"no_ipmitool": 1}
    ep = db.query(HwBmcEndpoint).filter(HwBmcEndpoint.target_id == a.id).one()
    assert ep.ipmi_status == "no_ipmitool"
    assert db.query(HwLogEntry).count() == 0


def test_inband_ssh_failure_marks_error_but_continues(db):
    a, b = _linux(db, "a", "10.0.0.31"), _linux(db, "b", "10.0.0.32")
    now = _now()

    def run(creds, script):
        return (False, "") if creds["host"] == "10.0.0.31" else (True, _runner_text(now))
    out = IP.collect_inband(db, now, runner=run)
    assert out["ok"] == 1 and len(out["errors"]) == 1
    st = {e.target_id: e.ipmi_status for e in db.query(HwBmcEndpoint).all()}
    assert st[a.id] == "error" and st[b.id] == "ok"


def _flags(monkeypatch, host=False, ipmi=False, bmc=False):
    monkeypatch.setattr(HL, "enabled", lambda: host)
    monkeypatch.setattr(IP, "enabled", lambda: ipmi)
    monkeypatch.setattr(bmc_logs, "enabled", lambda: bmc)


def test_flags_default_off_and_sync_noop(db, monkeypatch):
    from app.services.runtime_settings import ADVANCED_SCHEMA
    for k in ("hw_ipmi_inband_enabled", "hw_bmc_logs_enabled", "hw_host_logs_enabled"):
        assert ADVANCED_SCHEMA[k]["default"] is False
    _flags(monkeypatch)
    called = []
    out = HL.run_host_log_sync(db, ipmi_runner=lambda c, s: called.append(1) or (True, ""),
                               bmc_factory=lambda *a: called.append(2))
    assert out == {"skipped": "disabled"} and not called and HL.any_enabled() is False
    _flags(monkeypatch, bmc=True)
    assert HL.any_enabled() is True


def test_sync_runs_ipmi_when_only_that_flag_is_on(db, monkeypatch):
    _linux(db, "p", "10.0.0.41")
    _flags(monkeypatch, ipmi=True)
    now = _now()
    out = HL.run_host_log_sync(db, ipmi_runner=lambda c, s: (True, _runner_text(now)))
    assert "esxi" not in out and "projection" not in out         # 3a bayrağı kapalı → ESXi/yansıtma yok
    assert out["ipmi"]["ok"] == 1


# ═══ D) Redfish (sahte oturum) ══════════════════════════════════════════════════════════════════════════════════

class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body

    def json(self):
        if self._b is None:
            raise ValueError("no json")
        return self._b


class FakeBmc:
    """requests.Session yerine: iDRAC benzeri Redfish ağacı. Kimlik: Basic (user/pw); servis kökü kimliksiz."""

    def __init__(self, user="ro", pw="pw", tree=None, down=False, collapsed=False):
        import base64
        self.expect = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
        self.calls = []                      # (method, path, params, authed)
        self.down, self.collapsed = down, collapsed
        now = _now()
        stamp = lambda m: (now - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%S+00:00")  # noqa: E731
        sel = [
            {"Id": "1", "Created": stamp(30), "Severity": "Critical", "Message": "The power supply 1 has failed."},
            {"Id": "2", "Created": stamp(20), "Severity": "OK", "Message": "The power supply 1 has been restored."},
            {"Id": "3", "Created": stamp(10), "Severity": "Warning", "Message": "Correctable memory error rate exceeded for DIMM A1."},
            {"Id": "4", "Created": (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"), "Severity": "Critical",
             "Message": "Old critical event beyond retention."},
        ]
        lc = [
            {"Id": "9", "Created": stamp(5), "Severity": "OK", "Message": "Successfully logged in using root, from 10.1.1.1 and GUI."},
            {"Id": "10", "Created": stamp(4), "Severity": "Critical", "Message": "Fan 2 is not responding."},
        ]
        self.entries = {"Sel": sel, "Lclog": lc}
        self.root = {"RedfishVersion": "1.11.0", "Vendor": "Dell", "@odata.id": "/redfish/v1",
                     "Managers": {"@odata.id": "/redfish/v1/Managers"}, "Systems": {"@odata.id": "/redfish/v1/Systems"}}

    def close(self):
        pass

    def _route(self, path):
        p = path.rstrip("/")
        if p == "/redfish/v1":
            return 200, self.root, False
        if p == "/redfish/v1/Managers":
            return 200, {"Members": [{"@odata.id": "/redfish/v1/Managers/iDRAC.Embedded.1"}]}, True
        if p == "/redfish/v1/Systems":
            return 200, {"Members": [{"@odata.id": "/redfish/v1/Systems/System.Embedded.1"}]}, True
        if p == "/redfish/v1/Managers/iDRAC.Embedded.1":
            return 200, {"LogServices": {"@odata.id": "/redfish/v1/Managers/iDRAC.Embedded.1/LogServices"}}, True
        if p == "/redfish/v1/Systems/System.Embedded.1":
            return 200, {"Name": "System"}, True                                   # LogServices yok → atlanır
        if p == "/redfish/v1/Managers/iDRAC.Embedded.1/LogServices":
            base = "/redfish/v1/Managers/iDRAC.Embedded.1/LogServices/"
            return 200, {"Members": [{"@odata.id": base + "Sel"}, {"@odata.id": base + "Lclog"}]}, True
        m = re.match(r"^/redfish/v1/Managers/iDRAC\.Embedded\.1/LogServices/(Sel|Lclog)/Entries(?:/(\d+))?$", p)
        if m:
            ents = self.entries[m.group(1)]
            if m.group(2):
                hit = [e for e in ents if e["Id"] == m.group(2)]
                return (200, hit[0], True) if hit else (404, {}, True)
            if self.collapsed:
                base = f"/redfish/v1/Managers/iDRAC.Embedded.1/LogServices/{m.group(1)}/Entries/"
                return 200, {"Members@odata.count": len(ents), "Members": [{"@odata.id": base + e["Id"]} for e in ents]}, True
            return 200, {"Members@odata.count": len(ents), "Members": ents}, True
        return 404, {}, True

    def request(self, method, url, params=None, json=None, headers=None, verify=None, timeout=None, allow_redirects=None):
        from urllib.parse import urlparse
        path = urlparse(url).path
        authed = "Authorization" in (headers or {})
        self.calls.append((method, path, params, authed))
        if self.down:
            from requests.exceptions import ConnectionError
            raise ConnectionError("down")
        code, body, needs_auth = self._route(path)
        if needs_auth and (headers or {}).get("Authorization") != self.expect:
            return _Resp(401, {})
        return _Resp(code, body)


def _rf(bmc: FakeBmc, user="ro", pw="pw"):
    return RF.RedfishClient("10.9.8.7", user, pw, verify=False, session=bmc)


def test_redfish_collects_sel_and_lclog_with_severity_from_redfish():
    bmc = FakeBmc()
    res = _rf(bmc).collect(_now())
    assert sorted(res.services) == ["Lclog", "Sel"] and res.bmc["vendor"] == "Dell"
    msgs = {i.message: i for i in res.items}
    assert msgs["The power supply 1 has failed."].severity == "critical" and msgs["The power supply 1 has failed."].category == "power"
    assert msgs["The power supply 1 has been restored."].severity == "info"          # Redfish OK → info (sınıflandırıcıya DEĞİL)
    assert msgs["Correctable memory error rate exceeded for DIMM A1."].severity == "warning"
    assert "Old critical event beyond retention." not in msgs                        # saklama penceresi
    assert "Fan 2 is not responding." in msgs                                        # Lclog'dan Critical alındı
    assert not any("logged in" in m for m in msgs)                                   # Lclog gürültüsü (OK + donanım değil) elendi
    assert all(i.ts is not None and i.ts.tzinfo is not None for i in res.items)


def test_redfish_is_get_only_and_never_touches_actions_or_sessions():
    bmc = FakeBmc()
    _rf(bmc).collect(_now())
    assert {m for m, *_ in bmc.calls} == {"GET"}
    assert not any("/Actions" in p or "Sessions" in p or "AccountService" in p for _m, p, *_ in bmc.calls)
    # izin listesi dışı yollar ağa çıkmadan reddedilir
    from app.services.hw.http import HwApiError
    c = _rf(FakeBmc())
    for bad in ("/redfish/v1/Managers/1/Actions/Manager.Reset", "/redfish/v1/SessionService/Sessions", "/redfish/v1/AccountService/Accounts",
                "/redfish/v1/Systems/1/Actions/ComputerSystem.Reset", "/api/whatever"):
        with pytest.raises(HwApiError) as ei:
            c.http.get(bad)
        assert ei.value.kind == "readonly"
    assert all(method == "GET" for method, *_ in c.http.s.calls)                     # reddedilenler ağa gitmedi
    assert len(c.http.s.calls) == 0


def test_redfish_bad_credentials_single_authenticated_attempt():
    bmc = FakeBmc(user="ro", pw="pw")
    with pytest.raises(RF.AuthHalt) as ei:
        _rf(bmc, pw="WRONG").collect(_now())
    assert ei.value.kind == "auth"
    authed = [c for c in bmc.calls if c[3]]
    assert len(authed) == 1                          # TEK kimlikli istek; yeniden deneme YOK
    assert "WRONG" not in str(ei.value.message)


def test_redfish_unreachable_and_unsupported():
    with pytest.raises(RF.Unreachable):
        _rf(FakeBmc(down=True)).collect(_now())
    b = FakeBmc()
    b.root = {"nothing": 1}
    with pytest.raises(RF.Unsupported):
        _rf(b).collect(_now())


def test_redfish_collapsed_members_are_fetched_individually_with_cap():
    bmc = FakeBmc(collapsed=True)
    res = _rf(bmc).collect(_now())
    assert any(i.message == "The power supply 1 has failed." for i in res.items)


def test_redfish_test_uses_root_and_managers_only():
    bmc = FakeBmc()
    info = _rf(bmc).test()
    assert info["redfish"] == "1.11.0"
    assert [p for _m, p, *_ in bmc.calls] == ["/redfish/v1/", "/redfish/v1/Managers"]
    assert sum(1 for c in bmc.calls if c[3]) == 1


@pytest.mark.parametrize("v,ok", [("2026-10-27T10:11:12+03:00", datetime(2026, 10, 27, 7, 11, 12, tzinfo=timezone.utc)),
                                  ("2026-10-27T10:11:12Z", datetime(2026, 10, 27, 10, 11, 12, tzinfo=timezone.utc)),
                                  ("2026-10-27T10:11:12", datetime(2026, 10, 27, 10, 11, 12, tzinfo=timezone.utc)),
                                  ("2026-10-27T10:11:12.1234567+00:00", datetime(2026, 10, 27, 10, 11, 12, 123456, tzinfo=timezone.utc)),
                                  ("garbage", None), (None, None)])
def test_parse_created(v, ok):
    assert RF.parse_created(v) == ok


# ═══ D) Orkestrasyon (DB) ═══════════════════════════════════════════════════════════════════════════════════════

def _hw(db, inst, name, ip, vendor="dell", ref=None):
    h = HwServer(instance_id=inst.id, provider_ref=ref or name, vendor=vendor, name=name, bmc_ip=ip, serial=name.upper())
    db.add(h)
    db.commit()
    return h


def _factory(bmcs):
    created = []

    def f(ip, user, pw, verify):
        c = RF.RedfishClient(ip, user, pw, verify=verify, session=bmcs[ip])
        created.append(ip)
        return c
    f.created = created
    return f


def test_collect_bmc_ingests_to_hw_target_and_status_ok(db):
    inst = F.make_row(db)
    h = _hw(db, inst, "blade1", "10.1.1.1")
    _prof(db, "global", "ro", "pw")
    bmcs = {"10.1.1.1": FakeBmc()}
    out = bmc_logs.collect_bmc(db, _now(), client_factory=_factory(bmcs))
    assert out["ok"] == 1 and out["entries"] >= 3
    ep = db.query(HwBmcEndpoint).filter_by(target_kind="hw", target_id=h.id).one()
    assert (ep.status, ep.auth_halted, ep.ip_source) == ("ok", False, "portal")
    rows = db.query(HwLogEntry).filter(HwLogEntry.source == "bmc_redfish").all()
    assert rows and all((r.target_kind, r.target_id) == ("hw", h.id) for r in rows)


def test_collect_bmc_writes_to_linked_host_target(db):
    inst = F.make_row(db)
    h = _hw(db, inst, "rack1", "10.1.1.2")
    srv = _linux(db, "lin1", "10.0.0.50")
    db.add(HwHostLink(hw_server_id=h.id, target_kind="server", target_id=srv.id, method="serial", confidence="exact"))
    db.commit()
    _prof(db, "global", "ro", "pw")
    bmc_logs.collect_bmc(db, _now(), client_factory=_factory({"10.1.1.2": FakeBmc()}))
    rows = db.query(HwLogEntry).filter(HwLogEntry.source == "bmc_redfish").all()
    assert rows and all((r.target_kind, r.target_id) == ("server", srv.id) for r in rows)
    assert EP.sync_endpoints(db)["created"] == 0                      # bağlı sunucu için ayrı 'server' uç noktası açılmadı


def test_auth_failure_stops_group_no_chain_no_retry(db):
    inst = F.make_row(db)
    hs = [_hw(db, inst, f"b{i}", f"10.2.0.{i}") for i in range(1, 4)]
    _prof(db, "global", "ro", "WRONG")                             # tüm uç noktalar aynı (global) profil
    bmcs = {f"10.2.0.{i}": FakeBmc(user="ro", pw="pw") for i in range(1, 4)}
    fac = _factory(bmcs)
    out = bmc_logs.collect_bmc(db, _now(), client_factory=fac)
    assert out["auth_failed"] == 1 and out["skipped_group"] == 2 and out["ok"] == 0
    assert len(fac.created) == 1                                   # kanarya dışında HİÇ bağlanılmadı
    eps = {e.target_id: e for e in db.query(HwBmcEndpoint).all()}
    assert eps[hs[0].id].status == "auth_failed" and eps[hs[0].id].auth_halted is True
    assert eps[hs[1].id].auth_halted is False
    # sonraki tur: durdurulmuş uç nokta ATLANIR (yeni deneme yok); kalanlardan yalnız biri denenir
    fac2 = _factory(bmcs)
    out2 = bmc_logs.collect_bmc(db, _now(), client_factory=fac2)
    assert out2["halted"] == 1 and len(fac2.created) == 1
    assert "10.2.0.1" not in fac2.created


def test_no_ip_and_no_cred_never_connect(db):
    inst = F.make_row(db)
    _hw(db, inst, "noip", None)
    _hw(db, inst, "nocred", "10.3.0.1")
    fac = _factory({})
    out = bmc_logs.collect_bmc(db, _now(), client_factory=fac)
    assert out["no_ip"] == 1 and out["no_cred"] == 1 and fac.created == []


def test_disabled_endpoint_is_not_contacted(db):
    inst = F.make_row(db)
    h = _hw(db, inst, "off", "10.4.0.1")
    _prof(db, "global", "ro", "pw")
    EP.sync_endpoints(db)
    db.query(HwBmcEndpoint).filter_by(target_id=h.id).one().enabled = False
    db.commit()
    fac = _factory({"10.4.0.1": FakeBmc()})
    out = bmc_logs.collect_bmc(db, _now(), client_factory=fac)
    assert out["endpoints"] == 0 and fac.created == []


def test_instance_profile_beats_global_and_host_beats_instance(db):
    inst = F.make_row(db)
    h = _hw(db, inst, "x", "10.5.0.1")
    _prof(db, "global", "ro", "WRONG-GLOBAL")
    _prof(db, "instance", "ro", "pw", instance_id=inst.id)
    out = bmc_logs.collect_bmc(db, _now(), client_factory=_factory({"10.5.0.1": FakeBmc()}))
    assert out["ok"] == 1                                         # portal profili doğru → global denenmedi
    ep = db.query(HwBmcEndpoint).filter_by(target_id=h.id).one()
    hp = _prof(db, "host", "other", "nope", name="özel")
    ep.profile_id = hp.id
    ep.auth_halted = False
    db.commit()
    out2 = bmc_logs.collect_bmc(db, _now(), client_factory=_factory({"10.5.0.1": FakeBmc()}))
    assert out2["auth_failed"] == 1                               # host profili kazandı (yanlış) → zincirleme yok


def test_test_endpoint_single_attempt_and_clears_halt_only_on_success(db):
    inst = F.make_row(db)
    h = _hw(db, inst, "t", "10.6.0.1")
    _prof(db, "global", "ro", "WRONG")
    EP.sync_endpoints(db)
    ep = db.query(HwBmcEndpoint).filter_by(target_id=h.id).one()
    bmc = FakeBmc()
    r = bmc_logs.test_endpoint(db, ep, client_factory=lambda ip, u, p, v: RF.RedfishClient(ip, u, p, verify=v, session=bmc))
    assert r["ok"] is False and r["status"] == "auth_failed" and ep.auth_halted is True
    assert sum(1 for c in bmc.calls if c[3]) == 1
    db.query(HwBmcProfile).delete()
    db.commit()
    _prof(db, "global", "ro", "pw")
    bmc2 = FakeBmc()
    r2 = bmc_logs.test_endpoint(db, ep, client_factory=lambda ip, u, p, v: RF.RedfishClient(ip, u, p, verify=v, session=bmc2))
    assert r2["ok"] is True and ep.auth_halted is False and ep.status == "ok"
    # IP/kimlik yoksa ağa çıkmadan açıklama
    ep.bmc_ip = None
    assert bmc_logs.test_endpoint(db, ep)["status"] == "no_ip"


def test_unreachable_does_not_halt_and_keeps_old_data(db):
    inst = F.make_row(db)
    h = _hw(db, inst, "u", "10.7.0.1")
    _prof(db, "global", "ro", "pw")
    bmc_logs.collect_bmc(db, _now(), client_factory=_factory({"10.7.0.1": FakeBmc()}))
    n = db.query(HwLogEntry).count()
    out = bmc_logs.collect_bmc(db, _now(), client_factory=_factory({"10.7.0.1": FakeBmc(down=True)}))
    ep = db.query(HwBmcEndpoint).filter_by(target_id=h.id).one()
    assert out["unreachable"] == 1 and ep.status == "unreachable" and ep.auth_halted is False
    assert db.query(HwLogEntry).count() == n                        # mevcut veri silinmedi


def test_endpoint_sync_prefers_manual_and_cleans_orphans(db):
    inst = F.make_row(db)
    h = _hw(db, inst, "m", "10.8.0.1")
    EP.sync_endpoints(db)
    ep = db.query(HwBmcEndpoint).filter_by(target_id=h.id).one()
    ep.bmc_ip, ep.ip_source = "172.16.0.9", "manual"
    h.bmc_ip = "10.8.0.99"
    db.commit()
    EP.sync_endpoints(db)
    db.refresh(ep)
    assert (ep.bmc_ip, ep.ip_source) == ("172.16.0.9", "manual")          # manuel > portal
    db.delete(h)
    db.commit()
    assert EP.sync_endpoints(db)["removed"] == 1


# ═══ Kaynak kaydı + yasak uçlar ═════════════════════════════════════════════════════════════════════════════════

def test_redfish_paths_are_documented_and_forbidden_ones_rejected():
    from pathlib import Path
    from app.services.hw import endpoints as ep
    doc = Path(__file__).resolve().parents[3] / "docs" / "plans" / "hw-api-sources.md"
    if not doc.exists():
        pytest.skip("docs/plans yok (yalnız repo kökünde çalışır)")
    text = doc.read_text(encoding="utf-8")
    for frag in ("/redfish/v1/", "LogServices", "Entries", "Managers", "Systems", "Actions", "SessionService/Sessions",
                 "ipmitool sel elist", "ipmitool mc info", "ipmitool sel time get", "ipmitool lan print"):
        assert frag in text, frag
    assert ep.allowed("redfish", "GET", "/redfish/v1/Managers/1/LogServices/Sel/Entries")
    assert ep.allowed("redfish", "GET", "/redfish/v1/Systems/1/LogServices/IML/Entries/")
    for bad in ("/redfish/v1/Managers/1/Actions/Manager.Reset", "/redfish/v1/SessionService/Sessions",
                "/redfish/v1/AccountService/Accounts", "/redfish/v1/Managers/1/NetworkProtocol", "/rest/server-hardware"):
        assert not ep.allowed("redfish", "GET", bad), bad
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert not ep.allowed("redfish", method, "/redfish/v1/Managers/1/LogServices/Sel/Actions/LogService.ClearLog")
        assert not ep.allowed("redfish", method, "/redfish/v1/SessionService/Sessions")
