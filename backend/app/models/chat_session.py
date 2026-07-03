"""
Chat Session Model
"""
from sqlalchemy import Column, Integer, String, DateTime, JSON, Text
from sqlalchemy.sql import func
from app.core.database import Base

class ChatSession(Base):
    """Chat session model"""
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    server_ids = Column(JSON, default=list)  # İlgili sunucu ID'leri
    category = Column(String(32), default="linux", index=True)  # linux | windows | hypervisor
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ChatMessage(Base):
    """Chat message model"""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, nullable=False, index=True)
    role = Column(String(20), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    meta = Column(JSON, default=dict)  # intents, report_type, latency_ms, error
    created_at = Column(DateTime(timezone=True), server_default=func.now())
