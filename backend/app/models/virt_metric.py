"""
VM ve datastore zaman serileri (TimescaleDB hypertable).

Neden gerekli: `servers.vm_*` ve `virt_datastores` alanları UPSERT edilir —
yalnızca "şu an" bilinir. Bu yüzden "son 7 günde performansı kötüleşen VM'ler",
"datastore ne zaman dolar", "uzun süredir düşük kaynak kullanan VM'ler
(right-sizing)" gibi sorular yapısal olarak cevaplanamıyordu. Burada her sync
turunda bir satır yazılır ve trend/forecast DB'den hesaplanabilir hale gelir.

vCenter'ın kendi rollup'ı (QueryPerf + lookback_hours) tek varlık için canlı
geçmiş verebiliyor; bu tablolar ise FİLO GENELİNDE tek sorguyla karşılaştırma
ve sıralama yapmak için gerekli (50 VM'i tek tek QueryPerf ile taramak yerine).
"""
from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Index, Integer, String,
)
from sqlalchemy.sql import func

from app.core.database import Base


class VirtVmMetric(Base):
    """VM kaynak kullanımı zaman serisi — vm_stats sync turu başına bir satır."""
    __tablename__ = "virt_vm_metrics"

    timestamp = Column(
        DateTime(timezone=True), server_default=func.now(),
        nullable=False, primary_key=True,
    )
    hypervisor_id = Column(
        Integer, ForeignKey("hypervisors.id", ondelete="CASCADE"),
        nullable=False, primary_key=True, index=True,
    )
    vm_ref = Column(String(64), nullable=False, primary_key=True)  # vm-123
    vm_name = Column(String(255), index=True)
    server_id = Column(Integer, index=True)      # servers.id (varsa)
    host_name = Column(String(255), index=True)  # çalıştığı ESXi host
    cluster_name = Column(String(255))
    datastore = Column(String(255))
    power_state = Column(String(32))

    # ── Tahsis (right-sizing karşılaştırması için) ───────────────────────────
    num_cpu = Column(Integer)
    mem_total_mb = Column(Float)

    # ── Kullanım ─────────────────────────────────────────────────────────────
    cpu_usage_mhz = Column(Float)
    cpu_usage_pct = Column(Float)
    mem_used_mb = Column(Float)
    mem_usage_pct = Column(Float)
    guest_disk_pct = Column(Float)

    # ── Contention / baskı göstergeleri ──────────────────────────────────────
    cpu_ready_ms = Column(Float)
    cpu_ready_pct = Column(Float)
    cpu_costop_ms = Column(Float)
    balloon_mb = Column(Float)
    swapped_mb = Column(Float)
    mem_swapin_kbps = Column(Float)
    mem_swapout_kbps = Column(Float)

    # ── IO / ağ ──────────────────────────────────────────────────────────────
    disk_read_iops = Column(Float)
    disk_write_iops = Column(Float)
    disk_latency_ms = Column(Float)
    net_rx_kbps = Column(Float)
    net_tx_kbps = Column(Float)
    net_dropped_rx = Column(Float)
    net_dropped_tx = Column(Float)

    snapshot_count = Column(Integer)
    snapshot_space_gb = Column(Float)

    __table_args__ = (
        Index("idx_vvm_hv_vm_ts", "hypervisor_id", "vm_ref", "timestamp"),
        Index("idx_vvm_name_ts", "vm_name", "timestamp"),
        Index("idx_vvm_ts", "timestamp"),
    )


class VirtDatastoreMetric(Base):
    """Datastore doluluk zaman serisi — kapasite tükenme tahmini için."""
    __tablename__ = "virt_datastore_metrics"

    timestamp = Column(
        DateTime(timezone=True), server_default=func.now(),
        nullable=False, primary_key=True,
    )
    hypervisor_id = Column(
        Integer, ForeignKey("hypervisors.id", ondelete="CASCADE"),
        nullable=False, primary_key=True, index=True,
    )
    name = Column(String(255), nullable=False, primary_key=True)
    ds_ref = Column(String(64))
    ds_type = Column(String(32))

    capacity_gb = Column(Float)
    free_gb = Column(Float)
    used_gb = Column(Float)
    usage_pct = Column(Float)
    uncommitted_gb = Column(Float)   # thin provisioning taahhüdü
    accessible = Column(Integer)     # 1/0 — erişilebilirlik geçmişi
    host_count = Column(Integer)

    __table_args__ = (
        Index("idx_vdm_hv_name_ts", "hypervisor_id", "name", "timestamp"),
        Index("idx_vdm_ts", "timestamp"),
    )
