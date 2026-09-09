"""Canlı envanter özeti — Ayarlar'daki Mimari GUIDE PDF'i için.

Sırlar, credential, IP listesi dump'ı yok; yalnızca sayılar + 2–3 örnek ad.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.version import get_app_version
from app.services.platform_scope import is_windows_server


def _safe_count(fn) -> int:
    try:
        return int(fn() or 0)
    except Exception:
        return 0


def _names(rows: List[Any], attr: str = "name", limit: int = 3) -> List[str]:
    out: List[str] = []
    for r in rows[:limit]:
        val = getattr(r, attr, None) or getattr(r, "hostname", None) or getattr(r, "host_name", None)
        if val:
            out.append(str(val))
    return out


def collect_architecture_snapshot(db: Session) -> Dict[str, Any]:
    from app.models.server import Server
    from app.models.hypervisor import Hypervisor
    from app.models.event import SystemEvent, Incident

    servers = db.query(Server).all()
    linux = [s for s in servers if not is_windows_server(s) and not s.hypervisor_id]
    windows = [s for s in servers if is_windows_server(s)]
    vms = [s for s in servers if s.hypervisor_id]
    ai_ready_linux = [s for s in linux if s.ai_ready]
    ai_ready_win = [s for s in windows if s.ai_ready]

    hyps = db.query(Hypervisor).all()
    hyp_rows = []
    for h in hyps:
        htype = getattr(h, "hypervisor_type", None)
        htype_s = getattr(htype, "value", None) or str(htype or "")
        hyp_rows.append({
            "name": h.name,
            "type": htype_s,
            "status": h.status,
        })

    hosts = 0
    host_examples: List[str] = []
    try:
        from app.models.hypervisor_inventory import HypervisorHostInventory
        host_q = db.query(HypervisorHostInventory).all()
        hosts = len(host_q)
        host_examples = _names(host_q, "host_name")
    except Exception:
        pass

    ds_count = 0
    ds_examples: List[str] = []
    ds_hot: Optional[Dict[str, Any]] = None
    try:
        from app.models.virt_datastore import VirtDatastore
        dss = db.query(VirtDatastore).all()
        ds_count = len(dss)
        ds_examples = _names(dss)
        fullest = max(
            (d for d in dss if d.usage_pct is not None),
            key=lambda d: float(d.usage_pct or 0),
            default=None,
        )
        if fullest:
            ds_hot = {
                "name": fullest.name,
                "usage_pct": round(float(fullest.usage_pct or 0), 1),
                "free_gb": round(float(fullest.free_gb or 0), 1) if fullest.free_gb is not None else None,
            }
    except Exception:
        pass

    clusters = 0
    cluster_examples: List[str] = []
    try:
        from app.models.virt_cluster import VirtCluster
        cls = db.query(VirtCluster).all()
        clusters = len(cls)
        cluster_examples = _names(cls)
    except Exception:
        pass

    ocp = 0
    ocp_examples: List[str] = []
    try:
        from app.models.openshift import OpenShiftCluster
        ocps = db.query(OpenShiftCluster).all()
        ocp = len(ocps)
        ocp_examples = _names(ocps)
    except Exception:
        pass

    exa = 0
    try:
        from app.models.exadata import ExadataRack
        exa = db.query(ExadataRack).count()
    except Exception:
        pass

    events_open = _safe_count(
        lambda: db.query(SystemEvent).filter(SystemEvent.resolved == False).count()  # noqa: E712
    )
    incidents_open = _safe_count(
        lambda: db.query(Incident).filter(Incident.status.in_(["open", "investigating"])).count()
    )

    vm_on = [v for v in vms if (v.vm_power_state or "").lower() in ("poweredon", "powered_on", "up", "running")]
    vm_examples = _names(vms, "vm_name") or _names(vms)

    return {
        "version": get_app_version(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "linux_hosts": len(linux),
            "windows_hosts": len(windows),
            "vms": len(vms),
            "vms_powered_on": len(vm_on),
            "ai_ready_linux": len(ai_ready_linux),
            "ai_ready_windows": len(ai_ready_win),
            "hypervisors": len(hyps),
            "esxi_hosts": hosts,
            "datastores": ds_count,
            "clusters": clusters,
            "openshift_clusters": ocp,
            "exadata_racks": exa,
            "events_open": events_open,
            "incidents_open": incidents_open,
        },
        "examples": {
            "linux": _names(linux),
            "windows": _names(windows),
            "vms": vm_examples,
            "esxi_hosts": host_examples,
            "datastores": ds_examples,
            "clusters": cluster_examples,
            "openshift": ocp_examples,
            "hypervisors": [h["name"] for h in hyp_rows[:3]],
        },
        "hypervisors": hyp_rows[:8],
        "hottest_datastore": ds_hot,
    }
