"""
Server Model
"""
from sqlalchemy import Column, Integer, String, Boolean, JSON, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base

class Server(Base):
    """Server model"""
    __tablename__ = "servers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    hostname = Column(String(255))
    ip_address = Column(String(45), index=True)
    status = Column(String(50), default="unknown")
    os_type       = Column(String(50))
    os_version    = Column(String(255))   # PRETTY_NAME
    os_release_id = Column(String(50))    # ID: "rhel"|"ol"|"rocky"|"ubuntu"
    os_version_id = Column(String(20))    # VERSION_ID: "9.5"|"8.10"|"22.04"
    kernel_version= Column(String(100))   # uname -r
    server_type   = Column(String(50))
    cpu_cores = Column(Integer, default=0)
    memory_gb = Column(Integer, default=0)
    ai_ready = Column(Boolean, default=False, index=True)
    connection_config = Column(JSON, default=dict)
    
    # Hypervisor iliskisi
    hypervisor_id = Column(Integer, ForeignKey("hypervisors.id", ondelete="SET NULL"), nullable=True, index=True)
    hypervisor_vm_id = Column(String(255), nullable=True)
    
    # Node Exporter durum cache (background task 5dk'da bir gunceller)
    node_exporter_installed = Column(Boolean, default=False)
    node_exporter_running = Column(Boolean, default=False)
    node_exporter_last_check = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    hypervisor = relationship("Hypervisor", back_populates="servers")
    events = relationship("SystemEvent", back_populates="server", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="server", cascade="all, delete-orphan")
