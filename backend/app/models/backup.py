"""Normalize yedekleme/DR şeması (sağlayıcıdan bağımsız).

Tablolar her kurulumda oluşur (create_all); Veeam yoksa boş kalır.
Davranışı tablo varlığı değil capability registry belirler.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, func,
)

from app.core.database import Base


class BkJob(Base):
    __tablename__ = "bk_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, ForeignKey("integration_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_job_id = Column(String(128), nullable=False)
    name = Column(String(512), nullable=False, default="")
    job_type = Column(String(32), nullable=False, default="backup")  # backup|replica|copy
    schedule = Column(String(255), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    meta_json = Column(Text, nullable=True)
    # Dilim D: job durumu (jobs/states)
    status = Column(String(32), nullable=True)
    last_result = Column(String(32), nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    repository_provider_id = Column(String(128), nullable=True)
    repository_name = Column(String(512), nullable=True)
    objects_count = Column(Integer, nullable=True)
    # F.1: iş yapılandırması (Get All Jobs). NULL = ölçülemedi (yanıtta yok / yetki) — False DEĞİL.
    encryption_enabled = Column(Boolean, nullable=True)
    cbt_enabled = Column(Boolean, nullable=True)
    app_aware_enabled = Column(Boolean, nullable=True)
    backup_health_enabled = Column(Boolean, nullable=True)
    retention_type = Column(String(32), nullable=True)
    retention_quantity = Column(Integer, nullable=True)
    gfs_enabled = Column(Boolean, nullable=True)
    retry_enabled = Column(Boolean, nullable=True)
    retry_count = Column(Integer, nullable=True)
    retry_wait_min = Column(Integer, nullable=True)
    window_enabled = Column(Boolean, nullable=True)
    schedule_summary = Column(String(255), nullable=True)
    config_state = Column(String(16), nullable=True)   # ok | forbidden | error | NULL (hiç okunmadı)
    config_json = Column(Text, nullable=True)          # GFS ayrıntısı, proxy seçimi, dahil edilen VM'ler (özet)


class BkSession(Base):
    __tablename__ = "bk_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("bk_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_session_id = Column(String(128), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    result = Column(String(64), nullable=True)  # success|warning|failed|…
    processed_bytes = Column(BigInteger, nullable=True)
    transferred_bytes = Column(BigInteger, nullable=True)
    session_type = Column(String(64), nullable=True)
    message = Column(Text, nullable=True)


class BkRepository(Base):
    __tablename__ = "bk_repositories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, ForeignKey("integration_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_repo_id = Column(String(128), nullable=False)
    name = Column(String(512), nullable=False, default="")
    capacity_bytes = Column(BigInteger, nullable=True)
    free_bytes = Column(BigInteger, nullable=True)
    immutable = Column(Boolean, nullable=False, default=False)
    used_bytes = Column(BigInteger, nullable=True)
    is_online = Column(Boolean, nullable=True)
    repo_type = Column(String(64), nullable=True)
    # F.1: değişmezlik DOĞRULANAMAZ (Get All Repositories şemasında alan yok) → daima 'not_measurable'.
    # `immutable` (Dilim A, varsayılan False) yanıltıcıdır; okunmaz.
    immutability_status = Column(String(24), nullable=False, default="not_measurable", server_default="not_measurable")


class BkProtectedObject(Base):
    __tablename__ = "bk_protected_objects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, ForeignKey("integration_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_object_id = Column(String(256), nullable=False)
    name = Column(String(512), nullable=False, default="")
    platform = Column(String(64), nullable=True)  # vmware|…
    matched_vm_id = Column(Integer, nullable=True, index=True)  # servers.id
    match_method = Column(String(64), nullable=True)
    match_confidence = Column(String(16), nullable=False, default="none")  # exact|high|low|none
    # Dilim D: özet (restore point listesi şişmesin diye son nokta nesne üzerinde)
    object_ref = Column(String(256), nullable=True)   # sağlayıcı nesne kimliği (ör. moref) — doğrulanmadı
    path = Column(String(1024), nullable=True)
    last_restore_point_at = Column(DateTime(timezone=True), nullable=True, index=True)
    restore_points_count = Column(Integer, nullable=True)
    job_provider_id = Column(String(128), nullable=True)  # restorePoint.backupId → backups.jobId
    # F.1: eşleşme anahtarı = normalize(vCenter hostName) + moref. Doküman örneğiyle uyumlu, sahada doğrulanmadı.
    host_name = Column(String(255), nullable=True)
    host_verified = Column(Boolean, nullable=False, default=False, server_default="false")


class BkProxy(Base):
    """F.1: yedek proxy'leri (Get All Proxy States + Get All Proxies; Viewer dahil)."""
    __tablename__ = "bk_proxies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, ForeignKey("integration_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_proxy_id = Column(String(128), nullable=False)
    name = Column(String(512), nullable=False, default="")
    proxy_type = Column(String(32), nullable=True)
    host_name = Column(String(512), nullable=True)      # ham değer ("This server" olabilir — api_ref #9)
    is_online = Column(Boolean, nullable=True)
    is_disabled = Column(Boolean, nullable=True)
    is_out_of_date = Column(Boolean, nullable=True)
    transport_mode = Column(String(32), nullable=True)
    max_tasks = Column(Integer, nullable=True)
    synced_at = Column(DateTime(timezone=True), server_default=func.now())


class BkRestorePoint(Base):
    __tablename__ = "bk_restore_points"

    id = Column(Integer, primary_key=True, autoincrement=True)
    protected_object_id = Column(
        Integer, ForeignKey("bk_protected_objects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id = Column(Integer, ForeignKey("bk_jobs.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True, index=True)
    point_type = Column(String(64), nullable=True)


class BkRpoPolicy(Base):
    """Hedef RPO/RTO — ainew'de yönetilir; Veeam'den gelmez."""
    __tablename__ = "bk_rpo_policies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope_kind = Column(String(32), nullable=False, default="vm")  # vm|tag|folder|cluster
    scope_ref = Column(String(512), nullable=False, default="")
    target_rpo_min = Column(Integer, nullable=True)
    target_rto_min = Column(Integer, nullable=True)
    label = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BkRestoreTest(Base):
    __tablename__ = "bk_restore_tests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    protected_object_id = Column(
        Integer, ForeignKey("bk_protected_objects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tested_at = Column(DateTime(timezone=True), nullable=True)
    duration_sec = Column(Float, nullable=True)
    result = Column(String(64), nullable=True)
