"""OpenShift hiyerarşisi: pod sayıları workload'tan, VM sayıları envanterden (node'a ve namespace'e)."""
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject, OpenShiftWorkload
from app.models.server import Server
from app.services.ocp_hierarchy import hierarchy
from app.services.openshift_virt_inventory import META_CLUSTER_ID
from app.tests.isolated_db import _isolated_engine, isolated_db  # noqa: F401


def test_counts_come_from_inventory_not_node_field(isolated_db):
    db = isolated_db
    c = OpenShiftCluster(name="ocp", api_url="https://api.x:6443", connection_config={})
    db.add(c)
    db.flush()
    db.add(OpenShiftNode(cluster_id=c.id, name="master-0", role="master", status="Ready", pod_count=999))
    db.add(OpenShiftNode(cluster_id=c.id, name="worker-1", role="worker", status="NotReady", pod_count=999))
    db.add(OpenShiftProject(cluster_id=c.id, name="app", status="Active"))
    db.add(OpenShiftProject(cluster_id=c.id, name="openshift-dns", status="Active", meta_data={"is_system": True}))
    for name, node, ns, status in (
        ("p1", "worker-1", "app", "Running"), ("p2", "worker-1", "app", "CrashLoopBackOff"),
        ("p3", "master-0", "openshift-dns", "Running"),
    ):
        db.add(OpenShiftWorkload(cluster_id=c.id, project=ns, kind="pod", name=name, status=status, node_name=node))
    hv = Hypervisor(name="ocp-virt", hypervisor_type=HypervisorType.OPENSHIFT_VIRT, hostname="api.x",
                    ip_address="10.0.0.2", connection_config={}, meta_data={META_CLUSTER_ID: c.id})
    db.add(hv)
    db.flush()
    db.add(Server(name="vm1", hostname="vm1", ip_address="10.9.0.1", server_type="VM", os_type="linux",
                  hypervisor_id=hv.id, hypervisor_vm_id="app/vm1", vm_host_name="worker-1", status="ONLINE",
                  vm_power_state="Running"))
    db.add(Server(name="vm2", hostname="vm2", ip_address="10.9.0.2", server_type="VM", os_type="linux",
                  hypervisor_id=hv.id, hypervisor_vm_id="app/vm2", vm_host_name=None, status="OFFLINE",
                  vm_power_state="Stopped"))
    db.commit()

    h = hierarchy(db)["clusters"][0]
    assert h["node_count"] == 2 and h["nodes_not_ready"] == 1
    assert h["pod_count"] == 3 and h["pods_bad"] == 1          # node.pod_count (999) YOK SAYILIR
    assert h["vm_count"] == 2
    worker = next(n for n in h["nodes"] if n["name"] == "worker-1")
    assert worker["pods_total"] == 2 and worker["pods_bad"] == 1 and worker["vms_total"] == 1 and worker["vms_running"] == 1
    app = next(n for n in h["namespaces"] if n["name"] == "app")
    assert app["pods_total"] == 2 and app["vms_total"] == 2 and app["vms_running"] == 1 and app["system"] is False
    dns = next(n for n in h["namespaces"] if n["name"] == "openshift-dns")
    assert dns["system"] is True and dns["pods_total"] == 1
