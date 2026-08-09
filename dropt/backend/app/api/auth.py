from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.api.deps import client_user_agent, get_current_user
from app.core.config import get_settings
from app.core.database import get_session
from app.core.security import create_access_token, hash_password, safe_decode_token, verify_password
from app.models.job import AuditStatus
from app.models.user import AuthSource, User, UserRole
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    TokenResponse,
    UserPreferencesUpdate,
    UserPublic,
)
from app.schemas.security import MfaChallengeRequest, MfaEnrollStartResponse, MfaTokenRequest
from app.schemas.settings import ChangePasswordRequest
from app.services.ad_auth import authenticate_ad
from app.services.audit import write_audit
from app.services.identity_store import get_or_create_identity
from app.services.kerberos_sso import keytab_status, try_accept_negotiate
from app.services import lockout as lockout_svc
from app.services import mfa_totp as mfa_svc
from app.services import portal_sessions as sess_svc
from app.services.security_policy import get_security_policy
from app.services.sso_oidc import (
    build_authorize_url,
    exchange_code_and_resolve,
    frontend_sso_error_url,
    frontend_sso_success_url,
)
from app.services.user_ids import next_directory_id

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


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


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return (request.client.host or "")[:64]
    return ""


def _mfa_applies(user: User, source: str) -> bool:
    """Portal MFA for local+AD only; SSO trusts IdP."""
    if source in {"sso", "kerberos", "oidc"}:
        return False
    return user.auth_source in {AuthSource.local, AuthSource.ad}


def _issue_mfa_token(user: User, *, source: str) -> str:
    return create_access_token(
        subject=user.username,
        role=user.role.value,
        expires_minutes=10,
        extra={"purpose": "mfa", "src": source, "uid": user.id},
    )


def _issue_login(
    session: Session,
    user: User,
    *,
    client_ip: str = "",
    user_agent: str = "",
    source: str = "local",
    skip_mfa: bool = False,
) -> LoginResponse:
    if not user.is_active or user.role == UserRole.none:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hesap yetkilendirilmemiş veya pasif — Admin rol atamalı",
        )

    policy = get_security_policy(session)
    if policy.mfa_enabled and _mfa_applies(user, source) and not skip_mfa:
        enrolled = mfa_svc.is_mfa_enrolled(session, user.id)  # type: ignore[arg-type]
        mfa_token = _issue_mfa_token(user, source=source)
        if enrolled:
            return LoginResponse(mfa_required=True, mfa_token=mfa_token)
        return LoginResponse(mfa_enrollment_required=True, mfa_token=mfa_token)

    user.last_login_at = datetime.now(UTC)
    session.add(user)
    session.commit()
    session.refresh(user)

    row = sess_svc.create_session(
        session,
        user,
        auth_source=source,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    write_audit(
        session,
        action=f"auth.login.{source}",
        status=AuditStatus.success,
        message=f"Giriş başarılı ({source})",
        user_id=user.id,
        username=user.username,
        role=user.role.value,
        client_ip=client_ip,
        after_state={"session_id": row.id, "jti": row.jti},
    )
    abs_min = policy.session_absolute_minutes
    token = create_access_token(
        subject=user.username,
        role=user.role.value,
        expires_minutes=abs_min,
        extra={"src": source, "jti": row.jti, "sid": row.id},
    )
    return LoginResponse(
        token=TokenResponse(access_token=token, expires_in_minutes=abs_min),
        user=_to_public(session, user),
    )


def _upsert_directory_user(
    session: Session,
    *,
    username: str,
    role,
    auth_source: AuthSource,
) -> User:
    user = session.exec(select(User).where(User.username == username)).first()
    if user is not None and user.auth_source == AuthSource.local and user.password_hash:
        raise ValueError(
            f"'{username}' Local hesap olarak kayıtlı; AD/SSO ile aynı ad kullanılamaz"
        )
    if user is None:
        user = User(
            id=next_directory_id(session),
            username=username,
            password_hash=None,
            role=role,
            auth_source=auth_source,
            is_active=role != UserRole.none,
            created_at=datetime.now(UTC),
        )
    else:
        if user.role == UserRole.none or user.auth_source != AuthSource.local:
            user.role = role
        user.auth_source = auth_source
        user.is_active = user.role != UserRole.none
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _resolve_mfa_user(session: Session, mfa_token: str) -> tuple[User, str]:
    try:
        payload = safe_decode_token(mfa_token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA oturumu geçersiz") from exc
    if payload.get("purpose") != "mfa":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA oturumu geçersiz")
    username = payload.get("sub")
    source = str(payload.get("src") or "local")
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kullanıcı bulunamadı")
    return user, source


def _fail_login(session: Session, username: str, client_ip: str, message: str) -> None:
    policy = get_security_policy(session)
    locked = lockout_svc.register_failure(username, client_ip, policy)
    write_audit(
        session,
        action="auth.login.failed",
        status=AuditStatus.failed,
        message=message,
        username=username,
        client_ip=client_ip,
        after_state={"lockout_triggered": locked} if locked else None,
    )
    if locked:
        write_audit(
            session,
            action="auth.lockout",
            status=AuditStatus.failed,
            message="Brute-force kilidi uygulandı",
            username=username,
            client_ip=client_ip,
        )


@router.get("/login-options")
def login_options(session: Session = Depends(get_session)) -> dict:
    cfg = get_or_create_identity(session)
    mode = (cfg.sso_mode or "kerberos").lower()
    policy = get_security_policy(session)
    return {
        "ad_enabled": bool(cfg.ad_enabled),
        "sso_enabled": bool(cfg.sso_enabled),
        "sso_mode": mode,
        "sso_start_url": "/api/auth/sso/start" if cfg.sso_enabled else "",
        "mfa_enabled": policy.mfa_enabled,
    }


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> LoginResponse:
    username = body.username.strip()
    client_ip = _client_ip(request)
    ua = client_user_agent(request)
    policy = get_security_policy(session)

    locked, lock_msg = lockout_svc.is_locked(username, client_ip, policy)
    if locked:
        write_audit(
            session,
            action="auth.login.blocked",
            status=AuditStatus.failed,
            message=lock_msg,
            username=username,
            client_ip=client_ip,
        )
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=lock_msg)

    user = session.exec(select(User).where(User.username == username)).first()

    if user is not None and user.auth_source == AuthSource.local and user.password_hash:
        if user.is_active and verify_password(body.password, user.password_hash):
            lockout_svc.clear_failures(username, client_ip)
            return _issue_login(session, user, client_ip=client_ip, user_agent=ua, source="local")
        _fail_login(session, username, client_ip, "Local giriş başarısız")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı adı veya şifre hatalı",
        )

    cfg = get_or_create_identity(session)
    if cfg.ad_enabled:
        ad = authenticate_ad(cfg, username, body.password)
        if ad.ok and ad.role is not None:
            try:
                ad_user = _upsert_directory_user(
                    session,
                    username=ad.username or username.split("@")[0].split("\\")[-1],
                    role=ad.role,
                    auth_source=AuthSource.ad,
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
            lockout_svc.clear_failures(username, client_ip)
            return _issue_login(session, ad_user, client_ip=client_ip, user_agent=ua, source="ad")
        _fail_login(session, username, client_ip, ad.message or "AD giriş başarısız")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ad.message or "Kullanıcı adı veya şifre hatalı",
        )

    _fail_login(session, username, client_ip, "Kullanıcı adı veya şifre hatalı")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Kullanıcı adı veya şifre hatalı",
    )


@router.post("/mfa/enroll/start", response_model=MfaEnrollStartResponse)
def mfa_enroll_start(body: MfaTokenRequest, session: Session = Depends(get_session)) -> MfaEnrollStartResponse:
    user, _source = _resolve_mfa_user(session, body.mfa_token)
    policy = get_security_policy(session)
    if not policy.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA kapalı")
    if mfa_svc.is_mfa_enrolled(session, user.id):  # type: ignore[arg-type]
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA zaten kayıtlı")
    secret, url = mfa_svc.begin_enrollment(session, user)
    write_audit(
        session,
        action="auth.mfa.enroll.start",
        status=AuditStatus.info,
        message="MFA enrollment başladı",
        user_id=user.id,
        username=user.username,
        role=user.role.value,
    )
    return MfaEnrollStartResponse(secret=secret, otpauth_url=url)


@router.post("/mfa/enroll/confirm", response_model=LoginResponse)
def mfa_enroll_confirm(
    body: MfaChallengeRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> LoginResponse:
    user, source = _resolve_mfa_user(session, body.mfa_token)
    if not mfa_svc.confirm_enrollment(session, user.id, body.code):  # type: ignore[arg-type]
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Geçersiz doğrulama kodu")
    write_audit(
        session,
        action="auth.mfa.enroll.confirm",
        status=AuditStatus.success,
        message="MFA enrollment tamamlandı",
        user_id=user.id,
        username=user.username,
        role=user.role.value,
        client_ip=_client_ip(request),
    )
    return _issue_login(
        session,
        user,
        client_ip=_client_ip(request),
        user_agent=client_user_agent(request),
        source=source,
        skip_mfa=True,
    )


@router.post("/mfa/verify", response_model=LoginResponse)
def mfa_verify(
    body: MfaChallengeRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> LoginResponse:
    user, source = _resolve_mfa_user(session, body.mfa_token)
    if not mfa_svc.verify_code(session, user.id, body.code):  # type: ignore[arg-type]
        write_audit(
            session,
            action="auth.mfa.verify.failed",
            status=AuditStatus.failed,
            message="MFA kodu hatalı",
            user_id=user.id,
            username=user.username,
            client_ip=_client_ip(request),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz doğrulama kodu")
    write_audit(
        session,
        action="auth.mfa.verify",
        status=AuditStatus.success,
        message="MFA doğrulandı",
        user_id=user.id,
        username=user.username,
        role=user.role.value,
        client_ip=_client_ip(request),
    )
    return _issue_login(
        session,
        user,
        client_ip=_client_ip(request),
        user_agent=client_user_agent(request),
        source=source,
        skip_mfa=True,
    )


@router.get("/sso/start")
def sso_start(request: Request, session: Session = Depends(get_session)):
    cfg = get_or_create_identity(session)
    if not cfg.sso_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SSO kapalı")

    mode = (cfg.sso_mode or "kerberos").lower()
    if mode == "oidc":
        try:
            url, _state = build_authorize_url(cfg)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"SSO başlatılamadı: {exc}") from exc
        return RedirectResponse(url=url, status_code=302)

    if not keytab_status(cfg)["uploaded"] or not (cfg.kerberos_realm or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kerberos Realm / Keytab yapılandırılmamış",
        )

    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("negotiate "):
        token = auth.split(" ", 1)[1].strip()
        username = try_accept_negotiate(cfg, token)
        if not username:
            return RedirectResponse(
                frontend_sso_error_url(cfg, "Kerberos doğrulama başarısız"),
                status_code=302,
            )
        existing = session.exec(select(User).where(User.username == username)).first()
        if existing is None:
            try:
                user = _upsert_directory_user(
                    session,
                    username=username,
                    role=UserRole.none,
                    auth_source=AuthSource.sso,
                )
            except ValueError as exc:
                return RedirectResponse(frontend_sso_error_url(cfg, str(exc)), status_code=302)
        else:
            user = existing
            if user.auth_source == AuthSource.local and user.password_hash:
                return RedirectResponse(
                    frontend_sso_error_url(cfg, "Bu kullanıcı Local hesap; SSO kullanılamaz"),
                    status_code=302,
                )
        try:
            issued = _issue_login(
                session,
                user,
                client_ip=_client_ip(request),
                user_agent=client_user_agent(request),
                source="kerberos",
            )
        except HTTPException as exc:
            return RedirectResponse(frontend_sso_error_url(cfg, str(exc.detail)), status_code=302)
        if not issued.token:
            return RedirectResponse(frontend_sso_error_url(cfg, "SSO oturum açılamadı"), status_code=302)
        return RedirectResponse(frontend_sso_success_url(cfg, issued.token.access_token), status_code=302)

    from fastapi.responses import Response

    return Response(
        content="Negotiate",
        status_code=401,
        headers={"WWW-Authenticate": "Negotiate"},
        media_type="text/plain",
    )


@router.get("/sso/callback")
def sso_callback(
    request: Request,
    session: Session = Depends(get_session),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    cfg = get_or_create_identity(session)
    if error:
        return RedirectResponse(
            frontend_sso_error_url(cfg, error_description or error),
            status_code=302,
        )
    if not code or not state:
        return RedirectResponse(frontend_sso_error_url(cfg, "SSO code/state eksik"), status_code=302)
    try:
        username, role, _claims = exchange_code_and_resolve(cfg, code=code, state=state)
        user = _upsert_directory_user(
            session,
            username=username,
            role=role,
            auth_source=AuthSource.sso,
        )
        issued = _issue_login(
            session,
            user,
            client_ip=_client_ip(request),
            user_agent=client_user_agent(request),
            source="oidc",
        )
        if not issued.token:
            return RedirectResponse(frontend_sso_error_url(cfg, "SSO oturum açılamadı"), status_code=302)
        return RedirectResponse(frontend_sso_success_url(cfg, issued.token.access_token), status_code=302)
    except Exception as exc:  # noqa: BLE001
        write_audit(
            session,
            action="auth.login.sso.failed",
            status=AuditStatus.failed,
            message=str(exc)[:500],
            client_ip=_client_ip(request),
        )
        return RedirectResponse(frontend_sso_error_url(cfg, str(exc)), status_code=302)


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> UserPublic:
    return _to_public(session, user)


@router.patch("/preferences", response_model=UserPublic)
def update_preferences(
    body: UserPreferencesUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> UserPublic:
    data = body.model_dump(exclude_unset=True)
    if "theme" in data and data["theme"]:
        user.theme = data["theme"]
    if "locale" in data and data["locale"]:
        user.locale = data["locale"]
    session.add(user)
    session.commit()
    session.refresh(user)
    return _to_public(session, user)


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    if user.auth_source != AuthSource.local or not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bu hesap türü için şifre değiştirilemez",
        )
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mevcut şifre hatalı",
        )
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Yeni şifre eskisiyle aynı olamaz",
        )

    user.password_hash = hash_password(body.new_password)
    session.add(user)
    session.commit()
    return {"detail": "Şifre güncellendi"}


@router.post("/logout")
def logout(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    from app.core.security import TokenError, safe_decode_token

    auth = request.headers.get("authorization") or ""
    jti = None
    if auth.lower().startswith("bearer "):
        try:
            payload = safe_decode_token(auth.split(" ", 1)[1].strip())
            jti = payload.get("jti")
        except TokenError:
            jti = None
    if jti:
        row = sess_svc.get_active_session(session, str(jti))
        if row:
            sess_svc.revoke_session(session, row)
            write_audit(
                session,
                action="auth.session.revoke",
                status=AuditStatus.success,
                message="Kullanıcı çıkış yaptı",
                user_id=user.id,
                username=user.username,
                role=user.role.value,
                client_ip=_client_ip(request),
                after_state={"session_id": row.id, "self": True},
            )
    return {"ok": True}
