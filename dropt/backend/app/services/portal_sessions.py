"""Server-side portal sessions (JWT jti bound)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, select

from app.models.security import PortalSession
from app.models.user import User
from app.services.security_policy import get_security_policy


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def create_session(
    session: Session,
    user: User,
    *,
    auth_source: str,
    client_ip: str = "",
    user_agent: str = "",
) -> PortalSession:
    policy = get_security_policy(session)
    enforce_concurrent_limit(session, user.id, limit=policy.session_max_concurrent)
    now = _now()
    row = PortalSession(
        jti=uuid.uuid4().hex,
        user_id=user.id,  # type: ignore[arg-type]
        username=user.username,
        auth_source=auth_source,
        client_ip=(client_ip or "")[:64],
        user_agent=(user_agent or "")[:512],
        created_at=now,
        last_seen_at=now,
        absolute_expires_at=now + timedelta(minutes=policy.session_absolute_minutes),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def enforce_concurrent_limit(session: Session, user_id: int, *, limit: int) -> None:
    active = session.exec(
        select(PortalSession)
        .where(PortalSession.user_id == user_id)
        .where(col(PortalSession.revoked_at).is_(None))
        .where(PortalSession.absolute_expires_at > _now())
        .order_by(col(PortalSession.created_at).asc())
    ).all()
    overflow = len(active) - limit + 1
    if overflow <= 0:
        return
    for row in active[:overflow]:
        row.revoked_at = _now()
        session.add(row)
    session.commit()


def get_active_session(session: Session, jti: str) -> PortalSession | None:
    if not jti:
        return None
    row = session.exec(select(PortalSession).where(PortalSession.jti == jti)).first()
    if row is None or row.revoked_at is not None:
        return None
    if row.absolute_expires_at.replace(tzinfo=None) <= _now():
        return None
    return row


def touch_session(session: Session, row: PortalSession, *, idle_minutes: int) -> None:
    now = _now()
    last = row.last_seen_at
    if last.tzinfo is not None:
        last = last.replace(tzinfo=None)
    idle = timedelta(minutes=idle_minutes)
    if now - last > idle:
        row.revoked_at = now
        session.add(row)
        session.commit()
        raise SessionIdleError("Oturum hareketsizlik nedeniyle sonlandırıldı")
    # Throttle DB writes
    if now - last >= timedelta(seconds=45):
        row.last_seen_at = now
        session.add(row)
        session.commit()


def revoke_session(session: Session, row: PortalSession) -> None:
    if row.revoked_at is None:
        row.revoked_at = _now()
        session.add(row)
        session.commit()


def revoke_user_sessions(session: Session, user_id: int, *, except_jti: str | None = None) -> int:
    rows = session.exec(
        select(PortalSession)
        .where(PortalSession.user_id == user_id)
        .where(col(PortalSession.revoked_at).is_(None))
    ).all()
    n = 0
    now = _now()
    for row in rows:
        if except_jti and row.jti == except_jti:
            continue
        row.revoked_at = now
        session.add(row)
        n += 1
    if n:
        session.commit()
    return n


def list_sessions(
    session: Session,
    *,
    user_id: int | None = None,
    active_only: bool = True,
) -> list[PortalSession]:
    q = select(PortalSession)
    if user_id is not None:
        q = q.where(PortalSession.user_id == user_id)
    if active_only:
        q = q.where(col(PortalSession.revoked_at).is_(None)).where(
            PortalSession.absolute_expires_at > _now()
        )
    q = q.order_by(col(PortalSession.last_seen_at).desc())
    return list(session.exec(q).all())


class SessionIdleError(Exception):
    pass


class SessionInvalidError(Exception):
    pass
