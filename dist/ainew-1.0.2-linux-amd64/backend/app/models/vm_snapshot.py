"""
Sanal makine snapshot kayıtları (oVirt / vCenter)
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class VMSnapshot(Base):
    __tablename__ = "vm_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True)
    hypervisor_id = Column(Integer, ForeignKey("hypervisors.id", ondelete="SET NULL"), nullable=True, index=True)
    plan_id = Column(Integer, ForeignKey("system_update_plans.id", ondelete="SET NULL"), nullable=True, index=True)
    vm_id = Column(String(255), nullable=False)
    snapshot_id = Column(String(255), nullable=True)
    snapshot_name = Column(String(255), nullable=False)
    platform = Column(String(20), nullable=False)  # ovirt | vmware
    source = Column(String(30), default="manual")  # manual | system_update
    retention = Column(String(20), default="1w")  # 1d | 1w | 1m | indefinite
    status = Column(String(20), default="active", index=True)  # active | deleted | failed
    error_message = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    server = relationship("Server")
    hypervisor = relationship("Hypervisor")
    plan = relationship("SystemUpdatePlan")
