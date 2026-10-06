"""OpenShift karar katmanı: drain/what-if hesabı, yapılandırma anlık görüntüsü ve baseline kontrolü."""
from types import SimpleNamespace

from app.services.findings.registry import CHECKS
from app.services.ocp_capacity_sim import simulate
from app.services.ocp_insights import _mask_url, config_snapshots
from app.services.virt_config_drift import diff_configs


def _w(name, cpu_m=8000, mem=32.0, req_cpu=2000, req_mem=8.0, ready=True, sched=True):
    return {"name": name, "cpu_m": cpu_m, "mem_gb": mem, "req_cpu_m": req_cpu, "req_mem_gb": req_mem,
            "ready": ready, "schedulable": sched}


CAP = {"workers": [_w("a"), _w("b"), _w("c")]}


def test_drain_one_of_three_fits():
    r = simulate(CAP, drain=["a"])
    assert r["ok"] and r["verdict"] == "ok" and r["remaining_workers"] == 2
    assert r["after"]["memory_pct"] == 37.5  # 24 / 64
    assert r["before"]["memory_pct"] == 25.0


def test_drain_plus_workload_fails_and_counts_headroom():
    r = simulate(CAP, drain=["a"], cpu_cores=4, memory_gb=16, count=4)
    assert r["verdict"] == "fail"  # 24+64 > 64
    assert r["max_additional"] == 2  # (64-24)/16


def test_warn_band_and_unknown_node_and_empty():
    hot = simulate({"workers": [_w("a", req_mem=28.0), _w("b", req_mem=28.0)]}, drain=[], memory_gb=0)
    assert hot["verdict"] == "warn"  # 56/64 = 87.5
    assert simulate(CAP, drain=["zzz"])["ok"] is False
    assert simulate({}, drain=[])["ok"] is False
    assert simulate({"workers": [_w("a")]}, drain=["a"])["verdict"] == "fail"


def test_unschedulable_workers_not_counted_as_capacity():
    cap = {"workers": [_w("a"), _w("b", sched=False)]}
    r = simulate(cap, drain=[])
    assert r["remaining_workers"] == 1 and r["after"]["memory_pct"] == 50.0  # 16 GB request / 32 GB zamanlanabilir


def test_mask_proxy_credentials():
    assert _mask_url("http://user:pw@proxy:3128") == "http://***@proxy:3128"
    assert _mask_url("http://proxy:3128") == "http://proxy:3128"
    assert _mask_url(None) is None


def test_config_snapshots_are_normalized_and_secret_free():
    cluster = SimpleNamespace(name="c1")
    col = {
        "cv": {"spec": {"channel": "stable-4.21"}, "status": {"desired": {"version": "4.21.15"}, "history": [1, 2]}},
        "nodes": [{"metadata": {"name": "n1", "labels": {"node-role.kubernetes.io/worker": ""},
                                "annotations": {"machineconfiguration.openshift.io/currentConfig": "rendered-1"}},
                   "spec": {"taints": [{"key": "k", "effect": "NoSchedule"}]},
                   "status": {"nodeInfo": {"kubeletVersion": "v1"}, "conditions": [{"type": "Ready", "status": "True"}]}}],
        "mcps": [{"metadata": {"name": "worker"}, "spec": {}, "status": {"configuration": {
            "name": "rendered-1", "source": [{"name": "b"}, {"name": "a"}]}}}],
        "cos": [{"metadata": {"name": "etcd"}, "status": {"versions": [{"name": "operator", "version": "4.21.15"}]}}],
        "cfg": {"proxy": {"spec": {"httpProxy": "http://u:p@h:1"}}},
    }
    snaps = {(s["kind"], s["ref"]): s for s in config_snapshots(cluster, col)}
    assert snaps[("node", "n1")]["config"]["taints"] == ["k:NoSchedule"]
    assert snaps[("node", "n1")]["config"]["mc_current"] == "rendered-1"
    assert snaps[("mcp", "worker")]["config"]["sources"] == ["a", "b"]
    assert snaps[("operator", "etcd")]["config"]["versions"] == {"operator": "4.21.15"}
    assert "u:p" not in str(snaps[("platform", "config:proxy")])
    # oynak alanlar (hazır durumu) hash'e giren config'te yok
    assert "ready" not in snaps[("node", "n1")]["config"]


def test_mc_rollout_shows_up_as_diff():
    old = {"mc_current": "rendered-1", "kubelet": "v1"}
    new = {"mc_current": "rendered-2", "kubelet": "v1"}
    d = diff_configs(old, new)
    assert [x["path"] for x in d] == ["mc_current"]


def test_baseline_check_covers_ocp():
    assert "ocp" in CHECKS["drift.entity.baseline"].platforms


def test_baseline_requests_allow_all_sources():
    from app.api.ocp_insights import BaselineRequest as OcpReq
    from app.api.virt_insights import BaselineRequest as VirtReq
    assert OcpReq().cluster_id is None
    v = VirtReq(entity_kind="host")
    assert v.platform is None and v.hypervisor_id is None
