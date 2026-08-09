from datetime import UTC, datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class UserRole(str, Enum):
    none = "none"  # directory user not yet authorized
    admin = "admin"
    operator = "operator"


class AuthSource(str, Enum):
    local = "local"
    ad = "ad"
    sso = "sso"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=128)
    password_hash: Optional[str] = Field(default=None, max_length=255)
    role: UserRole = Field(default=UserRole.operator, index=True)
    auth_source: AuthSource = Field(default=AuthSource.local)
    is_active: bool = Field(default=True)
    theme: str = Field(default="dark", max_length=16)  # dark | light
    locale: str = Field(default="tr", max_length=8)  # tr | en
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_login_at: Optional[datetime] = Field(default=None)
