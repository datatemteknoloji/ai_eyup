"""Portal sessions + MFA enrollment (server-side auth state)."""

from datetime import UTC, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class PortalSession(SQLModel, table=True):
    __tablename__ = "portal_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    jti: str = Field(index=True, unique=True, max_length=64)
    user_id: int = Field(index=True)
    username: str = Field(default="", max_length=128, index=True)
    auth_source: str = Field(default="local", max_length=32)
    client_ip: str = Field(default="", max_length=64)
    user_agent: str = Field(default="", max_length=512)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None), index=True)
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None), index=True)
    absolute_expires_at: datetime = Field(index=True)
    revoked_at: Optional[datetime] = Field(default=None, index=True)


class UserMfa(SQLModel, table=True):
    __tablename__ = "user_mfa"

    user_id: int = Field(primary_key=True)
    totp_secret_enc: str = Field(default="", max_length=2048)
    enabled: bool = Field(default=False, index=True)
    enrolled_at: Optional[datetime] = Field(default=None)
    last_verified_at: Optional[datetime] = Field(default=None)
