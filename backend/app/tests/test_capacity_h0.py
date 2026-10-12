"""H.0 — hiyerarşi ve kapsam kuralı: cluster hesap birimidir, havuzlama yok, host seviyesinde yerleşim.

Zorunlu testler: aynı adlı cluster iki vCenter'da · cluster toplamı yeter ama hiçbir host'a sığmaz (parçalanma) ·
farklı cluster'ların boşu toplanmaz · datastore erişimi olmayan host'a yerleşmez · resource pool rezervasyonu düşülür ·
OCP node ↔ alttaki VM iki katmanlı sonuç. Ek: topoloji ayrıştırma, politika override önceliği.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.infra_finding import VirtConfigSnapshot
from app.models.server import Server
from app.models.virt_cluster import VirtCluster
from app.models.virt_datastore import VirtDatastore
from app.services import capacity_policy
from app.services import virt_capacity_planner as vcp
from app.services.capacity import hierarchy, nested, placement
from app.services.capacity.model import ClusterModel, HaSpec, Node, ResourcePoolSpec
from app.services.findings.collectors.vmware import parse_topology

NOW = datetime.now(timezone.utc)
HA_OFF_AC = HaSpec(ha_enabled=True, admission_control_enabled=False)    # rezerv yok → hesap yalın


@pytest.fixture(autouse=True)
def _thr():
    capacity_policy.activate(values={})
    yield
    capacity_policy.activate(values={})


def _model(free_per_host, *, mem=256.0, pools=(), refs=None, cores=32.0, thr=85.0):
    """Her host'un eşik sonrası boşu = free_per_host[i] olacak şekilde küme (HA rezervi yok)."""
    nodes = []
    for i, f in enumerate(free_per_host):
        used = mem * thr / 100.0 - f
        nodes.append(Node(name=f"esx{i + 1:02d}", mem_gb=mem, cpu_cores=cores, mem_used_gb=used,
                          ref=(refs[i] if refs else f"host-{i + 1}")))
    return ClusterModel(platform="vmware", name="CL", nodes=tuple(nodes), ha=HA_OFF_AC, pools=tuple(pools))


# ── 1) parçalanma ────────────────────────────────────────────────────────────

def test_fragmentation_total_enough_but_no_single_host():
    m = _model([40.0, 40.0, 40.0])
    r = placement.place_on_hosts(m, vm_mem_gb=64, vm_vcpu=4)
    assert sum(h["free_gb"] for h in r["host_free"]) == pytest.approx(120.0, abs=0.1)     # toplam 64'ten büyük
    assert r["fits"] is False
    assert r["verdict"] == "Sığmaz — parçalanma" and r["reason"] == "fragmentation"
    # aynı toplam tek host'ta olsaydı sığardı
    assert placement.place_on_hosts(_model([120.0, 0.0]), vm_mem_gb=64, vm_vcpu=4)["fits"] is True


def test_multiple_vms_spread_then_capacity_runs_out():
    r = placement.place_on_hosts(_model([70.0, 70.0]), vm_mem_gb=64, vm_vcpu=2, count=3)
    assert r["unplaced"] == 1 and len(r["placed"]) == 2
    assert {p["host"] for p in r["placed"]} == {"esx01", "esx02"}       # her biri ayrı host
    assert r["verdict"] == "Sığmaz — kapasite"                          # kalan toplam 12 GB < 64: parçalanma değil, yetersizlik


def test_vcpu_above_host_cores_warns():
    r = placement.place_on_hosts(_model([100.0], cores=8.0), vm_mem_gb=8, vm_vcpu=16)
    assert any("fiziksel çekirdeğ" in w for w in r["warnings"])
    assert any("NUMA" in n for n in r["notes"])                          # NUMA ölçülemedi notu


# ── 2) datastore erişimi ─────────────────────────────────────────────────────

def _ds(name, refs, free=500.0, cap=1000.0):
    return {"name": name, "free_gb": free, "capacity_gb": cap, "accessible": True, "host_refs": set(refs)}


def test_no_placement_on_host_without_datastore_access():
    m = _model([200.0, 100.0], refs=["h1", "h2"])          # esx01 daha boş ama datastore'a erişemiyor
    r = placement.place_on_hosts(m, vm_mem_gb=32, vm_vcpu=2, disk_gb=100, datastores=[_ds("DS1", ["h2"])])
    assert r["fits"] and r["placed"][0]["host"] == "esx02" and r["placed"][0]["datastore"] == "DS1"


def test_datastore_access_missing_everywhere_is_not_a_fit():
    m = _model([200.0, 200.0], refs=["h1", "h2"])
    r = placement.place_on_hosts(m, vm_mem_gb=32, vm_vcpu=2, disk_gb=100, datastores=[_ds("DS1", ["h9"])])
    assert r["fits"] is False and r["verdict"] == "Sığmaz — datastore erişimi yok"


def test_datastore_unknown_is_noted_not_blocking():
    r = placement.place_on_hosts(_model([200.0]), vm_mem_gb=32, vm_vcpu=2, disk_gb=100, datastores=None)
    assert r["fits"] and any("erişimi okunamadı" in n for n in r["notes"])


# ── 3) resource pool rezervasyonu ────────────────────────────────────────────

def test_pool_reservation_is_subtracted_from_free():
    base = placement.place_on_hosts(_model([100.0, 100.0]), vm_mem_gb=8, vm_vcpu=1)
    pool = ResourcePoolSpec(name="Prod", mem_reservation_gb=100.0)           # kullanım bilinmiyor → tamamı düşülür
    r = placement.place_on_hosts(_model([100.0, 100.0], pools=[pool]), vm_mem_gb=8, vm_vcpu=1)
    assert base["cluster_free_gb"] - r["cluster_free_gb"] == pytest.approx(100.0 * 0.85, abs=0.2)
    assert r["pools"][0]["deducted_gb"] == 100.0
    assert any("tamamı boş kapasiteden düşüldü" in n for n in r["notes"])
    assert r["confidence"] == "high"


def test_pool_reservation_can_make_vm_not_fit():
    pool = ResourcePoolSpec(name="Prod", mem_reservation_gb=150.0)
    r = placement.place_on_hosts(_model([40.0, 40.0], pools=[pool]), vm_mem_gb=30, vm_vcpu=1)
    assert r["fits"] is False


def test_pool_used_memory_reduces_deduction():
    pool = ResourcePoolSpec(name="Prod", mem_reservation_gb=100.0, used_mem_gb=70.0)
    assert placement.pool_deduction([pool])["deduct_gb"] == 30.0


def test_pools_unread_is_low_confidence_with_note():
    m = ClusterModel(platform="vmware", name="CL", nodes=_model([100.0]).nodes, ha=HA_OFF_AC, pools=None)
    r = placement.place_on_hosts(m, vm_mem_gb=8, vm_vcpu=1)
    assert r["confidence"] == "low" and placement.NOTE_POOLS_UNREAD in r["notes"]


# ── 4) topoloji ayrıştırma ───────────────────────────────────────────────────

def test_parse_topology_datacenter_and_top_level_pools():
    dcs = [{"_ref": "datacenter-2", "name": "DC-IST"}]
    folders = [{"_ref": "group-h4", "parent": {"_value": "datacenter-2"}}]
    clusters = [{"_ref": "domain-c7", "name": "CL-PROD", "parent": {"_value": "group-h4"}}]
    pools = [
        {"_ref": "resgroup-8", "owner": {"_value": "domain-c7"}, "parent": {"_value": "group-h4"}, "name": "Resources"},
        {"_ref": "resgroup-9", "owner": {"_value": "domain-c7"}, "parent": {"_value": "resgroup-8"}, "name": "Prod",
         "config.cpuAllocation": {"reservation": 2000, "limit": -1},
         "config.memoryAllocation": {"reservation": 51200, "limit": -1, "expandableReservation": True}},
        {"_ref": "resgroup-10", "owner": {"_value": "domain-c7"}, "parent": {"_value": "resgroup-9"}, "name": "Alt"},
    ]
    out = parse_topology(clusters, folders, dcs, pools)["domain-c7"]
    assert out["datacenter"] == "DC-IST"
    assert [p["name"] for p in out["pools"]] == ["Prod"]                  # kök ve alt havuz sayılmaz
    assert out["pools"][0]["mem_reservation_mb"] == 51200 and out["pools"][0]["expandable"] is True
    # havuz verisi hiç gelmezse "okunamadı" (None) — boş liste ile karışmaz
    assert parse_topology(clusters, folders, dcs, [])["domain-c7"]["pools"] is None


# ── 5) OCP node ↔ alttaki VM: iki katmanlı sonuç ─────────────────────────────

def _vm(name, hid, cluster, host):
    return {"name": name, "hypervisor_id": hid, "cluster": cluster, "host": host}


def _cl(hid, inst, cluster, n1="ok", dc="DC1"):
    return {"hypervisor_id": hid, "hypervisor": inst, "cluster": cluster, "datacenter": dc, "platform": "vmware",
            "n_plus_one": {"status": n1}}


def test_ocp_node_to_underlying_vm_two_layer_path():
    vms = [_vm("worker-1", 1, "CL-PROD", "esx01"), _vm("worker-2", 1, "CL-PROD", "esx01"),
           _vm("worker-1", 2, "CL-DEV", "esx09")]
    r = nested.match_underlay(["worker-1.ocp.example.com", "worker-3"], vms[:2], [_cl(1, "vc01", "CL-PROD", n1="fail")])
    n0, n1 = r["nodes"]
    assert n0["matched"] and n0["path"] == "vc01 / DC1 / CL-PROD / esx01"
    assert n1["matched"] is False and nested.NOTE_NO_MATCH in n1["notes"]
    u = r["clusters"][0]
    assert u["n1_status"] == "fail"                                       # alt katmanın kendi N+1'i
    assert any("N+1 bozulur" in n for n in r["notes"])
    r2 = nested.match_underlay(["worker-1", "worker-2"], vms[:2], [_cl(1, "vc01", "CL-PROD")])
    assert any("aynı fiziksel host" in n for n in r2["notes"])           # iki node aynı host'ta
    # farklı instance'larda aynı ad → belirsiz, eşleme yok
    amb = nested.match_underlay(["worker-1"], [vms[0], vms[2]], [_cl(1, "vc01", "CL-PROD"), _cl(2, "vc02", "CL-DEV")])
    assert amb["nodes"][0]["ambiguous"] and not amb["nodes"][0]["matched"]


# ── 6) hiyerarşi kimlikleri / yol ────────────────────────────────────────────

def test_cluster_key_includes_instance_and_path_format():
    assert hierarchy.cluster_key(1, "PROD") != hierarchy.cluster_key(2, "PROD")
    assert hierarchy.path_str("vc01", "DC-IST", "CL-PROD-01", "esx03") == "vc01 / DC-IST / CL-PROD-01 / esx03"
    assert hierarchy.path_str("ocp-prod", "worker", None, "node-07") == "ocp-prod / worker / node-07"
    assert hierarchy.path_str("vc01", None, "CL").startswith("vc01 / ? /")      # uydurma ad yok


# ── 7) DB uçtan uca: aynı adlı cluster iki vCenter'da + havuzlama yok ───────────

def _seed_vc(db, name, cluster, hosts, *, ds_hosts=None):
    """hosts: [(host_name, host_ref, mem_total_gb, mem_used_gb)]"""
    hv = Hypervisor(name=name, hypervisor_type=HypervisorType.VMWARE, hostname=f"{name}.x", ip_address="10.0.0.1",
                    connection_config={})
    db.add(hv)
    db.flush()
    db.add(VirtCluster(hypervisor_id=hv.id, name=cluster, ha_enabled=True, admission_control_enabled=False, as_of=NOW))
    for hn, ref, tot, used in hosts:
        db.add(HypervisorHostMetric(timestamp=NOW, hypervisor_id=hv.id, host_name=hn, host_ref=ref, cpu_cores=32,
                                    mem_total_mb=tot * 1024, mem_used_mb=used * 1024, cpu_usage_pct=10,
                                    connection_state="connected", maintenance_mode=0, cluster_name=cluster))
    db.commit()
    return hv


def test_same_cluster_name_on_two_vcenters_never_mixes(isolated_db):
    db = isolated_db
    a = _seed_vc(db, "vc01", "PROD", [("esx01", "host-1", 256, 200), ("esx02", "host-2", 256, 200)])   # dolu
    b = _seed_vc(db, "vc02", "PROD", [("esx01", "host-1", 256, 20), ("esx02", "host-2", 256, 20)])     # boş
    res = vcp.simulate(db, vcpu=4, memory_gb=64)
    by_inst = {r["hypervisor"]: r for r in res["results"]}
    assert set(by_inst) == {"vc01", "vc02"} and len(res["results"]) == 2
    assert by_inst["vc01"]["fits"] is False and by_inst["vc02"]["fits"] is True
    assert by_inst["vc02"]["path"] == "vc02 / ? / PROD" and by_inst["vc02"]["verdict"] == "Sığar"
    assert by_inst["vc02"]["placement"]["placed"][0]["path"].startswith("vc02 / ? / PROD / esx0")
    assert res["best"]["hypervisor"] == "vc02"
    # kapsam seçici: yalnız vc01 → yalnız onun sonucu
    only = vcp.simulate(db, vcpu=4, memory_gb=64, hypervisor_id=a.id)
    assert [r["hypervisor"] for r in only["results"]] == ["vc01"]


def test_free_capacity_is_not_pooled_across_clusters(isolated_db):
    db = isolated_db
    # iki cluster: her birinin tek host'unda ~40 GB boş (toplam ~80 GB > 64 GB) — toplanarak "sığar" denmemeli
    _seed_vc(db, "vc01", "A", [("e1", "host-1", 256, 177), ("e2", "host-2", 256, 256 * 0.85 + 1)])
    _seed_vc(db, "vc02", "B", [("e1", "host-1", 256, 177), ("e2", "host-2", 256, 256 * 0.85 + 1)])
    res = vcp.simulate(db, vcpu=2, memory_gb=64)
    assert len(res["results"]) == 2 and not any(r["fits"] for r in res["results"])
    assert res["best"] is None or not res["best"]["fits"]


def test_datastore_access_end_to_end_vmware(isolated_db):
    db = isolated_db
    hv = _seed_vc(db, "vc01", "PROD", [("esx01", "host-1", 256, 20), ("esx02", "host-2", 256, 120)])
    db.add(VirtDatastore(hypervisor_id=hv.id, ds_ref="datastore-1", name="DS1", capacity_gb=1000, free_gb=600,
                         used_gb=400, usage_pct=40, accessible=True, as_of=NOW))
    db.add_all([
        VirtConfigSnapshot(platform="vmware", source_id=hv.id, entity_kind="cluster", entity_ref="domain-c1",
                           entity_name="PROD", cluster_name="PROD", payload={"config": {"datastore_refs": ["datastore-1"]}},
                           payload_hash="a", is_latest=True),
        VirtConfigSnapshot(platform="vmware", source_id=hv.id, entity_kind="datastore", entity_ref="datastore-1",
                           entity_name="DS1", cluster_name=None, payload={"config": {"mounted_hosts": ["host-2"]}},
                           payload_hash="b", is_latest=True),
    ])
    db.commit()
    res = vcp.simulate(db, vcpu=2, memory_gb=16, disk_gb=100, hypervisor_id=hv.id)
    pl = res["results"][0]["placement"]
    assert pl["placed"][0]["host"] == "esx02"          # esx01 çok daha boş ama DS1'e erişemiyor
    assert pl["placed"][0]["datastore"] == "DS1"
    # hosts kapsamı yalnız erişimsiz host ile sınırlanırsa sığmaz
    res2 = vcp.simulate(db, vcpu=2, memory_gb=16, disk_gb=100, hypervisor_id=hv.id, hosts=["esx01"])
    assert res2["results"][0]["fits"] is False
    assert res2["results"][0]["verdict"] == "Sığmaz — datastore erişimi yok"


# ── 8) politika: global < instance < cluster ─────────────────────────────────

def test_policy_override_precedence_and_per_cluster_thresholds(isolated_db):
    db = isolated_db
    hv = _seed_vc(db, "vc01", "A", [("e1", "host-1", 256, 20), ("e2", "host-2", 256, 20)])
    capacity_policy.save(db, {"memory": 80})
    assert capacity_policy.effective(db, hv.id, "A")["memory"] == 80
    capacity_policy.save_override(db, hv.id, None, {"memory": 75})            # instance varsayılanı
    assert capacity_policy.effective(db, hv.id, "A")["memory"] == 75
    assert capacity_policy.effective(db, hv.id, "B")["memory"] == 75
    capacity_policy.save_override(db, hv.id, "A", {"memory": 60})             # cluster override
    assert capacity_policy.effective(db, hv.id, "A")["memory"] == 60
    assert capacity_policy.effective(db, hv.id, "B")["memory"] == 75
    cap = vcp.build_capacity(db, with_forecast=False)
    assert cap["clusters"][0]["thresholds"]["memory"] == 60
    assert capacity_policy.delete_override(db, hv.id, "A", "memory") == 1
    assert capacity_policy.effective(db, hv.id, "A")["memory"] == 75
    with pytest.raises(ValueError):
        capacity_policy.save_override(db, hv.id, "A", {"memory": 5})          # sınır dışı reddedilir


# ── 9) açık taşıma senaryosu (H.0 #10) ───────────────────────────────────────

def test_explicit_move_scenario_computes_both_clusters_separately(isolated_db):
    db = isolated_db
    a = _seed_vc(db, "vc01", "A", [("e1", "host-1", 256, 150), ("e2", "host-2", 256, 150)])
    b = _seed_vc(db, "vc02", "B", [("e1", "host-1", 256, 20), ("e2", "host-2", 256, 20)])
    r = vcp.move_scenario(db, vcpu=4, memory_gb=32, count=2, from_hypervisor_id=a.id, from_cluster="A",
                          to_hypervisor_id=b.id, to_cluster="B")
    assert r["ok"] and r["target"]["fits"] is True
    assert r["target"]["path"] == "vc02 / ? / B"
    assert r["source"]["freed_memory_gb"] == 64.0
    assert r["source"]["effective_used_pct_after"] < r["source"]["effective_used_pct_before"]
    same = vcp.move_scenario(db, vcpu=4, memory_gb=32, from_hypervisor_id=a.id, from_cluster="A",
                             to_hypervisor_id=a.id, to_cluster="A")
    assert same["ok"] is False
    missing = vcp.move_scenario(db, vcpu=4, memory_gb=32, from_hypervisor_id=a.id, from_cluster="A",
                                to_hypervisor_id=b.id, to_cluster="YOK")
    assert missing["ok"] is False


def test_simulate_never_places_outside_the_cluster_scope(isolated_db):
    """Cluster kapsamı verilince başka cluster'a yerleştirme önerilmez (motor kendiliğinden taşmaz)."""
    db = isolated_db
    a = _seed_vc(db, "vc01", "A", [("e1", "host-1", 256, 217), ("e2", "host-2", 256, 217)])   # dolu
    _seed_vc(db, "vc01b", "B", [("e1", "host-1", 256, 10), ("e2", "host-2", 256, 10)])        # boş ama kapsam dışı
    res = vcp.simulate(db, vcpu=2, memory_gb=64, hypervisor_id=a.id, clusters=["A"])
    assert len(res["results"]) == 1 and res["results"][0]["cluster"] == "A" and res["results"][0]["fits"] is False
