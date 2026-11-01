"""OpenShift hiyerarşisi: Cluster → Node → Namespace → Pod (ve KubeVirt VM).

Sayılar envanterden gelir (`openshift_nodes/projects/workloads` + `servers`). Pod sayıları
workload tablosundan node_name'e göre gruplanır; node.pod_count alanı kullanılmaz (kaynak tek olsun).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject, OpenShiftWorkload
from app.models.server import Server
from app.services.openshift_virt_inventory import META_CLUSTER_ID

_OK_POD = {"running", "succeeded", "completed"}


def _hv_id_for(db: Session, cluster: OpenShiftCluster) -> Optional[int]:
    """Cluster'a bağlı openshift_virt hypervisor (VM'ler `servers`'ta onun altında)."""
    from app.models.hypervisor import Hypervisor
    cid = cluster.id
    for hv in db.query(Hypervisor).all():
        meta = hv.meta_data or {}
        if meta.get(META_CLUSTER_ID) == cid or str(meta.get(META_CLUSTER_ID) or "") == str(cid):
            return hv.id
    return None


def hierarchy(db: Session, cluster_id: Optional[int] = None) -> dict:
    q = db.query(OpenShiftCluster)
    if cluster_id:
        q = q.filter(OpenShiftCluster.id == cluster_id)
    clusters = q.order_by(OpenShiftCluster.name.asc()).all()

    out = []
    for c in clusters:
        nodes = db.query(OpenShiftNode).filter(OpenShiftNode.cluster_id == c.id).order_by(OpenShiftNode.name).all()
        projects = db.query(OpenShiftProject).filter(OpenShiftProject.cluster_id == c.id).all()
        pods = (
            db.query(OpenShiftWorkload.node_name, OpenShiftWorkload.project, OpenShiftWorkload.status)
            .filter(OpenShiftWorkload.cluster_id == c.id, OpenShiftWorkload.kind == "pod")
            .all()
        )
        pods_by_node: dict = {}
        pods_by_ns: dict = {}
        bad = 0
        for node_name, project, status in pods:
            ok = (status or "").strip().lower() in _OK_POD
            if not ok:
                bad += 1
            nk = (node_name or "").strip().lower()
            if nk:
                t = pods_by_node.setdefault(nk, [0, 0])
                t[0] += 1
                t[1] += 0 if ok else 1
            pk = (project or "").strip()
            if pk:
                t = pods_by_ns.setdefault(pk, [0, 0])
                t[0] += 1
                t[1] += 0 if ok else 1

        hv_id = _hv_id_for(db, c)
        vms_by_node: dict = {}
        vms_by_ns: dict = {}
        vm_total = 0
        if hv_id:
            for host, vm_id, status, pw in (
                db.query(Server.vm_host_name, Server.hypervisor_vm_id, Server.status, Server.vm_power_state)
                .filter(Server.hypervisor_id == hv_id).all()
            ):
                vm_total += 1
                on = (status or "").upper() == "ONLINE" or (pw or "").strip().lower() in ("poweredon", "running", "on", "up")
                nk = (host or "").strip().lower()
                if nk:
                    t = vms_by_node.setdefault(nk, [0, 0])
                    t[0] += 1
                    t[1] += 1 if on else 0
                ns = (vm_id or "").split("/", 1)[0].strip() if vm_id and "/" in vm_id else ""
                if ns:
                    t = vms_by_ns.setdefault(ns, [0, 0])
                    t[0] += 1
                    t[1] += 1 if on else 0

        node_rows = []
        not_ready = 0
        for n in nodes:
            if (n.status or "").strip().lower() != "ready":
                not_ready += 1
            pc = pods_by_node.get((n.name or "").strip().lower(), [0, 0])
            vc = vms_by_node.get((n.name or "").strip().lower(), [0, 0])
            node_rows.append({
                "name": n.name, "role": n.role, "status": n.status,
                "cpu_cores": n.cpu_cores, "memory_gb": n.memory_gb,
                "cpu_pct": n.cpu_usage_pct, "mem_pct": n.memory_usage_pct,
                "pods_total": pc[0], "pods_bad": pc[1], "vms_total": vc[0], "vms_running": vc[1],
            })
        ns_rows = []
        for p in sorted(projects, key=lambda x: x.name or ""):
            pc = pods_by_ns.get(p.name, [0, 0])
            vc = vms_by_ns.get(p.name, [0, 0])
            ns_rows.append({
                "name": p.name, "display_name": p.display_name, "status": p.status,
                "system": bool((p.meta_data or {}).get("is_system")),
                "pods_total": pc[0], "pods_bad": pc[1], "vms_total": vc[0], "vms_running": vc[1],
            })
        out.append({
            "cluster_id": c.id, "name": c.name, "version": c.version, "status": c.status,
            "node_count": len(nodes), "nodes_not_ready": not_ready,
            "project_count": len(projects), "pod_count": len(pods), "pods_bad": bad,
            "vm_count": vm_total, "nodes": node_rows, "namespaces": ns_rows,
        })
    return {"clusters": out}
