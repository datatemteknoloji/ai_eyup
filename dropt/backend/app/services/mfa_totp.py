"""TOTP MFA helpers (pyotp). Encrypted at rest via Fernet."""

from __future__ import annotations

from datetime import UTC, datetime

import pyotp
from sqlmodel import Session

from app.models.security import UserMfa
from app.models.user import User
from app.services.credential_manager import CredentialManager


def _cm() -> CredentialManager:
    return CredentialManager()


def get_mfa(session: Session, user_id: int) -> UserMfa | None:
    return session.get(UserMfa, user_id)


def is_mfa_enrolled(session: Session, user_id: int) -> bool:
    row = get_mfa(session, user_id)
    return bool(row and row.enabled and row.totp_secret_enc)


def begin_enrollment(session: Session, user: User) -> tuple[str, str]:
    """Return (plaintext_secret, otpauth_url). Does not enable until confirm."""
    secret = pyotp.random_base32()
    enc = _cm().encrypt(secret)
    row = get_mfa(session, user.id)  # type: ignore[arg-type]
    if row is None:
        row = UserMfa(user_id=user.id, totp_secret_enc=enc, enabled=False)  # type: ignore[arg-type]
    else:
        row.totp_secret_enc = enc
        row.enabled = False
        row.enrolled_at = None
    session.add(row)
    session.commit()
    totp = pyotp.TOTP(secret)
    url = totp.provisioning_uri(name=user.username, issuer_name="DrOPT Portal")
    return secret, url


def confirm_enrollment(session: Session, user_id: int, code: str) -> bool:
    row = get_mfa(session, user_id)
    if row is None or not row.totp_secret_enc:
        return False
    secret = _cm().decrypt(row.totp_secret_enc)
    totp = pyotp.TOTP(secret)
    if not totp.verify(code.strip(), valid_window=1):
        return False
    row.enabled = True
    row.enrolled_at = datetime.now(UTC)
    row.last_verified_at = datetime.now(UTC)
    session.add(row)
    session.commit()
    return True


def verify_code(session: Session, user_id: int, code: str) -> bool:
    row = get_mfa(session, user_id)
    if row is None or not row.enabled or not row.totp_secret_enc:
        return False
    secret = _cm().decrypt(row.totp_secret_enc)
    totp = pyotp.TOTP(secret)
    if not totp.verify(code.strip(), valid_window=1):
        return False
    row.last_verified_at = datetime.now(UTC)
    session.add(row)
    session.commit()
    return True


def reset_mfa(session: Session, user_id: int) -> bool:
    row = get_mfa(session, user_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def mfa_status_map(session: Session, user_ids: list[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for uid in user_ids:
        row = get_mfa(session, uid)
        if row is None:
            out[uid] = {"status": "disabled", "enrolled_at": None, "last_verified_at": None}
        elif row.enabled:
            out[uid] = {
                "status": "enabled",
                "enrolled_at": row.enrolled_at,
                "last_verified_at": row.last_verified_at,
            }
        else:
            out[uid] = {
                "status": "pending",
                "enrolled_at": row.enrolled_at,
                "last_verified_at": row.last_verified_at,
            }
    return out
