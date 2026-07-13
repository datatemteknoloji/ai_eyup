"""
Merkezi audit log — kim, neyi, ne zaman, hangi sonuçla yaptı.

Tüm alt sistemler (auth, agent, sistem güncelleme, SSH, RCA, snapshot) buraya yazar.
"""
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Aktör (kim) — kullanıcı tablosuna gevşek bağ; isim her zaman saklanır.
    actor_id = Column(Integer, nullable=True, index=True)
    actor_name = Column(String(100), nullable=True, index=True)

    # Ne yaptı — kategori (alt sistem) + action (nokta-ayraçlı eylem adı)
    category = Column(String(40), nullable=False, index=True)   # auth|agent|system_update|ssh|rca|snapshot|...
    action = Column(String(80), nullable=False, index=True)     # ör. agent.approve, auth.login

    # Hedef
    target_type = Column(String(40), nullable=True)             # server|incident|plan|action|user|...
    target_id = Column(String(64), nullable=True)
    server_id = Column(Integer, nullable=True, index=True)

    # Sonuç
    status = Column(String(20), default="success", index=True)  # success|failure|pending|blocked|rejected
    summary = Column(Text, nullable=True)                        # insan-okur kısa özet
    detail = Column(JSONB, nullable=True)                        # serbest yapılandırılmış ek veri

    ip_address = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
