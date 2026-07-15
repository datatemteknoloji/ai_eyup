"""
Uygulama kullanıcıları — kimlik doğrulama ve yetkilendirme.
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String
from sqlalchemy.sql import func

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    # admin | operator | viewer
    role = Column(String(20), default="operator", nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    # NLQ RBAC: null/eksik = tüm tier'lar; örn. ["production","staging"]
    allowed_tiers = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)
