"""
Altyapı Rapor Modelleri
  - InfrastructureReport  : Üretilen raporların anlık görüntülerini saklar
  - CostConfig            : Kaynak başına maliyet yapılandırması (chargeback)
  - BusinessServiceMap    : İş servisi → VM eşleşmesi
"""
from sqlalchemy import (
    Column, Integer, String, DateTime, JSON, Text,
    Float, Boolean, ForeignKey, Index,
)
from sqlalchemy.sql import func
from app.core.database import Base


class InfrastructureReport(Base):
    __tablename__ = "infrastructure_reports"

    id            = Column(Integer, primary_key=True, index=True)
    report_type   = Column(String(60), nullable=False, index=True)
    report_title  = Column(String(200))
    generated_at  = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    data          = Column(JSON, nullable=False, default=dict)
    summary       = Column(Text)          # AI tarafından üretilen özet metin
    status        = Column(String(20), default="ready")   # ready | generating | error
    hypervisor_id = Column(Integer, ForeignKey("hypervisors.id"), nullable=True)

    __table_args__ = (
        Index("ix_infra_report_type_ts", "report_type", "generated_at"),
    )


class CostConfig(Base):
    """CPU çekirdeği / GB RAM / GB disk başına aylık maliyet."""
    __tablename__ = "cost_config"

    id             = Column(Integer, primary_key=True)
    name           = Column(String(100), unique=True, nullable=False)
    cpu_per_core   = Column(Float, default=50.0)    # TL/çekirdek/ay
    ram_per_gb     = Column(Float, default=20.0)    # TL/GB/ay
    storage_per_gb = Column(Float, default=0.5)     # TL/GB/ay
    currency       = Column(String(10), default="TL")
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())


class BusinessServiceMap(Base):
    """İş servisi adı → sunucu (VM) eşleşmesi."""
    __tablename__ = "business_service_map"

    id             = Column(Integer, primary_key=True)
    service_name   = Column(String(200), nullable=False, index=True)
    service_tier   = Column(String(20), default="standard")  # critical / high / standard / low
    server_id      = Column(Integer, ForeignKey("servers.id"), nullable=False)
    department     = Column(String(100))
    owner          = Column(String(100))
    notes          = Column(Text)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
