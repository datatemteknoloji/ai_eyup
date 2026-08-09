"""Uygulama oturumları ve MFA kayıtları."""
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(128), default="", nullable=False, index=True)
    auth_source = Column(String(32), default="local", nullable=False)
    client_ip = Column(String(64), default="", nullable=False)
    user_agent = Column(String(512), default="", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    absolute_expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True, index=True)


class UserMfa(Base):
    __tablename__ = "user_mfa"

    user_id = Column(Integer, primary_key=True)
    totp_secret_enc = Column(String(2048), default="", nullable=False)
    enabled = Column(Boolean, default=False, nullable=False, index=True)
    enrolled_at = Column(DateTime(timezone=True), nullable=True)
    last_verified_at = Column(DateTime(timezone=True), nullable=True)
