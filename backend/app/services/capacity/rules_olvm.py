"""OLVM kural modülü (H.0): HA Reservation ve Memory Optimization (overcommit).

Kaynak: Oracle Linux Virtualization Manager — Scheduling Policy "Enable HA Reservation" (Manager, HA VM'lerin
yeniden başlatılabilmesi için host kapasitesi ayırır; AYRILAN MİKTARIN hesabı belgede tanımlı DEĞİL → açıkken 1 host
varsayımı, etiketli) ve Cluster → Optimization → Memory Optimization (None=100%, For Server Load=150%,
For Desktop Load=200%): zamanlayıcı fiziksel belleğin %oc'sine kadar VM yerleştirir. Doğrulama 2026-10-13.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from app.services.capacity.model import ClusterModel, Node


def reserve(model: ClusterModel, usable: Sequence[Node], by_mem: Sequence[Node]) -> Optional[Dict[str, Any]]:
    """HA Reservation açıkça kapalıysa rezerv yok; aksi halde None (genel varsayım; açıksa etiket için `ha_label`)."""
    if model.ha_reservation is False:
        return {"policy": "ha_reservation_off",
                "label": "HA Reservation kapalı — Manager HA kapasitesini garanti etmez, rezerv yok",
                "mem_gb": 0.0, "cpu_cores": 0.0, "assumed": False}
    return None


def assumed_label(model: ClusterModel) -> Optional[str]:
    if model.ha_reservation is True:
        return "HA Reservation açık — ayrılan miktar resmi belgede tanımlı değil; varsayım: 1 host rezerv"
    return None


def overcommit(model: ClusterModel, mem_eff: float) -> Optional[Dict[str, Any]]:
    """Zamanlayıcı kapasitesi = (fiziksel − rezerv) × oc/100; taahhüt tabanı = çalışan VM bellek tahsisi."""
    oc = model.mem_overcommit_pct
    if oc is None or oc <= 0:
        return None
    sched = mem_eff * oc / 100.0
    committed = float(model.mem_allocated_gb or 0.0)
    return {"pct": float(oc), "scheduling_gb": sched, "committed_gb": committed,
            "committed_pct": round(100.0 * committed / sched, 1) if sched > 0 else None}
