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
    ref: str = ""                 # platform nesne kimliği (vCenter host moref vb.); datastore erişim eşlemesi için


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
class ResourcePoolSpec:
    """vSphere resource pool: rezervasyon ve limit (ResourceConfigSpec.cpuAllocation / memoryAllocation).

    `mem_reservation_gb` / `cpu_reservation_mhz` boş (None) → okunamadı. `limit` -1 = sınırsız (vSphere sözleşmesi).
    `used_mem_gb`: havuzdaki VM'lerin kullandığı bellek; None → bilinmiyor (rezervasyonun TAMAMI düşülür — temkinli).
    """
    name: str
    mem_reservation_gb: Optional[float] = None
    cpu_reservation_mhz: Optional[float] = None
    mem_limit_gb: Optional[float] = None
    expandable: Optional[bool] = None
    used_mem_gb: Optional[float] = None


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
    # H.0 hiyerarşi: instance → datacenter → cluster → host. Kimlikler instance kimliğini içerir.
    instance_id: Optional[int] = None
    instance_name: str = ""
    datacenter: Optional[str] = None               # bilinmiyorsa None (yolda "?" gösterilir)
    # vSphere resource pool'ları. None = OKUNAMADI (sonuç düşük güven + "rezervasyonlar hesaba katılmadı").
    pools: Optional[Tuple[ResourcePoolSpec, ...]] = None


@dataclass(frozen=True)
class Demand:
    """Senaryoya eklenen talep (toplam)."""
    mem_gb: float = 0.0
    cpu_cores: float = 0.0        # etkin (kullanım varsayımlı) çekirdek
    vcpus: float = 0.0            # tahsis edilen vCPU (oran için)
    count: int = 0
