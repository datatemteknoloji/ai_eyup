"""Portal user ID pools: Local 1..9999, Directory (AD/SSO) 10000+."""

from __future__ import annotations

from sqlmodel import Session, func, select

from app.models.user import User

LOCAL_ID_MAX = 9999
DIRECTORY_ID_MIN = 10000


def next_local_id(session: Session) -> int:
    current = session.exec(select(func.max(User.id)).where(User.id < DIRECTORY_ID_MIN)).one()
    nxt = int(current or 0) + 1
    if nxt >= DIRECTORY_ID_MIN:
        raise ValueError("Local kullanıcı ID havuzu doldu (1–9999)")
    return nxt


def next_directory_id(session: Session) -> int:
    current = session.exec(select(func.max(User.id)).where(User.id >= DIRECTORY_ID_MIN)).one()
    if current is None or int(current) < DIRECTORY_ID_MIN:
        return DIRECTORY_ID_MIN
    return int(current) + 1
