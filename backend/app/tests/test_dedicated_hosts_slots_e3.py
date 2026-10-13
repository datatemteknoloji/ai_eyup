"""E3 — vCenter "ayrılmış failover host" ve slot politikası: ayrılmış host yerleşime kapalı, slot yoksa VM sığmaz."""
from __future__ import annotations

import pytest

from app.services import capacity_policy
from app.services.capacity import engine, placement, rules_vmware
from app.services.capacity.model import ClusterModel, HaSpec, Node

DED = "ClusterFailoverHostAdmissionControlPolicy"
SLOT = "ClusterFailoverLevelAdmissionControlPolicy"


@pytest.fixture(autouse=True)
def _thr():
    capacity_policy.activate(values={})
    yield
    capacity_policy.activate(values={})


def _model(ha, used=(100.0, 100.0, 0.0)):
    nodes = tuple(Node(name=f"esx{i + 1:02d}", mem_gb=256.0, cpu_cores=32.0, mem_used_gb=u, ref=f"host-{i + 1}")
                  for i, u in enumerate(used))
    return ClusterModel(platform="vmware", name="CL", nodes=nodes, ha=ha)


def _ha(policy, **kw):
    return HaSpec(ha_enabled=True, admission_control_enabled=True, policy_type=policy, **kw)


def test_dedicated_host_closed_to_placement():
    m = _model(_ha(DED, failover_hosts=("host-3",)))
    b = placement.host_budgets(m, 85.0)
    assert [h["name"] for h in b["hosts"]] == ["esx01", "esx02"]
    assert b["closed_hosts"] == ["esx03"]
    assert engine.reserve_for(m)["mem_gb"] == 256.0
    # esx03 boş olsa da 2 host yeterli değilse ona yerleşmez: 2×(217.6-100)=235 GB < 240
    r = placement.place_on_hosts(m, vm_mem_gb=120.0, vm_vcpu=2, count=2, mem_thr_pct=85.0)
    assert {p["host"] for p in r["placed"]} <= {"esx01", "esx02"}
    assert any("yerleşime kapalı" in n for n in r["notes"])
    r2 = placement.place_on_hosts(m, vm_mem_gb=120.0, vm_vcpu=2, count=3, mem_thr_pct=85.0)
    assert not r2["fits"]


def test_dedicated_unread_assumes_one_host_labelled():
    rs = engine.reserve_for(_model(_ha(DED)))
    assert rs["assumed"] is True and rs["mem_gb"] == 256.0 and "okunamadı" in rs["label"]


def test_dedicated_none_usable_no_reserve():
    rs = engine.reserve_for(_model(_ha(DED, failover_hosts=("host-99",))))
    assert rs["mem_gb"] == 0.0 and "kullanılabilir değil" in rs["label"]


def test_slot_blocks_even_when_memory_fits():
    m = _model(_ha(SLOT, failover_level=1, total_slots=100, used_slots=98, unreserved_slots=2), used=(10.0, 10.0, 10.0))
    ok = placement.place_on_hosts(m, vm_mem_gb=4.0, vm_vcpu=1, count=2, mem_thr_pct=85.0)
    assert ok["fits"] and ok["slots"]["fits"]
    no = placement.place_on_hosts(m, vm_mem_gb=4.0, vm_vcpu=1, count=3, mem_thr_pct=85.0)
    assert not no["fits"] and no["verdict"] == placement.V_SLOT
    assert no["limiting"] == ["ha_slots"] and no["max_fit"] == 2


def test_slot_not_applied_for_other_policies_or_unread():
    m = _model(_ha("ClusterFailoverResourcesAdmissionControlPolicy", mem_failover_pct=25, cpu_failover_pct=25))
    assert rules_vmware.slot_check(m, 5) is None
    m2 = _model(_ha(SLOT, failover_level=1))
    assert rules_vmware.slot_check(m2, 5) is None
    r = placement.place_on_hosts(m2, vm_mem_gb=4.0, vm_vcpu=1, count=2, mem_thr_pct=85.0)
    assert "slots" not in r
