"""
vCenter cluster envanteri — HA/DRS yapılandırması ve effective kapasite.

`list_clusters_status()` her soruda canlı SOAP login açıyordu; cluster verisi
nadiren değiştiği için ESX metric sync ile buraya upsert edilir. Cluster'ın
zaman serisi ayrı tabloda tutulmaz: host metrikleri `cluster_name` ile
etiketlendiği için cluster trendi `hypervisor_host_metrics` üzerinden
gruplanarak hesaplanır.
"""
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String,
    UniqueConstraint, Index,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class VirtCluster(Base):
    __tablename__ = "virt_clusters"

    id = Column(Integer, primary_key=True, index=True)
    hypervisor_id = Column(
        Integer, ForeignKey("hypervisors.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    cluster_ref = Column(String(64), nullable=True)      # domain-c123
    name = Column(String(255), nullable=False, index=True)

    # ── Kapasite ─────────────────────────────────────────────────────────────
    hosts = Column(Integer, nullable=True)
    effective_hosts = Column(Integer, nullable=True)     # HA için sağlıklı host
    cpu_cores = Column(Integer, nullable=True)
    cpu_total_mhz = Column(Float, nullable=True)
    cpu_effective_mhz = Column(Float, nullable=True)
    memory_gb = Column(Float, nullable=True)
    memory_effective_gb = Column(Float, nullable=True)

    # ── HA ───────────────────────────────────────────────────────────────────
    ha_enabled = Column(Boolean, nullable=True)
    admission_control_enabled = Column(Boolean, nullable=True)
    policy_type = Column(String(80), nullable=True)      # ClusterFailover*Policy
    policy_label = Column(String(120), nullable=True)
    failover_level = Column(Integer, nullable=True)
    cpu_failover_pct = Column(Integer, nullable=True)
    mem_failover_pct = Column(Integer, nullable=True)
    current_failover_level = Column(Integer, nullable=True)
    host_monitoring = Column(String(32), nullable=True)  # enabled / disabled
    vm_monitoring = Column(String(48), nullable=True)    # vmMonitoringDisabled …

    # ── HA slot bilgisi (RetrieveDasAdvancedRuntimeInfo) ─────────────────────
    total_slots = Column(Integer, nullable=True)
    used_slots = Column(Integer, nullable=True)
    unreserved_slots = Column(Integer, nullable=True)
    slot_cpu_mhz = Column(Integer, nullable=True)
    slot_memory_mb = Column(Integer, nullable=True)
    total_good_hosts = Column(Integer, nullable=True)

    # ── DRS ──────────────────────────────────────────────────────────────────
    drs_enabled = Column(Boolean, nullable=True)
    drs_behavior = Column(String(48), nullable=True)     # fullyAutomated …
    drs_migration_threshold = Column(Integer, nullable=True)
    vmotions = Column(Integer, nullable=True)

    overall_status = Column(String(32), nullable=True)   # green / yellow / red
    host_refs = Column(JSON, default=list)

    as_of = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    hypervisor = relationship("Hypervisor")

    __table_args__ = (
        UniqueConstraint("hypervisor_id", "name", name="uq_virt_cluster_hv_name"),
        Index("ix_virt_cluster_hv_as_of", "hypervisor_id", "as_of"),
    )
