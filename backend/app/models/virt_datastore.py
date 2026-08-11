"""
vCenter datastore envanteri — isim bazlı kapasite (host aggregate değil).

hypervisor_host_metrics.ds_* host toplamıdır; chat/planlama için datastore
başına free/capacity burada tutulur (ESX metric sync ile upsert).
"""
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String,
    UniqueConstraint, Index,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class VirtDatastore(Base):
    __tablename__ = "virt_datastores"

    id = Column(Integer, primary_key=True, index=True)
    hypervisor_id = Column(
        Integer, ForeignKey("hypervisors.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ds_ref = Column(String(64), nullable=True)
    name = Column(String(255), nullable=False, index=True)
    ds_type = Column(String(64), nullable=True)
    capacity_gb = Column(Float, nullable=True)
    free_gb = Column(Float, nullable=True)
    used_gb = Column(Float, nullable=True)
    usage_pct = Column(Float, nullable=True)
    accessible = Column(Boolean, default=True)
    host_count = Column(Integer, nullable=True)
    as_of = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    hypervisor = relationship("Hypervisor")

    __table_args__ = (
        UniqueConstraint("hypervisor_id", "name", name="uq_virt_ds_hv_name"),
        Index("ix_virt_ds_hv_as_of", "hypervisor_id", "as_of"),
    )
