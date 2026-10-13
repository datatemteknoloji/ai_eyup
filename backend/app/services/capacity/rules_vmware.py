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
    if "failoverhost" in pt:
        return _dedicated(vc, usable, by_mem)
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


def is_slot_policy(vc: Optional[HaSpec]) -> bool:
    """"Host failures cluster tolerates" (ClusterFailoverLevelAdmissionControlPolicy) → slot tabanlı admission control."""
    return bool(vc and vc.ha_enabled and vc.admission_control_enabled and "failoverlevel" in str(vc.policy_type or "").lower())


def _dedicated(vc: HaSpec, usable: Sequence[Node], by_mem: Sequence[Node]) -> Dict[str, Any]:
    """E3 — "Use dedicated failover hosts": ayrılmış host'lar normal çalışmada VM çalıştırmaz (yerleşime KAPALI);
    kapasiteleri rezervdir. Kaynak: vSphere Availability — Admission Control ("Dedicated Failover Hosts").
    Host listesi okunamadıysa 1 host varsayımı (etiketli); okundu ama hiçbiri kullanılabilir değilse rezerv 0 (HA
    arıza anında yeniden başlatma kapasitesi YOK uyarısı)."""
    if vc.failover_hosts is None:
        top = by_mem[:1]
        return {"policy": "dedicated_hosts_unread", "assumed": True,
                "label": "Ayrılmış failover host politikası — host listesi okunamadı; varsayım: 1 host rezerv",
                "mem_gb": sum(h.mem_gb for h in top),
                "cpu_cores": sum(float(h.cpu_cores or 0) for h in top)}
    refs = set(vc.failover_hosts)
    closed = [n for n in usable if n.ref in refs]
    if not closed:
        return {"policy": "dedicated_hosts", "assumed": False, "mem_gb": 0.0, "cpu_cores": 0.0, "closed_hosts": [],
                "label": "Ayrılmış failover host politikası — ayrılmış host kullanılabilir değil (bakımda/bağlantısız ya da "
                         "listede yok); rezerv yok"}
    return {"policy": "dedicated_hosts", "assumed": False, "closed_hosts": [n.name for n in closed],
            "label": f"Ayrılmış failover host: {', '.join(n.name for n in closed)} (yerleşime kapalı)",
            "mem_gb": sum(n.mem_gb for n in closed), "cpu_cores": sum(float(n.cpu_cores or 0) for n in closed)}


def slot_check(model: ClusterModel, count: int) -> Optional[Dict[str, Any]]:
    """E3 — slot politikasında admission control: yeni VM'ler boş (reserve edilmemiş) slot ister.

    Slot boyutu, cluster'daki VM'lerin EN BÜYÜK CPU / Memory rezervasyonundan gelir (rezervasyon yoksa CPU 32 MHz,
    Memory 0+overhead); rezervasyonsuz yeni VM 1 slot kullanır. Bu VM'in rezervasyonu bilinmediği için 1 slot/VM
    varsayılır (etiketli). `unreserved_slots` son HA runtime okumasıdır (anlık değil). Slot politikası değilse veya
    okuma yoksa None. Kaynak: vSphere Availability — "Slot Policy" (RetrieveDasAdvancedRuntimeInfo).
    """
    vc = model.ha
    if not is_slot_policy(vc) or vc is None or vc.unreserved_slots is None:
        return None
    need = max(1, int(count))
    return {"policy": "slot", "total_slots": vc.total_slots, "used_slots": vc.used_slots,
            "unreserved_slots": vc.unreserved_slots, "slot_cpu_mhz": vc.slot_cpu_mhz, "slot_memory_mb": vc.slot_memory_mb,
            "needed_slots": need, "fits": need <= int(vc.unreserved_slots),
            "assumption": "Yeni VM'de CPU/Memory rezervasyonu yok sayıldı → 1 slot/VM; slot sayısı son HA okumasından "
                          "(anlık değil)."}
