"""Uygulama geneli güvenlik: politika, oturumlar, MFA, TLS."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import client_ip, get_current_user, require_role
from app.core.database import get_db
from app.core.security import decode_access_token, revoke_token
from app.models.user import User
from app.services import mfa_totp, tls_certs, user_sessions
from app.services.audit import record_audit
from app.services.security_policy import get_security_policy, update_security_policy
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


class PolicyPatch(BaseModel):
    session_idle_minutes: Optional[int] = None
    session_absolute_minutes: Optional[int] = None
    session_max_concurrent: Optional[int] = None
    mfa_enabled: Optional[bool] = None
    lockout_enabled: Optional[bool] = None
    lockout_max_attempts: Optional[int] = None
    lockout_window_minutes: Optional[int] = None
    lockout_duration_minutes: Optional[int] = None
    password_min_length: Optional[int] = None


class TlsUpload(BaseModel):
    cert_pem: str
    key_pem: str
    chain_pem: str = ""


class TlsSelfSigned(BaseModel):
    cn: Optional[str] = None
    days: int = 3650


def _session_public(row) -> dict:
    return {
        "id": row.id,
        "jti": row.jti,
        "user_id": row.user_id,
        "username": row.username,
        "auth_source": row.auth_source,
        "client_ip": row.client_ip,
        "user_agent": row.user_agent,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "absolute_expires_at": row.absolute_expires_at.isoformat() if row.absolute_expires_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }


@router.get("/policy")
def get_policy(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    return get_security_policy(db).as_public()


@router.patch("/policy")
def patch_policy(
    body: PolicyPatch,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    pol = update_security_policy(db, body.model_dump(exclude_unset=True))
    record_audit(
        db, category="auth", action="security.policy_update", actor=admin,
        summary="Güvenlik politikası güncellendi", ip_address=client_ip(request),
    )
    return pol.as_public()


@router.get("/sessions")
def list_all_sessions(
    active_only: bool = True,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    rows = user_sessions.list_sessions(db, active_only=active_only)
    return {"sessions": [_session_public(r) for r in rows]}


@router.get("/sessions/mine")
def list_my_sessions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = [
        r for r in user_sessions.list_sessions(db, active_only=True)
        if r.user_id == user.id
    ]
    return {"sessions": [_session_public(r) for r in rows]}


@router.delete("/sessions/{session_id}")
def revoke_one(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    from app.models.security import UserSession
    row = db.query(UserSession).filter(UserSession.id == session_id).first()
    if not row:
        raise HTTPException(404, "Oturum bulunamadı")
    user_sessions.revoke_session(db, row)
    revoke_token(row.jti)
    record_audit(
        db, category="auth", action="security.session_revoke", actor=admin,
        summary=f"Oturum iptal: {row.username}", ip_address=client_ip(request),
    )
    return {"ok": True}


@router.post("/sessions/revoke-others")
def revoke_others(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
):
    except_jti = None
    if creds and creds.credentials:
        payload = decode_access_token(creds.credentials)
        if payload:
            except_jti = payload.get("jti")
    n = user_sessions.revoke_user_sessions(db, user.id, except_jti=except_jti)
    record_audit(
        db, category="auth", action="security.revoke_others", actor=user,
        summary=f"Diğer oturumlar iptal: {n}", ip_address=client_ip(request),
    )
    return {"revoked": n}


@router.get("/mfa/users")
def list_mfa_users(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    users = db.query(User).order_by(User.username.asc()).all()
    statuses = mfa_totp.mfa_status_map(db, [u.id for u in users])
    return {
        "users": [
            {
                "user_id": u.id,
                "username": u.username,
                "auth_source": getattr(u, "auth_source", None) or "local",
                "role": u.role,
                "status": statuses.get(u.id, {}).get("status", "disabled"),
                "enrolled_at": statuses.get(u.id, {}).get("enrolled_at"),
                "last_verified_at": statuses.get(u.id, {}).get("last_verified_at"),
            }
            for u in users
        ]
    }


@router.post("/mfa/users/{user_id}/reset")
def reset_mfa_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    ok = mfa_totp.reset_mfa(db, user_id)
    n = user_sessions.revoke_user_sessions(db, user_id)
    record_audit(
        db, category="auth", action="security.mfa_reset", actor=admin,
        target_type="user", target_id=user_id,
        summary=f"MFA sıfırlandı (sessions={n})", ip_address=client_ip(request),
    )
    return {"ok": True, "had_mfa": ok, "sessions_revoked": n}


@router.get("/tls")
def tls_status(_admin: User = Depends(require_role("admin"))):
    return tls_certs.status()


@router.post("/tls/upload")
def tls_upload(
    body: TlsUpload,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    try:
        st = tls_certs.install_uploaded(
            cert_pem=body.cert_pem, key_pem=body.key_pem, chain_pem=body.chain_pem,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    reload = tls_certs.reload_frontend_nginx()
    record_audit(
        db, category="auth", action="security.tls_upload", actor=admin,
        summary="TLS sertifikası yüklendi", ip_address=client_ip(request),
    )
    return {"status": st, "reload": reload}


@router.post("/tls/self-signed")
def tls_self_signed(
    body: TlsSelfSigned,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    st = tls_certs.generate_self_signed(days=body.days, cn=body.cn)
    reload = tls_certs.reload_frontend_nginx()
    record_audit(
        db, category="auth", action="security.tls_self_signed", actor=admin,
        summary="Self-signed TLS üretildi", ip_address=client_ip(request),
    )
    return {"status": st, "reload": reload}
