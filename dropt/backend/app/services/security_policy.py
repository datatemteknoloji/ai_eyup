"""Security policy stored in app_settings (defaults are secure-but-usable)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlmodel import Session

from app.models.settings import AppSetting

# Defaults — MFA OFF by product decision
SESSION_IDLE_MINUTES = "sec_session_idle_minutes"
SESSION_ABSOLUTE_MINUTES = "sec_session_absolute_minutes"
SESSION_MAX_CONCURRENT = "sec_session_max_concurrent"
MFA_ENABLED = "sec_mfa_enabled"
LOCKOUT_ENABLED = "sec_lockout_enabled"
LOCKOUT_MAX_ATTEMPTS = "sec_lockout_max_attempts"
LOCKOUT_WINDOW_MINUTES = "sec_lockout_window_minutes"
LOCKOUT_DURATION_MINUTES = "sec_lockout_duration_minutes"


@dataclass
class SecurityPolicy:
    session_idle_minutes: int = 30
    session_absolute_minutes: int = 480
    session_max_concurrent: int = 5
    mfa_enabled: bool = False
    lockout_enabled: bool = True
    lockout_max_attempts: int = 5
    lockout_window_minutes: int = 15
    lockout_duration_minutes: int = 15

    def as_public(self) -> dict:
        return asdict(self)


def _get_int(session: Session, key: str, default: int, *, lo: int, hi: int) -> int:
    row = session.get(AppSetting, key)
    if row is None or not str(row.value).strip():
        return default
    try:
        val = int(str(row.value).strip())
    except ValueError:
        return default
    return max(lo, min(hi, val))


def _get_bool(session: Session, key: str, default: bool) -> bool:
    row = session.get(AppSetting, key)
    if row is None:
        return default
    return str(row.value).strip().lower() in {"1", "true", "yes", "on"}


def _set(session: Session, key: str, value: str) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value
        session.add(row)


def get_security_policy(session: Session) -> SecurityPolicy:
    return SecurityPolicy(
        session_idle_minutes=_get_int(session, SESSION_IDLE_MINUTES, 30, lo=5, hi=1440),
        session_absolute_minutes=_get_int(session, SESSION_ABSOLUTE_MINUTES, 480, lo=30, hi=10080),
        session_max_concurrent=_get_int(session, SESSION_MAX_CONCURRENT, 5, lo=1, hi=50),
        mfa_enabled=_get_bool(session, MFA_ENABLED, False),
        lockout_enabled=_get_bool(session, LOCKOUT_ENABLED, True),
        lockout_max_attempts=_get_int(session, LOCKOUT_MAX_ATTEMPTS, 5, lo=3, hi=50),
        lockout_window_minutes=_get_int(session, LOCKOUT_WINDOW_MINUTES, 15, lo=1, hi=1440),
        lockout_duration_minutes=_get_int(session, LOCKOUT_DURATION_MINUTES, 15, lo=1, hi=1440),
    )


def update_security_policy(session: Session, patch: dict) -> SecurityPolicy:
    mapping = {
        "session_idle_minutes": (SESSION_IDLE_MINUTES, 5, 1440),
        "session_absolute_minutes": (SESSION_ABSOLUTE_MINUTES, 30, 10080),
        "session_max_concurrent": (SESSION_MAX_CONCURRENT, 1, 50),
        "lockout_max_attempts": (LOCKOUT_MAX_ATTEMPTS, 3, 50),
        "lockout_window_minutes": (LOCKOUT_WINDOW_MINUTES, 1, 1440),
        "lockout_duration_minutes": (LOCKOUT_DURATION_MINUTES, 1, 1440),
    }
    for field, (key, lo, hi) in mapping.items():
        if field in patch and patch[field] is not None:
            val = int(patch[field])
            val = max(lo, min(hi, val))
            _set(session, key, str(val))
    if "mfa_enabled" in patch and patch["mfa_enabled"] is not None:
        _set(session, MFA_ENABLED, "1" if bool(patch["mfa_enabled"]) else "0")
    if "lockout_enabled" in patch and patch["lockout_enabled"] is not None:
        _set(session, LOCKOUT_ENABLED, "1" if bool(patch["lockout_enabled"]) else "0")
    session.commit()
    return get_security_policy(session)


def ensure_security_defaults(session: Session) -> None:
    defaults = {
        SESSION_IDLE_MINUTES: "30",
        SESSION_ABSOLUTE_MINUTES: "480",
        SESSION_MAX_CONCURRENT: "5",
        MFA_ENABLED: "0",
        LOCKOUT_ENABLED: "1",
        LOCKOUT_MAX_ATTEMPTS: "5",
        LOCKOUT_WINDOW_MINUTES: "15",
        LOCKOUT_DURATION_MINUTES: "15",
    }
    changed = False
    for key, value in defaults.items():
        if session.get(AppSetting, key) is None:
            session.add(AppSetting(key=key, value=value))
            changed = True
    if changed:
        session.commit()
