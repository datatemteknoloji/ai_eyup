"""OpenShift Virtualization host metrikleri → hypervisor_host_metrics.

VMware ESX metrik sync'inin OCP karşılığı: yönetilen openshift_virt
hypervisor kayıtları için cluster node CPU/RAM (+ PV/PVC disk özeti)
değerlerini yazar. Kaynak: openshift_nodes + kube API.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_inventory import HypervisorHostInventory
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.openshift import OpenShiftCluster, OpenShiftNode
from app.models.server import Server
from app.services.chat_quality import power_state as _ps_canon
from app.services.openshift_virt_inventory import META_CLUSTER_ID

logger = logging.getLogger(__name__)


def _clamp_pct(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(max(0.0, min(100.0, float(v))), 1)
    except (TypeError, ValueError):
        return None


def _pv_disk_usage(cluster: OpenShiftCluster) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Bound PVC kapasitesi / PV kapasitesi → (used_gb, total_gb, pct)."""
    try:
        from app.services.openshift.cluster_ops import client_from_cluster
        from app.services.openshift.ocp_client import OpenShiftClient

        client = client_from_cluster(cluster)
        try:
            pv_r = client._get("/api/v1/persistentvolumes", params={"limit": 500}, timeout=30)
            pvc_r = client._get("/api/v1/persistentvolumeclaims", params={"limit": 500}, timeout=30)
            if pv_r.status_code != 200:
                return None, None, None
            pvs = (pv_r.json() or {}).get("items") or []
            pvcs = (pvc_r.json() or {}).get("items") or [] if pvc_r.status_code == 200 else []
            total = 0.0
            for pv in pvs:
                cap = ((pv.get("spec") or {}).get("capacity") or {}).get("storage")
                if cap:
                    total += float(OpenShiftClient._parse_quantity(cap))
            used = 0.0
            for pvc in pvcs:
                status = pvc.get("status") or {}
                if (status.get("phase") or "") != "Bound":
                    continue
                cap = (
                    status.get("capacity")
                    or ((pvc.get("spec") or {}).get("resources") or {}).get("requests")
                    or {}
                ).get("storage")
                if cap:
                    used += float(OpenShiftClient._parse_quantity(cap))
            if total <= 0:
                return None, None, None
            return round(used, 2), round(total, 2), round(min(100.0, (used / total) * 100.0), 1)
        finally:
            try:
                client.logout()
            except Exception:
                pass
    except Exception as exc:
        logger.debug("PV disk kullanımı alınamadı (cluster=%s): %s", cluster.name, exc)
        return None, None, None


def _resolve_cluster(db: Session, hv: Hypervisor) -> Optional[OpenShiftCluster]:
    meta = hv.meta_data or {}
    cluster_id = meta.get(META_CLUSTER_ID)
    if cluster_id:
        c = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == int(cluster_id)).first()
        if c:
            return c
    api = ((hv.connection_config or {}).get("api_url") or hv.hostname or "").rstrip("/")
    if not api:
        return None
    for c in db.query(OpenShiftCluster).all():
        if (c.api_url or "").rstrip("/") == api:
            return c
    return None


def _write_fake_host_vm_counts(db: Session, hv: Hypervisor, now: datetime) -> None:
    """Sahte OpenShift Virt envanteri için node başı VM sayısı (yalnız en son metrik satırı güncellenir)."""
    from sqlalchemy import func as sa_func

    sub = (
        db.query(HypervisorHostMetric.host_name, sa_func.max(HypervisorHostMetric.timestamp).label("last_ts"))
        .filter(HypervisorHostMetric.hypervisor_id == hv.id)
        .group_by(HypervisorHostMetric.host_name)
        .subquery()
    )
    latest = (
        db.query(HypervisorHostMetric)
        .join(sub, (HypervisorHostMetric.host_name == sub.c.host_name) & (HypervisorHostMetric.timestamp == sub.c.last_ts))
        .filter(HypervisorHostMetric.hypervisor_id == hv.id)
        .all()
    )
    counts: dict = {}
    for v in db.query(Server).filter(Server.hypervisor_id == hv.id).all():
        key = (v.vm_host_name or "").strip().lower()
        if not key:
            continue
        tot, on = counts.get(key, (0, 0))
        counts[key] = (tot + 1, on + (1 if ((v.status or "").upper() == "ONLINE" or _ps_canon.is_on(v.vm_power_state)) else 0))
    for row in latest:
        tot, on = counts.get((row.host_name or "").strip().lower(), (0, 0))
        if row.vms_total != tot or row.vms_running != on:
            row.vms_total, row.vms_running = tot, on
    db.commit()


def sync_openshift_virt_host_metrics(db: Session) -> Dict[str, Any]:
    """Tüm openshift_virt hypervisor'lar için node metriklerini yaz."""
    hvs = (
        db.query(Hypervisor)
        .filter(Hypervisor.hypervisor_type == HypervisorType.OPENSHIFT_VIRT)
        .all()
    )
    if not hvs:
        return {"hypervisors": 0, "hosts": 0, "errors": []}

    now = datetime.now(timezone.utc)
    total_hosts = 0
    errors: List[str] = []
    disk_cache: Dict[int, Tuple[Optional[float], Optional[float], Optional[float]]] = {}

    for hv in hvs:
        if (hv.meta_data or {}).get("fake_seed"):
            # Sahte envanter (scripts/fake_virt_seed.py): gerçek cluster yok ama node başı VM sayısı
            # envanterden (vm_host_name) yazılır — yoksa eski «cluster toplamı × node» şişmesi durur.
            _write_fake_host_vm_counts(db, hv, now)
            total_hosts += 1
            continue
        cluster = _resolve_cluster(db, hv)
        if not cluster:
            errors.append(f"{hv.name}: bağlı OpenShift cluster bulunamadı")
            continue

        nodes = db.query(OpenShiftNode).filter(OpenShiftNode.cluster_id == cluster.id).all()
        if not nodes:
            errors.append(f"{hv.name}: openshift_nodes boş (önce cluster sync)")
            continue

        if cluster.id not in disk_cache:
            disk_cache[cluster.id] = _pv_disk_usage(cluster)
        ds_used, ds_total, ds_pct = disk_cache[cluster.id]

        vms = db.query(Server).filter(Server.hypervisor_id == hv.id).all()

        def _vm_on(v) -> bool:
            return (v.status or "").upper() == "ONLINE" or _ps_canon.is_on(v.vm_power_state)

        # VM sayıları NODE BAŞINA: envanterden (vm_host_name/ref). Eskiden hypervisor toplamı
        # her node'a yazılıyordu ve dashboard hostları toplayınca N kat şişiriyordu (500 VM × 15 node = 7500).
        by_node: dict = {}
        for v in vms:
            key = (v.vm_host_name or "").strip().lower() or (v.vm_host_ref or "").rsplit("/", 1)[-1].strip().lower()
            if not key:
                continue
            tot, on = by_node.get(key, (0, 0))
            by_node[key] = (tot + 1, on + (1 if _vm_on(v) else 0))

        for node in nodes:
            cpu_pct = _clamp_pct(node.cpu_usage_pct)
            mem_pct = _clamp_pct(node.memory_usage_pct)
            mem_total_mb = round(float(node.memory_gb or 0) * 1024, 1) if node.memory_gb else None
            mem_used_mb = (
                round(mem_total_mb * (mem_pct / 100.0), 1)
                if mem_total_mb is not None and mem_pct is not None
                else None
            )
            node_tot, node_on = by_node.get((node.name or "").strip().lower(), (0, 0))
            conn = "connected" if (node.status or "").lower() == "ready" else "notResponding"
            meta = node.meta_data if isinstance(getattr(node, "meta_data", None), dict) else {}
            ip = (meta.get("ip_address") or meta.get("internal_ip") or "").strip() or None
            db.add(
                HypervisorHostMetric(
                    timestamp=now,
                    hypervisor_id=hv.id,
                    host_name=node.name,
                    host_ref=f"ocp-node/{node.name}",
                    cpu_usage_pct=cpu_pct,
                    cpu_cores=int(node.cpu_cores) if node.cpu_cores else None,
                    mem_used_mb=mem_used_mb,
                    mem_total_mb=mem_total_mb,
                    mem_usage_pct=mem_pct,
                    ds_used_gb=ds_used,
                    ds_total_gb=ds_total,
                    ds_usage_pct=ds_pct,
                    vms_running=node_on,
                    vms_total=node_tot,
                    connection_state=conn,
                    power_state="poweredOn" if conn == "connected" else "unknown",
                    maintenance_mode=0,
                    cluster_name=cluster.name,
                    overall_status="green" if conn == "connected" else "red",
                )
            )
            href = f"ocp-node/{node.name}"
            inv = (
                db.query(HypervisorHostInventory)
                .filter(
                    HypervisorHostInventory.hypervisor_id == hv.id,
                    HypervisorHostInventory.host_ref == href,
                )
                .first()
            )
            if inv is None:
                inv = HypervisorHostInventory(hypervisor_id=hv.id, host_ref=href)
                db.add(inv)
            inv.host_name = node.name
            inv.product_full_name = "OpenShift node"
            inv.product_version = getattr(node, "kubelet_version", None)
            inv.vnics = [{"device": "mgmt", "portgroup": "management", "ip_address": ip}] if ip else []
            inv.dns = {
                "host_name": node.name,
                "address": ip,
                "roles": getattr(node, "role", None) or "worker",
            }
            inv.cluster_name = cluster.name
            inv.overall_status = "green" if conn == "connected" else "red"
            inv.last_synced_at = now
            total_hosts += 1

        hv.status = "ONLINE"
        db.add(hv)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("openshift_virt host metric commit failed")
        return {"hypervisors": len(hvs), "hosts": 0, "errors": errors + [str(exc)]}

    logger.info(
        "OpenShift Virt host metrics: hv=%s hosts=%s errors=%s",
        len(hvs),
        total_hosts,
        errors,
    )
    return {"hypervisors": len(hvs), "hosts": total_hosts, "errors": errors}
