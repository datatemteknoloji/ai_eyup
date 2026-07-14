"""
Oracle Exadata DB Machine envanter modelleri — rack/kabinet, compute node ve storage cell.
"""
from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey, Float, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class ExadataNodeRole(str, enum.Enum):
    COMPUTE_NODE = "compute_node"
    STORAGE_CELL = "storage_cell"
    IB_SWITCH = "ib_switch"
    PDU = "pdu"
    OTHER = "other"


class ExadataRack(Base):
    """Exadata rack / DB Machine — aynı kabinetteki tüm bileşenlerin üst varlığı."""
    __tablename__ = "exadata_racks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    rack_name = Column(String(255), nullable=True)          # fiziksel rack adı
    model = Column(String(128), nullable=True)              # X8M-2, X9M, vb.
    datacenter = Column(String(128), nullable=True)
    cabinet_label = Column(String(128), nullable=True)      # kabinet / lokasyon etiketi
    hostname = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True, index=True)
    status = Column(String(50), default="unknown")
    connection_config = Column(JSON, nullable=False, default=dict)
    meta_data = Column(JSON, nullable=True)
    last_sync = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    nodes = relationship(
        "ExadataNode",
        back_populates="rack",
        cascade="all, delete-orphan",
        order_by="ExadataNode.role, ExadataNode.name",
    )


class ExadataNode(Base):
    """Compute node veya storage cell — rack içindeki bileşen."""
    __tablename__ = "exadata_nodes"

    id = Column(Integer, primary_key=True, index=True)
    rack_id = Column(Integer, ForeignKey("exadata_racks.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(Enum(ExadataNodeRole, name="exadatanoderole"), nullable=False, default=ExadataNodeRole.OTHER)
    name = Column(String(255), nullable=False, index=True)
    hostname = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True, index=True)
    ilom_ip = Column(String(45), nullable=True)
    status = Column(String(50), default="unknown")
    position_in_rack = Column(String(64), nullable=True)    # U-slot veya slot etiketi
    cpu_cores = Column(Integer, nullable=True)
    memory_gb = Column(Float, nullable=True)
    storage_tb = Column(Float, nullable=True)
    cell_disk_info = Column(JSON, nullable=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="SET NULL"), nullable=True, index=True)
    meta_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    rack = relationship("ExadataRack", back_populates="nodes")
