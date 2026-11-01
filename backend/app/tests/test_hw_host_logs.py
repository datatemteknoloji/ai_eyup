"""Faz 3a — host donanım logları (ESXi SEL/vmkernel, Linux/Windows). Ağa ÇIKMAZ; DB testleri izole geçici DB'de.

Kapanış kriterleri: docs/plans/hw-providers.md › Faz 3a.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.models.infrastructure_report  # noqa: F401
from app.models.event import SystemEvent
from app.models.hw import HwLogEntry
from app.models.server import Server
from app.services.hw import host_log_rules as R
from app.services.hw import host_logs as HL


@pytest.fixture()
def db(isolated_db):
    yield isolated_db


# ═══ 2) Sınıflandırıcı (saf) ═════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("line,cat,sev", [
    ("2026-10-27T09:12:33.123Z cpu5:2097234)WARNING: MCE: 1234: Machine Check Exception: uncorrectable", "cpu", "critical"),
    ("mce: [Hardware Error]: Machine check events logged", "cpu", "warning"),
    ("EDAC MC0: 1 CE memory read error on CPU_SrcID#0_Ha#0_Chan#1_DIMM#0", "memory", "warning"),
    ("EDAC MC0: 1 UE memory read error on CPU_SrcID#0_Ha#0_Chan#1_DIMM#0", "memory", "critical"),
    ("Correctable memory error logged on DIMM A1", "memory", "warning"),
    ("Uncorrectable memory error detected on DIMM B3", "memory", "critical"),
    ("Power Supply 2 Failure detected", "power", "critical"),
    ("Redundancy lost for Power Supply", "power", "critical"),
    ("CPU3: Core temperature above threshold, cpu clock throttled", "thermal", "warning"),
    ("Fan 3 failed", "thermal", "critical"),
    ("pcieport 0000:00:1c.0: AER: Uncorrected (Fatal) error received: 0000:00:1c.0", "pcie", "critical"),
    ("pcieport 0000:00:1c.0: AER: Corrected error received: 0000:00:1c.0", "pcie", "warning"),
    ("smartd[812]: Device: /dev/sda [SAT], FAILED SMART self-check. BACK UP DATA NOW!", "storage", "critical"),
    ("nvme nvme0: I/O 123 QID 4 timeout, aborting", "storage", "warning"),
    ("ata3.00: exception Emask 0x0 SAct 0x0 SErr 0x0 action 0x6 frozen", "storage", "warning"),
    ("2026-10-27T09:12:33.123Z cpu1:2097234)WARNING: NMP: nmp_ThrottleLogForDevice: Cmd 0x28 to dev naa.600 failed H:0x0 D:0x2 P:0x0 Valid sense data: 0x3 0x11 0x0", "storage", "critical"),
    ("vmnic3 Link Down", "network", "warning"),
    ("2026-10-27T09:12:33.123Z cpu0:2098173)WARNING: LinNet: netdev_watchdog:3675: NETDEV WATCHDOG: vmnic2: transmit timed out", "network", "warning"),
    ("2026-10-27T09:12:33.123Z cpu1:2097234)ScsiDeviceIO: 3449: Cmd(0x45d4c) 0x28 to dev \"naa.600\" failed H:0x0 D:0x2 P:0x0 Valid sense data: 0x4 0x44 0x0.", "storage", "critical"),
    ("ipmi_si: error communicating with BMC", "platform", "critical"),
])
def test_classify_text_known_patterns(line, cat, sev):
    c = R.classify_text(line)
    assert c is not None, line
    assert (c.category, c.severity) == (cat, sev), (line, c)


@pytest.mark.parametrize("line", [
    "systemd[1]: Started Daily apt download activities.",
    "sshd[123]: Accepted publickey for root from 10.0.0.5 port 4242",
    "Out of memory: Killed process 4321 (java)",                      # OOM = bellek baskısı, DONANIM değil
    "2026-10-27T09:12:33.123Z cpu2:2097234)NetPort: 1234: enabled port 0x4000002",
    "kernel: nf_conntrack: table full, dropping packet",
    # ESXi'nin her satırdaki `cpuN:` dünya öneki ve çok yaygın zararsız SCSI sense kodları gürültü ÜRETMEMELİ
    "2026-10-27T09:12:33.123Z cpu1:2097234)ScsiDeviceIO: 3449: Cmd(0x45d4c) 0x1a, CmdSN 0x6 from world 0 to dev \"naa.600\" failed H:0x0 D:0x2 P:0x0 Valid sense data: 0x5 0x24 0x0.",
    "2026-10-27T09:12:33.123Z cpu1:2097234)ScsiDeviceIO: 3449: Cmd(0x45d4c) 0x25, CmdSN 0x7 to dev \"naa.600\" failed H:0x0 D:0x2 P:0x0 Valid sense data: 0x2 0x3a 0x0.",
    "2026-10-27T09:12:33.123Z cpu3:2097234)VSCSI: 1234: handle 8192(vscsi0:0):Destroying Device",
    "2026-10-27T09:12:33.123Z cpu5:2097234)WARNING: ThrottleLog: rate limiter throttled 12 messages",
    "short",
    "",
])
def test_classify_text_ignores_unrelated_noise(line):
    assert R.classify_text(line) is None, line


def test_memory_ce_is_warning_ue_is_critical():
    assert R.classify_text("EDAC MC0: 3 CE memory error").severity == "warning"
    assert R.classify_text("EDAC MC0: 1 UE memory error").severity == "critical"


def test_sel_always_hardware_with_heuristic():
    assert R.classify_sel("Temperature sensor 1 Upper Critical - going high").severity == "critical"
    assert R.classify_sel("Drive Slot 4: predictive failure asserted").category == "storage"
    unknown = R.classify_sel("Chassis cover opened")
    assert unknown.category == "platform"
    assert R.classify_sel("Session audit logged").severity == "info"


@pytest.mark.parametrize("prov,eid,msg,cat,sev", [
    ("Microsoft-Windows-WHEA-Logger", 18, "A fatal hardware error has occurred.", "cpu", "critical"),
    ("Microsoft-Windows-WHEA-Logger", 17, "A corrected hardware error has occurred.", "pcie", "warning"),
    ("Microsoft-Windows-WHEA-Logger", 47, "A corrected hardware error has occurred (memory).", "memory", "warning"),
    ("Microsoft-Windows-Kernel-Power", 41, "The system has rebooted without cleanly shutting down first.", "platform", "critical"),
    ("Microsoft-Windows-Kernel-Processor-Power", 37, "The speed of processor 0 is being limited by system firmware.", "thermal", "warning"),
    ("disk", 7, "The device, \\Device\\Harddisk1\\DR1, has a bad block.", "storage", "critical"),
    ("stornvme", 129, "Reset to device, \\Device\\RaidPort0, was issued.", "storage", "warning"),
])
def test_classify_windows(prov, eid, msg, cat, sev):
    c = R.classify_windows(prov, eid, msg)
    assert c is not None and (c.category, c.severity) == (cat, sev), c


def test_windows_unrelated_provider_not_classified():
    assert R.classify_windows("Service Control Manager", 7036, "The Print Spooler service entered the running state.") is None
    assert R.classify_windows("Microsoft-Windows-Kernel-Power", 999, "Some unrelated power message.") is None


def test_event_key_ignores_timestamps_numbers_and_ips():
    a = "2026-10-27T09:12:33.123Z cpu5:2097234)WARNING: NMP: dev naa.600abc failed H:0x0 D:0x2 from 10.0.0.1"
    b = "2026-10-27T10:55:01.999Z cpu9:2097999)WARNING: NMP: dev naa.600abc failed H:0x0 D:0x2 from 10.9.9.9"
    assert R.event_key("esxi_vmkernel", a) == R.event_key("esxi_vmkernel", b)
    assert R.event_key("esxi_vmkernel", a) != R.event_key("linux_journal", a)
    assert R.event_key("esxi_vmkernel", a) != R.event_key("esxi_vmkernel", "totally different hardware message")


def test_parse_ts_and_mask():
    t = R.parse_ts("2026-10-27T09:12:33.123Z cpu5:1)WARNING: x")
    assert t == datetime(2026, 10, 27, 9, 12, 33, 123000, tzinfo=timezone.utc)
    assert R.parse_ts("2026-10-27 09:12:33") == datetime(2026, 10, 27, 9, 12, 33, tzinfo=timezone.utc)
    assert R.parse_ts("no timestamp here") is None and R.parse_ts(None) is None
    m = R.mask_text("link 10.20.30.42 mac 00:11:22:33:44:55 dev naa.6000c29aabbccdd uuid 123e4567-e89b-12d3-a456-426614174000")
    for secret in ("10.20.30.42", "00:11:22:33:44:55", "naa.6000c29aabbccdd", "123e4567-e89b-12d3-a456-426614174000"):
        assert secret not in m


# ═══ 3) Tekilleştirme (DB) ═══════════════════════════════════════════════════════════════════════════════════════

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _items(n=3, base=None, msg="EDAC MC0: 1 CE memory read error on DIMM#0"):
    base = base or (NOW - timedelta(minutes=30))
    return [HL.Item(base + timedelta(minutes=i), "warning", "memory", msg) for i in range(n)]


def test_ingest_lines_dedupes_and_is_idempotent(db):
    items = _items(3)
    HL.ingest_lines(db, "esxi", 5, "esxi_vmkernel", items, NOW)
    HL.ingest_lines(db, "esxi", 5, "esxi_vmkernel", items, NOW)           # aynı satırlar yeniden okundu
    HL.ingest_lines(db, "esxi", 5, "esxi_vmkernel", items, NOW)
    rows = db.query(HwLogEntry).all()
    assert len(rows) == 1 and rows[0].occurrences == 3 and rows[0].category == "memory"
    assert rows[0].target_kind == "esxi" and rows[0].target_id == 5 and rows[0].source == "esxi_vmkernel"


def test_ingest_lines_counts_only_newer_lines(db):
    HL.ingest_lines(db, "esxi", 5, "esxi_vmkernel", _items(2), NOW)
    newer = _items(2) + _items(2, base=NOW + timedelta(minutes=5))
    HL.ingest_lines(db, "esxi", 5, "esxi_vmkernel", newer, NOW)
    assert db.query(HwLogEntry).one().occurrences == 4


def test_same_message_on_different_targets_is_separate(db):
    HL.ingest_lines(db, "esxi", 1, "esxi_vmkernel", _items(1), NOW)
    HL.ingest_lines(db, "esxi", 2, "esxi_vmkernel", _items(1), NOW)
    assert db.query(HwLogEntry).count() == 2


def test_message_is_masked_on_write(db):
    HL.ingest_lines(db, "esxi", 1, "esxi_sel", [HL.Item(NOW, "critical", "power", "PSU 2 failed, BMC 10.20.30.42 reports loss")], NOW)
    assert "10.20.30.42" not in db.query(HwLogEntry).one().message


def test_new_key_cap_per_target(db, monkeypatch):
    monkeypatch.setattr(HL, "MAX_NEW_KEYS_PER_TARGET", 5)
    items = [HL.Item(NOW, "warning", "memory", f"DIMM error type-{chr(97 + i)}{chr(100 + i)} on slot") for i in range(12)]
    items.append(HL.Item(NOW, "critical", "memory", "Uncorrectable memory error on DIMM Z9"))
    HL.ingest_lines(db, "esxi", 1, "esxi_vmkernel", items, NOW)
    rows = db.query(HwLogEntry).all()
    assert len(rows) == 5 and any(r.severity == "critical" for r in rows)       # en ağır kayıt elenmez


def test_purge_removes_only_old(db):
    HL.ingest_lines(db, "esxi", 1, "esxi_vmkernel", _items(1, base=NOW - timedelta(days=40)), NOW)
    HL.ingest_lines(db, "esxi", 2, "esxi_vmkernel", _items(1), NOW)
    assert HL.purge(db, NOW) == 1
    assert db.query(HwLogEntry).one().target_id == 2


# ═══ Linux / Windows yansıtma ═══════════════════════════════════════════════════════════════════════════════════

def _srv(db, name, stype="PHYSICAL", os_type="linux"):
    s = Server(name=name, hostname=name, ip_address="10.0.0.2", server_type=stype, os_type=os_type)
    db.add(s)
    db.flush()
    return s


def _ev(db, srv, source, text, count=1, raw=None, sev="warning"):
    e = SystemEvent(server_id=srv.id, event_type="log_entry", severity=sev, source=source, title=text[:200],
                    description=text, raw_data=raw or {}, occurrence_count=count, last_seen=NOW - timedelta(hours=1),
                    created_at=NOW - timedelta(hours=5))
    db.add(e)
    return e


def test_projection_picks_hardware_lines_from_physical_hosts_only(db):
    phys = _srv(db, "lin-phys-01")
    virt = _srv(db, "lin-vm-01", stype="VIRTUAL")
    win = _srv(db, "win-phys-01", os_type="windows")
    _ev(db, phys, "log_collector", "kernel: EDAC MC0: 2 CE memory read error on DIMM#1", count=4)
    _ev(db, phys, "log_collector", "systemd[1]: Failed to start Daily apt download activities.")
    _ev(db, virt, "log_collector", "kernel: EDAC MC0: 2 CE memory read error on DIMM#1")
    _ev(db, win, "windows_collector", "A corrected hardware error has occurred.",
        raw={"category": "Microsoft-Windows-WHEA-Logger", "windows_event_id": 17})
    _ev(db, win, "windows_collector", "The Print Spooler service entered the running state.",
        raw={"category": "Service Control Manager", "windows_event_id": 7036})
    db.commit()
    res = HL.project_system_events(db, NOW)
    db.commit()
    rows = {(r.target_id, r.source): r for r in db.query(HwLogEntry).all()}
    assert set(rows) == {(phys.id, "linux_journal"), (win.id, "windows_event")}      # sanal ve gürültü YOK
    assert rows[(phys.id, "linux_journal")].occurrences == 4 and rows[(phys.id, "linux_journal")].category == "memory"
    assert rows[(win.id, "windows_event")].category == "pcie" and res["targets"] == 2


def test_projection_is_idempotent(db):
    phys = _srv(db, "lin-phys-01")
    _ev(db, phys, "log_collector", "kernel: EDAC MC0: 2 CE memory read error on DIMM#1", count=4)
    db.commit()
    for _ in range(3):
        HL.project_system_events(db, NOW)
        db.commit()
    r = db.query(HwLogEntry).one()
    assert r.occurrences == 4 and db.query(HwLogEntry).count() == 1


# ═══ vCenter yanıt ayrıştırma ve ESXi toplama ═══════════════════════════════════════════════════════════════════

SEL_XML = """<?xml version="1.0"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body>
<FetchSystemEventLogResponse xmlns="urn:vim25">
<returnval><recordId>12</recordId><when>2026-10-27T08:00:00Z</when><selType>2</selType><message>Power Supply 2 Failure detected</message><sensorNumber>9</sensorNumber></returnval>
<returnval><recordId>13</recordId><when>2026-10-27T08:05:00Z</when><selType>2</selType><message>Correctable memory error logged on DIMM A1</message><sensorNumber>3</sensorNumber></returnval>
</FetchSystemEventLogResponse></soapenv:Body></soapenv:Envelope>"""

DIAG_XML = """<?xml version="1.0"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body>
<BrowseDiagnosticLogResponse xmlns="urn:vim25"><returnval>
<lineStart>10</lineStart><lineEnd>13</lineEnd>
<lineText>2026-10-27T09:00:00.000Z cpu1:1)WARNING: NMP: nmp_ThrottleLogForDevice: Cmd 0x28 to dev naa.600 failed H:0x0 D:0x2 P:0x0 Valid sense data: 0x3 0x11 0x0</lineText>
<lineText>2026-10-27T09:00:01.000Z cpu1:1)NetPort: 1234: enabled port 0x4000002</lineText>
<lineText>2026-10-27T09:00:02.000Z cpu1:1)WARNING: MCE: Machine Check Exception: uncorrectable error</lineText>
</returnval></BrowseDiagnosticLogResponse></soapenv:Body></soapenv:Envelope>"""


def _client_stub():
    from app.services.vmware.vcenter_client import VCenterClient
    return VCenterClient.__new__(VCenterClient)


def test_vcenter_parse_sel_and_diag_log():
    c = _client_stub()
    sel = c._parse_sel(ET.fromstring(SEL_XML))
    assert [r["record_id"] for r in sel] == ["12", "13"] and sel[0]["message"].startswith("Power Supply")
    d = c._parse_diag_log(ET.fromstring(DIAG_XML))
    assert d["line_start"] == 10 and d["line_end"] == 13 and len(d["lines"]) == 3
    assert c._parse_sel(None) == [] and c._parse_diag_log(None)["lines"] == []


def test_items_from_payload_filter_noise():
    c = _client_stub()
    sel = c._parse_sel(ET.fromstring(SEL_XML))
    items = HL.items_from_sel(sel)
    assert [(i.category, i.severity) for i in items] == [("power", "critical"), ("memory", "warning")]
    lines = c._parse_diag_log(ET.fromstring(DIAG_XML))["lines"]
    li = HL.items_from_log_lines(lines)
    assert len(li) == 2 and {i.category for i in li} == {"storage", "cpu"}       # NetPort satırı elendi


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get_host_hw_logs(self, **_kw):
        self.calls += 1
        return self.payload


def _hv_with_hosts(db, name="vc01"):
    from app.models.hypervisor import Hypervisor, HypervisorType
    from app.models.hypervisor_inventory import HypervisorHostInventory
    hv = Hypervisor(name=name, hypervisor_type=HypervisorType.VMWARE, hostname=f"{name}.x", ip_address="10.0.0.1",
                    username="ro", connection_config={})
    db.add(hv)
    db.flush()
    inv = HypervisorHostInventory(hypervisor_id=hv.id, host_ref="host-1", host_name="esx01.corp")
    db.add(inv)
    db.commit()
    return hv, inv


def _payload():
    c = _client_stub()
    return {"login_failed": False, "hosts": {"host-1": {
        "host_name": "esx01.corp",
        "sel": c._parse_sel(ET.fromstring(SEL_XML)),
        "logs": {"vmkernel": c._parse_diag_log(ET.fromstring(DIAG_XML))["lines"], "vmkwarning": []},
        "errors": []}, "host-99": {"host_name": "unknown", "sel": [], "logs": {}, "errors": []}}}


def test_collect_esxi_writes_and_is_idempotent(db):
    hv, inv = _hv_with_hosts(db)
    fc = _FakeClient(_payload())
    for _ in range(3):
        res = HL.collect_esxi(db, NOW, client_factory=lambda _hv: fc)
    assert fc.calls == 3 and res["hosts"] == 1                                  # envanterde olmayan host-99 atlanır
    rows = db.query(HwLogEntry).filter(HwLogEntry.target_kind == "esxi", HwLogEntry.target_id == inv.id).all()
    assert {r.source for r in rows} == {"esxi_sel", "esxi_vmkernel"} and len(rows) == 4
    assert all(r.occurrences == 1 for r in rows)                                # tekrar okuma sayacı şişirmez


def test_collect_esxi_login_failed_skips_that_vcenter_only(db):
    hv1, inv1 = _hv_with_hosts(db, "vc01")
    hv2, inv2 = _hv_with_hosts(db, "vc02")
    seen = []

    def factory(hv):
        seen.append(hv.name)
        return _FakeClient({"login_failed": True, "hosts": {}} if hv.name == "vc01" else _payload())

    res = HL.collect_esxi(db, NOW, client_factory=factory)
    assert res["login_failed"] == ["vc01"] and seen.count("vc01") == 1          # yeniden DENENMEZ
    assert db.query(HwLogEntry).filter(HwLogEntry.target_id == inv2.id).count() == 4
    assert db.query(HwLogEntry).filter(HwLogEntry.target_id == inv1.id).count() == 0


def test_collect_esxi_client_exception_does_not_stop_others(db):
    _hv_with_hosts(db, "vc01")
    hv2, inv2 = _hv_with_hosts(db, "vc02")

    def factory(hv):
        if hv.name == "vc01":
            raise RuntimeError("boom")
        return _FakeClient(_payload())

    res = HL.collect_esxi(db, NOW, client_factory=factory)
    assert any("vc01" in e for e in res["errors"]) and res["entries"] > 0


# ═══ 4) Bayrak kapalı = no-op ═══════════════════════════════════════════════════════════════════════════════════

def test_disabled_flag_is_noop(db, monkeypatch):
    monkeypatch.setattr(HL, "enabled", lambda: False)
    boom = _FakeClient(_payload())
    out = HL.run_host_log_sync(db, client_factory=lambda hv: boom)
    assert out == {"skipped": "disabled"} and boom.calls == 0 and db.query(HwLogEntry).count() == 0


def test_runtime_setting_defaults_off():
    from app.services.runtime_settings import ADVANCED_SCHEMA
    assert ADVANCED_SCHEMA["hw_host_logs_enabled"]["default"] is False
    assert ADVANCED_SCHEMA["hw_host_logs_interval_sec"]["min"] >= 900


def test_run_sync_enabled_end_to_end(db, monkeypatch):
    monkeypatch.setattr(HL, "enabled", lambda: True)
    # `run_host_log_sync` gerçek «şimdi»yi kullanır; sabit NOW'daki olaylar tarama penceresinin dışında kalıyordu.
    monkeypatch.setitem(globals(), "NOW", datetime.now(timezone.utc))
    hv, inv = _hv_with_hosts(db)
    phys = _srv(db, "lin-phys-01")
    _ev(db, phys, "log_collector", "kernel: EDAC MC0: 2 CE memory read error on DIMM#1", count=2)
    db.commit()
    fc = _FakeClient(_payload())
    out = HL.run_host_log_sync(db, client_factory=lambda _hv: fc)
    assert out["ok"] and out["esxi"]["entries"] > 0 and out["projection"]["entries"] == 1
    assert db.query(HwLogEntry).count() == 5


# ═══ Salt-okunur ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_soap_surface_is_read_only():
    from app.services.vmware.perf_catalog import SOAP_MUTATE_DENY, SOAP_READ_ALLOW, is_mutate_method
    assert {"FetchSystemEventLog", "BrowseDiagnosticLog"} <= SOAP_READ_ALLOW
    assert {"ClearSystemEventLog", "ResetSystemHealthInfo"} <= SOAP_MUTATE_DENY
    assert is_mutate_method("ClearSystemEventLog") and not is_mutate_method("FetchSystemEventLog")
    assert not ({"FetchSystemEventLog", "BrowseDiagnosticLog"} & SOAP_MUTATE_DENY)


def test_new_client_calls_only_use_allowed_methods():
    import inspect
    from app.services.vmware.vcenter_client import VCenterClient
    src = inspect.getsource(VCenterClient.get_host_hw_logs) + inspect.getsource(VCenterClient._browse_log_body)
    assert "ClearSystemEventLog" not in src and "ResetSystemHealthInfo" not in src
    assert "FetchSystemEventLog" in src and "BrowseDiagnosticLog" in src


# ═══ 5) API + yetki ═════════════════════════════════════════════════════════════════════════════════════════════

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


def _seed_rows(db):
    hv, inv = _hv_with_hosts(db)
    HL.ingest_lines(db, "esxi", inv.id, "esxi_sel", [
        HL.Item(datetime.now(timezone.utc), "critical", "power", "PSU 2 failed, BMC 10.20.30.42 reports loss"),
        HL.Item(datetime.now(timezone.utc), "info", "platform", "Chassis cover opened")], datetime.now(timezone.utc))
    db.commit()
    return inv


def test_api_disabled_and_empty_returns_not_enabled(db, monkeypatch):
    monkeypatch.setattr(HL, "enabled", lambda: False)
    j = _client(db, role="admin").get("/hw/host-logs?kind=esxi&id=1").json()
    assert j["ok"] and j["enabled"] is False and j["available"] is False and j["items"] == []


def test_api_target_view_masked_and_filtered(db, monkeypatch):
    monkeypatch.setattr(HL, "enabled", lambda: True)
    inv = _seed_rows(db)
    j = _client(db, role="admin").get(f"/hw/host-logs?kind=esxi&id={inv.id}").json()
    assert j["available"] and j["total"] == 1 and j["items"][0]["severity"] == "critical"     # info varsayılan gizli
    assert j["items"][0]["target"]["name"] == "esx01.corp" and "10.20.30.42" not in str(j)
    j2 = _client(db, role="admin").get(f"/hw/host-logs?kind=esxi&id={inv.id}&severity=all").json()
    assert j2["total"] == 2 and j2["counts"] == {"critical": 1, "info": 1}
    assert _client(db, role="admin").get(f"/hw/host-logs?kind=esxi&id={inv.id + 99}").json()["items"] == []


def test_api_fleet_view_requires_hardware_module(db, monkeypatch):
    monkeypatch.setattr(HL, "enabled", lambda: True)
    _seed_rows(db)
    assert _client(db, role="operator", uid=999).get("/hw/host-logs").status_code == 403
    assert _client(db, role="admin").get("/hw/host-logs").status_code == 200
    assert _client(db, role="admin").get("/hw/host-logs?kind=esxi").status_code == 422        # id eksik


def test_policy_platform_modules_can_read_target_host_logs_only():
    from app.core.module_policy import decide
    for mod in ("linux", "windows", "virtualization"):
        assert decide(role="operator", modules=(mod,), method="GET", path="/api/v1/hw/host-logs", query={}).allowed
        assert not decide(role="operator", modules=(mod,), method="POST", path="/api/v1/hw/host-logs", query={}).allowed
    assert decide(role="operator", modules=("hardware",), method="GET", path="/api/v1/hw/host-logs", query={}).allowed
    assert not decide(role="operator", modules=("exadata",), method="GET", path="/api/v1/hw/host-logs", query={}).allowed


# ── Sahada bulunan hatalar (ESXi 8.0.1): SOAPAction, log kuyruğu, vmkwarning yok, eski SEL ───────────────────────────
class _FakeResp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


class _FakeSoapSession:
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def post(self, url, data=None, headers=None, verify=None, timeout=None):
        body = data.decode() if isinstance(data, bytes) else data
        self.calls.append((headers or {}, body))
        return self.handler(headers or {}, body)


def _vc():
    from app.services.vmware.vcenter_client import VCenterClient
    return VCenterClient(host="x", username="u", password="p", port=443, verify_ssl=False)


def test_soap_text_call_sends_soapaction_and_raises_on_fault():
    ok = '<e xmlns:s="x"><r>1</r></e>'
    sess = _FakeSoapSession(lambda h, b: _FakeResp(200, ok) if "SOAPAction" in h else _FakeResp(
        500, "<f><faultstring>Unable to resolve WSDL method name X</faultstring></f>"))
    assert _vc()._soap_text_call(sess, "u", "<b/>") is not None
    assert sess.calls[0][0]["SOAPAction"].startswith('"urn:vim25/')
    bad = _FakeSoapSession(lambda h, b: _FakeResp(500, "<f><faultstring>Unable to resolve WSDL</faultstring></f>"))
    with pytest.raises(RuntimeError, match="Unable to resolve WSDL"):
        _vc()._soap_text_call(bad, "u", "<b/>")


def test_browse_tail_probes_total_then_reads_last_lines():
    def handler(h, b):
        if "<vim25:start>100000000</vim25:start>" in b:
            return _FakeResp(200, '<e><BrowseDiagnosticLogResponse xmlns="urn:vim25"><returnval>'
                                  '<lineStart>0</lineStart><lineEnd>1000</lineEnd></returnval>'
                                  '</BrowseDiagnosticLogResponse></e>')
        assert "<vim25:start>991</vim25:start>" in b and "<vim25:lines>10</vim25:lines>" in b
        lines = "".join(f"<lineText>L{i}</lineText>" for i in range(991, 1001))
        return _FakeResp(200, '<e><BrowseDiagnosticLogResponse xmlns="urn:vim25"><returnval>'
                              f'<lineStart>991</lineStart><lineEnd>1000</lineEnd>{lines}</returnval>'
                              '</BrowseDiagnosticLogResponse></e>')
    out = _vc()._browse_tail(_FakeSoapSession(handler), "u", "DiagMgr", "host-1", "vmkernel", 10)
    assert out[0] == "L991" and out[-1] == "L1000" and len(out) == 10


def test_query_log_keys_parses_keys():
    xml = ('<e><QueryDescriptionsResponse xmlns="urn:vim25"><returnval><key>fdm</key></returnval>'
           '<returnval><key>vmkernel</key></returnval></QueryDescriptionsResponse></e>')
    keys = _vc()._query_log_keys(_FakeSoapSession(lambda h, b: _FakeResp(200, xml)), "u", "DiagMgr", "host-1")
    assert keys == ["fdm", "vmkernel"]


def test_sel_older_than_retention_is_skipped():
    old = {"message": "Assert + Power Supply Failure status", "when": "2019-11-12T07:32:17"}
    new_when = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    new = {"message": "Assert + Power Supply Failure status", "when": new_when}
    items = HL.items_from_sel([old, new])
    assert len(items) == 1


# ── Son toplama zamanı (kartta «son toplama 14:52») ─────────────────────────────────────────────────────────────
class _FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, k, v, ex=None):
        self.store[k] = v

    def get(self, k):
        return self.store.get(k)


def test_mark_run_and_last_run_roundtrip(monkeypatch):
    import app.core.redis_client as rc
    fr = _FakeRedis()
    monkeypatch.setattr(rc, "get_redis", lambda **kw: fr)
    now = datetime(2026, 10, 27, 11, 52, tzinfo=timezone.utc)
    HL.mark_run(now, {"esxi": {"errors": ["a", "b"], "login_failed": ["vc1"]}})
    lr = HL.last_run()
    assert lr["at"].startswith("2026-10-27T11:52") and lr["errors"] == 3


def test_last_run_is_none_without_redis(monkeypatch):
    import app.core.redis_client as rc
    monkeypatch.setattr(rc, "get_redis", lambda **kw: None)
    assert HL.last_run() is None
    HL.mark_run(datetime.now(timezone.utc), {})            # fail-open: hata fırlatmaz


def test_sync_with_fake_client_does_not_touch_redis(monkeypatch, db):
    import app.core.redis_client as rc
    called = []
    monkeypatch.setattr(rc, "get_redis", lambda **kw: called.append(1) or None)
    HL.run_host_log_sync(db, force=True, client_factory=lambda hv: None)
    assert called == []
