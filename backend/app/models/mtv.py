"""MTV (Migration Toolkit for Virtualization / Forklift) taşıma geçmişi.

`mtv_service` kümedeki Plan/Migration CR'lerini CANLI okur; CR silinince geçmiş kaybolur. Bu tablo
periyodik anlık görüntüyü (plan başına tek satır, her turda güncellenir) saklar → Migrasyon raporu
geçmiş ve trend gösterebilir. Tablo `Base.metadata.create_all` ile oluşur (Alembic kullanılmıyor).
"""
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class MtvPlanSnapshot(Base):
    __tablename__ = "mtv_plan_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(Integer, ForeignKey("openshift_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    cluster_name = Column(String(255))
    plan_uid = Column(String(64), nullable=False)           # CR metadata.uid (ad yeniden kullanılabilir)
    plan_name = Column(String(255), nullable=False)
    namespace = Column(String(255))
    source_provider = Column(String(255))
    target_namespace = Column(String(255))
    warm = Column(Boolean, default=False)
    # succeeded | failed | running | ready | validating | archived
    state = Column(String(24), nullable=False, default="validating")
    vm_total = Column(Integer, default=0)
    vm_succeeded = Column(Integer, default=0)
    vm_failed = Column(Integer, default=0)
    vm_running = Column(Integer, default=0)
    error = Column(Text)
    started_at = Column(DateTime(timezone=True))             # ilk Migration başlangıcı
    completed_at = Column(DateTime(timezone=True))
    vms = Column(JSON, default=list)                         # [{name, phase, started, completed, error}]
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    # Son turda kümede görünmediyse dolar (CR silindi); satır silinmez → geçmiş korunur.
    removed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("cluster_id", "plan_uid", name="uq_mtv_plan_identity"),
        Index("ix_mtv_plan_cluster_state", "cluster_id", "state"),
    )
