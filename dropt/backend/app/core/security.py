from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt  # PyJWT (python-jose bakımsız ve açıklı olduğu için değiştirildi)
from jwt import PyJWTError as JWTError

from app.core.config import get_settings

settings = get_settings()


def _pw_bytes(password: str) -> bytes:
    # bcrypt 72 bayt sınırı: bcrypt 4.x fazlasını sessizce kesiyordu, 5.x ValueError veriyor.
    # Davranış (ve mevcut hash'lerin doğrulanması) değişmesin diye açıkça kesilir.
    return (password or "").encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            _pw_bytes(plain_password),
            hashed_password.encode("utf-8"),
        )
    except ValueError:
        return False


def create_access_token(
    *,
    subject: str,
    role: str,
    extra: dict[str, Any] | None = None,
    expires_minutes: int | None = None,
) -> str:
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    expire = datetime.now(UTC) + timedelta(minutes=max(1, int(minutes)))
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "exp": expire,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


class TokenError(Exception):
    pass


def safe_decode_token(token: str) -> dict[str, Any]:
    try:
        return decode_access_token(token)
    except JWTError as exc:
        raise TokenError("Geçersiz veya süresi dolmuş oturum") from exc
