"""
Sistem Güncelleme Modelleri
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, JSON, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class SystemUpdatePlan(Base):
    __tablename__ = "system_update_plans"
    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String(255), nullable=False)
    update_type   = Column(String(20), nullable=False)
    distro_filter = Column(String(50))
    repo_id       = Column(Integer, ForeignKey("repo_sources.id", ondelete="SET NULL"), nullable=True)
    server_ids    = Column(JSON, default=list)
    status        = Column(String(20), default="draft", index=True)
    ai_analysis   = Column(Text)
    ai_summary    = Column(Text)
    total_servers     = Column(Integer, default=0)
    completed_servers = Column(Integer, default=0)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())
    started_at    = Column(DateTime(timezone=True))
    completed_at  = Column(DateTime(timezone=True))
    # Güncelleme için kullanılacak yetkili kullanıcı (opsiyonel override)
    override_username     = Column(String(255))
    override_password     = Column(String(512))
    override_sudo_password= Column(String(512))
    # Yetki yükseltme yöntemi: sudo | dzdo | su | pbrun | direct
    priv_method           = Column(String(20), default="sudo")

    repo = relationship("RepoSource")
    jobs = relationship("SystemUpdateJob", back_populates="plan", cascade="all, delete-orphan", order_by="SystemUpdateJob.id")


class SystemUpdateJob(Base):
    __tablename__ = "system_update_jobs"
    id                 = Column(Integer, primary_key=True, index=True)
    plan_id            = Column(Integer, ForeignKey("system_update_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    server_id          = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True)
    status             = Column(String(20), default="pending", index=True)
    packages_to_update = Column(JSON, default=list)
    packages_updated   = Column(JSON, default=list)
    reboot_required    = Column(Boolean, default=False)
    rebooted           = Column(Boolean, default=False)
    log                = Column(Text)
    started_at         = Column(DateTime(timezone=True))
    completed_at       = Column(DateTime(timezone=True))
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
    plan   = relationship("SystemUpdatePlan", back_populates="jobs")
    server = relationship("Server")
