"""Dilim C: dinamik aşırı boyut (p95 + pencere + asgari küçülme) ve sahipsiz disk kanıtı."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.database import SessionLocal, engine
from app.models.capacity_policy import CapacityPolicy
from app.services import capacity_policy as cp
from app.services import virt_reclaim as rc


@pytest.fixture()
def db():
    CapacityPolicy.__table__.create(bind=engine, checkfirst=True)
    s = SessionLocal()
    s.query(CapacityPolicy).delete()
    s.commit()
    try:
        yield s
    finally:
        s.query(CapacityPolicy).delete()
        s.commit()
        s.close()
        cp.activate(values=cp.defaults())


def _usage(avg, p95, days=30):
    return {"avg_cpu_pct": avg, "avg_mem_pct": 50.0, "p95_cpu_pct": p95, "p95_mem_pct": 50.0, "samples": 500, "data_days": days}


def _vm(name, vcpu, on=True):
    return {"id": 1, "name": name, "hypervisor_id": 1, "cluster": "C", "host": "h", "ref": name, "vcpu": vcpu,
            "memory_gb": 16.0, "disk_gb": 100.0, "powered_on": on, "datastore": "ds", "tier": None}


def _rows(monkeypatch, db, vms, usage):
    monkeypatch.setattr(rc.vd, "vm_allocations", lambda d, ids: vms)
    monkeypatch.setattr(rc.vd, "platform_of", lambda h: "vmware")
    monkeypatch.setattr(rc, "vm_usage", lambda d, ids, days=7: usage)
    monkeypatch.setattr(rc, "last_powered_on", lambda d, ids: ({}, None))
    return rc._vm_rows(db, [SimpleNamespace(id=1, name="vc")])


def test_oversized_uses_p95_not_average(monkeypatch, db):
    # ortalama düşük (%12) ama p95 yüksek (%65): zirveleri var → aşırı boyutlu DEĞİL
    out = _rows(monkeypatch, db, [_vm("peaky", 8)], {(1, "peaky"): _usage(12.0, 65.0)})
    assert out["oversized"] == [] and out["idle"] == []


def test_oversized_when_p95_demand_fits_fewer_vcpu(monkeypatch, db):
    out = _rows(monkeypatch, db, [_vm("big", 8)], {(1, "big"): _usage(20.0, 30.0)})
    (r,) = out["oversized"]
    assert r["rightsize"]["vcpu"] == 4          # ceil(8*30/70)
    assert r["confidence"] == "high" and r["window_days"] == 30
    assert "p95" in r["reason"]


def test_min_reduction_threshold(monkeypatch, db):
    # 8 vCPU, p95 %60 → öneri 7 (%12,5 küçülme) → varsayılan %25 altında → aday değil
    out = _rows(monkeypatch, db, [_vm("edge", 8)], {(1, "edge"): _usage(30.0, 60.0)})
    assert out["oversized"] == []
    cp.save(db, {"rs_min_reduction_pct": 10})
    out = _rows(monkeypatch, db, [_vm("edge", 8)], {(1, "edge"): _usage(30.0, 60.0)})
    assert [r["vm"] for r in out["oversized"]] == ["edge"]


def test_target_pct_policy_changes_recommendation(monkeypatch, db):
    cp.save(db, {"rs_target_pct": 50})
    out = _rows(monkeypatch, db, [_vm("big", 8)], {(1, "big"): _usage(20.0, 30.0)})
    assert out["oversized"][0]["rightsize"]["vcpu"] == 5   # ceil(8*30/50)


def test_min_vcpu_and_low_confidence(monkeypatch, db):
    out = _rows(monkeypatch, db, [_vm("small", 2)], {(1, "small"): _usage(20.0, 10.0)})
    assert out["oversized"] == []                           # < rs_min_vcpu(4)
    out = _rows(monkeypatch, db, [_vm("newvm", 8)], {(1, "newvm"): _usage(20.0, 30.0, days=3)})
    assert out["oversized"][0]["confidence"] == "low"


def test_folder_of():
    assert rc._folder_of("[datastore2] gorkem/gorkem.vmdk") == ("datastore2", "gorkem")
    assert rc._folder_of("[ds] a/b/c.vmdk") == ("ds", "a/b")
    assert rc._folder_of("[ds] flat.vmdk") == ("ds", "")
    assert rc._folder_of("disk:123") == ("", "")


def _file(path, attached, hv=1, kind="vmdk"):
    return SimpleNamespace(kind=kind, path=path, attached=attached, source_id=hv)


def test_orphan_evidence_classes(monkeypatch, db):
    monkeypatch.setattr(rc.vd, "vm_allocations", lambda d, ids: [_vm("rhel8", 2, on=False), _vm("lonely", 2)])
    rows = [
        _file("[ds] rhel8/rhel8.vmdk", True), _file("[ds] rhel8/rhel8_1.vmdk", False),      # detached_from_vm
        _file("[ds] gone/gone.vmdk", False),                                                 # vm_gone
        _file("[ds] lonely/lonely.vmdk", False),                                             # check_vm
        _file("[ds] other/x.vmdk", True), _file("[ds] other/y.vmdk", False),                 # check_other_vcenter
        _file("disk:abc", False),                                                            # api_verified
    ]
    old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    orphans = [{"hypervisor_id": 1, "path": r.path, "modified_at": old} for r in rows if not r.attached]
    rc._explain_orphans(db, [1], rows, orphans)
    cls = {o["path"]: o["evidence"]["class"] for o in orphans}
    assert cls["[ds] rhel8/rhel8_1.vmdk"] == "detached_from_vm"
    assert cls["[ds] gone/gone.vmdk"] == "vm_gone"
    assert cls["[ds] lonely/lonely.vmdk"] == "check_vm"
    assert cls["[ds] other/y.vmdk"] == "check_other_vcenter"
    assert cls["disk:abc"] == "api_verified"
    assert all(o["evidence"]["reason"] and o["evidence"]["modified_days"] == 100 for o in orphans)
