"""Login brute-force lockout via Redis (Dropt ile aynı pattern)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.redis_client import get_redis
from app.services.security_policy import get_security_policy


def _keys(username: str, client_ip: str) -> tuple[str, str, str, str]:
    u = (username or "").strip().lower()[:128]
    ip = (client_ip or "unknown").strip()[:64]
    return (
        f"ainew:lockout:fail:user:{u}",
        f"ainew:lockout:fail:ip:{ip}",
        f"ainew:lockout:block:user:{u}",
        f"ainew:lockout:block:ip:{ip}",
    )


def is_locked(db: Session, username: str, client_ip: str = "") -> tuple[bool, str]:
    policy = get_security_policy(db)
    if not policy.lockout_enabled:
        return False, ""
    r = get_redis()
    if r is None:
        return False, ""
    try:
        _, _, bu, bi = _keys(username, client_ip)
        if r.exists(bu):
            ttl = int(r.ttl(bu) or 0)
            return True, f"Hesap geçici olarak kilitli ({max(ttl, 1)} sn)"
        if r.exists(bi):
            ttl = int(r.ttl(bi) or 0)
            return True, f"IP geçici olarak kilitli ({max(ttl, 1)} sn)"
    except Exception:
        return False, ""
    return False, ""


def record_failure(db: Session, username: str, client_ip: str = "") -> bool:
    """Return True if this failure triggered a new lockout."""
    policy = get_security_policy(db)
    if not policy.lockout_enabled:
        return False
    r = get_redis()
    if r is None:
        return False
    try:
        fu, fi, bu, bi = _keys(username, client_ip)
        window = max(60, int(policy.lockout_window_minutes) * 60)
        duration = max(60, int(policy.lockout_duration_minutes) * 60)
        max_a = max(1, int(policy.lockout_max_attempts))
        locked = False
        for fail_key, block_key in ((fu, bu), (fi, bi)):
            count = int(r.incr(fail_key))
            if count == 1:
                r.expire(fail_key, window)
            if count >= max_a:
                r.setex(block_key, duration, "1")
                r.delete(fail_key)
                locked = True
        return locked
    except Exception:
        return False


def clear_failures(db: Session, username: str, client_ip: str = "") -> None:
    r = get_redis()
    if r is None:
        return
    try:
        fu, fi, _, _ = _keys(username, client_ip)
        r.delete(fu, fi)
    except Exception:
        pass
