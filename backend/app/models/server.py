"""
Server Model
"""
from sqlalchemy import Column, Integer, String, Boolean, JSON, Text, DateTime
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
    os_type = Column(String(50))
    os_version = Column(String(255))
    server_type = Column(String(50))
    cpu_cores = Column(Integer, default=0)
    memory_gb = Column(Integer, default=0)
    ai_ready = Column(Boolean, default=False, index=True)
    connection_config = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # AIOps relationships
    events = relationship("SystemEvent", back_populates="server", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="server", cascade="all, delete-orphan")
