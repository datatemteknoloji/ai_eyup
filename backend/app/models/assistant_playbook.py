"""Assistant playbook ORM — başarılı READ_ONLY tool zincirleri."""
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func
from sqlalchemy.types import JSON

from app.core.database import Base


class AssistantPlaybook(Base):
    __tablename__ = "assistant_playbooks"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(32), nullable=False, index=True)
    intent_norm = Column(Text, nullable=False)
    tools_json = Column(JSON, nullable=False, default=list)
    server_scope = Column(String(80), nullable=True)
    outcome_summary = Column(String(500), nullable=True)
    hit_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
