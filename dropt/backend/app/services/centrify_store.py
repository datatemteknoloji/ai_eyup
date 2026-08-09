from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.models.centrify import CentrifyCredential
from app.services.credential_manager import CredentialManager


def encrypt_password(plain: str) -> str:
    return CredentialManager().encrypt(plain)


def decrypt_password(token: str) -> str:
    return CredentialManager().decrypt(token)


def list_credentials(session: Session) -> list[CentrifyCredential]:
    return list(session.exec(select(CentrifyCredential).order_by(CentrifyCredential.domain)).all())


def credential_public(row: CentrifyCredential) -> dict[str, Any]:
    return {
        "id": row.id,
        "label": row.label or row.domain,
        "username": row.username,
        "domain": row.domain,
        "password_set": bool((row.password_enc or "").strip()),
        "enabled": bool(row.enabled),
    }


def find_row_by_domain(session: Session, domain: str) -> CentrifyCredential | None:
    want = (domain or "").strip().lower()
    if not want:
        return None
    for row in list_credentials(session):
        if (row.domain or "").strip().lower() == want:
            return row
    return None


def find_usable_by_domain(session: Session, domain: str) -> CentrifyCredential | None:
    row = find_row_by_domain(session, domain)
    if row is None or not row.enabled or not (row.password_enc or "").strip():
        return None
    return row


def get_plain_creds(session: Session, domain: str) -> tuple[str, str, str] | None:
    """(username, password, domain) or None."""
    row = find_usable_by_domain(session, domain)
    if row is None:
        return None
    try:
        password = decrypt_password(row.password_enc)
    except Exception:
        return None
    if not password:
        return None
    return (
        (row.username or "").strip(),
        password,
        (row.domain or "").strip().lower(),
    )
