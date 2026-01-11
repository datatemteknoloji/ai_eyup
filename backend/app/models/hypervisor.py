"""
Hypervisor Model
"""
from sqlalchemy import Column, Integer, String, JSON, DateTime, Enum
from sqlalchemy.sql import func
import enum
from app.core.database import Base

class HypervisorType(str, enum.Enum):
    """Hypervisor type enum"""
    VMWARE = "vmware"
    HYPERV = "hyperv"
    KVM = "kvm"
    XEN = "xen"

class Hypervisor(Base):
    """Hypervisor model"""
    __tablename__ = "hypervisors"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    hypervisor_type = Column(Enum(HypervisorType, name="hypervisortype"), nullable=False)  # Database'de enum olarak tanımlı
    hostname = Column(String(255), nullable=False)
    ip_address = Column(String(45), nullable=False, index=True)
    port = Column(Integer, default=443)
    username = Column(String(255))
    password = Column(String(255))  # Should be encrypted in production
    connection_config = Column(JSON, nullable=False, default=dict)
    status = Column(String(50))
    last_sync = Column(DateTime(timezone=True))
    meta_data = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Backward compatibility: type property
    @property
    def type(self):
        return self.hypervisor_type.value if self.hypervisor_type else None
