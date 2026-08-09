"""Admin security: policy, sessions, MFA reset."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_token_jti, require_admin
from app.core.database import get_session
from app.models.job import AuditStatus
from app.models.user import User
from app.schemas.security import (
    MfaUserStatus,
    PortalSessionPublic,
    SecurityPolicyPublic,
    SecurityPolicyUpdate,
    TlsEnableUpdate,
    TlsStatusPublic,
    TlsUploadBody,
)
from app.services.audit import write_audit
from app.services import mfa_totp as mfa_svc
from app.services import portal_sessions as sess_svc
from app.services import tls_certs as tls_svc
from app.services.security_policy import get_security_policy, update_security_policy

router = APIRouter(prefix="/security", tags=["security"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return (request.client.host or "")[:64]
    return ""


def _session_public(row, *, current_jti: str | None) -> PortalSessionPublic:
    return PortalSessionPublic(
        id=row.id,
        user_id=row.user_id,
        username=row.username,
        auth_source=row.auth_source,
        client_ip=row.client_ip,
        user_agent=row.user_agent,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        absolute_expires_at=row.absolute_expires_at,
        is_current=bool(current_jti and row.jti == current_jti),
        revoked=row.revoked_at is not None,
    )


@router.get("/policy", response_model=SecurityPolicyPublic)
def get_policy(admin: User = Depends(require_admin), session: Session = Depends(get_session)) -> SecurityPolicyPublic:
    return SecurityPolicyPublic(**get_security_policy(session).as_public())


@router.patch("/policy", response_model=SecurityPolicyPublic)
def patch_policy(
    body: SecurityPolicyUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> SecurityPolicyPublic:
    before = get_security_policy(session).as_public()
    patch = body.model_dump(exclude_unset=True)
    after = update_security_policy(session, patch)
    write_audit(
        session,
        action="security.policy.update",
        status=AuditStatus.success,
        message="Güvenlik politikası güncellendi",
        user_id=admin.id,
        username=admin.username,
        role=admin.role.value,
        client_ip=_client_ip(request),
        before_state=before,
        after_state=after.as_public(),
    )
    return SecurityPolicyPublic(**after.as_public())


@router.get("/sessions", response_model=list[PortalSessionPublic])
def list_all_sessions(
    active_only: bool = Query(True),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
    jti: str | None = Depends(get_token_jti),
) -> list[PortalSessionPublic]:
    rows = sess_svc.list_sessions(session, active_only=active_only)
    return [_session_public(r, current_jti=jti) for r in rows]


@router.get("/sessions/mine", response_model=list[PortalSessionPublic])
def list_my_sessions(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    jti: str | None = Depends(get_token_jti),
) -> list[PortalSessionPublic]:
    rows = sess_svc.list_sessions(session, user_id=user.id, active_only=True)  # type: ignore[arg-type]
    return [_session_public(r, current_jti=jti) for r in rows]


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    rows = sess_svc.list_sessions(session, active_only=False)
    row = next((r for r in rows if r.id == session_id), None)
    if row is None:
        # also search inactive
        from sqlmodel import select
        from app.models.security import PortalSession

        row = session.get(PortalSession, session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Oturum bulunamadı")
    if user.role.value != "admin" and row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Yetkisiz")
    sess_svc.revoke_session(session, row)
    write_audit(
        session,
        action="auth.session.revoke",
        status=AuditStatus.success,
        message=f"Oturum sonlandırıldı id={session_id}",
        user_id=user.id,
        username=user.username,
        role=user.role.value,
        client_ip=_client_ip(request),
        after_state={"target_user_id": row.user_id, "session_id": row.id},
    )
    return {"ok": True}


@router.post("/sessions/revoke-others")
def revoke_others(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    jti: str | None = Depends(get_token_jti),
) -> dict:
    n = sess_svc.revoke_user_sessions(session, user.id, except_jti=jti)  # type: ignore[arg-type]
    write_audit(
        session,
        action="auth.session.revoke_others",
        status=AuditStatus.success,
        message=f"{n} diğer oturum sonlandırıldı",
        user_id=user.id,
        username=user.username,
        role=user.role.value,
        client_ip=_client_ip(request),
        after_state={"count": n},
    )
    return {"ok": True, "revoked": n}


@router.get("/mfa/users", response_model=list[MfaUserStatus])
def list_mfa_users(admin: User = Depends(require_admin), session: Session = Depends(get_session)) -> list[MfaUserStatus]:
    users = session.exec(select(User).order_by(User.username)).all()
    statuses = mfa_svc.mfa_status_map(session, [u.id for u in users if u.id is not None])  # type: ignore[misc]
    out: list[MfaUserStatus] = []
    for u in users:
        if u.id is None:
            continue
        st = statuses.get(u.id, {"status": "disabled"})
        out.append(
            MfaUserStatus(
                user_id=u.id,
                username=u.username,
                auth_source=u.auth_source.value,
                status=st.get("status", "disabled"),
                enrolled_at=st.get("enrolled_at"),
                last_verified_at=st.get("last_verified_at"),
            )
        )
    return out


@router.post("/mfa/users/{user_id}/reset")
def reset_user_mfa(
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict:
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kullanıcı yok")
    ok = mfa_svc.reset_mfa(session, user_id)
    # Invalidate sessions so they must re-auth / re-enroll
    n = sess_svc.revoke_user_sessions(session, user_id)
    write_audit(
        session,
        action="auth.mfa.reset",
        status=AuditStatus.success,
        message=f"MFA sıfırlandı user={target.username}",
        user_id=admin.id,
        username=admin.username,
        role=admin.role.value,
        client_ip=_client_ip(request),
        after_state={"target_user_id": user_id, "had_mfa": ok, "sessions_revoked": n},
    )
    return {"ok": True, "had_mfa": ok, "sessions_revoked": n}


@router.get("/tls", response_model=TlsStatusPublic)
def get_tls_status(admin: User = Depends(require_admin)) -> TlsStatusPublic:
    return TlsStatusPublic(**tls_svc.status())


@router.patch("/tls", response_model=TlsStatusPublic)
def patch_tls(
    body: TlsEnableUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> TlsStatusPublic:
    before = tls_svc.status()
    tls_svc.set_https_enabled(body.https_enabled)
    reload = tls_svc.reload_frontend_nginx()
    after = tls_svc.status()
    write_audit(
        session,
        action="security.tls.toggle",
        status=AuditStatus.success if reload.get("ok") else AuditStatus.info,
        message=f"HTTPS {'açık' if body.https_enabled else 'kapalı'}",
        user_id=admin.id,
        username=admin.username,
        role=admin.role.value,
        client_ip=_client_ip(request),
        before_state={"https_enabled": before.get("https_enabled")},
        after_state={**after, "reload": reload},
    )
    if not reload.get("ok"):
        # Still applied flag; warn client
        after["error"] = reload.get("detail") or "nginx reload başarısız"
    return TlsStatusPublic(**after)


@router.post("/tls/upload", response_model=TlsStatusPublic)
def upload_tls(
    body: TlsUploadBody,
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> TlsStatusPublic:
    try:
        after = tls_svc.install_uploaded(
            cert_pem=body.cert_pem,
            key_pem=body.key_pem,
            chain_pem=body.chain_pem or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    reload = tls_svc.reload_frontend_nginx()
    write_audit(
        session,
        action="security.tls.upload",
        status=AuditStatus.success,
        message="TLS sertifikası yüklendi",
        user_id=admin.id,
        username=admin.username,
        role=admin.role.value,
        client_ip=_client_ip(request),
        after_state={
            "source": after.get("source"),
            "fingerprint_sha256": after.get("fingerprint_sha256"),
            "reload": reload,
        },
    )
    if not reload.get("ok"):
        after["error"] = reload.get("detail")
    return TlsStatusPublic(**after)


@router.post("/tls/self-signed", response_model=TlsStatusPublic)
def regen_self_signed(
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> TlsStatusPublic:
    after = tls_svc.generate_self_signed()
    reload = tls_svc.reload_frontend_nginx()
    write_audit(
        session,
        action="security.tls.self_signed",
        status=AuditStatus.success,
        message="Self-signed TLS üretildi",
        user_id=admin.id,
        username=admin.username,
        role=admin.role.value,
        client_ip=_client_ip(request),
        after_state={"fingerprint_sha256": after.get("fingerprint_sha256"), "reload": reload},
    )
    if not reload.get("ok"):
        after["error"] = reload.get("detail")
    return TlsStatusPublic(**after)
