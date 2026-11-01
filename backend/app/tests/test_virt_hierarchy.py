"""Sanallaştırma hiyerarşisi: VM sayıları envanterden, cluster'sız grup, host başı sayım."""
from datetime import datetime, timezone

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_inventory import HypervisorHostInventory
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.server import Server
from app.models.virt_cluster import VirtCluster
from app.services.virt_hierarchy import STANDALONE, hierarchy
from app.tests.isolated_db import _isolated_engine, isolated_db  # noqa: F401


def _hv(db, name, typ=HypervisorType.VMWARE):
    hv = Hypervisor(name=name, hypervisor_type=typ, hostname=name, ip_address="10.0.0.1", connection_config={})
    db.add(hv)
    db.flush()
    return hv


def test_cluster_and_standalone_grouping_counts_from_inventory(isolated_db):
    db = isolated_db
    hv = _hv(db, "vc")
    db.add(VirtCluster(hypervisor_id=hv.id, name="PROD", ha_enabled=True, drs_enabled=True,
                       as_of=datetime.now(timezone.utc)))
    db.add(HypervisorHostInventory(hypervisor_id=hv.id, host_ref="h1", host_name="esx1", cluster_name="PROD"))
    db.add(HypervisorHostInventory(hypervisor_id=hv.id, host_ref="h2", host_name="esx2", cluster_name="PROD"))
    db.add(HypervisorHostInventory(hypervisor_id=hv.id, host_ref="h3", host_name="esx-solo", cluster_name=None))
    # Şişirilmiş host metriği: toplanırsa 300 olurdu — hiyerarşi bunu KULLANMAMALI
    for hn in ("esx1", "esx2", "esx-solo"):
        db.add(HypervisorHostMetric(hypervisor_id=hv.id, host_name=hn, host_ref=hn, vms_total=100, vms_running=100,
                                     cpu_usage_pct=10, mem_usage_pct=20, connection_state="connected"))
    for n, host, cl, pw in (("a", "esx1", "PROD", "poweredOn"), ("b", "esx1", "PROD", "poweredOff"),
                            ("c", "esx2", "PROD", "POWERED_ON"), ("d", "esx-solo", None, "poweredOn"),
                            ("e", None, None, "poweredOff")):
        db.add(Server(name=n, hostname=n, ip_address="10.1.0.9", server_type="VM", os_type="linux",
                      hypervisor_id=hv.id, vm_host_name=host, vm_cluster=cl, vm_power_state=pw))
    db.commit()

    tree = hierarchy(db)["hypervisors"]
    assert len(tree) == 1
    h = tree[0]
    assert h["vms_total"] == 5 and h["vms_running"] == 3 and h["vms_unmapped"] == 1
    by_name = {c["name"]: c for c in h["clusters"]}
    assert by_name["PROD"]["host_count"] == 2 and by_name["PROD"]["vms_total"] == 3 and by_name["PROD"]["ha_enabled"] is True
    solo = by_name[STANDALONE]
    assert solo["standalone"] is True and solo["host_count"] == 1 and solo["vms_total"] == 2
    esx1 = next(x for x in by_name["PROD"]["hosts"] if x["host_name"] == "esx1")
    assert esx1["vms_total"] == 2 and esx1["vms_running"] == 1


def test_hierarchy_endpoint(isolated_db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.api.hypervisors as hv_api
    from app.core.database import get_db

    db = isolated_db
    hv = _hv(db, "vc2")
    db.add(HypervisorHostInventory(hypervisor_id=hv.id, host_ref="h1", host_name="esx1", cluster_name="C1"))
    db.add(Server(name="vm1", hostname="vm1", ip_address="10.2.0.1", server_type="VM", os_type="linux",
                  hypervisor_id=hv.id, vm_host_name="esx1", vm_cluster="C1", vm_power_state="Running"))
    db.commit()

    app = FastAPI()
    app.include_router(hv_api.router, prefix="/hypervisors")
    app.dependency_overrides[get_db] = lambda: db
    r = TestClient(app).get("/hypervisors/hierarchy")
    assert r.status_code == 200
    body = r.json()
    assert body["hypervisors"][0]["vms_total"] == 1
    assert body["hypervisors"][0]["clusters"][0]["name"] == "C1"
