from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.user import AuthSource, UserRole


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class UserPublic(BaseModel):
    id: int
    username: str
    role: UserRole
    auth_source: AuthSource
    is_active: bool
    theme: str = "dark"
    locale: str = "tr"
    last_login_at: Optional[datetime] = None
    mfa_enabled: bool = False


class UserPreferencesUpdate(BaseModel):
    theme: Optional[str] = Field(default=None, pattern="^(dark|light)$")
    locale: Optional[str] = Field(default=None, pattern="^(tr|en)$")


class LoginResponse(BaseModel):
    token: Optional[TokenResponse] = None
    user: Optional[UserPublic] = None
    mfa_required: bool = False
    mfa_enrollment_required: bool = False
    mfa_token: Optional[str] = None
