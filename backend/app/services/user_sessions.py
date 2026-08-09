"""Sunucu tarafı kullanıcı oturumları (JWT jti bağlı)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.security import UserSession
from app.models.user import User
from app.services.security_policy import get_security_policy


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(
    db: Session,
    user: User,
    *,
    jti: str | None = None,
    auth_source: str,
    client_ip: str = "",
    user_agent: str = "",
) -> UserSession:
    policy = get_security_policy(db)
    enforce_concurrent_limit(db, user.id, limit=policy.session_max_concurrent)
    now = _now()
    row = UserSession(
        jti=jti or uuid.uuid4().hex,
        user_id=user.id,
        username=user.username,
        auth_source=auth_source,
        client_ip=(client_ip or "")[:64],
        user_agent=(user_agent or "")[:512],
        created_at=now,
        last_seen_at=now,
        absolute_expires_at=now + timedelta(minutes=policy.session_absolute_minutes),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def enforce_concurrent_limit(db: Session, user_id: int, *, limit: int) -> None:
    now = _now()
    active = (
        db.query(UserSession)
        .filter(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.absolute_expires_at > now,
        )
        .order_by(UserSession.created_at.asc())
        .all()
    )
    overflow = len(active) - limit + 1
    if overflow <= 0:
        return
    for row in active[:overflow]:
        row.revoked_at = now
        exp = row.absolute_expires_at
        ttl = None
        if exp is not None:
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            ttl = max(60, int((exp - now).total_seconds()))
        _mark_jti_revoked_redis(row.jti, ttl_sec=ttl)
    db.commit()


def get_active_session(db: Session, jti: str) -> UserSession | None:
    if not jti:
        return None
    row = db.query(UserSession).filter(UserSession.jti == jti).first()
    if row is None or row.revoked_at is not None:
        return None
    exp = row.absolute_expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp <= _now():
        return None
    return row


class SessionIdleError(Exception):
    pass


def touch_session(db: Session, row: UserSession, *, idle_minutes: int) -> None:
    now = _now()
    last = row.last_seen_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if now - last > timedelta(minutes=idle_minutes):
        row.revoked_at = now
        db.commit()
        exp = row.absolute_expires_at
        ttl = None
        if exp is not None:
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            ttl = max(60, int((exp - _now()).total_seconds()))
        _mark_jti_revoked_redis(row.jti, ttl_sec=ttl)
        raise SessionIdleError("Oturum hareketsizlik nedeniyle sonlandırıldı")
    if now - last >= timedelta(seconds=120):
        row.last_seen_at = now
        db.commit()


def _mark_jti_revoked_redis(jti: str, *, ttl_sec: int | None = None) -> None:
    """Revoke denylist — auth hot path Redis ile hızlı reddeder (Postgres SoT)."""
    if not jti:
        return
    try:
        from app.core.redis_client import get_redis

        r = get_redis()
        if r is None:
            return
        ttl = int(ttl_sec) if ttl_sec and ttl_sec > 0 else 7 * 24 * 3600
        r.setex(f"ainew:session:revoked:{jti}", ttl, "1")
    except Exception:
        pass


def is_jti_revoked_cached(jti: str) -> bool:
    if not jti:
        return False
    try:
        from app.core.redis_client import get_redis

        r = get_redis()
        if r is None:
            return False
        return bool(r.exists(f"ainew:session:revoked:{jti}"))
    except Exception:
        return False


def revoke_session(db: Session, row: UserSession) -> None:
    if row.revoked_at is None:
        row.revoked_at = _now()
        db.commit()
    exp = row.absolute_expires_at
    ttl = None
    if exp is not None:
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        ttl = max(60, int((exp - _now()).total_seconds()))
    _mark_jti_revoked_redis(row.jti, ttl_sec=ttl)


def revoke_user_sessions(db: Session, user_id: int, *, except_jti: str | None = None) -> int:
    rows = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .all()
    )
    n = 0
    now = _now()
    for row in rows:
        if except_jti and row.jti == except_jti:
            continue
        row.revoked_at = now
        n += 1
        exp = row.absolute_expires_at
        ttl = None
        if exp is not None:
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            ttl = max(60, int((exp - now).total_seconds()))
        _mark_jti_revoked_redis(row.jti, ttl_sec=ttl)
    if n:
        db.commit()
    return n


def list_sessions(db: Session, *, active_only: bool = True) -> list[UserSession]:
    q = db.query(UserSession)
    if active_only:
        now = _now()
        q = q.filter(UserSession.revoked_at.is_(None), UserSession.absolute_expires_at > now)
    return q.order_by(UserSession.created_at.desc()).limit(500).all()
