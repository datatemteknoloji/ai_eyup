"""Sahte (test) OpenShift cluster desteği — `scripts/fake_virt_seed.py seed-ocp` ile oluşturulan kayıtlar.

Sahte cluster'ın gerçek bir API'si yoktur (`*.invalid`). Bu yüzden:
- Periyodik/elle senkron, event, monitoring ve bulgu turları sahte cluster'ı ATLAR (`is_fake`).
- Canlı API'ye bağlı iki uç (cluster overview, KubeVirt VM listesi) veriyi DB'den üretir; böylece OpenShift
  modülünün VM ve özet ekranları sahte envanterle de çalışır. Diğer canlı uçlar (topology, YAML, konsol, güç/klon
  işlemleri) sahte cluster'da çalışmaz.

Sahte kayıtların tek işareti: `openshift_clusters.meta_data.fake_seed == True`.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject, OpenShiftWorkload

FAKE_MESSAGE = "Sahte (test) cluster — canlı API yok"


def is_fake(cluster: Any) -> bool:
    return bool((getattr(cluster, "meta_data", None) or {}).get("fake_seed"))


def _vm_servers(db: Session, cluster: OpenShiftCluster) -> List[Any]:
    """Cluster'a bağlı (meta_data.openshift_cluster_id) sahte openshift_virt hypervisor'ının VM'leri."""
    from app.models.hypervisor import Hypervisor, HypervisorType
    from app.models.server import Server
    from app.services.openshift_virt_inventory import META_CLUSTER_ID

    for hv in db.query(Hypervisor).filter(Hypervisor.hypervisor_type == HypervisorType.OPENSHIFT_VIRT).all():
        meta = hv.meta_data or {}
        if meta.get("fake_seed") and meta.get(META_CLUSTER_ID) == cluster.id:
            return db.query(Server).filter(Server.hypervisor_id == hv.id).all()
    return []


def fake_kubevirt_vms(db: Session, cluster: OpenShiftCluster) -> List[Dict[str, Any]]:
    """`KubeVirtClient.list_vms()` ile aynı anahtarlar (OcpVmsPanel bunları okur)."""
    out: List[Dict[str, Any]] = []
    for s in _vm_servers(db, cluster):
        key = s.hypervisor_vm_id or f"default/{s.name}"
        ns = key.split("/", 1)[0]
        running = str(s.vm_power_state or "").lower() == "running"
        phase = "Running" if running else "Stopped"
        mem_gb = round((s.vm_memory_mb or 0) / 1024.0, 1)
        out.append({
            "name": s.vm_name or s.name, "ip_address": s.vm_guest_ip or s.ip_address or "",
            "hostname": s.vm_guest_hostname or s.name, "vm_guest_hostname": s.vm_guest_hostname or "",
            "os_type": s.os_type or "", "guest_os": s.os_type or "",
            "cpu_cores": s.vm_cpu_count or 0, "cpu_count": s.vm_cpu_count or 0,
            "memory_gb": mem_gb, "memory_mb": s.vm_memory_mb or 0,
            "status": "ONLINE" if running else "OFFLINE", "power_state": "poweredOn" if running else "poweredOff",
            "vm_id": key, "uid": "", "moref": key, "namespace": ns,
            "node_name": s.vm_host_name or "", "node": s.vm_host_name or "", "host": s.vm_host_name or "",
            "phase": phase, "printable_status": phase, "usage": None,
        })
    return out


def fake_overview(db: Session, cluster: OpenShiftCluster) -> Dict[str, Any]:
    """`cluster_ops.cluster_overview` çıktısının DB'den üretilen karşılığı."""
    nodes = db.query(OpenShiftNode).filter(OpenShiftNode.cluster_id == cluster.id).order_by(OpenShiftNode.name).all()
    projects = db.query(OpenShiftProject).filter(OpenShiftProject.cluster_id == cluster.id).all()
    pods = db.query(OpenShiftWorkload).filter(OpenShiftWorkload.cluster_id == cluster.id,
                                              OpenShiftWorkload.kind == "pod").all()
    node_rows, cpu_total, mem_total, ready_n = [], 0.0, 0.0, 0
    for n in nodes:
        meta = n.meta_data or {}
        ready = (n.status or "").lower() == "ready"
        ready_n += 1 if ready else 0
        cpu_total += float(n.cpu_cores or 0)
        mem_total += float(n.memory_gb or 0)
        node_rows.append({
            "name": n.name, "ready": ready, "roles": [n.role or "worker"], "cpu": n.cpu_cores,
            "memory_gb": n.memory_gb, "kubelet": n.kubelet_version, "os": n.os_image,
            "internal_ip": meta.get("internal_ip") or "", "external_ip": "", "hostname": meta.get("hostname") or n.name,
            "ip_address": meta.get("ip_address") or "", "usage": None,
            "cpu_request_pct": n.cpu_usage_pct, "memory_request_pct": n.memory_usage_pct,
        })
    from app.services.openshift.cluster_ops import OPERATOR_GROUPS
    operators = [{**op, "installed": True} for op in OPERATOR_GROUPS]
    user_ns = [p.name for p in projects if not (p.meta_data or {}).get("is_system")]
    return {
        "cluster": {"id": cluster.id, "name": cluster.name, "api_url": cluster.api_url, "verify_ssl": False,
                    "status": cluster.status},
        "version": cluster.version or "",
        "operators": operators, "migration_ready": True, "migration_missing": [],
        "nodes": node_rows,
        "capacity": {"cpu_cores": round(cpu_total, 1), "cpu_used_cores": None, "memory_gb": round(mem_total, 1),
                     "memory_used_gb": None, "nodes_total": len(node_rows), "nodes_ready": ready_n,
                     "pods_running": sum(1 for p in pods if (p.status or "") == "Running"), "pods_total": len(pods),
                     "metrics_available": False},
        "storage_classes": [{"name": "fake-ceph-rbd", "provisioner": "fake.csi", "default": True}],
        "network_attachment_definitions": [],
        "namespaces": {"total": len(projects), "user": user_ns[:50], "user_count": len(user_ns)},
        "kubevirt_vms": len(_vm_servers(db, cluster)),
        "fake": True,
    }
