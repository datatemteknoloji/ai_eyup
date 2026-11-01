"""Sanallaştırma hiyerarşisi: Hypervisor → Cluster → Host → VM (tek kaynak: `servers`).

Neden ayrı servis: host metriklerindeki `vms_total` güvenilir değil (OpenShift'te cluster toplamı
her node'a yazıldığı için toplanınca N kat şişiyordu). VM sayıları bu yüzden YALNIZ `servers`
envanterinden hesaplanır; host metrikleri yalnız kaynak kullanımı (CPU/RAM) içindir.

Cluster üyeliği: host envanteri `cluster_name` (yoksa metrikteki), VM `vm_cluster`. Cluster'sız
host'lar `STANDALONE` anahtarıyla gruplanır (vCenter'da cluster'sız ESXi gerçek bir durumdur).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_inventory import HypervisorHostInventory
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.server import Server
from app.models.virt_cluster import VirtCluster
from app.services.chat_quality import power_state as _ps

STANDALONE = "__standalone__"

_VIRT_TYPES = (HypervisorType.VMWARE, HypervisorType.KVM, HypervisorType.OPENSHIFT_VIRT,
               HypervisorType.HYPERV, HypervisorType.PROXMOX, HypervisorType.XEN)


def _latest_host_usage(db: Session, hv_id: int) -> Dict[str, dict]:
    """host_name(lower) → son metrik satırının kullanım özeti."""
    sub = (
        db.query(HypervisorHostMetric.host_name, sa_func.max(HypervisorHostMetric.timestamp).label("ts"))
        .filter(HypervisorHostMetric.hypervisor_id == hv_id)
        .group_by(HypervisorHostMetric.host_name)
        .subquery()
    )
    rows = (
        db.query(HypervisorHostMetric)
        .join(sub, (HypervisorHostMetric.host_name == sub.c.host_name) & (HypervisorHostMetric.timestamp == sub.c.ts))
        .filter(HypervisorHostMetric.hypervisor_id == hv_id)
        .all()
    )
    out = {}
    for r in rows:
        out[(r.host_name or "").strip().lower()] = {
            "cpu_pct": r.cpu_usage_pct, "mem_pct": r.mem_usage_pct,
            "state": r.connection_state, "cluster_name": r.cluster_name,
        }
    return out


def _vm_counts(db: Session, hv_id: int) -> dict:
    """Envanterden VM sayıları: cluster, host ve toplam. Host anahtarı vm_host_name (lower)."""
    rows = (
        db.query(Server.vm_cluster, Server.vm_host_name, Server.status, Server.vm_power_state)
        .filter(Server.hypervisor_id == hv_id)
        .all()
    )
    by_cluster: Dict[str, List[int]] = {}
    by_host: Dict[str, List[int]] = {}
    total = [0, 0]
    unmapped = 0
    for cl, host, status, pw in rows:
        on = 1 if ((status or "").upper() == "ONLINE" or _ps.is_on(pw)) else 0
        total[0] += 1
        total[1] += on
        ck = (cl or "").strip() or STANDALONE
        by_cluster.setdefault(ck, [0, 0])
        by_cluster[ck][0] += 1
        by_cluster[ck][1] += on
        hk = (host or "").strip().lower()
        if hk:
            by_host.setdefault(hk, [0, 0])
            by_host[hk][0] += 1
            by_host[hk][1] += on
        else:
            unmapped += 1
    return {"by_cluster": by_cluster, "by_host": by_host, "total": total, "unmapped": unmapped}


def hierarchy(db: Session, hypervisor_id: Optional[int] = None) -> dict:
    """Hypervisor → cluster → host ağacı. VM satırları dahil değil (lazy: /host-vms)."""
    q = db.query(Hypervisor).filter(Hypervisor.hypervisor_type.in_(_VIRT_TYPES))
    if hypervisor_id:
        q = q.filter(Hypervisor.id == hypervisor_id)
    hvs = q.order_by(Hypervisor.name.asc()).all()

    out = []
    for hv in hvs:
        usage = _latest_host_usage(db, hv.id)
        counts = _vm_counts(db, hv.id)
        inv = (
            db.query(HypervisorHostInventory)
            .filter(HypervisorHostInventory.hypervisor_id == hv.id)
            .all()
        )
        clusters_meta = {
            c.name: {"ha_enabled": c.ha_enabled, "drs_enabled": getattr(c, "drs_enabled", None),
                     "cpu_cores": c.cpu_cores, "memory_gb": c.memory_gb}
            for c in db.query(VirtCluster).filter(VirtCluster.hypervisor_id == hv.id).all()
        }
        # Host'ların gerçek cluster'ı: envanter/metrikteki cluster_name. VM'lerin vm_cluster değeri
        # farklı bir ada işaret ediyorsa (OpenShift'te namespace/etiket yazılabiliyor) host'ların
        # cluster'ı esas alınır ki VM'ler boş bir «cluster» altında yalnız kalmasın.
        host_cluster_names = {
            ((i.cluster_name or "").strip()
             or (usage.get((i.host_name or "").strip().lower(), {}).get("cluster_name") or "").strip())
            for i in inv
        }
        host_cluster_names.discard("")

        groups: Dict[str, List[dict]] = {}
        for i in inv:
            key = (i.cluster_name or "").strip()
            if not key:
                key = (usage.get((i.host_name or "").strip().lower(), {}).get("cluster_name") or "").strip()
            key = key or STANDALONE
            u = usage.get((i.host_name or "").strip().lower(), {})
            hc = counts["by_host"].get((i.host_name or "").strip().lower(), [0, 0])
            dns = i.dns if isinstance(i.dns, dict) else {}
            groups.setdefault(key, []).append({
                "host_name": i.host_name, "host_ref": i.host_ref,
                "role": dns.get("roles") or dns.get("role") or None,
                "state": u.get("state") or i.overall_status, "cpu_pct": u.get("cpu_pct"),
                "mem_pct": u.get("mem_pct"), "vms_total": hc[0], "vms_running": hc[1],
            })
        clusters = []
        vm_cluster_names = {k for k in counts["by_cluster"] if k != STANDALONE and k in host_cluster_names}
        # VM'lerin vm_cluster adı host cluster'larından hiçbiriyle eşleşmiyorsa (OpenShift'te
        # vm_cluster namespace/etiket olabiliyor) VE tek bir host cluster'ı varsa sayıları ona yaz.
        # Birden fazla cluster varsa (VM cluster'ı gerçekten bilinmiyor) uydurma dağıtım yapma.
        orphan_vm = [0, 0]
        if len(host_cluster_names) == 1 and not (set(counts["by_cluster"]) & host_cluster_names):
            for v in counts["by_cluster"].values():
                orphan_vm[0] += v[0]
                orphan_vm[1] += v[1]
        for name in sorted(set(groups) | set(clusters_meta) | vm_cluster_names):
            hosts = sorted(groups.get(name, []), key=lambda h: (h["host_name"] or ""))
            vc = list(counts["by_cluster"].get(name, [0, 0]))
            if orphan_vm[0] and name in host_cluster_names:
                vc[0] += orphan_vm[0]
                vc[1] += orphan_vm[1]
            meta = clusters_meta.get(name, {})
            clusters.append({
                "name": name, "standalone": name == STANDALONE,
                "ha_enabled": meta.get("ha_enabled"), "drs_enabled": meta.get("drs_enabled"),
                "host_count": len(hosts), "vms_total": vc[0], "vms_running": vc[1], "hosts": hosts,
            })
        out.append({
            "hypervisor_id": hv.id, "name": hv.name,
            "type": getattr(hv.hypervisor_type, "value", str(hv.hypervisor_type)),
            "host_count": len(inv), "vms_total": counts["total"][0], "vms_running": counts["total"][1],
            "vms_unmapped": counts["unmapped"], "clusters": clusters,
        })
    return {"hypervisors": out}
