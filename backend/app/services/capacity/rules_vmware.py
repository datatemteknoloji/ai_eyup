"""vCenter kural modülü (H.0): vSphere HA admission control rezervi.

Kaynak: vSphere Availability — "Admission Control": "Host failures cluster tolerates" (failover level N → N en büyük
host kadar kaynak), "Percentage of cluster resources reserved" (yüzde), "Dedicated failover hosts"; admission control
kapalıyken veya HA kapalıyken rezerv garantisi yoktur. Doğrulama 2026-10-13.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from app.services.capacity.model import ClusterModel, HaSpec, Node


def _none(policy: str, label: str) -> Dict[str, Any]:
    return {"policy": policy, "label": label, "mem_gb": 0.0, "cpu_cores": 0.0, "assumed": False}


def reserve(model: ClusterModel, usable: Sequence[Node], by_mem: Sequence[Node],
            mem_total: float, cpu_total: float) -> Optional[Dict[str, Any]]:
    """HaSpec okunduysa rezerv; okunmadıysa None (çağıran genel varsayımı uygular)."""
    if model.ha is None:
        return None
    vc: HaSpec = model.ha
    if not vc.ha_enabled:
        return _none("ha_off", "HA kapalı — rezerv yok")
    if not vc.admission_control_enabled:
        return _none("ac_off", "Admission control kapalı — rezerv garanti değil")
    pt = str(vc.policy_type or "").lower()
    if "resource" in pt or "percent" in pt or vc.mem_failover_pct:
        mp = float(vc.mem_failover_pct or 0)
        cp = float(vc.cpu_failover_pct or 0)
        return {"policy": "percentage", "label": f"Yüzde politikası (CPU %{cp:.0f} / Memory %{mp:.0f})",
                "mem_gb": mem_total * mp / 100.0, "cpu_cores": cpu_total * cp / 100.0, "assumed": False}
    n = int(vc.failover_level or 1)
    top = by_mem[:n]
    return {"policy": "failover_level", "label": f"Host failover seviyesi = {n}",
            "mem_gb": sum(h.mem_gb for h in top),
            "cpu_cores": sum(float(h.cpu_cores or 0) for h in top), "assumed": False}
