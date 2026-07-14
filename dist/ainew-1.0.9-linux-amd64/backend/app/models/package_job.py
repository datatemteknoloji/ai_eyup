"""
Paket Yönetimi Modelleri
  PackageFile  — yüklenen .deb / .rpm dosyaları
  PackageJob   — dağıtım / güncelleme işleri
"""
from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class PackageFile(Base):
    __tablename__ = "package_files"

    id            = Column(Integer, primary_key=True, index=True)
    filename      = Column(String(255), nullable=False)        # UUID-prefix'li saklanan ad
    original_name = Column(String(255), nullable=False)        # Kullanıcının yüklediği ad
    file_path     = Column(String(500), nullable=False)        # /app/uploads/packages/...
    file_size     = Column(Integer, default=0)                 # bytes
    package_type  = Column(String(10), default="unknown")      # deb | rpm | unknown
    description   = Column(String(500))
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    jobs = relationship("PackageJob", back_populates="package_file")


class PackageJob(Base):
    """
    job_type  : deploy | upgrade | check_updates
    status    : pending | running | completed | failed | partial
    results   : { "server_id": { status, output, error, duration } }
    """
    __tablename__ = "package_jobs"

    id                = Column(Integer, primary_key=True, index=True)
    job_type          = Column(String(30), nullable=False)
    status            = Column(String(20), default="pending", index=True)
    title             = Column(String(255))
    package_file_id   = Column(Integer, ForeignKey("package_files.id", ondelete="SET NULL"), nullable=True)
    server_ids        = Column(JSON, default=list)
    results           = Column(JSON, default=dict)       # {str(server_id): {...}}
    live_log          = Column(JSON, default=dict)       # {str(server_id): "partial output..."}
    total_servers     = Column(Integer, default=0)
    completed_servers = Column(Integer, default=0)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    updated_at        = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at      = Column(DateTime(timezone=True), nullable=True)

    package_file = relationship("PackageFile", back_populates="jobs")
