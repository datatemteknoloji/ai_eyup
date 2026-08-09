"""
Field-level encryption for sensitive DB columns (passwords, private keys).

Uses Fernet (AES-128-CBC + HMAC-SHA256) derived from SECRET_KEY.
Migration-safe: decrypt_secret() falls back to plaintext for legacy rows,
then re-encrypts on next save.
"""
import base64
import hashlib
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_FERNET_PREFIX = b"gAA"  # Fernet tokens always start with this


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    raw = settings.SECRET_KEY.encode()
    derived = hashlib.sha256(raw).digest()  # always 32 bytes
    key = base64.urlsafe_b64encode(derived)
    return Fernet(key)


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    """Encrypt a sensitive string. Returns None unchanged."""
    if not value:
        return value
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    """Decrypt a Fernet-encrypted string.
    Falls back to returning the raw value for un-migrated plaintext rows
    so existing data keeps working after the first deploy.
    """
    if not value:
        return value
    try:
        token = value.encode()
        return _fernet().decrypt(token).decode()
    except (InvalidToken, Exception):
        # Legacy plaintext — return as-is; will be re-encrypted on next write
        return value


def is_encrypted(value: Optional[str]) -> bool:
    """True if value looks like a Fernet ciphertext (urlsafe base64, version 0x80)."""
    if not value:
        return False
    # Fernet token string form always starts with gAAAAA… (version byte 0x80)
    if value.startswith("gAAAA"):
        return True
    try:
        return base64.urlsafe_b64decode(value[:4].encode() + b"==")[:3] == _FERNET_PREFIX
    except Exception:
        return False
