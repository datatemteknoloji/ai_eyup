"""
Local Repository Yönetimi Modelleri
  RepoSource   — Kaynak repo tanımı (RHEL/OEL/Rocky/Custom)
  RepoSyncJob  — Senkronizasyon işleri
  RepoPackage  — Repo içindeki paket katalog kaydı
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, JSON, DateTime, ForeignKey, BigInteger
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class RepoSource(Base):
    """
    Kaynak repo tanımı.
    auth_type   : none | basic | ssl_cert
    sync_method : http | rhsm
      - http : repomd.xml + HTTP indirme (mevcut)
      - rhsm : SSH → subscription-manager + reposync (yeni)
    repo_type   : rhel | oel | rocky | ubuntu | custom
    """
    __tablename__ = "repo_sources"

    id           = Column(Integer, primary_key=True, index=True)
    name         = Column(String(100), unique=True, nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    repo_type    = Column(String(20), default="custom")
    os_version   = Column(String(20))
    arch         = Column(String(20), default="x86_64")
    base_url     = Column(String(1000), nullable=False)

    # Auth (HTTP sync için)
    auth_type    = Column(String(20), default="none")      # none|basic|ssl_cert
    username     = Column(String(255))
    password     = Column(String(512))
    ssl_cert     = Column(Text)
    ssl_key      = Column(Text)
    ssl_ca       = Column(Text)

    # RHSM sync ayarları
    sync_method      = Column(String(20), default="http")   # http | rhsm
    rhsm_repo_id     = Column(String(255))   # örn: rhel-9-for-x86_64-baseos-rpms
    # Mirror host SSH (varsayılan: localhost = yönetim sunucusunun kendisi)
    mirror_host      = Column(String(255), default="127.0.0.1")
    mirror_port      = Column(Integer,     default=22)
    mirror_username  = Column(String(255))
    mirror_password  = Column(String(512))
    mirror_key       = Column(Text)
    # Host'taki indirme dizini (container dışında)
    mirror_download_path = Column(String(500), default="/var/lib/server_management/repos")

    # State
    enabled        = Column(Boolean, default=True)
    sync_status    = Column(String(20), default="never")
    last_sync      = Column(DateTime(timezone=True))
    package_count  = Column(Integer, default=0)
    total_size_mb  = Column(Integer, default=0)
    local_path     = Column(String(500))                   # /app/repos/{name}/

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    sync_jobs = relationship("RepoSyncJob", back_populates="repo",
                             cascade="all, delete-orphan", order_by="RepoSyncJob.id.desc()")
    packages  = relationship("RepoPackage",  back_populates="repo",
                             cascade="all, delete-orphan")


class RepoSyncJob(Base):
    """Senkronizasyon işi geçmişi."""
    __tablename__ = "repo_sync_jobs"

    id                = Column(Integer, primary_key=True, index=True)
    repo_id           = Column(Integer, ForeignKey("repo_sources.id", ondelete="CASCADE"),
                               nullable=False, index=True)
    status            = Column(String(20), default="pending")  # pending|running|completed|failed
    total_packages    = Column(Integer, default=0)
    synced_packages   = Column(Integer, default=0)
    skipped_packages  = Column(Integer, default=0)   # already present
    failed_packages   = Column(Integer, default=0)
    log               = Column(Text)                 # summary log
    started_at        = Column(DateTime(timezone=True))
    completed_at      = Column(DateTime(timezone=True))
    created_at        = Column(DateTime(timezone=True), server_default=func.now())

    repo = relationship("RepoSource", back_populates="sync_jobs")


class RepoPackage(Base):
    """
    Bir repodaki paket kataloğu.
    Hem metadata (her zaman) hem de downloaded=True ise fiziksel dosya var.
    """
    __tablename__ = "repo_packages"

    id           = Column(Integer, primary_key=True, index=True)
    repo_id      = Column(Integer, ForeignKey("repo_sources.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    name         = Column(String(255), nullable=False, index=True)
    epoch        = Column(String(10),  default="0")
    version      = Column(String(100), nullable=False)
    release      = Column(String(100))
    arch         = Column(String(20),  index=True)
    summary      = Column(String(500))
    size_bytes   = Column(BigInteger, default=0)
    location     = Column(String(500))    # Packages/n/nginx-1.24.0...rpm (upstream relative)
    checksum     = Column(String(128))
    checksum_type= Column(String(20), default="sha256")
    downloaded   = Column(Boolean, default=False, index=True)
    local_path   = Column(String(500))    # full local path when downloaded
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    repo = relationship("RepoSource", back_populates="packages")
