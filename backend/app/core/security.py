"""
Güvenlik yardımcıları — parola hash'leme (bcrypt) ve JWT üretimi/çözümü.
Token revocation için jti (JWT ID) tabanlı blacklist.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── In-memory revocation set (jti'ler) ─────────────────────────────────────
# DB olmadan hızlı kontrol; TTL'i geçen token'lar zaten geçersiz olduğundan
# set sınırlı büyüklükte kalır.  Restart'ta sıfırlanır fakat tokenlar
# zaten süresi dolmuş olur (ACCESS_TOKEN_EXPIRE_MINUTES ≤ 60).
_revoked_jti: set[str] = set()


def revoke_token(jti: str) -> None:
    """Token'ı blacklist'e ekle (logout)."""
    if jti:
        _revoked_jti.add(jti)


def is_token_revoked(jti: str) -> bool:
    return jti in _revoked_jti


def hash_password(password: str) -> str:
    # bcrypt 72 bayt sınırı — uzun parolaları kırp.
    return pwd_context.hash((password or "")[:72])


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify((plain or "")[:72], hashed)
    except Exception:
        return False


def create_access_token(subject: str, *, extra: Optional[Dict[str, Any]] = None,
                        expires_minutes: Optional[int] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    jti = str(uuid.uuid4())
    to_encode: Dict[str, Any] = {"sub": str(subject), "exp": expire, "jti": jti}
    if extra:
        to_encode.update(extra)
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        # Revoke edilmiş token'ları reddet
        jti = payload.get("jti", "")
        if jti and is_token_revoked(jti):
            return None
        return payload
    except JWTError:
        return None
