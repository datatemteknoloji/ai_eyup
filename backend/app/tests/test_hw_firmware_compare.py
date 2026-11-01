"""Faz C2 — referans sunucu tabanlı firmware karşılaştırması: sürüm ayrıştırma, referans çözümü (şasi > model),
«kabul edildi» (sürüm değişince düşer), bulgu, API izinleri, HPE bileşen firmware okuması. Ağa ÇIKMAZ."""
from __future__ import annotations

import pytest

import app.models.infrastructure_report  # noqa: F401
from app.models.hw import HwEnclosure, HwFirmware, HwFirmwareAccept, HwFirmwareReference, HwServer
from app.services.hw import firmware_compare as FC
from app.tests import hw_fakes as F


@pytest.fixture()
def db(isolated_db):
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()
    yield isolated_db
    invalidate_capabilities()


# ── sürüm ayrıştırma (saf) ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cur,ref,want", [
    ("7.00.00.172", "7.10.50.00", "outdated"),
    ("7.10.50.00", "7.10.50", "ok"),                       # sondaki sıfırlar eşit
    ("2.9.1", "2.10.0", "outdated"),                       # sayısal (metinsel değil) karşılaştırma
    ("2.11.0", "2.10.0", "newer"),
    ("I42 v2.40 (04/09/2020)", "I42 v2.62 (11/02/2023)", "outdated"),
    ("I41 v2.40", "I42 v2.62", "unknown"),                 # ROM ailesi farklı → ölçülemedi
    ("iLO 5 v2.78", "iLO 5 v2.81", "outdated"),
    ("abc", "7.0.0", "unknown"),                           # ayrıştırılamaz → asla «düşük» değil
    ("12", "13", "unknown"),                               # tek tamsayı güvenilir değil
    ("abc", "abc", "ok"),                                  # birebir aynı metin
    (None, "1.0.0", "unknown"),
])
def test_compare_versions(cur, ref, want):
    assert FC.compare_versions(cur, ref) == want


def test_component_key_strips_mac_and_installed_only():
    a = HwFirmware(name="Broadcom NetXtreme - 00:11:22:33:44:55", version="21.80.1", status="Installed")
    b = HwFirmware(name="Broadcom NetXtreme - AA:BB:CC:DD:EE:FF", version="21.80.1", status="Installed")   # aynı anahtar, aynı sürüm
    c = HwFirmware(name="BIOS", version="1.0.0", status="Available")                                        # önceki sürüm → yok sayılır
    d = HwFirmware(name="Disk", version="A", status="Installed")
    e = HwFirmware(name="Disk", version="B", status="Installed")                                            # belirsiz → çıkarılır
    s = HwServer(vendor="dell", model="x")
    comps, real = FC.component_map(s, [a, b, c, d, e])
    assert real and list(comps) == ["broadcom netxtreme|"]


# ── veri kurulumu ───────────────────────────────────────────────────────────────────────────────────────────────
def _row(db):
    from app.services.capabilities import invalidate_capabilities
    row = F.make_row(db, kind="hpe_oneview", endpoint="ov.example", meta={"mode": "oneview"})
    invalidate_capabilities()
    return row


def _srv(db, row, i, *, model="ProLiant DL380 Gen10", vendor="hpe", fw=None, encl=None, bay=None):
    s = HwServer(instance_id=row.id, provider_ref=f"p{i}", vendor=vendor, name=f"srv-{i}", model=model,
                 form_factor="blade" if encl else "rack", enclosure_ref=(f"/rest/enclosures/{encl.provider_ref}" if encl else None),
                 enclosure_name=(encl.name if encl else None), bay=bay, health="ok")
    db.add(s)
    db.flush()
    for name, ver in (fw or {}).items():
        db.add(HwFirmware(server_id=s.id, name=name, component_type="FW", version=ver, status="Installed"))
    db.commit()
    return s


def _ref(db, srv, scope="model", encl=None):
    r = HwFirmwareReference(scope=scope, vendor=srv.vendor, model=srv.model, reference_server_id=srv.id,
                            enclosure_id=(encl.id if encl else None))
    db.add(r)
    db.commit()
    return r


def test_model_reference_flags_lower_firmware_only_for_same_model(db):
    row = _row(db)
    ref = _srv(db, row, 1, fw={"System ROM": "I42 v2.62", "iLO 5": "2.81"})
    low = _srv(db, row, 2, fw={"System ROM": "I42 v2.40", "iLO 5": "2.81"})
    same = _srv(db, row, 3, fw={"System ROM": "I42 v2.62", "iLO 5": "2.81"})
    other = _srv(db, row, 4, model="ProLiant DL360 Gen10", fw={"System ROM": "I42 v1.00"})
    _ref(db, ref)
    res = FC.compare_all(db, [ref, low, same, other])
    assert res[ref.id]["status"] == "reference"
    assert res[low.id]["status"] == "outdated" and res[low.id]["outdated"] == 1
    assert [c["name"] for c in res[low.id]["components"]] == ["System ROM"]            # yalnız ok olmayanlar
    assert res[same.id]["status"] == "ok"
    assert res[other.id]["status"] == "no_reference"                                   # başka model kıyaslanmaz


def test_chassis_reference_overrides_model_and_is_scoped_to_chassis(db):
    row = _row(db)
    e1 = HwEnclosure(instance_id=row.id, provider_ref="E1", name="Encl-1", bay_count=4)
    e2 = HwEnclosure(instance_id=row.id, provider_ref="E2", name="Encl-2", bay_count=4)
    db.add_all([e1, e2])
    db.commit()
    gm = _srv(db, row, 1, fw={"iLO 5": "2.90"})                               # model referansı (kasasız)
    c1 = _srv(db, row, 2, fw={"iLO 5": "2.72"}, encl=e1, bay="1")             # şasi-1 referansı
    c1b = _srv(db, row, 3, fw={"iLO 5": "2.72"}, encl=e1, bay="2")
    c2 = _srv(db, row, 4, fw={"iLO 5": "2.72"}, encl=e2, bay="1")
    _ref(db, gm)
    _ref(db, c1, scope="chassis", encl=e1)
    res = FC.compare_all(db, [gm, c1, c1b, c2])
    assert res[c1b.id]["status"] == "ok" and res[c1b.id]["reference"]["scope"] == "chassis"   # şasi > model
    assert res[c1.id]["status"] == "reference"
    assert res[c2.id]["status"] == "outdated" and res[c2.id]["reference"]["scope"] == "model"  # başka şasi model referansına düşer


def test_accept_lapses_when_version_changes(db):
    row = _row(db)
    ref = _srv(db, row, 1, fw={"iLO 5": "2.81"})
    low = _srv(db, row, 2, fw={"iLO 5": "2.72"})
    _ref(db, ref)
    db.add(HwFirmwareAccept(server_id=low.id, component_key=FC.component_key("iLO 5"), accepted_version="2.72", accepted_by="u"))
    db.commit()
    r = FC.compare_all(db, [ref, low])[low.id]
    assert r["status"] == "accepted" and r["accepted"] == 1 and r["outdated"] == 0
    f = db.query(HwFirmware).filter(HwFirmware.server_id == low.id).one()
    f.version = "2.75"                                                         # sürüm değişti, hâlâ referansın altında
    db.commit()
    assert FC.compare_all(db, [ref, low])[low.id]["status"] == "outdated"      # kabul düştü


def test_unparseable_and_missing_data_never_outdated(db):
    row = _row(db)
    ref = _srv(db, row, 1, fw={"Thing": "alpha"})
    weird = _srv(db, row, 2, fw={"Thing": "beta"})
    nodata = _srv(db, row, 3)
    _ref(db, ref)
    res = FC.compare_all(db, [ref, weird, nodata])
    assert res[weird.id]["status"] == "unknown" and res[weird.id]["outdated"] == 0
    assert res[nodata.id]["status"] == "no_data"


def test_bmc_bios_fallback_when_no_firmware_rows(db):
    row = _row(db)
    ref = _srv(db, row, 1)
    low = _srv(db, row, 2)
    ref.bmc_version, ref.bios_version = "2.81", "I42 v2.62"
    low.bmc_version, low.bios_version = "2.72", "I42 v2.62"
    db.commit()
    _ref(db, ref)
    r = FC.compare_all(db, [ref, low])[low.id]
    assert r["status"] == "outdated" and [c["name"] for c in r["components"]] == ["BMC"]


# ── bulgu ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_finding_only_for_outdated_and_has_no_versions(db):
    from app.services.hw.findings_engine import hw_findings
    row = _row(db)
    ref = _srv(db, row, 1, fw={"iLO 5": "2.81"})
    low = _srv(db, row, 2, fw={"iLO 5": "2.72"})
    ok = _srv(db, row, 3, fw={"iLO 5": "2.81"})
    _ref(db, ref)
    fs = [d for d in hw_findings(db) if d.check_id == "hw.firmware.outdated"]
    assert [d.ref if hasattr(d, "ref") else d for d in fs] and len(fs) == 1
    d = fs[0]
    assert "2.72" not in d.detail and "2.81" not in d.detail and "2.72" not in str(d.evidence)
    assert "iLO 5" in d.detail


# ── HPE OneView bileşen firmware okuması ────────────────────────────────────────────────────────────────────────
def test_norm_firmware_defensive():
    from app.services.hw.oneview import norm_firmware
    assert norm_firmware(None, "r") == [] and norm_firmware({"components": "x"}, "r") == []
    recs = norm_firmware({"components": [
        {"componentName": "System ROM", "componentVersion": "I42 v2.62", "componentLocation": "System Board"},
        {"componentName": "", "componentVersion": "1"}, {"componentName": "X", "componentVersion": None}, "junk",
        {"componentName": "NIC", "componentVersion": 5}]}, "r")
    assert [(r.name, r.version, r.location, r.status) for r in recs] == [
        ("System ROM", "I42 v2.62", "System Board", "Installed"), ("NIC", "5", None, "Installed")]


def test_hpe_appliance_reads_component_firmware_with_cursor(db):
    from app.services.hw import sync
    from app.services.hw.oneview import HpeProvider
    from app.services.hw.snapshot import PART_INVENTORY
    from app.services.capabilities import invalidate_capabilities
    row = F.make_row(db, kind="hpe_oneview", endpoint="ov.example",
                     meta={"mode": "oneview", "fetch_firmware": True, "firmware_max_per_run": 1})
    invalidate_capabilities()
    fw = {"37333036": {"components": [{"componentName": "System ROM", "componentVersion": "I42 v2.62",
                                       "componentLocation": "System Board"}]},
          "99999": {"components": [{"componentName": "iLO 5", "componentVersion": "2.72"}]}}
    log: list = []
    for _ in range(2):
        def factory(base, product):
            h, _s = F.http_for(F.oneview_router(firmware=fw, calls_log=log), base, product)
            return h
        res = sync.sync_instance(db, row, force=True, provider=HpeProvider(row, http_factory=factory), parts=[PART_INVENTORY])
        assert res["ok"] is True, res
        db.refresh(row)
    got = [p for m, p in log if p.endswith("/firmware")]
    assert len(got) == 2 and len(set(got)) == 2                                     # tur başına 1; imleç ikinci turda diğerini okur
    have = {s.provider_ref.split("|", 1)[1]: [f.name for f in db.query(HwFirmware).filter(HwFirmware.server_id == s.id)]
            for s in db.query(HwServer).all()}
    assert have["/rest/server-hardware/37333036"] == ["System ROM"] and have["/rest/server-hardware/99999"] == ["iLO 5"]


def test_hpe_ovgd_does_not_call_firmware(db):
    from app.services.hw.endpoints import allowed
    assert allowed("oneview", "GET", "/rest/server-hardware/abc-1/firmware")
    assert not allowed("oneview", "POST", "/rest/server-hardware/abc-1/firmware")
    assert not allowed("oneview", "GET", "/rest/server-hardware/abc/1/firmware")


# ── API: akış ───────────────────────────────────────────────────────────────────────────────────────────────────
def _live(db):
    row = _row(db)
    row.last_status = "ok"
    db.commit()
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()
    return row


def test_api_reference_accept_flow_and_validation(db):
    from app.tests.test_hw_bmc_api import _client
    row = _live(db)
    ref = _srv(db, row, 1, fw={"iLO 5": "2.81"})
    low = _srv(db, row, 2, fw={"iLO 5": "2.72"})
    nofw = _srv(db, row, 3)
    nomodel = _srv(db, row, 4, model="", fw={"iLO 5": "2.81"})
    c = _client(db)
    assert c.post("/hw/firmware/references", json={"server_id": nofw.id, "scope": "model"}).status_code == 400   # veri yok
    assert c.post("/hw/firmware/references", json={"server_id": nomodel.id, "scope": "model"}).status_code == 400
    assert c.post("/hw/firmware/references", json={"server_id": ref.id, "scope": "chassis"}).status_code == 400  # şasisi yok
    assert c.post("/hw/firmware/references", json={"server_id": ref.id, "scope": "x"}).status_code == 400
    assert c.post("/hw/firmware/references", json={"server_id": ref.id, "scope": "model"}).json()["ok"]
    assert c.post("/hw/firmware/references", json={"server_id": ref.id, "scope": "model"}).json()["ok"]            # yinelenen = güncelle
    assert db.query(HwFirmwareReference).count() == 1
    g = next(g for g in c.get("/hw/firmware/compare").json()["groups"] if g["model"] == "ProLiant DL380 Gen10")
    assert g["reference"]["server_id"] == ref.id and g["outdated"] == 1
    st = {x["id"]: x["status"] for x in g["servers"]}
    assert st[low.id] == "outdated" and st[ref.id] == "reference"

    assert c.post("/hw/firmware/accept", json={"server_id": ref.id}).status_code == 404       # düşük bileşen yok
    assert c.post("/hw/firmware/accept", json={"server_id": low.id, "note": "bakım penceresi"}).json()["accepted"] == 1
    d = c.get(f"/hw/servers/{low.id}").json()["server"]["firmware_status"]
    assert d["status"] == "accepted" and d["components"][0]["accepted"] is True and d["components"][0]["note"] == "bakım penceresi"
    assert c.delete(f"/hw/firmware/accept/{low.id}").json()["removed"] == 1
    assert c.get(f"/hw/servers/{low.id}").json()["server"]["firmware_status"]["status"] == "outdated"
    rid = db.query(HwFirmwareReference).one().id
    assert c.delete(f"/hw/firmware/references/{rid}").json()["removed"] == 1
    assert c.get(f"/hw/servers/{low.id}").json()["server"]["firmware_status"]["status"] == "no_reference"


def test_chassis_reference_via_api(db):
    from app.tests.test_hw_bmc_api import _client
    row = _live(db)
    e1 = HwEnclosure(instance_id=row.id, provider_ref="E1", name="Encl-1", bay_count=4)
    db.add(e1)
    db.commit()
    a = _srv(db, row, 1, fw={"iLO 5": "2.81"}, encl=e1, bay="1")
    b = _srv(db, row, 2, fw={"iLO 5": "2.72"}, encl=e1, bay="2")
    c = _client(db)
    assert c.post("/hw/firmware/references", json={"server_id": a.id, "scope": "chassis"}).json()["ok"]
    ref = db.query(HwFirmwareReference).one()
    assert ref.scope == "chassis" and ref.enclosure_id == e1.id
    g = c.get("/hw/firmware/compare").json()["groups"][0]
    assert g["chassis_refs"][0]["enclosure_name"] == "Encl-1" and g["reference"] is None and g["outdated"] == 1


def test_restricted_user_never_sees_firmware(db):
    """`hardware` modülü olmayan kullanıcı firmware/firmware_status görmez."""
    from app.tests.test_hw_bmc_api import _client
    row = _live(db)
    s = _srv(db, row, 1, fw={"iLO 5": "2.81"})
    c = _client(db, role="viewer")
    r = c.get(f"/hw/servers/{s.id}")
    if r.status_code == 200:
        body = r.json()["server"]
        if body.get("restricted"):
            assert "firmware" not in body and "firmware_status" not in body


def test_policy_registers_firmware_writes_as_operator():
    from app.core import module_policy as MP
    src = open(MP.__file__, encoding="utf-8").read()
    assert "firmware/(references|accept)" in src
