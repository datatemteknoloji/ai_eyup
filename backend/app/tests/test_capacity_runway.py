"""Runway: durum kodları (neden hesaplanmadı) + cluster başına erişilebilir datastore runway'i."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.infra_finding import VirtConfigSnapshot
from app.models.virt_datastore import VirtDatastore
from app.models.virt_metric import VirtDatastoreMetric
from app.services import capacity_policy
from app.services import virt_capacity_planner as vcp
from app.tests.test_capacity_h0 import _seed_vc  # noqa: F401

NOW = datetime.now(timezone.utc)


def test_runway_states():
    grow = [50 + i * 1.0 for i in range(30)]                      # +1 %/gün
    assert vcp._runway(grow, 79.0, 85.0)["state"] == "ok"
    assert vcp._runway(grow, 79.0, 85.0)["days"]["typical"] == 6
    few = vcp._runway([50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61], 61.0, 85.0)
    assert few["state"] == "insufficient_data" and few["data_days"] == 12 and few["min_days"] == 14 and few["window_days"] == 90
    assert vcp._runway(grow, 90.0, 85.0)["state"] == "exceeded"
    assert vcp._runway([60.0] * 30, 60.0, 85.0)["state"] in ("flat", "low_confidence")
    assert vcp._runway(grow, None, 85.0)["state"] == "no_current"
    assert vcp._runway([], 50.0, 85.0)["data_days"] == 0


def _ds(db, hv, ref, name, usage, days=30):
    db.add(VirtDatastore(hypervisor_id=hv.id, ds_ref=ref, name=name, capacity_gb=1000, free_gb=1000 - usage * 10,
                         used_gb=usage * 10, usage_pct=usage, accessible=True, as_of=NOW))
    for i in range(days):
        db.add(VirtDatastoreMetric(timestamp=NOW - timedelta(days=days - i), hypervisor_id=hv.id, name=name,
                                   usage_pct=usage - (days - i) * 1.0, capacity_gb=1000))


def test_cluster_datastore_runway_lists_accessible_only_and_does_not_sum(isolated_db):
    db = isolated_db
    capacity_policy.activate(values={})
    hv = _seed_vc(db, "vc01", "PROD", [("esx01", "host-1", 256, 20), ("esx02", "host-2", 256, 20)])
    # ikinci cluster (DR): esx03
    from app.models.hypervisor_metric import HypervisorHostMetric
    from app.models.virt_cluster import VirtCluster
    db.add(VirtCluster(hypervisor_id=hv.id, name="DR", ha_enabled=True, admission_control_enabled=False, as_of=NOW))
    db.add(HypervisorHostMetric(timestamp=NOW, hypervisor_id=hv.id, host_name="esx03", host_ref="host-3", cpu_cores=32,
                                mem_total_mb=256 * 1024, mem_used_mb=20 * 1024, cpu_usage_pct=10,
                                connection_state="connected", maintenance_mode=0, cluster_name="DR"))
    _ds(db, hv, "ds-1", "DS-SHARED", 79)
    _ds(db, hv, "ds-2", "DS-PROD", 60)
    _ds(db, hv, "ds-3", "DS-DR-ONLY", 40)
    snaps = [("cluster", "c-prod", "PROD", ["ds-1", "ds-2"]), ("cluster", "c-dr", "DR", ["ds-1", "ds-3"])]
    for kind, ref, name, refs in snaps:
        db.add(VirtConfigSnapshot(platform="vmware", source_id=hv.id, entity_kind=kind, entity_ref=ref, entity_name=name,
                                  cluster_name=name, payload={"config": {"datastore_refs": refs}},
                                  payload_hash=f"h-{ref}", is_latest=True))
    for ref, name, mounted in [("ds-1", "DS-SHARED", ["host-1", "host-2", "host-3"]), ("ds-2", "DS-PROD", ["host-1"]),
                               ("ds-3", "DS-DR-ONLY", ["host-3"])]:
        db.add(VirtConfigSnapshot(platform="vmware", source_id=hv.id, entity_kind="datastore", entity_ref=ref,
                                  entity_name=name, cluster_name=None, payload={"config": {"mounted_hosts": mounted}},
                                  payload_hash=f"h-{ref}", is_latest=True))
    db.commit()
    cap = vcp.build_capacity(db, hypervisor_id=hv.id)
    by = {c["cluster"]: c["datastore_runway"] for c in cap["clusters"]}
    assert {i["name"] for i in by["PROD"]["items"]} == {"DS-SHARED", "DS-PROD"}
    assert {i["name"] for i in by["DR"]["items"]} == {"DS-SHARED", "DS-DR-ONLY"}      # ortak datastore iki yerde de, toplanmadan
    assert by["PROD"]["worst"]["name"] == "DS-SHARED" and by["PROD"]["worst"]["days"]["typical"] == 6
    assert by["PROD"]["threshold"] == 85.0 and by["PROD"]["items"][0]["name"] == "DS-SHARED"   # en kötü başta
    assert by["PROD"]["items"][0]["forecast"]["state"] == "ok"
    # cluster Memory/CPU runway'inde durum kodu var (host metrik geçmişi yok → veri yetersiz)
    assert cap["clusters"][0]["forecast"]["memory"]["state"] in ("insufficient_data", "no_current")


def test_cluster_datastore_runway_unmeasurable_cases():
    c = {"platform": "olvm", "hypervisor_id": 1, "cluster": "X"}
    assert vcp._cluster_ds_runway(None, c, [], set())["reason"] == "olvm_no_mapping"
    assert vcp._cluster_ds_runway(None, {**c, "platform": "ocp_virt"}, [], set())["state"] == "unmeasurable"
