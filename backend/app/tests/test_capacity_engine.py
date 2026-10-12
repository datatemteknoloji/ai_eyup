"""H Faz 1: ortak kapasite motoru — eski motorlarla eşdeğerlik + platform birim testleri.

Eşdeğerlik: aynı girdiler → aynı sonuçlar (referans = eski motor, CAPACITY_ENGINE=legacy ile korunan kod).
"""
from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from app.services import capacity_policy, ocp_capacity_sim
from app.services import virt_capacity_planner as vcp
from app.services.capacity import adapters, engine, engine_mode
from app.services.capacity.model import ClusterModel, HaSpec, Node


@pytest.fixture(autouse=True)
def _default_thresholds():
    capacity_policy.activate(values={})
    yield


# ── yardımcılar ──────────────────────────────────────────────────────────────

def host(name, mem=256.0, cores=32.0, mem_used=100.0, cpu_used=8.0, usable=True):
    return {"host_name": name, "mem_total_gb": mem, "cpu_cores": cores, "mem_used_gb": mem_used,
            "cpu_used_cores": cpu_used, "usable": usable}


def vc(**kw):
    base = dict(ha_enabled=True, admission_control_enabled=True, policy_type="failoverLevel", mem_failover_pct=None,
                cpu_failover_pct=None, failover_level=1)
    base.update(kw)
    return SimpleNamespace(**base)


def core(platform, hosts, v=None, cfg=None, on=None):
    m = adapters.from_virt_hosts(platform, "C", hosts, v, olvm_cfg=cfg, vms_on=on)
    return engine.summarize(m, vcp.T.n1_warn)


# ── Eşdeğerlik: virt çekirdek (rezerv + N+1) ────────────────────────────────

def _rand_hosts(rng):
    n = rng.randint(0, 6)
    return [host(f"h{i}", mem=rng.choice([64.0, 128.0, 256.0, 512.0, 384.0]), cores=rng.choice([16.0, 32.0, 48.0, 64.0]),
                 mem_used=round(rng.uniform(0, 300), 1), cpu_used=round(rng.uniform(0, 40), 1),
                 usable=rng.random() > 0.2) for i in range(n)]


def _rand_vc(rng):
    k = rng.randint(0, 5)
    if k == 0:
        return None
    if k == 1:
        return vc(ha_enabled=False)
    if k == 2:
        return vc(admission_control_enabled=False)
    if k == 3:
        return vc(policy_type="resourcePercentage", mem_failover_pct=rng.choice([10, 25, 33]), cpu_failover_pct=rng.choice([10, 25]))
    return vc(failover_level=rng.randint(1, 3))


def test_virt_core_equivalence_random_inputs():
    rng = random.Random(20261013)
    for i in range(600):
        platform = rng.choice(["vmware", "olvm", "ocp_virt"])
        hs, v = _rand_hosts(rng), _rand_vc(rng)
        usable = [h for h in hs if h["usable"]]
        old = vcp._core_legacy(usable, v, platform)
        new = core(platform, hs, v)  # olvm_cfg yok → bilinmiyor → eski davranış
        for k in ("mem_total", "mem_used", "cpu_total", "cpu_used", "mem_eff", "cpu_eff", "reserve", "n1"):
            assert new[k] == old[k], (i, platform, k, new[k], old[k])
        assert "overcommit" not in new


def _rand_cluster_dict(rng):
    eff = rng.choice([0.0, 100.0, 400.0, 900.0])
    return {
        "memory": {"used_gb": rng.choice([0.0, 50.0, 300.0, 700.0]), "effective_gb": eff},
        "cpu": {"used_cores": rng.choice([0.0, 8.0, 40.0]), "effective_cores": rng.choice([0.0, 32.0, 96.0]),
                "vcpu_allocated": rng.choice([0, 40, 400]), "total_cores": rng.choice([0.0, 32.0, 96.0])},
        "n_plus_one": {"remaining_mem_gb": rng.choice([None, 0, 200.0, 600.0])},
        "hosts_usable": rng.choice([0, 1, 3]),
        "typical_host_cores": rng.choice([None, 16.0, 32.0]),
    }


def test_place_equivalence_random_inputs():
    rng = random.Random(7)
    for i in range(800):
        c = _rand_cluster_dict(rng)
        kw = dict(add_mem=rng.choice([0.0, 16.0, 64.0, 500.0]), add_cpu=rng.choice([0.0, 2.0, 30.0]),
                  add_vcpu=rng.choice([0, 8, 100]))
        vcpu = rng.choice([1, 4, 64])
        old = vcp._place_legacy(c, vcpu=vcpu, **kw)
        new = engine.place(c, vcpu_single=vcpu, thr=vcp.T, **kw)
        assert {k: new[k] for k in old} == old, (i, c, kw)
        assert new["committed_after_pct"] is None  # overcommit verisi yok → eski davranış


# ── Eşdeğerlik: OpenShift drene senaryosu ────────────────────────────────────

def _w(name, cpu_m=8000, mem=32.0, req_cpu=2000, req_mem=8.0, ready=True, sched=True, raw=None):
    w = {"name": name, "cpu_m": cpu_m, "mem_gb": mem, "req_cpu_m": req_cpu, "req_mem_gb": req_mem,
         "ready": ready, "schedulable": sched}
    if raw is not None:
        w["mem_gb_raw"] = raw
    return w


def test_ocp_simulate_equivalence_random_inputs():
    rng = random.Random(99)
    for i in range(800):
        n = rng.randint(0, 6)
        ws = [_w(f"w{j}", cpu_m=rng.choice([4000, 8000, 16000]), mem=rng.choice([16.0, 32.0, 64.0]),
                 req_cpu=rng.choice([0, 1500, 6000]), req_mem=rng.choice([0.0, 8.0, 40.0]),
                 ready=rng.random() > 0.15, sched=rng.random() > 0.15,
                 raw=rng.choice([None, None, 34.0])) for j in range(n)]
        names = [w["name"] for w in ws] + ["zzz"]
        drain = rng.sample(names, k=rng.randint(0, min(3, len(names))))
        kw = dict(cpu_cores=rng.choice([0, 0.5, 4]), memory_gb=rng.choice([0, 4, 16]), count=rng.choice([0, 1, 4]))
        cap = {"workers": ws} if rng.random() > 0.05 else {}
        assert ocp_capacity_sim.simulate_legacy(cap, drain=drain, **kw) == \
            engine.drain(cap.get("workers") or [], drain_names=drain, **kw), i


def test_ocp_simulate_default_dispatches_to_engine_and_legacy_switch(monkeypatch):
    cap = {"workers": [_w("a"), _w("b"), _w("c")]}
    assert engine_mode() == "unified"
    new = ocp_capacity_sim.simulate(cap, drain=["a"], cpu_cores=4, memory_gb=16, count=2)
    monkeypatch.setenv("CAPACITY_ENGINE", "legacy")
    assert engine_mode() == "legacy"
    old = ocp_capacity_sim.simulate(cap, drain=["a"], cpu_cores=4, memory_gb=16, count=2)
    assert new == old
    monkeypatch.setenv("CAPACITY_ENGINE", "bilinmeyen")
    assert engine_mode() == "legacy"  # bilinmeyen değer → temkinli


def test_ocp_n_plus_one_equivalence():
    rng = random.Random(5)
    for _ in range(300):
        ws = [_w(f"w{j}", cpu_m=rng.choice([4000, 8000]), mem=rng.choice([16.0, 32.0, 64.0])) for j in range(rng.randint(2, 6))]
        req_cpu, req_mem = rng.choice([0, 9000, 40000]), rng.choice([1.0, 60.0, 200.0])
        # eski ocp_insights.evaluate satır içi hesabı (referans)
        tot_cpu, tot_mem = sum(w["cpu_m"] for w in ws), sum(w["mem_gb"] for w in ws)
        big = max(ws, key=lambda w: w["mem_gb"])
        rem_mem, rem_cpu = tot_mem - big["mem_gb"], tot_cpu - big["cpu_m"]
        n1_mem = 100.0 * req_mem / rem_mem if rem_mem > 0 else None
        n1_cpu = 100.0 * req_cpu / rem_cpu if rem_cpu > 0 else None
        fail = (n1_mem is None or n1_mem > 100) or (n1_cpu is not None and n1_cpu > 100)
        status = "fail" if fail else ("warn" if max(n1_mem or 0, n1_cpu or 0) > 90 else "ok")
        got = engine.worker_n_plus_one(ws, req_cpu, req_mem)
        assert (got["big"]["name"], got["n1_mem"], got["n1_cpu"], got["fail"], got["status"]) == (big["name"], n1_mem, n1_cpu, fail, status)


# ── Aynı küme → aynı sayılar (virt what-if ve OCP sayfası) ──────────────────

def test_same_cluster_same_numbers_in_virt_whatif_and_ocp_page():
    """Aynı ortak model, iki giriş noktası (yerleşim = virt what-if, drene = OCP sayfası) aynı yüzdeleri verir."""
    ws = [_w("a", cpu_m=16000, mem=64.0, req_cpu=6000, req_mem=20.0),
          _w("b", cpu_m=16000, mem=64.0, req_cpu=4000, req_mem=30.0),
          _w("c", cpu_m=8000, mem=32.0, req_cpu=1000, req_mem=8.0)]
    model = adapters.from_ocp_workers(ws, "ocp1")
    s = engine.summarize(model, 90.0)
    assert s["reserve"]["policy"] == "none"
    c = {"memory": {"used_gb": s["mem_used"], "effective_gb": s["mem_eff"]},
         "cpu": {"used_cores": s["cpu_used"], "effective_cores": s["cpu_eff"], "vcpu_allocated": 0, "total_cores": s["cpu_total"]},
         "n_plus_one": s["n1"], "hosts_usable": s["usable"], "typical_host_cores": 16.0}
    for add_cpu, add_mem, count in [(0.0, 0.0, 0), (2.0, 8.0, 3), (4.0, 16.0, 5)]:
        pl = engine.place(c, add_mem=add_mem * count, add_cpu=add_cpu * count, add_vcpu=0, vcpu_single=1, thr=vcp.T)
        page = engine.drain(ws, drain_names=[], cpu_cores=add_cpu, memory_gb=add_mem, count=count)
        assert round(pl["eff_mem_pct"], 1) == page["after"]["memory_pct"]
        assert round(pl["eff_cpu_pct"], 1) == page["after"]["cpu_pct"]


# ── vCenter HA admission control ─────────────────────────────────────────────

def _hosts3():
    return [host("a", mem=512.0, cores=64.0), host("b", mem=256.0, cores=32.0), host("c", mem=256.0, cores=32.0)]


def test_vcenter_failover_level_reserves_largest_hosts():
    r1 = core("vmware", _hosts3(), vc(failover_level=1))["reserve"]
    assert (r1["policy"], r1["mem_gb"], r1["cpu_cores"], r1["assumed"]) == ("failover_level", 512.0, 64.0, False)
    r2 = core("vmware", _hosts3(), vc(failover_level=2))["reserve"]
    assert r2["mem_gb"] == 512.0 + 256.0 and r2["cpu_cores"] == 96.0 and "= 2" in r2["label"]


def test_vcenter_percentage_policy_reserves_share_of_cluster():
    s = core("vmware", _hosts3(), vc(policy_type="resourcePercentage", mem_failover_pct=25, cpu_failover_pct=10))
    assert s["reserve"]["policy"] == "percentage"
    assert s["reserve"]["mem_gb"] == pytest.approx(1024.0 * 0.25) and s["reserve"]["cpu_cores"] == pytest.approx(128.0 * 0.10)
    assert s["mem_eff"] == pytest.approx(1024.0 - 256.0)


def test_vcenter_admission_control_and_ha_off_reserve_nothing():
    ac_off = core("vmware", _hosts3(), vc(admission_control_enabled=False))["reserve"]
    ha_off = core("vmware", _hosts3(), vc(ha_enabled=False))["reserve"]
    assert (ac_off["policy"], ac_off["mem_gb"]) == ("ac_off", 0.0)
    assert (ha_off["policy"], ha_off["mem_gb"]) == ("ha_off", 0.0)
    assert core("vmware", _hosts3(), vc(admission_control_enabled=False))["mem_eff"] == 1024.0


def test_vcenter_single_host_and_unreadable_policy():
    assert core("vmware", [host("a")], vc())["reserve"]["policy"] == "single_host"
    r = core("vmware", _hosts3(), None)["reserve"]  # politika okunamadı → varsayım, işaretli
    assert r["policy"] == "assumed_n1" and r["assumed"] is True and r["mem_gb"] == 512.0


def test_n_plus_one_largest_host_decides_by_memory():
    s = core("vmware", [host("a", mem=512.0, mem_used=100.0), host("b", mem=256.0, mem_used=100.0)], vc())
    assert s["n1"]["largest_host"] == "a" and s["n1"]["remaining_mem_gb"] == 256.0
    assert s["n1"]["mem_after_pct"] == round(100.0 * 200.0 / 256.0, 1) and s["n1"]["status"] == "ok"


# ── OLVM: overcommit + HA reservation açık/kapalı ───────────────────────────

OL_HOSTS = [host(f"o{i}", mem=100.0, cores=16.0, mem_used=60.0, cpu_used=4.0) for i in range(3)]
OL_VMS = [{"memory_gb": 330.0, "vcpu": 120}]


def test_olvm_ha_reservation_off_reserves_nothing_on_assumes_one_host():
    off = core("olvm", OL_HOSTS, cfg={"ha_reservation": False})
    assert off["reserve"]["policy"] == "ha_reservation_off" and off["reserve"]["mem_gb"] == 0.0 and off["mem_eff"] == 300.0
    on = core("olvm", OL_HOSTS, cfg={"ha_reservation": True})
    assert on["reserve"]["policy"] == "assumed_n1" and on["reserve"]["assumed"] is True
    assert on["reserve"]["mem_gb"] == 100.0 and on["mem_eff"] == 200.0
    assert "resmi belgede tanımlı değil" in on["reserve"]["label"]
    unknown = core("olvm", OL_HOSTS, cfg={})
    assert unknown["reserve"]["mem_gb"] == 100.0 and "Varsayım" in unknown["reserve"]["label"]  # eski davranış


def test_olvm_memory_overcommit_scales_scheduling_capacity_with_and_without_reservation():
    base = dict(cfg={"memory_overcommit_pct": 150, "ha_reservation": False}, on=OL_VMS)
    s_off = core("olvm", OL_HOSTS, **base)
    assert s_off["overcommit"]["scheduling_gb"] == 450.0           # 300 × 1.5, rezerv yok
    assert s_off["overcommit"]["committed_pct"] == round(100.0 * 330.0 / 450.0, 1)
    s_on = core("olvm", OL_HOSTS, cfg={"memory_overcommit_pct": 150, "ha_reservation": True}, on=OL_VMS)
    assert s_on["overcommit"]["scheduling_gb"] == 300.0            # (300 − 100) × 1.5
    assert s_on["overcommit"]["committed_pct"] == 110.0
    s_none = core("olvm", OL_HOSTS, cfg={"memory_overcommit_pct": 100, "ha_reservation": False}, on=OL_VMS)
    assert s_none["overcommit"]["scheduling_gb"] == 300.0          # None = %100


def test_olvm_overcommit_blocks_placement_beyond_scheduler_limit_only_when_known():
    def cl(cfg):
        s = core("olvm", OL_HOSTS, cfg=cfg, on=OL_VMS)
        return {"memory": {"used_gb": s["mem_used"], "effective_gb": s["mem_eff"], "overcommit": s.get("overcommit")},
                "cpu": {"used_cores": s["cpu_used"], "effective_cores": s["cpu_eff"], "vcpu_allocated": 120, "total_cores": s["cpu_total"]},
                "n_plus_one": s["n1"], "hosts_usable": 3, "typical_host_cores": 16.0}
    known = cl({"memory_overcommit_pct": 150, "ha_reservation": False})
    # 450 GB zamanlama kapasitesi, 330 taahhüt: +100 GB sığar (%95.5), +130 GB sığmaz (%102.2)
    ok = engine.place(known, add_mem=100.0, add_cpu=1.0, add_vcpu=4, vcpu_single=4, thr=vcp.T,
                      overcommit=known["memory"]["overcommit"])
    assert ok["committed_after_pct"] == round(100.0 * 430.0 / 450.0, 1)
    over = engine.place(known, add_mem=130.0, add_cpu=1.0, add_vcpu=4, vcpu_single=4, thr=vcp.T,
                        overcommit=known["memory"]["overcommit"])
    assert over["fits"] is False and any("zamanlayıcı sınırı" in r for r in over["reasons"])
    # overcommit bilinmiyorsa (cfg yok) taahhüt kuralı hiç devreye girmez
    unknown = cl(None)
    assert "overcommit" not in core("olvm", OL_HOSTS, cfg=None, on=OL_VMS)
    assert engine.place(unknown, add_mem=10.0, add_cpu=1.0, add_vcpu=4, vcpu_single=4, thr=vcp.T)["committed_after_pct"] is None


# ── OpenShift: request + virt-launcher yükü + allocation ratio + MCP maxUnavailable ──

def test_virt_launcher_memory_overhead_formula_official_docs():
    # 8 GiB, 4 vCPU: 0.002×8192 + 218 + 8×4 = 266.384 MiB
    assert engine.vm_memory_overhead_mib(8192, 4) == pytest.approx(266.384)
    # grafik aygıtı +16 MiB; her SR-IOV/GPU +1 GiB
    assert engine.vm_memory_overhead_mib(8192, 4, graphics=1) == pytest.approx(282.384)
    assert engine.vm_memory_overhead_mib(8192, 4, sriov_or_gpu=1) == pytest.approx(266.384 + 1024.0)
    # katsayı 0.002 (1.002 değil): 1 GiB'lik VM yükü bellekten küçük kalır
    assert engine.vm_memory_overhead_mib(1024, 1) < 1024.0


def test_cpu_allocation_ratio_default_ten_and_override():
    assert engine.vm_cpu_request_cores(1) == pytest.approx(0.1)           # 100 millicore / vCPU
    assert engine.vm_cpu_request_cores(8) == pytest.approx(0.8)
    assert engine.vm_cpu_request_cores(4, allocation_ratio=1) == 4.0       # 1 vCPU = 1 çekirdek
    assert engine.vm_cpu_request_cores(4, allocation_ratio=100) == pytest.approx(0.04)
    with pytest.raises(ValueError):
        engine.vm_cpu_request_cores(4, allocation_ratio=0)


def test_vm_request_demand_drives_drain_scenario():
    ws = [_w("a", cpu_m=16000, mem=64.0, req_cpu=2000, req_mem=16.0),
          _w("b", cpu_m=16000, mem=64.0, req_cpu=2000, req_mem=16.0),
          _w("c", cpu_m=16000, mem=64.0, req_cpu=2000, req_mem=16.0)]
    d = engine.vm_demand(10, 4, 8.0)  # 10 VM × (4 vCPU, 8 GiB)
    assert d["overhead_gb_each"] == pytest.approx(266.384 / 1024.0)
    assert d["memory_gb"] == pytest.approx(10 * (8.0 + 266.384 / 1024.0))
    assert d["cpu_cores"] == pytest.approx(4.0)                           # 40 vCPU / 10
    res = engine.drain(ws, drain_names=["a"], cpu_cores=d["cpu_cores_each"], memory_gb=d["memory_gb_each"], count=10)
    # kalan 2 worker: 128 GB allocatable, request 48 GB + 10×8.26 GB = 130.6 GB → sığmaz
    assert res["after"]["memory_pct"] == round(100.0 * (48.0 + d["memory_gb"]) / 128.0, 1) and res["verdict"] == "fail"
    # overhead olmasaydı (yalnız VM belleği) 128 GB sınırı altında kalırdı: yük kararı değiştiriyor
    naive = engine.drain(ws, drain_names=["a"], cpu_cores=0.4, memory_gb=8.0, count=10)
    assert naive["verdict"] != "fail"
    # ratio 1 → CPU request 10× artar
    r1 = engine.vm_demand(10, 4, 8.0, allocation_ratio=1)
    assert r1["cpu_cores"] == pytest.approx(40.0) and r1["memory_gb"] == d["memory_gb"]


def test_mcp_max_unavailable_default_one_worst_case_largest_node():
    ws = [_w("a", mem=64.0, cpu_m=16000), _w("b", mem=32.0), _w("c", mem=32.0)]
    r = engine.rolling_update(ws)                 # varsayılan 1
    assert r["rolling_update"] == {"max_unavailable": 1, "already_unavailable": 0, "additional_drained": ["a"]}
    assert r["remaining_workers"] == 2
    r2 = engine.rolling_update(ws, 2)
    assert r2["rolling_update"]["additional_drained"] == ["a", "b"] and r2["remaining_workers"] == 1
    assert r2["after"]["memory_pct"] > r["after"]["memory_pct"]            # paralel güncelleme daha riskli
    assert engine.rolling_update(ws, 3)["verdict"] == "fail"               # hepsi aynı anda → zamanlanabilir yok


def test_mcp_max_unavailable_zero_means_one_and_counts_already_unavailable_nodes():
    ws = [_w("a", mem=64.0), _w("b", mem=32.0, ready=False), _w("c", mem=32.0)]
    assert engine.parse_max_unavailable(0) == (1, None)                    # belge: 0 → 1
    assert engine.parse_max_unavailable(None) == (1, None)                 # belge: varsayılan 1
    assert engine.parse_max_unavailable("2") == (2, None)
    r = engine.rolling_update(ws, 1)                                       # b zaten erişilemez → bütçe 0
    assert r["rolling_update"]["already_unavailable"] == 1 and r["rolling_update"]["additional_drained"] == []
    r2 = engine.rolling_update(ws, 2)                                      # bütçe 1 → en büyük (a)
    assert r2["rolling_update"]["additional_drained"] == ["a"]


def test_mcp_max_unavailable_percentage_not_modeled_rounding_undocumented():
    r = engine.rolling_update([_w("a"), _w("b")], "25%")
    assert r["verdict"] == "not_measurable" and "yuvarlan" in r["reason"]
    assert engine.parse_max_unavailable("abc")[0] is None


# ── Planlayıcı uçtan uca: unified ≡ legacy (olvm/ocp_virt; ağ verisi yok) ────

class _NoDb:
    def rollback(self):
        pass


def test_analyze_cluster_unified_equals_legacy(monkeypatch):
    rng = random.Random(31)
    hv = SimpleNamespace(id=1, name="hv")
    for i in range(150):
        platform = rng.choice(["olvm", "ocp_virt"])
        hs = [dict(h, cluster_name="C") for h in _rand_hosts(rng)]
        vms = [{"hypervisor_id": 1, "cluster": "C", "powered_on": True, "vcpu": rng.choice([2, 4, 8]),
                "memory_gb": rng.choice([4.0, 16.0]), "host": None} for _ in range(rng.randint(0, 8))]
        monkeypatch.setenv("CAPACITY_ENGINE", "legacy")
        old = vcp._analyze_cluster(_NoDb(), hv, platform, "C", hs, vms, None, {}, with_forecast=False)
        monkeypatch.setenv("CAPACITY_ENGINE", "unified")
        new = vcp._analyze_cluster(_NoDb(), hv, platform, "C", hs, vms, None, {}, with_forecast=False)
        assert new == old, (i, platform)
