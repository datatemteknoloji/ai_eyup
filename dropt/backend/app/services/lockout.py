"""Login brute-force lockout via Redis."""

from __future__ import annotations

import redis

from app.core.config import get_settings
from app.services.security_policy import SecurityPolicy

_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


def _keys(username: str, client_ip: str) -> tuple[str, str, str, str]:
    u = (username or "").strip().lower()[:128]
    ip = (client_ip or "unknown").strip()[:64]
    return (
        f"lockout:fail:user:{u}",
        f"lockout:fail:ip:{ip}",
        f"lockout:block:user:{u}",
        f"lockout:block:ip:{ip}",
    )


def is_locked(username: str, client_ip: str, policy: SecurityPolicy) -> tuple[bool, str]:
    if not policy.lockout_enabled:
        return False, ""
    try:
        r = _redis()
        _, _, bu, bi = _keys(username, client_ip)
        if r.exists(bu):
            ttl = int(r.ttl(bu) or 0)
            return True, f"Hesap geçici olarak kilitli ({max(ttl, 1)} sn)"
        if r.exists(bi):
            ttl = int(r.ttl(bi) or 0)
            return True, f"IP geçici olarak kilitli ({max(ttl, 1)} sn)"
    except redis.RedisError:
        return False, ""
    return False, ""


def register_failure(username: str, client_ip: str, policy: SecurityPolicy) -> bool:
    """Return True if this failure triggered a new lockout."""
    if not policy.lockout_enabled:
        return False
    try:
        r = _redis()
        fu, fi, bu, bi = _keys(username, client_ip)
        window = policy.lockout_window_minutes * 60
        duration = policy.lockout_duration_minutes * 60
        max_a = policy.lockout_max_attempts
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
    except redis.RedisError:
        return False


def clear_failures(username: str, client_ip: str) -> None:
    try:
        r = _redis()
        fu, fi, _, _ = _keys(username, client_ip)
        r.delete(fu, fi)
    except redis.RedisError:
        pass
