"""
Kimlik doğrulama API — login (local/AD + MFA), profil ve kullanıcı yönetimi.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials as _Creds
from fastapi.security import HTTPBearer as _HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import client_ip, get_current_user, require_role
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    revoke_token,
    verify_password,
)
from app.models.user import User
from app.services import ad_sync, lockout, mfa_totp, user_sessions
from app.services.ad_auth import authenticate_ad
from app.services.audit import record_audit
from app.services.identity_store import get_or_create_identity
from app.services.security_policy import get_security_policy

_bearer_opt = _HTTPBearer(auto_error=False)

logger = logging.getLogger(__name__)
router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str


class MfaEnrollConfirm(BaseModel):
    mfa_token: Optional[str] = None
    code: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: str = "operator"


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class PasswordChangeRequest(BaseModel):
    new_password: str


def _user_dict(u: User) -> dict:
    theme = getattr(u, "theme", None) or "dark"
    if theme not in ("dark", "light"):
        theme = "dark"
    locale = (getattr(u, "locale", None) or "tr").strip().lower()
    if locale not in ("tr", "en"):
        locale = "tr"
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "auth_source": getattr(u, "auth_source", None) or "local",
        "theme": theme,
        "locale": locale,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login": u.last_login.isoformat() if u.last_login else None,
    }


def _user_dict_with_modules(u: User, db: Session) -> dict:
    from app.models.module import DEFAULT_MODULES, UserModule
    d = _user_dict(u)
    if u.role in ("admin", "superadmin"):
        d["modules"] = [m["id"] for m in DEFAULT_MODULES]
        d["is_admin"] = True
    else:
        rows = db.query(UserModule).filter(UserModule.user_id == u.id).all()
        d["modules"] = [r.module_id for r in rows]
        d["is_admin"] = False
    return d


def _issue_login(
    db: Session,
    user: User,
    request: Request,
    *,
    auth_source: str,
) -> dict:
    policy = get_security_policy(db)
    jti = uuid.uuid4().hex
    token = create_access_token(
        user.username,
        extra={"uid": user.id, "role": user.role, "jti": jti},
        expires_minutes=policy.session_absolute_minutes,
    )
    # create_access_token already sets jti — re-read from token
    payload = decode_access_token(token)
    real_jti = (payload or {}).get("jti") or jti
    user_sessions.create_session(
        db,
        user,
        jti=real_jti,
        auth_source=auth_source,
        client_ip=client_ip(request) or "",
        user_agent=(request.headers.get("user-agent") or "")[:512],
    )
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    record_audit(
        db, category="auth", action="auth.login", status="success",
        actor=user, summary=f"Giriş yapıldı: {user.username} ({auth_source})",
        ip_address=client_ip(request),
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_dict_with_modules(user, db),
    }


def _mfa_pending_token(user: User, *, need_enroll: bool) -> str:
    return create_access_token(
        user.username,
        extra={
            "uid": user.id,
            "purpose": "mfa_enroll" if need_enroll else "mfa_verify",
        },
        expires_minutes=10,
    )


def _resolve_mfa_user(db: Session, mfa_token: str) -> tuple[User, str]:
    payload = decode_access_token(mfa_token)
    if not payload or payload.get("purpose") not in ("mfa_verify", "mfa_enroll"):
        raise HTTPException(401, "Geçersiz veya süresi dolmuş MFA oturumu")
    uid = payload.get("uid")
    user = db.query(User).filter(User.id == uid).first() if uid else None
    if not user or not user.is_active:
        raise HTTPException(401, "Kullanıcı bulunamadı")
    return user, payload["purpose"]


@router.post("/login")
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    username = (req.username or "").strip()
    password = req.password or ""
    locked, lock_msg = lockout.is_locked(db, username, ip or "")
    if locked:
        raise HTTPException(status_code=423, detail=lock_msg or "Hesap kilitli")
    identity = get_or_create_identity(db)
    user = db.query(User).filter(User.username == username).first()
    auth_source = "local"

    # Local kullanıcı (parola hash varsa) — AD'ye düşme
    if user and (getattr(user, "auth_source", None) or "local") == "local" and user.hashed_password:
        if not user.is_active or not verify_password(password, user.hashed_password):
            lockout.record_failure(db, username, ip or "")
            record_audit(
                db, category="auth", action="auth.login", status="failure",
                actor=username, summary=f"Başarısız giriş: {username}", ip_address=ip,
            )
            raise HTTPException(status_code=401, detail="Kullanıcı adı veya parola hatalı")
    else:
        # AD yolu
        if identity.ad_enabled:
            result = authenticate_ad(identity, username, password)
            if not result.ok:
                # Local fallback: sync'lenmiş AD kaydı yoksa ve local hash varsa
                if user and user.hashed_password and verify_password(password, user.hashed_password):
                    if not user.is_active:
                        raise HTTPException(401, "Kullanıcı pasif")
                    auth_source = "local"
                else:
                    lockout.record_failure(db, username, ip or "")
                    record_audit(
                        db, category="auth", action="auth.login", status="failure",
                        actor=username, summary=f"Başarısız giriş: {username} — {result.message}",
                        ip_address=ip,
                    )
                    raise HTTPException(status_code=401, detail=result.message or "Giriş başarısız")
            else:
                auth_source = "ad"
                uname = result.username or username
                user = db.query(User).filter(User.username == uname).first()
                if user is None:
                    if not identity.ad_jit_enabled:
                        raise HTTPException(
                            403,
                            "AD kullanıcısı senkronize edilmemiş. Önce Ayarlar → Güvenlik → AD Sync çalıştırın.",
                        )
                    try:
                        user = ad_sync.upsert_ad_user_jit(
                            db,
                            username=uname,
                            role=result.role or "viewer",
                            email=result.email,
                            full_name=result.full_name,
                        )
                    except ValueError as exc:
                        raise HTTPException(409, str(exc)) from exc
                else:
                    if (user.auth_source or "local") == "local" and user.hashed_password:
                        raise HTTPException(409, "Bu kullanıcı adı local hesapla çakışıyor")
                    user.auth_source = "ad"
                    # Rolü ezme — Kullanıcı Yönetimi'ndeki yetki geçerli
                    if result.email:
                        user.email = result.email
                    if result.full_name:
                        user.full_name = result.full_name
                    db.commit()
                    db.refresh(user)
        else:
            if not user or not user.is_active or not user.hashed_password \
                    or not verify_password(password, user.hashed_password):
                lockout.record_failure(db, username, ip or "")
                record_audit(
                    db, category="auth", action="auth.login", status="failure",
                    actor=username, summary=f"Başarısız giriş: {username}", ip_address=ip,
                )
                raise HTTPException(status_code=401, detail="Kullanıcı adı veya parola hatalı")

    if not user or not user.is_active:
        raise HTTPException(401, "Kullanıcı pasif veya bulunamadı")

    lockout.clear_failures(db, username, ip or "")
    policy = get_security_policy(db)
    if policy.mfa_enabled:
        enrolled = mfa_totp.is_mfa_enrolled(db, user.id)
        if not enrolled:
            return {
                "mfa_required": True,
                "mfa_enrollment_required": True,
                "mfa_token": _mfa_pending_token(user, need_enroll=True),
                "user": {"id": user.id, "username": user.username},
            }
        return {
            "mfa_required": True,
            "mfa_enrollment_required": False,
            "mfa_token": _mfa_pending_token(user, need_enroll=False),
            "user": {"id": user.id, "username": user.username},
        }

    return _issue_login(db, user, request, auth_source=auth_source)


@router.post("/mfa/verify")
def mfa_verify(req: MfaVerifyRequest, request: Request, db: Session = Depends(get_db)):
    user, purpose = _resolve_mfa_user(db, req.mfa_token)
    if purpose != "mfa_verify":
        raise HTTPException(400, "Kayıt tamamlanmamış; önce MFA enroll kullanın")
    if not mfa_totp.verify_code(db, user.id, req.code):
        raise HTTPException(401, "Geçersiz MFA kodu")
    auth_source = getattr(user, "auth_source", None) or "local"
    return _issue_login(db, user, request, auth_source=auth_source)


class MfaEnrollStart(BaseModel):
    mfa_token: str


@router.post("/mfa/enroll/start")
def mfa_enroll_start(req: MfaEnrollStart, db: Session = Depends(get_db)):
    user, purpose = _resolve_mfa_user(db, req.mfa_token)
    if purpose not in ("mfa_enroll", "mfa_verify"):
        raise HTTPException(400, "Geçersiz MFA token")
    secret, url = mfa_totp.begin_enrollment(db, user)
    # enroll sonrası verify için token purpose'u enroll kalsın; confirm sonrası login
    return {
        "secret": secret,
        "otpauth_url": url,
        "mfa_token": _mfa_pending_token(user, need_enroll=True),
    }


@router.post("/mfa/enroll/confirm")
def mfa_enroll_confirm(req: MfaEnrollConfirm, request: Request, db: Session = Depends(get_db)):
    if not req.mfa_token:
        raise HTTPException(400, "mfa_token gerekli")
    user, _purpose = _resolve_mfa_user(db, req.mfa_token)
    if not mfa_totp.confirm_enrollment(db, user.id, req.code):
        raise HTTPException(400, "Geçersiz kod — kaydı tekrar deneyin")
    auth_source = getattr(user, "auth_source", None) or "local"
    return _issue_login(db, user, request, auth_source=auth_source)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db),
           creds: Optional[_Creds] = Depends(_bearer_opt)):
    if creds and creds.credentials:
        payload = decode_access_token(creds.credentials)
        if payload and payload.get("jti"):
            jti = payload["jti"]
            revoke_token(jti)
            row = user_sessions.get_active_session(db, jti)
            if row:
                user_sessions.revoke_session(db, row)
    record_audit(db, category="auth", action="auth.logout", status="success",
                 summary="Çıkış yapıldı", ip_address=client_ip(request))
    return {"success": True}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _user_dict_with_modules(user, db)


@router.post("/change-password")
def change_own_password(req: PasswordChangeRequest, request: Request,
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    if (getattr(user, "auth_source", None) or "local") != "local":
        raise HTTPException(400, "AD/SSO kullanıcıları parola değiştiremez")
    policy = get_security_policy(db)
    if len(req.new_password or "") < policy.password_min_length:
        raise HTTPException(
            status_code=400,
            detail=f"Parola en az {policy.password_min_length} karakter olmalı",
        )
    user.hashed_password = hash_password(req.new_password)
    db.commit()
    record_audit(db, category="auth", action="auth.change_password", actor=user,
                 summary="Kendi parolasını değiştirdi", ip_address=client_ip(request))
    return {"success": True}


class PreferencesPatch(BaseModel):
    theme: Optional[str] = None
    locale: Optional[str] = None


@router.patch("/preferences")
def update_preferences(
    req: PreferencesPatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if req.theme is not None:
        if req.theme not in ("dark", "light"):
            raise HTTPException(status_code=400, detail="theme dark veya light olmalı")
        user.theme = req.theme
    if req.locale is not None:
        loc = req.locale.strip().lower()
        if loc not in ("tr", "en"):
            raise HTTPException(status_code=400, detail="locale tr veya en olmalı")
        user.locale = loc
    db.commit()
    db.refresh(user)
    return _user_dict_with_modules(user, db)


@router.get("/users")
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    rows = db.query(User).order_by(User.id.asc()).all()
    return {"users": [_user_dict(u) for u in rows]}


@router.post("/users")
def create_user(req: CreateUserRequest, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require_role("admin"))):
    if req.role not in ("admin", "operator", "viewer"):
        raise HTTPException(status_code=400, detail="Geçersiz rol")
    policy = get_security_policy(db)
    if len(req.password or "") < policy.password_min_length:
        raise HTTPException(
            400, f"Parola en az {policy.password_min_length} karakter olmalı",
        )
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=409, detail="Bu kullanıcı adı zaten var")
    u = User(
        username=req.username,
        email=req.email,
        full_name=req.full_name,
        role=req.role,
        auth_source="local",
        hashed_password=hash_password(req.password),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    record_audit(db, category="auth", action="auth.create_user", actor=admin,
                 target_type="user", target_id=u.id,
                 summary=f"Kullanıcı oluşturuldu: {u.username} ({u.role})",
                 ip_address=client_ip(request))
    return _user_dict(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, req: UpdateUserRequest, request: Request,
                db: Session = Depends(get_db), admin: User = Depends(require_role("admin"))):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    if req.role is not None:
        if req.role not in ("admin", "operator", "viewer"):
            raise HTTPException(status_code=400, detail="Geçersiz rol")
        u.role = req.role
    if req.full_name is not None:
        u.full_name = req.full_name
    if req.email is not None:
        u.email = req.email
    if req.is_active is not None:
        u.is_active = req.is_active
    db.commit()
    record_audit(db, category="auth", action="auth.update_user", actor=admin,
                 target_type="user", target_id=u.id,
                 summary=f"Kullanıcı güncellendi: {u.username}",
                 ip_address=client_ip(request))
    return _user_dict(u)


@router.post("/users/{user_id}/password")
def admin_set_password(user_id: int, req: PasswordChangeRequest, request: Request,
                       db: Session = Depends(get_db),
                       admin: User = Depends(require_role("admin"))):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    if (getattr(u, "auth_source", None) or "local") != "local":
        raise HTTPException(400, "AD/SSO kullanıcılarına local parola atanamaz")
    policy = get_security_policy(db)
    if len(req.new_password or "") < policy.password_min_length:
        raise HTTPException(400, f"Parola en az {policy.password_min_length} karakter olmalı")
    u.hashed_password = hash_password(req.new_password)
    db.commit()
    user_sessions.revoke_user_sessions(db, u.id)
    record_audit(db, category="auth", action="auth.reset_password", actor=admin,
                 target_type="user", target_id=u.id,
                 summary=f"Parola sıfırlandı: {u.username}",
                 ip_address=client_ip(request))
    return {"success": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require_role("admin"))):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    if u.id == admin.id:
        raise HTTPException(status_code=400, detail="Kendi hesabınızı silemezsiniz")
    if u.role == "admin" and db.query(User).filter(User.role == "admin").count() <= 1:
        raise HTTPException(status_code=400, detail="Son admin hesabı silinemez")
    uname = u.username
    user_sessions.revoke_user_sessions(db, u.id)
    db.delete(u)
    db.commit()
    record_audit(db, category="auth", action="auth.delete_user", actor=admin,
                 target_type="user", target_id=user_id,
                 summary=f"Kullanıcı silindi: {uname}", ip_address=client_ip(request))
    return {"success": True}
