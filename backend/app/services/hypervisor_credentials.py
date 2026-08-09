"""Hypervisor / OpenShift connection secret helpers (Fernet via SECRET_KEY)."""
from __future__ import annotations

from typing import Any, Optional

from app.core.encryption import decrypt_secret, encrypt_secret


def plain(value: Optional[str]) -> str:
    """Decrypt Fernet ciphertext; legacy plaintext passes through."""
    if not value:
        return ""
    return decrypt_secret(value) or ""


def sealed(value: Optional[str]) -> Optional[str]:
    """Encrypt for DB storage. Empty stays empty/None."""
    if value is None:
        return None
    if value == "":
        return ""
    return encrypt_secret(value)


def hv_password(hv: Any) -> str:
    cc = getattr(hv, "connection_config", None) or {}
    return plain(getattr(hv, "password", None)) or plain(cc.get("password"))


def hv_token(hv: Any) -> str:
    cc = getattr(hv, "connection_config", None) or {}
    return plain(cc.get("token")) or plain(getattr(hv, "password", None))


def seal_connection_secrets(cc: Optional[dict]) -> dict:
    """Return a copy of connection_config with password/token encrypted."""
    out = dict(cc or {})
    if out.get("password"):
        out["password"] = sealed(out["password"])
    if out.get("token"):
        out["token"] = sealed(out["token"])
    return out
