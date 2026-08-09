"""
Chat Q&A Cache — Konuşmalardan öğrenilen soru-cevap çiftleri.
Tekrar sorulan sorular bu tablodan anında döner (platform-scoped + TTL).
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func
from app.core.database import Base


class ChatQACache(Base):
    __tablename__ = "chat_qa_cache"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    # Örn. linux:global, windows:a1b2c3… — platform sızıntısını önler
    context_key = Column(String(80), nullable=True, index=True)
    hit_count = Column(Integer, default=0)
    rejected = Column(Boolean, default=False, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used = Column(DateTime(timezone=True), server_default=func.now())
