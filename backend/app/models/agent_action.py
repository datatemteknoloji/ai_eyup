"""
Agent Action Model — agentic AI'nin önerdiği/çalıştırdığı tool çağrılarının
kalıcı kaydı ve insan onay (human-in-the-loop) durumu.

Akış:
  pending   → mutating bir tool için onay bekliyor
  approved  → kullanıcı onayladı, çalıştırılacak/çalıştırıldı
  rejected  → kullanıcı reddetti
  executed  → çalıştırıldı (read-only otomatik veya onay sonrası)
  failed    → çalıştırma hata verdi
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"),
                        nullable=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="SET NULL"),
                       nullable=True, index=True)

    tool_name = Column(String(100), nullable=False, index=True)
    arguments = Column(JSON, default=dict)        # tool'a verilen argümanlar
    risk_level = Column(String(20), default="mutating", index=True)  # read_only|mutating|denied
    status = Column(String(20), default="pending", index=True)

    preview = Column(Text)                        # çalıştırılacak komut/işlem önizlemesi
    result = Column(JSON, default=dict)           # çalıştırma sonucu (stdout/stderr/ok)

    # Onay sonrası döngüye kaldığı yerden devam edebilmek için konuşma transcript'i
    transcript = Column(JSON, default=list)

    model = Column(String(100))
    decided_by = Column(String(100))              # onaylayan/reddeden
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    decided_at = Column(DateTime(timezone=True))
    executed_at = Column(DateTime(timezone=True))
