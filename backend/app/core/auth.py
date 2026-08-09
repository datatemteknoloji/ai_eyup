"""
Kimlik doğrulama dependency'leri — JWT Bearer token çözümü ve rol kontrolü.
"""
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User

# auto_error=False → token yoksa 403 fırlatmak yerine None döner; kontrolü biz yaparız.
_bearer = HTTPBearer(auto_error=False)

ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3, "superadmin": 3}


def _resolve_user(
    creds: Optional[HTTPAuthorizationCredentials], db: Session, *, touch: bool = False
) -> Optional[User]:
    if not creds or not creds.credentials:
        return None
    payload = decode_access_token(creds.credentials)
    if not payload:
        return None
    # MFA ara token'ları API erişimi vermez
    if payload.get("purpose"):
        return None
    jti = payload.get("jti") or ""
    if jti:
        from app.models.security import UserSession
        from app.services import user_sessions
        from app.services.security_policy import get_security_policy
        from app.services.user_sessions import SessionIdleError

        # Redis denylist (Wave 6) — revoke sonrası multi-worker anında
        if user_sessions.is_jti_revoked_cached(jti):
            return None

        # İptal edilmiş oturum kaydı varsa reddet
        revoked = (
            db.query(UserSession.id)
            .filter(UserSession.jti == jti, UserSession.revoked_at.isnot(None))
            .first()
        )
        if revoked:
            return None
        row = user_sessions.get_active_session(db, jti)
        if row is not None:
            try:
                if touch:
                    policy = get_security_policy(db)
                    user_sessions.touch_session(db, row, idle_minutes=policy.session_idle_minutes)
            except SessionIdleError:
                return None
        # Session kaydı olan yeni login'ler: süresi dolmuş kayıt → reddet
        expired_row = (
            db.query(UserSession.id)
            .filter(UserSession.jti == jti)
            .first()
        )
        if expired_row is not None and row is None:
            return None
    uid = payload.get("uid")
    user = None
    if uid is not None:
        user = db.query(User).filter(User.id == uid).first()
    if user is None and payload.get("sub"):
        user = db.query(User).filter(User.username == payload["sub"]).first()
    if user is None or not user.is_active:
        return None
    return user


def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    user = _resolve_user(creds, db, touch=True)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz veya eksik kimlik bilgisi",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # İstemci IP'sini sonraki audit yazımları için request.state'e koy.
    request.state.actor = user
    return user


def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Optional[User]:
    return _resolve_user(creds, db, touch=False)


def require_role(min_role: str):
    """Belirli minimum role sahip kullanıcı şartı koşan dependency üretir."""
    min_rank = ROLE_RANK.get(min_role, 99)

    def _dep(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK.get(user.role, 0) < min_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Bu işlem için en az '{min_role}' yetkisi gerekli",
            )
        return user

    return _dep


def user_has_module(user: User, module_id: str, db: Session) -> bool:
    """Admin/superadmin tüm modüllere erişir; diğerleri UserModule atamasına bakar."""
    if user.role in ("admin", "superadmin"):
        return True
    from app.models.module import UserModule
    return (
        db.query(UserModule.id)
        .filter(UserModule.user_id == user.id, UserModule.module_id == module_id)
        .first()
        is not None
    )


def require_module(module_id: str):
    """Belirtilen platform modülüne erişimi zorunlu kılar (menü + URL + API)."""

    def _dep(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not user_has_module(user, module_id, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Bu alan için '{module_id}' modül yetkisi gerekli",
            )
        return user

    return _dep


def client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None
