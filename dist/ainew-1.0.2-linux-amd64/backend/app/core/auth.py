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

ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}


def _resolve_user(
    creds: Optional[HTTPAuthorizationCredentials], db: Session
) -> Optional[User]:
    if not creds or not creds.credentials:
        return None
    payload = decode_access_token(creds.credentials)
    if not payload:
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
    user = _resolve_user(creds, db)
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
    return _resolve_user(creds, db)


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


def client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None
