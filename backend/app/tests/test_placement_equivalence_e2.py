"""E2 — tek yerleşim mantığı: What-if, toplu yerleşim, host-arızası ve "VM nereye gitsin" aynı VM için aynı
SIĞAR/SIĞMAZ kararını verir (ortak çekirdek `capacity.placement.place_vms`)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_metric import HypervisorHostMetric
from app.services import capacity_policy, virt_bulk_placement as vbp, virt_capacity_planner as vcp, virt_placement
from app.services.capacity import failover, placement
from app.services.capacity.model import ClusterModel, HaSpec, Node

NOW = datetime.now(timezone.utc)
HA_OFF = HaSpec(ha_enabled=True, admission_control_enabled=False)          # rezerv yok
HA_PCT = HaSpec(ha_enabled=True, admission_control_enabled=True, policy_type="ClusterFailoverResourcesAdmissionControlPolicy",
                mem_failover_pct=25, cpu_failover_pct=25)


@pytest.fixture(autouse=True)
def _thr():
    capacity_policy.activate(values={})
    yield
    capacity_policy.activate(values={})


def _model(ha, used=(150.0, 100.0, 60.0), mem=256.0):
    nodes = tuple(Node(name=f"esx{i + 1:02d}", mem_gb=mem, cpu_cores=32.0, mem_used_gb=u, ref=f"host-{i + 1}")
                  for i, u in enumerate(used))
    return ClusterModel(platform="vmware", name="CL", nodes=nodes, ha=ha)


def _four_paths(model, mem, thr=85.0):
    a = placement.place_on_hosts(model, vm_mem_gb=mem, vm_vcpu=2, count=1, mem_thr_pct=thr)
    hosts = placement.host_budgets(model, thr)["hosts"]
    b = vbp.place_bulk(hosts, [{"vm": "x", "profile": "x", "memory_gb": mem, "vcpu": 2, "disk_gb": 0.0, "group": None}], None, 15.0)
    c = failover.failover_place([{"name": "x", "memory_gb": mem, "vcpu": 2}], list(model.nodes), thr, None, lambda v: v["memory_gb"])
    d = placement.memory_candidates(hosts, mem)
    return a, b, c, d


@pytest.mark.parametrize("mem", [8, 40, 70, 90, 110, 130, 300])
def test_same_vm_same_fit_decision_on_all_paths_without_ha_reserve(mem):
    a, b, c, d = _four_paths(_model(HA_OFF), mem)
    fits = a["fits"]
    assert (not b["unplaced"]) == fits
    assert (c["verdict"] == "fit") == fits            # "Sınırda" fiziksel kademe ayrı bir katman; rahat sığma aynı kural
    assert bool(d) == fits
    if fits:                                          # aynı host seçilir
        assert a["placed"][0]["host"] == b["plan"][0]["host"] == c["placed"][0]["host"]
    # nedenler de tutarlı
    if not fits:
        assert a["reason"] in ("capacity", "fragmentation") and b["unplaced"][0]["reason"] in ("memory", "fragmentation")
        assert c["unplaced"][0]["reason"] == "memory" or c["verdict"] == "tight"


@pytest.mark.parametrize("mem", [8, 40, 70, 90, 130])
def test_what_if_bulk_and_candidates_agree_with_ha_reserve(mem):
    a, b, _c, d = _four_paths(_model(HA_PCT), mem)
    assert (not b["unplaced"]) == a["fits"] == bool(d)
    if a["fits"]:
        assert a["placed"][0]["host"] == b["plan"][0]["host"]


def test_ha_reserve_changes_decision_consistently():
    # reserve yokken 90 GB sığar; %25 yüzde politikası ile bütçe küçülür → hiçbir yolda sığmaz
    free_off = max(h["free_gb"] for h in placement.host_budgets(_model(HA_OFF), 85.0)["hosts"])
    free_pct = max(h["free_gb"] for h in placement.host_budgets(_model(HA_PCT), 85.0)["hosts"])
    assert free_pct < free_off
    mem = (free_off + free_pct) / 2
    a_off, b_off, _, d_off = _four_paths(_model(HA_OFF), mem)
    a_pct, b_pct, _, d_pct = _four_paths(_model(HA_PCT), mem)
    assert a_off["fits"] and not b_off["unplaced"] and d_off
    assert not a_pct["fits"] and b_pct["unplaced"] and not d_pct


def test_failover_tight_tier_is_only_extra_layer():
    # eşik bütçesi yetmez ama fiziksel boş bellek yeter → "Sınırda" (karar katmanı), diğer yollar "sığmaz" der
    m = _model(HA_OFF, used=(200.0, 200.0), mem=256.0)           # eşik 217.6 → bütçe 17.6; fiziksel boş 56
    a, b, c, d = _four_paths(m, 40)
    assert not a["fits"] and b["unplaced"] and not d
    assert c["verdict"] == "tight" and c["placed"][0]["level"] == "tight"


def test_failover_datastore_restriction_is_a_layer_on_same_core():
    m = _model(HA_OFF, used=(240.0, 100.0, 60.0))
    nodes = list(m.nodes)
    mounts = {"ds1": {"host-1"}}                                  # yalnız host-1 görüyor; host-1 dolu (boş 16 GB)
    r = failover.failover_place([{"name": "x", "memory_gb": 60.0, "datastore": "ds1"}], nodes, 85.0, mounts, lambda v: v["memory_gb"])
    assert r["verdict"] == "fail" and r["unplaced"][0]["reason"] == "datastore"
    r2 = failover.failover_place([{"name": "x", "memory_gb": 60.0, "datastore": "ds1"}], nodes, 85.0, {"ds1": {"host-3"}}, lambda v: v["memory_gb"])
    assert r2["verdict"] == "fit" and r2["placed"][0]["host"] == "esx03"


def test_core_anti_affinity_and_ordering_is_deterministic():
    hosts = [{"name": f"h{i}", "ref": f"r{i}", "free_gb": 100.0} for i in range(2)]
    vms = [{"vm": f"v{i}", "memory_gb": 10.0, "vcpu": 1, "disk_gb": 0, "group": "g"} for i in range(3)]
    r = placement.place_vms(hosts, vms)
    assert [p["host"] for p in r["plan"]] == ["h0", "h1"] and r["unplaced"][0]["reason"] == "anti_affinity"
    assert placement.place_vms(hosts, vms) == r


# ── recommend_placement (DB) aynı Memory kuralını kullanır ───────────────────

def _seed(db, rows, name="vc01"):
    hv = Hypervisor(name=name, hypervisor_type=HypervisorType.VMWARE, hostname=f"{name}.x", ip_address="10.0.0.1",
                    connection_config={})
    db.add(hv)
    db.flush()
    for hn, ref, tot, used in rows:
        db.add(HypervisorHostMetric(timestamp=NOW, hypervisor_id=hv.id, host_name=hn, host_ref=ref, cpu_cores=32,
                                    mem_total_mb=tot * 1024, mem_used_mb=used * 1024, cpu_usage_pct=10,
                                    connection_state="connected", maintenance_mode=0, cluster_name="CL"))
    db.commit()
    return hv


@pytest.mark.parametrize("mem", [10, 40, 60, 100])
def test_recommend_placement_matches_what_if_decision(isolated_db, mem):
    db = isolated_db
    hv = _seed(db, [("e1", "host-1", 256, 150), ("e2", "host-2", 256, 100), ("e3", "host-3", 256, 60)])
    sim = vcp.simulate(db, vcpu=2, memory_gb=mem, hypervisor_id=hv.id)["results"][0]["placement"]
    rec = virt_placement.recommend_placement(db, vcpu=2, memory_gb=mem, hypervisor_id=hv.id, top_n=10)
    assert rec["ok"]
    mem_ok = [c for c in rec["candidates"] if True]
    # host düzeyinde Memory kararı: What-if "sığar" ⇔ en az bir aday host (N+1 ayrı katman: bu kümede bozulmuyor)
    n1_rejected = [r for r in rec["rejected"] if "N+1" in r["reason"]]
    if not n1_rejected:
        assert bool(sim["fits"]) == bool(mem_ok)
    budget_rejections = [r for r in rec["rejected"] if r["reason"].startswith("Memory bütçesi")]
    for r in budget_rejections:
        assert "HA rezervi" in r["reason"]
    if not sim["fits"]:
        assert not rec["candidates"]


def test_recommend_placement_notes_state_shared_rule(isolated_db):
    db = isolated_db
    hv = _seed(db, [("e1", "host-1", 256, 20), ("e2", "host-2", 256, 20)])
    rec = virt_placement.recommend_placement(db, vcpu=2, memory_gb=8, hypervisor_id=hv.id)
    assert any("AYNI kuralla" in n for n in rec["notes"])
