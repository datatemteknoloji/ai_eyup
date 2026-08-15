"""ChatTurn — kalıcı sohbet turu."""
from sqlalchemy import Column, Integer, String, DateTime, JSON, Text, BigInteger
from sqlalchemy.sql import func
from app.core.database import Base


class ChatTurn(Base):
    __tablename__ = "chat_turns"

    id = Column(String(36), primary_key=True)
    session_id = Column(Integer, nullable=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    platform = Column(String(32), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="queued", index=True)
    message = Column(Text, nullable=False)
    payload = Column(JSON, default=dict)
    source_plan = Column(JSON, default=dict)
    partial_response = Column(Text, default="")
    error = Column(Text, nullable=True)
    last_seq = Column(BigInteger, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)
