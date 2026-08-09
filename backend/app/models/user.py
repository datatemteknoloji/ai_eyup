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
    # Local kullanıcılar için zorunlu; AD/SSO için null olabilir
    hashed_password = Column(String(255), nullable=True)
    # admin | operator | viewer
    role = Column(String(20), default="operator", nullable=False, index=True)
    # local | ad | sso
    auth_source = Column(String(20), default="local", nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    # NLQ RBAC: null/eksik = tüm tier'lar; örn. ["production","staging"]
    allowed_tiers = Column(JSON, nullable=True)
    # UI theme: dark | light (per-user)
    theme = Column(String(16), default="dark", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)
