"""
ESX / Hypervisor host kaynak doluluk metrikleri (TimescaleDB hypertable)
Her hypervisor altındaki fiziksel ESX host'ların CPU, RAM, Datastore ve
Network anlık değerleri 15 dakikada bir bu tabloya yazılır.
"""
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Index, BigInteger
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class HypervisorHostMetric(Base):
    """
    ESX host kaynak metrikleri — TimescaleDB hypertable (timestamp PK).
    hypervisor_id → Hypervisor kaydı (vCenter bağlantısı)
    host_name     → ESX host'un FQDN veya kısa adı (örn. esxi01.local)
    host_ref      → vCenter'daki MOR/object-id (örn. host-12)
    """
    __tablename__ = "hypervisor_host_metrics"

    # TimescaleDB hypertable için timestamp + hypervisor_id composite PK
    timestamp = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        primary_key=True,
    )
    hypervisor_id = Column(
        Integer,
        ForeignKey("hypervisors.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
        index=True,
    )
    host_name = Column(String(255), nullable=False, primary_key=True)
    host_ref  = Column(String(64))           # vCenter host object-id

    # ── CPU ──────────────────────────────────────────────────────────────────
    cpu_usage_mhz   = Column(Float)          # Anlık kullanım (MHz)
    cpu_total_mhz   = Column(Float)          # Toplam kapasite (MHz)
    cpu_usage_pct   = Column(Float)          # Yüzde kullanım (0-100)
    cpu_cores       = Column(Integer)        # Fiziksel core sayısı
    cpu_threads     = Column(Integer)        # Thread/vCPU sayısı

    # ── Bellek ───────────────────────────────────────────────────────────────
    mem_used_mb     = Column(Float)          # Kullanılan RAM (MB)
    mem_total_mb    = Column(Float)          # Toplam RAM (MB)
    mem_usage_pct   = Column(Float)          # Yüzde kullanım (0-100)

    # ── Datastore (tüm datastore'ların toplamı) ───────────────────────────────
    ds_used_gb      = Column(Float)          # Kullanılan disk alanı (GB)
    ds_total_gb     = Column(Float)          # Toplam disk alanı (GB)
    ds_usage_pct    = Column(Float)          # Yüzde kullanım (0-100)

    # ── Ağ ───────────────────────────────────────────────────────────────────
    net_rx_kbps     = Column(Float)          # Alınan veri (kbps)
    net_tx_kbps     = Column(Float)          # Gönderilen veri (kbps)

    # ── VM sayıları ──────────────────────────────────────────────────────────
    vms_running     = Column(Integer)        # Açık VM sayısı
    vms_total       = Column(Integer)        # Toplam VM sayısı

    # ── Durum ────────────────────────────────────────────────────────────────
    connection_state = Column(String(32))    # connected / disconnected / notResponding
    power_state      = Column(String(32))    # poweredOn / standBy / ...
    maintenance_mode = Column(Integer, default=0)  # 1 = bakım modunda

    hypervisor = relationship("Hypervisor")

    __table_args__ = (
        Index("idx_hvm_hv_host_ts", "hypervisor_id", "host_name", "timestamp"),
        Index("idx_hvm_ts",         "timestamp"),
    )
