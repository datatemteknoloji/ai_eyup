from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SecurityPolicyPublic(BaseModel):
    session_idle_minutes: int
    session_absolute_minutes: int
    session_max_concurrent: int
    mfa_enabled: bool
    lockout_enabled: bool
    lockout_max_attempts: int
    lockout_window_minutes: int
    lockout_duration_minutes: int


class SecurityPolicyUpdate(BaseModel):
    session_idle_minutes: Optional[int] = Field(default=None, ge=5, le=1440)
    session_absolute_minutes: Optional[int] = Field(default=None, ge=30, le=10080)
    session_max_concurrent: Optional[int] = Field(default=None, ge=1, le=50)
    mfa_enabled: Optional[bool] = None
    lockout_enabled: Optional[bool] = None
    lockout_max_attempts: Optional[int] = Field(default=None, ge=3, le=50)
    lockout_window_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    lockout_duration_minutes: Optional[int] = Field(default=None, ge=1, le=1440)


class PortalSessionPublic(BaseModel):
    id: int
    user_id: int
    username: str
    auth_source: str
    client_ip: str
    user_agent: str
    created_at: datetime
    last_seen_at: datetime
    absolute_expires_at: datetime
    is_current: bool = False
    revoked: bool = False


class MfaTokenRequest(BaseModel):
    mfa_token: str = Field(min_length=10)


class MfaChallengeRequest(BaseModel):
    mfa_token: str = Field(min_length=10)
    code: str = Field(min_length=6, max_length=12)


class MfaEnrollStartResponse(BaseModel):
    secret: str
    otpauth_url: str


class MfaUserStatus(BaseModel):
    user_id: int
    username: str
    auth_source: str
    status: str  # disabled | pending | enabled
    enrolled_at: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None


class TlsStatusPublic(BaseModel):
    https_enabled: bool
    certs_dir: str
    cert_present: bool
    key_present: bool
    source: str
    subject: Optional[str] = None
    not_after: Optional[str] = None
    fingerprint_sha256: Optional[str] = None
    http_port: int = 3000
    https_port: int = 443
    error: Optional[str] = None


class TlsEnableUpdate(BaseModel):
    https_enabled: bool


class TlsUploadBody(BaseModel):
    cert_pem: str = Field(min_length=32)
    key_pem: str = Field(min_length=32)
    chain_pem: str = ""
