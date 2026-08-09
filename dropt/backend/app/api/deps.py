from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import TokenError, safe_decode_token
from app.models.user import User, UserRole
from app.services.portal_sessions import SessionIdleError, get_active_session, touch_session
from app.services.security_policy import get_security_policy

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturum gerekli",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = safe_decode_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # MFA pending tokens cannot access normal APIs
    if payload.get("purpose") == "mfa":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA doğrulaması tamamlanmadı",
        )

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz token")

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturum yenilenmeli — tekrar giriş yapın",
        )
    row = get_active_session(session, str(jti))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturum geçersiz veya sonlandırılmış",
        )
    policy = get_security_policy(session)
    try:
        touch_session(session, row, idle_minutes=policy.session_idle_minutes)
    except SessionIdleError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    user = session.exec(select(User).where(User.username == username)).first()
    if user is None or not user.is_active or user.role == UserRole.none:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kullanıcı bulunamadı veya pasif")
    return user


def get_token_jti(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str | None:
    if credentials is None or not credentials.credentials:
        return None
    try:
        payload = safe_decode_token(credentials.credentials)
    except TokenError:
        return None
    jti = payload.get("jti")
    return str(jti) if jti else None


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için Admin yetkisi gerekli")
    return user


def client_user_agent(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:512]
