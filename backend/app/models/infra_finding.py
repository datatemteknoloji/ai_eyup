"""
Sanallaştırma karar katmanı — ortak "kontrol → bulgu → kanıt" modeli.

Kapasite, geri kazanım, sağlık denetimi, donanım riski, sapma, zafiyet,
bilinen sorun, yükseltme ve denetim ekranlarının hepsi AYNI tablodan okur;
rapor ekranı ile sohbet tool'u bu yüzden asla farklı rakam göstermez.

Platform anahtarları: vmware | olvm | ocp_virt | ocp
source_id: ilk üçünde hypervisors.id, `ocp` için openshift_clusters.id.
"""
from sqlalchemy import (
    Boolean, Column, DateTime, Float, Index, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class InfraCheckRun(Base):
    """Tek bir toplama/değerlendirme turu — süre, durum ve hata kaydı."""
    __tablename__ = "infra_check_runs"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(16), nullable=False, index=True)
    source_id = Column(Integer, nullable=True, index=True)
    source_name = Column(String(255))
    kind = Column(String(32), nullable=False, default="full")   # collect | checks | file_scan | full
    status = Column(String(16), nullable=False, default="running")  # running | ok | partial | error
    error = Column(Text)
    stats = Column(JSON, default=dict)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at = Column(DateTime(timezone=True))


class InfraFinding(Base):
    """Bir kontrolün bir varlık üzerindeki son sonucu (pass / fail / not_measurable)."""
    __tablename__ = "infra_findings"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(16), nullable=False, index=True)
    source_id = Column(Integer, nullable=True, index=True)
    source_name = Column(String(255))
    # capacity | reclaim | health | hardware | drift | vuln | known_issue | upgrade | compliance
    category = Column(String(24), nullable=False, index=True)
    check_id = Column(String(96), nullable=False, index=True)
    entity_kind = Column(String(24), nullable=False)
    entity_ref = Column(String(512), nullable=False)
    entity_name = Column(String(512))
    cluster_name = Column(String(255), index=True)
    result = Column(String(16), nullable=False, index=True)     # pass | fail | not_measurable
    severity = Column(String(12), nullable=False, default="medium", index=True)
    title = Column(String(500), nullable=False)
    detail = Column(Text)
    evidence = Column(JSON, default=dict)
    recommendation = Column(Text)
    refs = Column(JSON, default=list)
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    # Son turda tekrar üretilmediyse False (kontrol artık geçerli değil / varlık gitti)
    active = Column(Boolean, default=True, index=True)
    resolved_at = Column(DateTime(timezone=True))
    run_id = Column(Integer, index=True)

    __table_args__ = (
        UniqueConstraint(
            "platform", "source_id", "entity_ref", "check_id",
            name="uq_infra_finding_identity",
        ),
        Index("ix_infra_finding_cat_active", "category", "active", "result"),
    )


class InfraFindingException(Base):
    """Operatörün "inceledim / istisna" kararı — bulguyu silmez, filtreler."""
    __tablename__ = "infra_finding_exceptions"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(16), nullable=False)
    source_id = Column(Integer, nullable=True)
    entity_ref = Column(String(512), nullable=False)
    check_id = Column(String(96), nullable=False)
    reason = Column(Text, nullable=False)
    created_by = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "platform", "source_id", "entity_ref", "check_id",
            name="uq_infra_finding_exception_identity",
        ),
    )


class VirtConfigSnapshot(Base):
    """Varlık yapılandırması (normalize JSON). Hash değişince yeni satır.

    En yeni satır = güncel durum (sağlık kontrolleri ve yerleştirme buradan
    okur); önceki satırlar = değişiklik geçmişi (sapma ekranı).
    """
    __tablename__ = "virt_config_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(16), nullable=False, index=True)
    source_id = Column(Integer, nullable=True, index=True)
    entity_kind = Column(String(24), nullable=False)  # cluster | host | datastore | vm | platform
    entity_ref = Column(String(512), nullable=False)
    entity_name = Column(String(512))
    cluster_name = Column(String(255))
    payload = Column(JSON, nullable=False, default=dict)
    payload_hash = Column(String(64), nullable=False)
    captured_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    is_latest = Column(Boolean, default=True, index=True)
    is_baseline = Column(Boolean, default=False, index=True)
    baseline_by = Column(String(100))
    baseline_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_virt_cfg_snap_entity", "platform", "source_id", "entity_kind",
            "entity_ref", "captured_at",
        ),
    )


class VirtDatastoreFile(Base):
    """Geri kazanım keşfi için depolama nesneleri.

    kind: vmdk | iso | snapshot | disk (OLVM) | datavolume | pvc (OCP Virt)
    Her tarama (platform, source_id, kind) kümesini yeniden yazar.
    """
    __tablename__ = "virt_datastore_files"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(16), nullable=False, index=True)
    source_id = Column(Integer, nullable=True, index=True)
    kind = Column(String(16), nullable=False, index=True)
    datastore = Column(String(255))
    path = Column(String(1024), nullable=False)
    name = Column(String(512))
    size_gb = Column(Float)
    modified_at = Column(DateTime(timezone=True))
    owner_vm = Column(String(512))
    attached = Column(Boolean)
    extra = Column(JSON, default=dict)
    as_of = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class InfraReferenceData(Base):
    """Offline içe aktarılan referans paketleri.

    kind: cve_feed | kb_feed | upgrade_matrix
    İnternete bağımlılık yok — paketi operatör yükler (air-gap uyumlu).
    """
    __tablename__ = "infra_reference_data"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(32), nullable=False, unique=True, index=True)
    payload = Column(JSON, nullable=False, default=dict)
    item_count = Column(Integer, default=0)
    source_label = Column(String(255))
    uploaded_by = Column(String(100))
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
