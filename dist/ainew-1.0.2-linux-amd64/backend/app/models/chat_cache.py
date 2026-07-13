"""
Chat Q&A Cache — Konuşmalardan öğrenilen soru-cevap çiftleri.
Tekrar sorulan sorular bu tablodan anında döner.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class ChatQACache(Base):
    __tablename__ = "chat_qa_cache"

    id          = Column(Integer, primary_key=True, index=True)
    question    = Column(Text, nullable=False)           # Normalize edilmiş soru
    answer      = Column(Text, nullable=False)           # AI yanıtı
    context_key = Column(String(64), nullable=True)      # Hangi sunucu bağlamında (hash)
    hit_count   = Column(Integer, default=0)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    last_used   = Column(DateTime(timezone=True), server_default=func.now())
