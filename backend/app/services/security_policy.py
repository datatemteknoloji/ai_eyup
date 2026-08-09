"""Güvenlik politikası — AppSettings key/value + TTL process cache."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings

SESSION_IDLE_MINUTES = "sec_session_idle_minutes"
SESSION_ABSOLUTE_MINUTES = "sec_session_absolute_minutes"
SESSION_MAX_CONCURRENT = "sec_session_max_concurrent"
MFA_ENABLED = "sec_mfa_enabled"
LOCKOUT_ENABLED = "sec_lockout_enabled"
LOCKOUT_MAX_ATTEMPTS = "sec_lockout_max_attempts"
LOCKOUT_WINDOW_MINUTES = "sec_lockout_window_minutes"
LOCKOUT_DURATION_MINUTES = "sec_lockout_duration_minutes"
PASSWORD_MIN_LENGTH = "sec_password_min_length"

_POLICY_KEYS = (
    SESSION_IDLE_MINUTES,
    SESSION_ABSOLUTE_MINUTES,
    SESSION_MAX_CONCURRENT,
    MFA_ENABLED,
    LOCKOUT_ENABLED,
    LOCKOUT_MAX_ATTEMPTS,
    LOCKOUT_WINDOW_MINUTES,
    LOCKOUT_DURATION_MINUTES,
    PASSWORD_MIN_LENGTH,
)

# Her authenticated istekte 9 AppSettings sorgusunu önlemek için
_CACHE_TTL_SEC = 45.0
_cache_lock = threading.Lock()
_cache: Optional[Tuple[float, "SecurityPolicy"]] = None


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
    password_min_length: int = 8

    def as_public(self) -> dict:
        return asdict(self)


def invalidate_security_policy_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None


def _clamp_int(raw: Optional[str], default: int, *, lo: int, hi: int) -> int:
    if raw is None or not str(raw).strip():
        return default
    try:
        val = int(str(raw).strip())
    except ValueError:
        return default
    return max(lo, min(hi, val))


def _parse_bool(raw: Optional[str], default: bool) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _set(db: Session, key: str, value: str) -> None:
    row = db.query(AppSettings).filter(AppSettings.key == key).first()
    if row is None:
        db.add(AppSettings(key=key, value=value))
    else:
        row.value = value


def _load_policy_from_db(db: Session) -> SecurityPolicy:
    rows = (
        db.query(AppSettings)
        .filter(AppSettings.key.in_(_POLICY_KEYS))
        .all()
    )
    kv = {r.key: r.value for r in rows}
    return SecurityPolicy(
        session_idle_minutes=_clamp_int(kv.get(SESSION_IDLE_MINUTES), 30, lo=5, hi=1440),
        session_absolute_minutes=_clamp_int(kv.get(SESSION_ABSOLUTE_MINUTES), 480, lo=30, hi=10080),
        session_max_concurrent=_clamp_int(kv.get(SESSION_MAX_CONCURRENT), 5, lo=1, hi=50),
        mfa_enabled=_parse_bool(kv.get(MFA_ENABLED), False),
        lockout_enabled=_parse_bool(kv.get(LOCKOUT_ENABLED), True),
        lockout_max_attempts=_clamp_int(kv.get(LOCKOUT_MAX_ATTEMPTS), 5, lo=3, hi=50),
        lockout_window_minutes=_clamp_int(kv.get(LOCKOUT_WINDOW_MINUTES), 15, lo=1, hi=1440),
        lockout_duration_minutes=_clamp_int(kv.get(LOCKOUT_DURATION_MINUTES), 15, lo=1, hi=1440),
        password_min_length=_clamp_int(kv.get(PASSWORD_MIN_LENGTH), 8, lo=4, hi=128),
    )


def get_security_policy(db: Session) -> SecurityPolicy:
    global _cache
    now = time.monotonic()
    with _cache_lock:
        if _cache is not None:
            ts, pol = _cache
            if now - ts < _CACHE_TTL_SEC:
                return pol
    pol = _load_policy_from_db(db)
    with _cache_lock:
        _cache = (now, pol)
    return pol


def update_security_policy(db: Session, patch: dict) -> SecurityPolicy:
    int_map = {
        "session_idle_minutes": (SESSION_IDLE_MINUTES, 5, 1440),
        "session_absolute_minutes": (SESSION_ABSOLUTE_MINUTES, 30, 10080),
        "session_max_concurrent": (SESSION_MAX_CONCURRENT, 1, 50),
        "lockout_max_attempts": (LOCKOUT_MAX_ATTEMPTS, 3, 50),
        "lockout_window_minutes": (LOCKOUT_WINDOW_MINUTES, 1, 1440),
        "lockout_duration_minutes": (LOCKOUT_DURATION_MINUTES, 1, 1440),
        "password_min_length": (PASSWORD_MIN_LENGTH, 4, 128),
    }
    for field, (key, lo, hi) in int_map.items():
        if field in patch and patch[field] is not None:
            try:
                val = max(lo, min(hi, int(patch[field])))
            except (TypeError, ValueError):
                continue
            _set(db, key, str(val))
    if "mfa_enabled" in patch and patch["mfa_enabled"] is not None:
        _set(db, MFA_ENABLED, "true" if patch["mfa_enabled"] else "false")
    if "lockout_enabled" in patch and patch["lockout_enabled"] is not None:
        _set(db, LOCKOUT_ENABLED, "true" if patch["lockout_enabled"] else "false")
    db.commit()
    invalidate_security_policy_cache()
    return get_security_policy(db)
