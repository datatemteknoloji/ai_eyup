"""Geri kazanım simülasyonu: cluster başına önce/sonra, vCPU ve Memory kazanımı ayrı, eşikler geçici."""
from __future__ import annotations

import pytest

from app.models.server import Server
from app.services import capacity_policy
from app.services.virt_reclaim_sim import reclaim_sim
from app.tests.test_capacity_v2 import _p95, _seed


@pytest.fixture(autouse=True)
def _thr():
    capacity_policy.activate(values={})
    yield
    capacity_policy.activate(values={})


def _big_vm(db, hv, name, host, vcpu=8, mem_gb=32, cluster="A"):
    db.add(Server(name=name, vm_name=name, hypervisor_id=hv.id, vm_host_name=host, vm_cluster=cluster,
                  vm_memory_mb=int(mem_gb * 1024), vm_cpu_count=vcpu, vm_power_state="poweredOn"))
    db.commit()


def _env(db):
    hv = _seed(db, "vc01", [("e1", "host-1", 256, 150, "A"), ("e2", "host-2", 256, 150, "A")])
    _big_vm(db, hv, "fat", "e1")
    _p95(db, hv, "fat", cpu=12, mem=15)
    return hv


def test_before_after_and_separate_vcpu_memory_gains(isolated_db):
    db = isolated_db
    hv = _env(db)
    r = reclaim_sim(db, hypervisor_id=hv.id)
    c = r["clusters"][0]
    assert c["vms_affected"] == 1
    assert c["vcpu"] == {"freed": 6, "vms": 1}                       # 8 → 2 vCPU
    assert c["memory"] == {"freed_gb": 24.0, "vms": 1}               # 32 → 8 GB (p95 aktif Memory %15 < %25)
    assert c["after"]["memory_effective_pct"] < c["before"]["memory_effective_pct"]
    assert c["after"]["vcpu_ratio"] < c["before"]["vcpu_ratio"]
    top = c["top"][0]
    assert (top["vm"], top["new_vcpu"], top["new_memory_gb"]) == ("fat", 2, 8)


def test_vcpu_only_reduction_does_not_free_memory(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("e1", "host-1", 256, 150, "A"), ("e2", "host-2", 256, 150, "A")])
    _big_vm(db, hv, "cpu-fat", "e1")
    _p95(db, hv, "cpu-fat", cpu=12, mem=60)                          # Memory p95 yüksek → Memory küçültme önerilmez
    c = reclaim_sim(db, hypervisor_id=hv.id)["clusters"][0]
    assert c["vcpu"]["freed"] == 6 and c["memory"]["freed_gb"] == 0.0
    assert c["after"]["memory_effective_pct"] == c["before"]["memory_effective_pct"]
    assert c["after"]["n1_memory_pct"] == c["before"]["n1_memory_pct"]


def test_thresholds_are_temporary_and_validated(isolated_db):
    db = isolated_db
    hv = _env(db)
    r = reclaim_sim(db, hypervisor_id=hv.id, thresholds={"rs_min_vcpu": 16})
    assert r["clusters"][0]["vms_affected"] == 0                      # 8 vCPU < 16 → aday değil
    assert r["overridden"] == ["rs_min_vcpu"] and r["thresholds"]["rs_min_vcpu"] == 16.0
    assert capacity_policy.load(db)["rs_min_vcpu"] == 4.0             # politika kaydedilmedi
    again = reclaim_sim(db, hypervisor_id=hv.id)
    assert again["clusters"][0]["vms_affected"] == 1 and again["thresholds"]["rs_min_vcpu"] == 4.0
    with pytest.raises(ValueError):
        reclaim_sim(db, thresholds={"nope": 1})
    with pytest.raises(ValueError):
        reclaim_sim(db, thresholds={"rs_target_pct": 5})              # aralık dışı


def test_no_candidates_no_change(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("e1", "host-1", 256, 150, "A"), ("e2", "host-2", 256, 150, "A")])
    c = reclaim_sim(db, hypervisor_id=hv.id)["clusters"][0]
    assert c["vms_affected"] == 0 and c["vcpu"]["freed"] == 0 and c["memory"]["freed_gb"] == 0.0
    assert c["after"]["memory_effective_pct"] == c["before"]["memory_effective_pct"]
    assert c["after"]["vcpu_ratio"] == c["before"]["vcpu_ratio"] and c["top"] == []
