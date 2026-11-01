"""Donanım arızasının etki alanı (blast radius): ESXi host → VM → iş servisi + küme kapasitesi.

Salt-okunur; yalnız ainew'in kendi envanterini (servers / business_service_map / hw_*) okur. Çıktı BMC IP/seri içermez
(olay `raw_data` ve incident kartında kullanılır).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.services.hw.constants import HEALTH_CRITICAL

_ON = {"poweredon", "on", "up", "running"}


def is_powered_on(state) -> bool:
    """vCenter `poweredOn`, oVirt/OCP `POWERED_ON`, `up`, `running` — büyük/küçük harf ve ayraç duyarsız."""
    return "".join(ch for ch in str(state or "").lower() if ch.isalpha()) in _ON
_TIER_RANK = {"critical": 0, "high": 1, "standard": 2, "low": 3}


def host_impact(db: Session, hypervisor_id: Optional[int], host_ref: Optional[str], host_name: Optional[str],
                *, max_vms: int = 12) -> Dict[str, Any]:
    from app.models.hw import HwHostLink, HwServer
    from app.models.hypervisor_inventory import HypervisorHostInventory
    from app.models.infrastructure_report import BusinessServiceMap
    from app.models.server import Server

    vms: List[Server] = []
    if hypervisor_id and (host_ref or host_name):
        conds = []
        if host_ref:
            conds.append(Server.vm_host_ref == host_ref)
        if host_name:
            conds.append(Server.vm_host_name == host_name)
        vms = db.query(Server).filter(Server.hypervisor_id == hypervisor_id, or_(*conds)).all()
    on = [v for v in vms if is_powered_on(v.vm_power_state)]
    ids = [v.id for v in vms]
    svc: Dict[str, Dict[str, Any]] = {}
    if ids:
        for m in db.query(BusinessServiceMap).filter(BusinessServiceMap.server_id.in_(ids)).all():
            d = svc.setdefault(m.service_name, {"name": m.service_name, "tier": m.service_tier or "standard", "vm_count": 0})
            d["vm_count"] += 1
            if _TIER_RANK.get(m.service_tier or "standard", 2) < _TIER_RANK.get(d["tier"], 2):
                d["tier"] = m.service_tier
    services = sorted(svc.values(), key=lambda x: (_TIER_RANK.get(x["tier"], 2), x["name"]))

    cluster: Optional[Dict[str, Any]] = None
    inv = (db.query(HypervisorHostInventory)
           .filter(HypervisorHostInventory.hypervisor_id == hypervisor_id,
                   or_(HypervisorHostInventory.host_ref == host_ref, HypervisorHostInventory.host_name == host_name)).first()
           if hypervisor_id else None)
    if inv is not None and inv.cluster_name:
        peers = db.query(HypervisorHostInventory).filter(HypervisorHostInventory.hypervisor_id == hypervisor_id,
                                                         HypervisorHostInventory.cluster_name == inv.cluster_name).all()
        pid = [p.id for p in peers]
        crit = 0
        for l, s in (db.query(HwHostLink, HwServer).join(HwServer, HwServer.id == HwHostLink.hw_server_id)
                     .filter(HwHostLink.target_kind == "esxi", HwHostLink.target_id.in_(pid or [-1])).all()):
            if s.health == HEALTH_CRITICAL:
                crit += 1
        healthy = len(peers) - crit
        cluster = {"name": inv.cluster_name, "hosts": len(peers), "hw_critical_hosts": crit, "healthy_hosts": healthy,
                   # kalan sağlıklı host sayısı 2'nin altındaysa bir sonraki host kaybında HA yeniden başlatma kapasitesi yok
                   "ha_risk": len(peers) > 1 and healthy < 2}
    return {"vm_count": len(vms), "vm_powered_on": len(on), "vms": [v.vm_name or v.name for v in vms[:max_vms]],
            "services": services[:10], "critical_services": sum(1 for s in services if s["tier"] in ("critical", "high")),
            "cluster": cluster}
