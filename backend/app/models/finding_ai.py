"""Bulgular sayfası AI yorumu — saklanan OLAY yorumu (sürümlü) ve kullanıcı geri bildirimi.

Yorum OLAY başına üretilir (`services/findings/events.py`: platform|source_id|entity_ref|aile) ve olayın tüm üye
bulgularında aynı görünür. Tablolar `app/models/__init__.py` kaydı sayesinde açılışta `Base.metadata.create_all` ile
oluşur. Referans SQL: `backend/migrations/add_finding_ai_comments.sql`; geri alma:
`backend/migrations/rollback_finding_ai_comments.sql`. Model ile SQL tutarlı tutulmalıdır.
"""
from __future__ import annotations

from sqlalchemy import (JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func)

from app.core.database import Base


class FindingAiComment(Base):
    """Bir OLAY için üretilmiş AI yorumu. Her üretim yeni bir sürümdür (en yeni sürüm geçerlidir; eskiler saklama süresi
    dolunca silinir, en son sürüm her zaman kalır)."""
    __tablename__ = "finding_ai_comments"

    id = Column(Integer, primary_key=True, index=True)
    # Olayın temsilci bulgusu (üyelerin en küçük id'si). Bulgu silinirse yorum silinmez (SET NULL); olay anahtarı kalır.
    finding_id = Column(Integer, ForeignKey("infra_findings.id", ondelete="SET NULL"), nullable=True, index=True)
    event_key = Column(String(300), nullable=False)   # platform|source_id|entity_ref|aile
    version = Column(Integer, nullable=False, default=1)
    model = Column(String(120))
    locale = Column(String(5), nullable=False, default="tr")
    # Doğrulamadan geçmiş yapısal yorum (ozet, olay_gorunumu, etki, oncelik, gozlenen, genel_bilgi, diger_iyilestirmeler, bilinmeyenler)
    content = Column(JSON, nullable=False)
    # Kodla hesaplanır (modelin beyanı değil): {"level": high|medium|low, "reasons": [kod, ...]}
    confidence = Column(JSON, nullable=False)
    # Girdi parmak izi: olay üyeleri + durumları + etki. Değişirse yorum "güncel olmayabilir" sayılır.
    input_hash = Column(String(64), nullable=False)
    # Modele verilen gözlenen veri (denetlenebilirlik); yorumdaki her sayı buradan doğrulanmıştır.
    facts = Column(JSON, nullable=False)
    validation = Column(JSON)            # {"attempts", "violations_first_try", "softened_*", "recommendation_fixes", "unsoftened_definitive_*", ...}
    generated_by = Column(String(100))
    generated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    duration_ms = Column(Integer)

    __table_args__ = (
        UniqueConstraint("event_key", "version", name="uq_finding_ai_comment_event_version"),
        Index("ix_finding_ai_comments_event_key", "event_key"),
    )


class FindingAiFeedback(Base):
    """Kullanıcı başına, yorum sürümü başına tek oy: Faydalı / Faydalı değil."""
    __tablename__ = "finding_ai_feedback"

    id = Column(Integer, primary_key=True, index=True)
    comment_id = Column(Integer, ForeignKey("finding_ai_comments.id", ondelete="CASCADE"), nullable=False, index=True)
    username = Column(String(100), nullable=False)
    helpful = Column(Boolean, nullable=False)
    note = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("comment_id", "username", name="uq_finding_ai_feedback_user"),
        Index("ix_finding_ai_feedback_comment_helpful", "comment_id", "helpful"),
    )
