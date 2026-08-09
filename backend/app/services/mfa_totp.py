"""TOTP MFA (pyotp) — sırlar Fernet ile saklanır."""
from __future__ import annotations

from datetime import datetime, timezone

import pyotp
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_secret, encrypt_secret
from app.models.security import UserMfa
from app.models.user import User


def get_mfa(db: Session, user_id: int) -> UserMfa | None:
    return db.query(UserMfa).filter(UserMfa.user_id == user_id).first()


def is_mfa_enrolled(db: Session, user_id: int) -> bool:
    row = get_mfa(db, user_id)
    return bool(row and row.enabled and row.totp_secret_enc)


def begin_enrollment(db: Session, user: User) -> tuple[str, str]:
    secret = pyotp.random_base32()
    enc = encrypt_secret(secret) or ""
    row = get_mfa(db, user.id)
    if row is None:
        row = UserMfa(user_id=user.id, totp_secret_enc=enc, enabled=False)
    else:
        row.totp_secret_enc = enc
        row.enabled = False
        row.enrolled_at = None
    db.add(row)
    db.commit()
    totp = pyotp.TOTP(secret)
    url = totp.provisioning_uri(name=user.username, issuer_name="AINew")
    return secret, url


def confirm_enrollment(db: Session, user_id: int, code: str) -> bool:
    row = get_mfa(db, user_id)
    if row is None or not row.totp_secret_enc:
        return False
    secret = decrypt_secret(row.totp_secret_enc) or ""
    totp = pyotp.TOTP(secret)
    if not totp.verify(code.strip(), valid_window=1):
        return False
    row.enabled = True
    row.enrolled_at = datetime.now(timezone.utc)
    row.last_verified_at = datetime.now(timezone.utc)
    db.commit()
    return True


def verify_code(db: Session, user_id: int, code: str) -> bool:
    row = get_mfa(db, user_id)
    if row is None or not row.enabled or not row.totp_secret_enc:
        return False
    secret = decrypt_secret(row.totp_secret_enc) or ""
    totp = pyotp.TOTP(secret)
    if not totp.verify(code.strip(), valid_window=1):
        return False
    row.last_verified_at = datetime.now(timezone.utc)
    db.commit()
    return True


def reset_mfa(db: Session, user_id: int) -> bool:
    row = get_mfa(db, user_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def mfa_status_map(db: Session, user_ids: list[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for uid in user_ids:
        row = get_mfa(db, uid)
        if row is None:
            out[uid] = {"status": "disabled", "enrolled_at": None, "last_verified_at": None}
        elif row.enabled:
            out[uid] = {
                "status": "enabled",
                "enrolled_at": row.enrolled_at.isoformat() if row.enrolled_at else None,
                "last_verified_at": row.last_verified_at.isoformat() if row.last_verified_at else None,
            }
        else:
            out[uid] = {
                "status": "pending",
                "enrolled_at": row.enrolled_at.isoformat() if row.enrolled_at else None,
                "last_verified_at": None,
            }
    return out
