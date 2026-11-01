"""Faz C1 — Dell OME firmware envanteri: imleç (sınırdan fazla sunucuda hepsi okunur), Status/ComponentId, BIOS türetme,
API sıralaması. Ağa ÇIKMAZ (sahte OME)."""
from __future__ import annotations

import pytest

import app.models.infrastructure_report  # noqa: F401
from app.models.hw import HwFirmware, HwServer
from app.services.hw import sync
from app.services.hw.dell_ome import DellOmeProvider
from app.services.hw.snapshot import PART_INVENTORY
from app.tests import hw_fakes as F
from app.tests.test_hw_bmc_api import _client


@pytest.fixture()
def db(isolated_db):
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()
    yield isolated_db
    invalidate_capabilities()


def _dev(i):
    return {"Id": 100 + i, "DeviceName": f"srv-{i}", "Model": "PowerEdge R650", "Type": 1000, "Identifier": f"TAG{i:04d}",
            "DeviceServiceTag": f"TAG{i:04d}", "Status": 1000, "PowerState": 17, "ConnectionState": True,
            "DeviceManagement": [{"NetworkAddress": f"10.0.0.{i}", "ManagementProfile": [{"AgentName": "iDRAC", "Version": "7.00"}]}]}


def _sw(i):
    return [
        {"Status": "Installed", "SoftwareType": "BIOS", "DeviceDescription": "BIOS", "Version": f"1.{i}.0", "ComponentId": "159"},
        {"Status": "Installed", "SoftwareType": "FRMW", "DeviceDescription": "Integrated Dell Remote Access Controller",
         "Version": "7.00", "ComponentId": "25227"},
        {"Status": "Available", "SoftwareType": "FRMW", "DeviceDescription": "Integrated Dell Remote Access Controller",
         "Version": "6.10", "ComponentId": "25227"},
    ]


def _run(db, row, devices, software, log=None):
    http, _ = F.http_for(F.ome_router(devices=devices, alerts=[], warranties=[], software=software, software_log=log),
                         "https://ome.example", "ome")
    res = sync.sync_instance(db, row, force=True, provider=DellOmeProvider(row, http=http), parts=[PART_INVENTORY])
    assert res["ok"] is True, res
    db.refresh(row)
    return res


def _row(db, **meta):
    from app.services.capabilities import invalidate_capabilities
    row = F.make_row(db, meta={"fetch_firmware": True, "throttle_sec": 0.0001, **meta})
    invalidate_capabilities()
    return row


def test_cursor_covers_all_servers_when_cap_is_smaller(db):
    import json
    devices = [_dev(i) for i in range(5)]
    software = {100 + i: _sw(i) for i in range(5)}
    row = _row(db, firmware_max_per_run=2)
    seen_runs = []
    for run in range(3):
        log: list = []
        res = _run(db, row, devices, software, log)
        seen_runs.append(log)
        assert res["counts"]["firmware_total"] == 5
    assert seen_runs[0] == [100, 101] and seen_runs[1] == [102, 103] and seen_runs[2] == [104, 100]   # imleç döner
    assert json.loads(row.meta_json)["firmware_cursors"]["ome"] == 1                                         # (4+2) % 5 → sonraki tur 101'den
    have = {h.provider_ref for h in db.query(HwServer).join(HwFirmware, HwFirmware.server_id == HwServer.id).all()}
    assert have == {str(100 + i) for i in range(5)}                                                   # 5 sunucunun HEPSİNDE firmware var


def test_status_component_and_bios_persist_and_survive_unread_round(db):
    devices = [_dev(0), _dev(1)]
    software = {100: _sw(0), 101: _sw(1)}
    row = _row(db)
    _run(db, row, devices, software)
    s = db.query(HwServer).filter(HwServer.provider_ref == "100").one()
    assert s.bios_version == "1.0.0"                                                                 # Installed BIOS
    rows = db.query(HwFirmware).filter(HwFirmware.server_id == s.id).all()
    assert {(r.status, r.component_id, r.version) for r in rows} >= {("Installed", "25227", "7.00"), ("Available", "25227", "6.10")}
    # firmware okunmayan tur (seçenek kapalı): BIOS silinmez
    import json
    meta = json.loads(row.meta_json)
    meta["fetch_firmware"] = False
    row.meta_json = json.dumps(meta)
    db.commit()
    _run(db, row, devices, software)
    db.expire_all()
    assert db.query(HwServer).filter(HwServer.provider_ref == "100").one().bios_version == "1.0.0"


def test_device_level_404_skips_device_but_cursor_advances(db):
    devices = [_dev(0), _dev(1), _dev(2)]
    software = {100: _sw(0), 102: _sw(2)}            # 101 → 404
    row = _row(db, firmware_max_per_run=10)
    res = _run(db, row, devices, software)
    assert res["counts"]["firmware_read"] == 3 and res["counts"]["firmware_total"] == 3
    got = {h.server_id for h in db.query(HwFirmware).all()}
    assert len(got) == 2


def test_server_detail_firmware_installed_first(db):
    devices = [_dev(0)]
    row = _row(db)
    _run(db, row, devices, {100: _sw(0)})
    hid = db.query(HwServer).one().id
    j = _client(db).get(f"/hw/servers/{hid}").json()["server"]
    st = [f["status"] for f in j["firmware"]]
    assert st == sorted(st, key=lambda x: 0 if x == "Installed" else 1) and st[-1] == "Available"
    assert j["firmware_collected_at"]
    assert all(f["component_id"] for f in j["firmware"])
