"""Platform adaptörleri: kaynak veriyi ortak `ClusterModel`e çevirir (hesap yok, yalnız eşleme)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.capacity.model import ClusterModel, HaSpec, Node


def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def from_virt_hosts(platform: str, cluster: str, hosts: List[Dict[str, Any]], vc: Any = None, *,
                    olvm_cfg: Optional[Dict[str, Any]] = None, vms_on: Optional[List[Dict[str, Any]]] = None,
                    instance_id: Optional[int] = None, instance_name: str = "", datacenter: Optional[str] = None,
                    pools: Optional[Any] = None,
                    failover_hosts: Optional[List[str]] = None) -> ClusterModel:
    """vCenter / OLVM / OpenShift Virt: `virt_insights_data.latest_hosts` satırları + cluster satırı.

    vCenter: `vc` (VirtCluster) HA/admission control alanları. OLVM: `olvm_cfg` (cluster config snapshot:
    `ha_reservation`, `memory_overcommit_pct`) — yoksa None (bilinmiyor → eski davranış).
    """
    nodes = tuple(Node(name=h["host_name"], mem_gb=_f(h["mem_total_gb"]), cpu_cores=_f(h.get("cpu_cores")),
                       usable=bool(h["usable"]), mem_used_gb=_f(h["mem_used_gb"]),
                       cpu_used_cores=_f(h["cpu_used_cores"]), ref=str(h.get("host_ref") or "")) for h in hosts)
    ha = None
    if platform == "vmware" and vc is not None:
        ha = HaSpec(ha_enabled=vc.ha_enabled, admission_control_enabled=vc.admission_control_enabled,
                    policy_type=vc.policy_type, mem_failover_pct=vc.mem_failover_pct,
                    cpu_failover_pct=vc.cpu_failover_pct, failover_level=vc.failover_level,
                    failover_hosts=(tuple(failover_hosts) if failover_hosts is not None else None),
                    total_slots=getattr(vc, "total_slots", None), used_slots=getattr(vc, "used_slots", None),
                    unreserved_slots=getattr(vc, "unreserved_slots", None),
                    slot_cpu_mhz=getattr(vc, "slot_cpu_mhz", None), slot_memory_mb=getattr(vc, "slot_memory_mb", None))
    ha_res: Optional[bool] = None
    oc: Optional[float] = None
    if platform == "olvm" and olvm_cfg:
        v = olvm_cfg.get("ha_reservation")
        ha_res = v if isinstance(v, bool) else None
        try:
            oc = float(olvm_cfg["memory_overcommit_pct"]) if olvm_cfg.get("memory_overcommit_pct") is not None else None
        except (TypeError, ValueError):
            oc = None
    on = vms_on or []
    return ClusterModel(platform=platform, name=cluster, nodes=nodes, ha=ha, ha_reservation=ha_res,
                        mem_overcommit_pct=oc, mem_allocated_gb=sum(_f(v.get("memory_gb")) for v in on),
                        vcpu_allocated=sum(_f(v.get("vcpu")) for v in on),
                        instance_id=instance_id, instance_name=instance_name, datacenter=datacenter, pools=pools)


def from_ocp_workers(workers: List[Dict[str, Any]], name: str = "cluster") -> ClusterModel:
    """OpenShift: `ocp_insights.evaluate` → `capacity.workers` (request tabanlı; HA rezervi kavramı yok)."""
    nodes = tuple(Node(name=w["name"], mem_gb=_f(w.get("mem_gb_raw", w.get("mem_gb"))), cpu_cores=_f(w.get("cpu_m")) / 1000.0,
                       usable=bool(w.get("ready") and w.get("schedulable")),
                       mem_used_gb=_f(w.get("req_mem_gb")), cpu_used_cores=_f(w.get("req_cpu_m")) / 1000.0)
                  for w in workers or [])
    return ClusterModel(platform="ocp", name=name, nodes=nodes, reserve_mode="none")
