"""Ainew host → Dropt auth bridge.

Issues a real Dropt portal session/JWT for an ainew-authenticated user.
Protected by shared secret (AINEW_BRIDGE_SECRET); not for browser use.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import create_access_token, hash_password
from app.models.job import AuditStatus
from app.models.user import AuthSource, User, UserRole
from app.schemas.auth import LoginResponse, TokenResponse, UserPublic
from app.services import mfa_totp as mfa_svc
from app.services import portal_sessions as sess_svc
from app.services.audit import write_audit
from app.services.security_policy import get_security_policy
from fastapi import Depends

router = APIRouter(prefix="/auth", tags=["auth-bridge"])


class BridgeRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    role: str = Field(default="operator", max_length=32)
    full_name: str | None = Field(default=None, max_length=255)


def _bridge_secret() -> str:
    return (os.getenv("AINEW_BRIDGE_SECRET") or "").strip()


def _map_role(role: str) -> UserRole:
    r = (role or "operator").strip().lower()
    if r == "admin":
        return UserRole.admin
    if r in ("operator", "viewer"):
        # Dropt has no viewer — map to operator
        return UserRole.operator
    return UserRole.operator


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return (request.client.host or "")[:64]
    return ""


def _to_public(session: Session, user: User) -> UserPublic:
    theme = (getattr(user, "theme", None) or "dark").strip().lower()
    if theme not in ("dark", "light"):
        theme = "dark"
    locale = (getattr(user, "locale", None) or "tr").strip().lower()
    if locale not in ("tr", "en"):
        locale = "tr"
    return UserPublic(
        id=user.id,  # type: ignore[arg-type]
        username=user.username,
        role=user.role,
        auth_source=user.auth_source,
        is_active=user.is_active,
        theme=theme,
        locale=locale,
        last_login_at=user.last_login_at,
        mfa_enabled=mfa_svc.is_mfa_enrolled(session, user.id),  # type: ignore[arg-type]
    )


@router.post("/bridge", response_model=LoginResponse)
def ainew_bridge_login(
    body: BridgeRequest,
    request: Request,
    session: Session = Depends(get_session),
    x_ainew_bridge_secret: str | None = Header(default=None, alias="X-Ainew-Bridge-Secret"),
) -> LoginResponse:
    expected = _bridge_secret()
    if not expected or (x_ainew_bridge_secret or "") != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bridge secret geçersiz")

    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username zorunlu")

    role = _map_role(body.role)
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        # Placeholder password — login only via bridge / local admin
        user = User(
            username=username,
            password_hash=hash_password(os.urandom(24).hex()),
            role=role,
            auth_source=AuthSource.sso,
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    else:
        # Keep active; elevate role if ainew says admin
        if role == UserRole.admin and user.role != UserRole.admin:
            user.role = UserRole.admin
        user.is_active = True
        session.add(user)
        session.commit()
        session.refresh(user)

    if not user.is_active or user.role == UserRole.none:
        raise HTTPException(status_code=403, detail="Hesap pasif veya yetkisiz")

    client_ip = _client_ip(request)
    user.last_login_at = datetime.now(UTC)
    session.add(user)
    session.commit()
    session.refresh(user)

    row = sess_svc.create_session(
        session,
        user,
        auth_source="ainew_bridge",
        client_ip=client_ip,
        user_agent=(request.headers.get("user-agent") or "")[:512],
    )
    write_audit(
        session,
        action="auth.login.ainew_bridge",
        status=AuditStatus.success,
        message="Ainew bridge oturumu",
        user_id=user.id,
        username=user.username,
        role=user.role.value,
        client_ip=client_ip,
        after_state={"session_id": row.id, "jti": row.jti},
    )
    policy = get_security_policy(session)
    abs_min = policy.session_absolute_minutes
    token = create_access_token(
        subject=user.username,
        role=user.role.value,
        expires_minutes=abs_min,
        extra={"src": "ainew_bridge", "jti": row.jti, "sid": row.id},
    )
    return LoginResponse(
        token=TokenResponse(access_token=token, expires_in_minutes=abs_min),
        user=_to_public(session, user),
    )
