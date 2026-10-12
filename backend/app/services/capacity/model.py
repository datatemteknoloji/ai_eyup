"""Ortak kapasite modeli — platformdan bağımsız veri sınıfları."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Node:
    name: str
    mem_gb: float                 # fiziksel (virt) / allocatable (k8s) bellek
    cpu_cores: float
    usable: bool = True           # bağlı + bakımda değil / Ready + zamanlanabilir
    mem_used_gb: float = 0.0      # gözlenen kullanım (virt) / toplam request (k8s)
    cpu_used_cores: float = 0.0


@dataclass(frozen=True)
class HaSpec:
    """vCenter cluster HA / admission control ayarları (yalnız VMware)."""
    ha_enabled: Optional[bool] = None
    admission_control_enabled: Optional[bool] = None
    policy_type: Optional[str] = None
    mem_failover_pct: Optional[float] = None
    cpu_failover_pct: Optional[float] = None
    failover_level: Optional[int] = None


@dataclass(frozen=True)
class ClusterModel:
    platform: str                                  # vmware | olvm | ocp_virt | ocp
    name: str
    nodes: Tuple[Node, ...]
    ha: Optional[HaSpec] = None                    # vmware
    ha_reservation: Optional[bool] = None          # olvm: None = bilinmiyor (eski davranış: 1 host varsayımı)
    mem_overcommit_pct: Optional[float] = None     # olvm: Memory Optimization (100/150/200); None = bilinmiyor
    mem_allocated_gb: float = 0.0                  # çalışan VM bellek tahsisi (taahhüt)
    vcpu_allocated: float = 0.0
    reserve_mode: str = "auto"                     # "auto" | "none" (k8s: HA rezervi kavramı yok)


@dataclass(frozen=True)
class Demand:
    """Senaryoya eklenen talep (toplam)."""
    mem_gb: float = 0.0
    cpu_cores: float = 0.0        # etkin (kullanım varsayımlı) çekirdek
    vcpus: float = 0.0            # tahsis edilen vCPU (oran için)
    count: int = 0
