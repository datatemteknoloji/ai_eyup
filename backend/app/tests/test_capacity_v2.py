"""What-if v2: gerekçe kodları, en fazla kaç VM sığar, bağımsız host (cluster yok) ayrı birim."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_metric import HypervisorHostMetric
from app.services import capacity_policy
from app.services import virt_capacity_planner as vcp
from app.services.capacity import engine, hierarchy, placement
from app.services.capacity.model import ClusterModel, HaSpec, Node

NOW = datetime.now(timezone.utc)
HA_OFF_AC = HaSpec(ha_enabled=True, admission_control_enabled=False)


@pytest.fixture(autouse=True)
def _thr():
    capacity_policy.activate(values={})
    yield
    capacity_policy.activate(values={})


def _model(free_per_host, *, mem=256.0, thr=85.0):
    nodes = [Node(name=f"esx{i + 1:02d}", mem_gb=mem, cpu_cores=32.0, mem_used_gb=mem * thr / 100.0 - f,
                  ref=f"host-{i + 1}") for i, f in enumerate(free_per_host)]
    return ClusterModel(platform="vmware", name="CL", nodes=tuple(nodes), ha=HA_OFF_AC)


# ── hierarchy ────────────────────────────────────────────────────────────────

def test_cluster_label_and_standalone():
    assert hierarchy.cluster_label("PROD", "esx1") == "PROD"
    assert hierarchy.cluster_label(None, "esx1") == "(cluster yok) · esx1"
    assert hierarchy.cluster_label("", None) == "(cluster yok)"
    assert hierarchy.is_standalone("(cluster yok) · esx1") and not hierarchy.is_standalone("PROD")


# ── host seviyesi max_fit / gerekçe kodu ─────────────────────────────────────

def test_max_fit_counts_extra_vms_beyond_requested():
    r = placement.place_on_hosts(_model([70.0, 70.0]), vm_mem_gb=32, vm_vcpu=2, count=1)
    assert r["fits"] and r["limiting"] == []
    assert r["max_fit"] == 4            # her host 70 GB → 2 VM


def test_max_fit_when_not_fitting_is_placed_count():
    r = placement.place_on_hosts(_model([70.0, 70.0]), vm_mem_gb=32, vm_vcpu=2, count=6)
    assert not r["fits"] and r["max_fit"] == 4 and r["limiting"] == ["memory"]


def test_fragmentation_code():
    r = placement.place_on_hosts(_model([40.0, 40.0, 40.0]), vm_mem_gb=64, vm_vcpu=4)
    assert r["limiting"] == ["fragmentation"] and r["max_fit"] == 0


def test_datastore_code_and_no_host_code():
    ds = [{"name": "DS1", "free_gb": 1000, "capacity_gb": 1000, "accessible": True, "host_refs": {"h9"}}]
    r = placement.place_on_hosts(_model([100.0]), vm_mem_gb=8, vm_vcpu=1, disk_gb=50, datastores=ds)
    assert r["limiting"] == ["datastore"]
    empty = ClusterModel(platform="vmware", name="CL", nodes=(), ha=HA_OFF_AC)
    assert placement.place_on_hosts(empty, vm_mem_gb=8, vm_vcpu=1)["limiting"] == ["no_host"]


def test_max_fit_unknown_without_memory_and_disk():
    assert placement.place_on_hosts(_model([100.0]), vm_mem_gb=0, vm_vcpu=1)["max_fit"] is None


# ── cluster kapısı: kodlar ve en fazla ───────────────────────────────────────

def _cluster(used=100.0, eff=200.0, total=256.0, rem=128.0):
    return {"memory": {"used_gb": used, "effective_gb": eff}, "cpu": {"used_cores": 4, "effective_cores": 32,
            "vcpu_allocated": 8, "total_cores": 32}, "n_plus_one": {"remaining_mem_gb": rem}, "hosts_usable": 2,
            "typical_host_cores": 32}


class _T:
    mem, cpu, n1_warn, vcpu_ratio = 85.0, 80.0, 90.0, 4.0


def test_place_reports_limiting_codes():
    c = _cluster(used=120.0, eff=140.0, rem=128.0)
    r = engine.place(c, add_mem=40.0, add_cpu=1.0, add_vcpu=2, vcpu_single=2, thr=_T)
    assert not r["fits"] and r["limiting"] == ["memory", "ha"]


def test_place_cpu_warning_does_not_block():
    c = _cluster(used=10.0)
    c["cpu"]["used_cores"] = 30
    r = engine.place(c, add_mem=1.0, add_cpu=1.0, add_vcpu=1, vcpu_single=1, thr=_T)
    assert r["fits"] and r["limiting"] == [] and "cpu" in r["warn_codes"]


def test_max_additional_takes_tightest_gate():
    c = _cluster(used=100.0, eff=200.0, rem=130.0)       # eşik 170 → (170-100)/10=7 ; N+1 (130-100)/10=3
    assert engine.max_additional(c, mem_each=10.0, thr=_T) == 3
    assert engine.max_additional(c, mem_each=0.0, thr=_T) is None
    c["hosts_usable"] = 0
    assert engine.max_additional(c, mem_each=10.0, thr=_T) == 0


# ── uçtan uca: bağımsız host ayrı birim, max_fit / status ────────────────────

def _seed(db, name, rows):
    hv = Hypervisor(name=name, hypervisor_type=HypervisorType.VMWARE, hostname=f"{name}.x", ip_address="10.0.0.1",
                    connection_config={})
    db.add(hv)
    db.flush()
    for hn, ref, tot, used, cl in rows:
        db.add(HypervisorHostMetric(timestamp=NOW, hypervisor_id=hv.id, host_name=hn, host_ref=ref, cpu_cores=32,
                                    mem_total_mb=tot * 1024, mem_used_mb=used * 1024, cpu_usage_pct=10,
                                    connection_state="connected", maintenance_mode=0, cluster_name=cl))
    db.commit()
    return hv


def test_standalone_hosts_are_separate_units(isolated_db):
    db = isolated_db
    _seed(db, "vc01", [("sa1", "host-1", 256, 20, None), ("sa2", "host-2", 256, 20, None)])
    res = vcp.simulate(db, vcpu=2, memory_gb=16)
    names = sorted(r["cluster"] for r in res["results"])
    assert names == ["(cluster yok) · sa1", "(cluster yok) · sa2"]
    assert all(r["standalone"] for r in res["results"])
    assert all(len(r["placement"]["host_free"]) == 1 for r in res["results"])      # havuzlanmadı
    assert any("bağımsız host" in a for a in res["assumptions"])


def test_simulate_returns_status_limiting_and_max_fit(isolated_db):
    db = isolated_db
    _seed(db, "vc01", [("e1", "host-1", 256, 20, "A"), ("e2", "host-2", 256, 20, "A")])
    ok = vcp.simulate(db, vcpu=2, memory_gb=16, count=2)["results"][0]
    assert ok["fits"] and ok["status"] in ("ok", "warn") and ok["limiting"] == []
    assert isinstance(ok["max_fit"], int) and ok["max_fit"] >= 2
    big = vcp.simulate(db, vcpu=2, memory_gb=100, count=20)["results"][0]
    assert not big["fits"] and big["status"] == "fail" and "memory" in big["limiting"]
    assert big["max_fit"] < 20


def test_platform_filter_limits_results(isolated_db):
    db = isolated_db
    _seed(db, "vc01", [("e1", "host-1", 256, 20, "A")])
    assert len(vcp.simulate(db, vcpu=2, memory_gb=8, platforms=["vmware"])["results"]) == 1
    assert vcp.simulate(db, vcpu=2, memory_gb=8, platforms=["olvm"])["results"] == []


def test_hosts_scope_adds_assumption_note(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("e1", "host-1", 256, 20, "A"), ("e2", "host-2", 256, 20, "A")])
    res = vcp.simulate(db, vcpu=2, memory_gb=8, hypervisor_id=hv.id, hosts=["e1"])
    assert any("Host kapsamı" in a for a in res["assumptions"])


# ── host arızası senaryosu ───────────────────────────────────────────────────

def _vm(db, hv, name, host, mem_gb, cluster="A", on=True, datastore=None):
    from app.models.server import Server
    db.add(Server(name=name, vm_name=name, hypervisor_id=hv.id, vm_host_name=host, vm_cluster=cluster,
                  vm_memory_mb=int(mem_gb * 1024), vm_cpu_count=2, vm_power_state="poweredOn" if on else "poweredOff",
                  vm_datastore=datastore))
    db.commit()


def test_host_failure_fits_when_remaining_hosts_have_room(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("e1", "host-1", 256, 100, "A"), ("e2", "host-2", 256, 20, "A"), ("e3", "host-3", 256, 20, "A")])
    _vm(db, hv, "vm-a", "e1", 40)
    _vm(db, hv, "vm-b", "e1", 30)
    _vm(db, hv, "vm-off", "e1", 90, on=False)         # kapalı VM taşınmaz
    r = vcp.host_failure(db, hypervisor_id=hv.id, cluster="A", hosts=["e1"])
    assert r["ok"] and r["verdict"] == "fit" and r["status"] == "ok"
    assert r["displaced"]["count"] == 2 and r["displaced"]["memory_gb"] == 70.0
    assert {p["host"] for p in r["placed"]} <= {"e2", "e3"} and not r["unplaced"]
    assert r["remaining_hosts"] == ["e2", "e3"]


def test_host_failure_tight_between_threshold_and_physical(isolated_db):
    db = isolated_db
    # e2: 256 GB, 200 kullanılıyor → eşik (%85=217.6) altı boş 17.6, fiziksel boş 56
    hv = _seed(db, "vc01", [("e1", "host-1", 256, 100, "A"), ("e2", "host-2", 256, 200, "A")])
    _vm(db, hv, "vm-a", "e1", 40)
    r = vcp.host_failure(db, hypervisor_id=hv.id, cluster="A", hosts=["e1"])
    assert r["verdict"] == "tight" and r["status"] == "warn" and r["placed"][0]["level"] == "tight"


def test_host_failure_does_not_fit(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("e1", "host-1", 256, 100, "A"), ("e2", "host-2", 256, 230, "A")])
    _vm(db, hv, "big", "e1", 60)
    r = vcp.host_failure(db, hypervisor_id=hv.id, cluster="A", hosts=["e1"])
    assert r["verdict"] == "fail" and r["unplaced"] == [{"vm": "big", "memory_gb": 60.0, "reason": "memory"}]


def test_host_failure_standalone_host_has_no_failover(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("sa1", "host-1", 256, 100, None)])
    _vm(db, hv, "vm-a", "sa1", 20, cluster=None)
    r = vcp.host_failure(db, hypervisor_id=hv.id, cluster="(cluster yok) · sa1", hosts=["sa1"])
    assert r["verdict"] == "fail" and r["remaining_hosts"] == [] and any("failover mümkün değil" in n for n in r["notes"])


def test_host_failure_without_vms_and_unknown_host(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("e1", "host-1", 256, 10, "A"), ("e2", "host-2", 256, 10, "A")])
    assert vcp.host_failure(db, hypervisor_id=hv.id, cluster="A", hosts=["e1"])["verdict"] == "no_vm"
    assert vcp.host_failure(db, hypervisor_id=hv.id, cluster="A", hosts=["zzz"])["ok"] is False
    assert vcp.host_failure(db, hypervisor_id=hv.id, cluster="A", hosts=[])["ok"] is False


# ── host arızası: p95 + CPU ──────────────────────────────────────────────────

def _p95(db, hv, name, cpu, mem, n=5):
    from datetime import timedelta
    from app.models.virt_metric import VirtVmMetric
    for i in range(n):
        db.add(VirtVmMetric(timestamp=NOW - timedelta(hours=i + 1), hypervisor_id=hv.id, vm_ref=f"ref-{name}",
                            vm_name=name, power_state="poweredOn", cpu_usage_pct=cpu, mem_usage_pct=mem))
    db.commit()


def test_host_failure_defined_and_p95_memory_side_by_side(isolated_db):
    db = isolated_db
    # e2: eşik altı boş 17.6 GB → tanımlı 40 GB sığmaz-eşik-üstü (sınırda), p95 (10 GB) rahat sığar
    hv = _seed(db, "vc01", [("e1", "host-1", 256, 100, "A"), ("e2", "host-2", 256, 200, "A")])
    _vm(db, hv, "vm-a", "e1", 40)
    _p95(db, hv, "vm-a", cpu=10, mem=25)
    r = vcp.host_failure(db, hypervisor_id=hv.id, cluster="A", hosts=["e1"])
    assert r["memory"]["defined"]["verdict"] == "tight" and r["memory"]["p95"]["verdict"] == "fit"
    assert r["memory"]["p95"]["placed"][0]["memory_gb"] == 10.0
    assert r["verdict"] == "tight" and r["overall"]["verdict"] == "tight"       # eski alan = tanımlı sonuç
    assert r["p95"]["coverage"] == {"vms_total": 1, "mem_with_p95": 1, "cpu_with_p95": 1}


def test_host_failure_vms_without_p95_use_defined_values(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("e1", "host-1", 256, 100, "A"), ("e2", "host-2", 256, 20, "A")])
    _vm(db, hv, "vm-a", "e1", 40)
    _vm(db, hv, "vm-b", "e1", 30)
    _p95(db, hv, "vm-a", cpu=10, mem=50)
    r = vcp.host_failure(db, hypervisor_id=hv.id, cluster="A", hosts=["e1"])
    assert r["p95"]["coverage"]["vms_total"] == 2 and r["p95"]["coverage"]["mem_with_p95"] == 1
    sizes = {p["vm"]: p["memory_gb"] for p in r["memory"]["p95"]["placed"]}
    assert sizes == {"vm-a": 20.0, "vm-b": 30.0}                                # vm-b tanımlı değerle


def test_cpu_check_rules():
    from app.services.capacity import failover as f
    cov = {"vms_total": 3, "mem_with_p95": 3, "cpu_with_p95": 3}
    ok = f.cpu_check(remaining_cores=64, vcpu_total=100, demand_cores=20, thr_pct=80, ratio_limit=4, cov=cov)
    assert ok["verdict"] == "fit" and ok["ratio_warn"] is False
    warn_only = f.cpu_check(remaining_cores=16, vcpu_total=100, demand_cores=4, thr_pct=80, ratio_limit=4, cov=cov)
    assert warn_only["verdict"] == "fit" and warn_only["ratio_warn"] is True       # oran karara karışmaz
    tight = f.cpu_check(remaining_cores=10, vcpu_total=20, demand_cores=9, thr_pct=80, ratio_limit=4, cov=cov)
    assert tight["verdict"] == "tight" and tight["limiting"] == "cpu"
    fail = f.cpu_check(remaining_cores=10, vcpu_total=20, demand_cores=11, thr_pct=80, ratio_limit=4, cov=cov)
    assert fail["verdict"] == "fail"
    assert f.cpu_check(remaining_cores=0, vcpu_total=5, demand_cores=1, thr_pct=80, ratio_limit=4,
                       cov=cov)["limiting"] == "no_host"


def test_host_failure_cpu_fail_makes_overall_fail_but_memory_fits(isolated_db):
    db = isolated_db
    # her host 32 çekirdek; kalan 32 çekirdek. VM'ler 40 vCPU, p95 %100 → talep 40 > 32 → Sığmaz (CPU)
    hv = _seed(db, "vc01", [("e1", "host-1", 256, 50, "A"), ("e2", "host-2", 256, 20, "A")])
    from app.models.server import Server
    db.add(Server(name="big", vm_name="big", hypervisor_id=hv.id, vm_host_name="e1", vm_cluster="A", vm_memory_mb=8192,
                  vm_cpu_count=40, vm_power_state="poweredOn"))
    db.commit()
    _p95(db, hv, "big", cpu=100, mem=50)
    r = vcp.host_failure(db, hypervisor_id=hv.id, cluster="A", hosts=["e1"])
    assert r["verdict"] == "fit"                                                   # Memory sığıyor
    assert r["cpu"]["verdict"] == "fail" and r["overall"]["verdict"] == "fail"
    assert r["overall"]["limiting"] == ["cpu"] and r["cpu"]["ratio_warn"] is False  # 40/32 = 1.25 < 4: oran uyarısı yok


# ── host arızası matrisi (her host için N+1) ─────────────────────────────────

def test_host_failure_matrix_her_host_icin_tekil_hesapla_ayni(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("e1", "host-1", 256, 100, "A"), ("e2", "host-2", 256, 230, "A"), ("e3", "host-3", 256, 10, "A")])
    _vm(db, hv, "vm-a", "e1", 40)
    _vm(db, hv, "big", "e2", 60)
    m = vcp.host_failure_matrix(db, hypervisor_id=hv.id, cluster="A")
    assert m["ok"] and m["hosts_total"] == 3 and m["single_host"] is False
    assert sorted(r["host"] for r in m["rows"]) == ["e1", "e2", "e3"]
    rank = {"fail": 0, "tight": 1, "fit": 2, "no_vm": 3}                   # F3: backend sırası riske göre (en kötü önce)
    ranks = [rank[r["overall"]["verdict"]] for r in m["rows"]]
    assert ranks == sorted(ranks)
    for a, b in zip(m["rows"], m["rows"][1:]):                             # eşitlikte host adı
        if rank[a["overall"]["verdict"]] == rank[b["overall"]["verdict"]]:
            assert a["host"] < b["host"]
    from app.services import method_registry as mr
    assert mr.resolve("cap.sim.host_failure_matrix") is not None and mr.resolve("cap.sim.host_failure") is not None
    for r in m["rows"]:                                                    # satır = tekil host_failure sonucu
        one = vcp.host_failure(db, hypervisor_id=hv.id, cluster="A", hosts=[r["host"]])
        assert r["overall"] == one["overall"] and r["vms"] == one["displaced"]["count"]
        assert r["defined"]["verdict"] == one["memory"]["defined"]["verdict"]
        assert r["p95"]["verdict"] == one["memory"]["p95"]["verdict"]
        assert r["remaining_hosts"] == len(one["remaining_hosts"]) and r["no_remaining_host"] is False
    by = {r["host"]: r for r in m["rows"]}
    assert by["e3"]["vms"] == 0 and by["e3"]["overall"]["verdict"] == "no_vm" and by["e3"]["cpu"] is None


def test_host_failure_matrix_tek_host_ve_bilinmeyen_cluster(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("sa1", "host-1", 256, 100, None)])
    _vm(db, hv, "vm-a", "sa1", 20, cluster=None)
    m = vcp.host_failure_matrix(db, hypervisor_id=hv.id, cluster="(cluster yok) · sa1")
    assert m["ok"] and m["single_host"] is True
    assert m["rows"][0]["no_remaining_host"] is True and m["rows"][0]["overall"]["verdict"] == "fail"
    assert m["rows"][0]["overall"]["limiting"] == ["no_host"]
    assert vcp.host_failure_matrix(db, hypervisor_id=hv.id, cluster="yok")["ok"] is False
