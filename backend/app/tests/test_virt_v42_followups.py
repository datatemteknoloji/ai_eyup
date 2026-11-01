"""v42 takip düzeltmeleri: OLVM follow zinciri, sync bayatlığı, incident gürültüsü, EN öneri, sahte OCP tohumu."""
from __future__ import annotations

import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.tests.isolated_db import isolated_db  # noqa: F401


# ── OLVM: follow zinciri ────────────────────────────────────────────────────────

def _client():
    from app.services.ovirt.ovirt_client import OVirtClient
    c = OVirtClient.__new__(OVirtClient)
    c.host = "olvm.test"
    return c


def test_list_vms_falls_back_on_http_500_to_nics():
    from app.services.ovirt.ovirt_parse import OVirtError
    c = _client()
    calls = []

    def paged(path, key, label, params=None, timeout=60):
        calls.append((params or {}).get("follow"))
        if params and params.get("follow", "").startswith("host"):
            raise OVirtError("engine 500", status_code=500)
        return [{"id": "1", "name": "vm1", "status": "up"}]

    c._paged = paged
    c._inventory_row = lambda vm: {"vm_id": vm["id"], "name": vm["name"]}
    c.fetch_full_details_parallel = lambda rows, *a, **k: {}
    try:
        c.list_vms()
    except Exception:
        pass   # detay tamamlama bu testin konusu değil
    assert calls[:2] == ["host,cluster,nics,guest_operating_system", "nics"]


def test_list_vms_raises_when_every_attempt_fails():
    from app.services.ovirt.ovirt_parse import OVirtError
    c = _client()
    n = {"i": 0}

    def paged(*a, **k):
        n["i"] += 1
        raise OVirtError("down", status_code=500)

    c._paged = paged
    with pytest.raises(OVirtError):
        c.list_vms()
    assert n["i"] == 3     # tam follow → nics → düz liste; sessiz boş liste YOK


# ── Envanter senkron bayatlığı ──────────────────────────────────────────────────

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def _hv(**kw):
    base = dict(id=7, name="olvm", last_sync=None, meta_data={})
    base.update(kw)
    return SimpleNamespace(**base)


def test_sync_stale_fail_when_old_and_reports_last_error():
    from app.services.virt_health_checks import sync_stale_draft
    hv = _hv(last_sync=NOW - timedelta(days=11),
             meta_data={"sync_job": {"status": "error", "error": "HTTP 500", "last_error_at": "x"}})
    d = sync_stale_draft(hv, interval_minutes=60, now=NOW)
    assert d.result == "fail" and d.check_id == "inv.sync.stale"
    assert d.severity == "high" and "11 gün" in d.detail and "HTTP 500" in d.detail
    assert d.evidence["age_hours"] > 260


def test_sync_stale_pass_within_threshold_and_uses_last_success():
    from app.services.virt_health_checks import sync_stale_draft
    hv = _hv(last_sync=NOW - timedelta(days=5),
             meta_data={"sync_job": {"last_success_at": (NOW - timedelta(hours=2)).isoformat()}})
    assert sync_stale_draft(hv, interval_minutes=60, now=NOW).result == "pass"


def test_sync_stale_threshold_scales_with_interval_and_never_synced_not_measurable():
    from app.services.virt_health_checks import sync_stale_draft
    hv = _hv(last_sync=NOW - timedelta(hours=7))
    assert sync_stale_draft(hv, interval_minutes=60, now=NOW).result == "fail"        # eşik 6 sa
    assert sync_stale_draft(hv, interval_minutes=180, now=NOW).result == "pass"       # eşik 9 sa
    assert sync_stale_draft(_hv(), interval_minutes=60, now=NOW).result == "not_measurable"


def test_sync_stale_fake_inventory_never_fails():
    from app.services.virt_health_checks import sync_stale_draft
    hv = _hv(last_sync=NOW - timedelta(days=30), meta_data={"fake_seed": True})
    assert sync_stale_draft(hv, interval_minutes=60, now=NOW).result == "not_measurable"


def test_stale_check_registered_for_all_virt_platforms():
    from app.services.findings.registry import get_check
    d = get_check("inv.sync.stale")
    assert d and set(d.platforms) == {"vmware", "olvm", "ocp_virt"} and d.recommendation_en


def test_record_sync_outcome_error_and_success_and_running_guard():
    from app.services import inventory_sync_service as iss
    hv = SimpleNamespace(meta_data={})
    with patch.object(iss, "update_sync_job") as upd:
        iss._record_sync_outcome(7, hv, ["HTTP 500 boom"])
        assert upd.call_args.kwargs["status"] == "error" and "boom" in upd.call_args.kwargs["error"]
        assert upd.call_args.kwargs["last_error_at"]
        iss._record_sync_outcome(7, hv, [])
        assert upd.call_args.kwargs["status"] == "done" and upd.call_args.kwargs["last_success_at"]
    running = SimpleNamespace(meta_data={"sync_job": {"status": "running", "updated_at": datetime.now(timezone.utc).isoformat()}})
    with patch.object(iss, "update_sync_job") as upd, patch.object(iss, "job_is_stale_running", return_value=False):
        iss._record_sync_outcome(7, running, ["x"])
        upd.assert_not_called()           # kullanıcının çalışan taramasının üstüne yazılmaz


def test_sync_all_skips_fake_hypervisors():
    from app.services import inventory_sync_service as iss
    fake = SimpleNamespace(id=9, name="fake", meta_data={"fake_seed": True})
    db = MagicMock()
    db.query.return_value.all.return_value = [fake]
    assert iss.sync_all_hypervisors(db) == {"success": True, "total_synced": 0, "hypervisors": []}


# ── Incident gürültüsü ──────────────────────────────────────────────────────────

def test_k8s_pod_suffix_normalisation_groups_same_root_cause():
    from app.services.event_grouping import normalize_k8s_object as n
    assert n("Pod/redhat-operators-r6scg") == n("Pod/redhat-operators-lqcg4") == "Pod/redhat-operators-*"
    assert n("Pod/controller-manager-8577cfd944-wcd69") == n("Pod/controller-manager-5c7475675b-abcde")
    assert n("Pod/etcd-0") == "Pod/etcd-0"           # StatefulSet sırası korunur
    assert n("Node/worker1") == "Node/worker1"        # yalnız Pod


def test_problem_key_same_for_recreated_pods_but_differs_by_reason_and_namespace():
    from app.services.event_grouping import event_problem_key as k

    def ev(obj, reason="Unhealthy", ns="openshift-marketplace"):
        return SimpleNamespace(event_type="openshift_event", source="openshift_collector", server_id=None, title="t",
                               raw_data={"cluster_id": 2, "namespace": ns, "reason": reason, "source_object": obj})
    assert k(ev("Pod/redhat-operators-r6scg")) == k(ev("Pod/redhat-operators-n7zbd"))
    assert k(ev("Pod/redhat-operators-r6scg")) != k(ev("Pod/redhat-operators-r6scg", reason="BackOff"))
    assert k(ev("Pod/redhat-operators-r6scg")) != k(ev("Pod/redhat-operators-r6scg", ns="other"))


def _inc(db, **kw):
    from app.models.event import Incident
    base = dict(title="t", severity="critical", status="open", source="auto_openshift_event",
                affected_servers=[], related_events=[])
    base.update(kw)
    i = Incident(**base)
    db.add(i)
    db.commit()
    return i


def test_auto_close_quiet_incidents(isolated_db):
    db = isolated_db
    from app.models.event import Incident
    from app.services.aiops_engine import auto_close_quiet_incidents
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=30)
    quiet = _inc(db, title="quiet")
    fresh = _inc(db, title="fresh")
    manual = _inc(db, title="manual", source="manual")
    owned = _inc(db, title="owned", assigned_to="ayse")
    inv = _inc(db, title="investigating", status="investigating")
    for i in (quiet, manual, owned, inv):
        db.query(Incident).filter(Incident.id == i.id).update({"created_at": old, "updated_at": old})
    db.commit()
    assert auto_close_quiet_incidents(db, now) == 1
    db.expire_all()
    by = {i.title: i for i in db.query(Incident).all()}
    assert by["quiet"].status == "resolved" and by["quiet"].resolved_at and "Otomatik kapatıldı" in by["quiet"].resolution
    assert by["fresh"].status == "open"
    assert by["manual"].status == "open" and by["owned"].status == "open" and by["investigating"].status == "investigating"


def test_auto_rca_skips_stale_incidents(isolated_db):
    db = isolated_db
    from app.models.event import Incident
    from app.services import aiops_engine as eng
    old = datetime.now(timezone.utc) - timedelta(days=3)
    stale = _inc(db, title="old", rca_result={})
    db.query(Incident).filter(Incident.id == stale.id).update({"created_at": old, "updated_at": datetime.now(timezone.utc)})
    fresh = _inc(db, title="new", rca_result={})
    db.commit()
    seen = []
    with patch.object(eng, "run_rca_sync", side_effect=lambda d, inc: seen.append(inc.title) or True):
        assert eng.auto_rca_pending_incidents(db) == 1
    assert seen == ["new"]


# ── EN öneri (senaryoya özel) ───────────────────────────────────────────────────

def test_en_locale_keeps_datastore_scenario_recommendation():
    from app.services.findings.store import finding_to_dict
    row = MagicMock()
    row.check_id, row.title, row.recommendation = "vmw.datastore.accessible", "t", "TR metin"
    row.evidence = {"scenario": "unmounted"}
    en = finding_to_dict(row, None, "en")["recommendation"]
    assert "not mounted on any host" in en
    tr = finding_to_dict(row, None, "tr")["recommendation"]
    assert tr == "TR metin"


# ── Sahte OpenShift tohumu ──────────────────────────────────────────────────────

def _load_seed():
    here = pathlib.Path(__file__).resolve()
    cands = [here.parents[i] / "scripts" / "fake_virt_seed.py" for i in (2, 3)]   # konteyner / repo kökü
    p = next((c for c in cands if c.exists()), None)
    if p is None:
        pytest.skip("scripts/fake_virt_seed.py bulunamadı")
    spec = importlib.util.spec_from_file_location("fake_virt_seed", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_fake_ocp_seed_os_mix_covers_requested_distributions():
    m = _load_seed()
    names = " ".join(x[1] for x in m._OCP_OS).lower()
    for needle in ("windows", "ubuntu", "red hat", "centos", "rocky", "almalinux", "oracle", "debian", "suse", "fedora"):
        assert needle in names, needle
    assert any(x[1] == "" for x in m._OCP_OS)           # guest-agent'sız (OS bilinmiyor) örnek
    assert m.OCP_HOST.endswith(".invalid")


# ── Sahte OpenShift cluster (OpenShift modülünde görünürlük) ─────────────────────

def _fake_cluster():
    return SimpleNamespace(id=3, name="ZZ-FAKE-OCP", api_url="https://fake-ocp.invalid:6443",
                           status="ONLINE", version="v1.29.5+fake", meta_data={"fake_seed": True})


def test_is_fake_only_for_marked_clusters():
    from app.services.openshift.fake_cluster import is_fake
    assert is_fake(_fake_cluster()) is True
    assert is_fake(SimpleNamespace(meta_data={"sync_job": {}})) is False
    assert is_fake(SimpleNamespace(meta_data=None)) is False


def test_fake_cluster_skipped_by_every_live_sync_path():
    from app.services import ocp_insights, openshift_event_collector as ev, openshift_sync_service as oss
    from app.services.openshift import ocp_monitoring
    c = _fake_cluster()
    db = MagicMock()
    r = oss.sync_openshift_cluster(db, c)
    assert r["skipped"] and r["errors"] == []
    assert ev.sync_openshift_events_for_cluster(db, c)["skipped"] is True
    assert ocp_insights.run_for_cluster(db, c)["status"] == "skipped"
    db.add.assert_not_called()
    with patch("app.services.fake_refresh.refresh_cluster", return_value={"rows": 7}) as rc:
        assert ocp_monitoring.sync_cluster_metrics(db, c) == {"rows": 7}
        rc.assert_called_once_with(db, 3)


def test_fake_kubevirt_vms_use_kubevirt_client_keys():
    from app.services.openshift import fake_cluster as fc
    srv = SimpleNamespace(hypervisor_vm_id="fake-prod-web/vm-a", vm_name="vm-a", name="vm-a", vm_guest_ip="198.19.0.2",
                          ip_address=None, vm_guest_hostname="vm-a", os_type="Ubuntu 22.04.4 LTS", vm_cpu_count=4,
                          vm_memory_mb=8192, vm_power_state="Running", vm_host_name="w1")
    off = SimpleNamespace(**{**srv.__dict__, "hypervisor_vm_id": "fake-dev/vm-b", "vm_power_state": "Stopped"})
    with patch.object(fc, "_vm_servers", return_value=[srv, off]):
        vms = fc.fake_kubevirt_vms(MagicMock(), _fake_cluster())
    a, b = vms
    assert a["namespace"] == "fake-prod-web" and a["phase"] == "Running" and a["memory_gb"] == 8.0 and a["node_name"] == "w1"
    assert b["status"] == "OFFLINE" and b["phase"] == "Stopped"
    for k in ("name", "vm_id", "namespace", "cpu_cores", "memory_gb", "status", "os_type", "ip_address", "node_name"):
        assert k in a


def test_fake_refresh_touches_only_fake_records():
    from app.services import fake_refresh as fr
    real = SimpleNamespace(id=1, meta_data={}, hypervisor_type="vmware")
    db = MagicMock()
    db.query.return_value.all.side_effect = [[real], []]
    out = fr.refresh_all(db)
    db.execute.assert_not_called()           # gerçek hypervisor'a hiçbir INSERT yok
    assert out["hosts"] == 0 and out["ocp_rows"] == 0
