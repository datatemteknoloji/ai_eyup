"""Chat oturumu sahipliği — liste/aç/sil yalnızca oturum sahibine."""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, Query

from app.models.chat_session import ChatSession
from app.models.user import User


def user_pk(user: Optional[User]) -> Optional[int]:
    if user is None:
        return None
    uid = getattr(user, "id", None)
    try:
        return int(uid) if uid is not None else None
    except (TypeError, ValueError):
        return None


def require_user_id(user: Optional[User]) -> int:
    uid = user_pk(user)
    if uid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kimlik doğrulaması gerekli",
        )
    return uid


def sessions_q(db: Session, user_id: int, category: Optional[str] = None) -> Query:
    q = db.query(ChatSession).filter(ChatSession.user_id == user_id)
    if category:
        q = q.filter(ChatSession.category == category)
    return q


def get_owned_session(
    db: Session,
    session_id: int,
    user_id: int,
    category: Optional[str] = None,
) -> Optional[ChatSession]:
    q = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == user_id,
    )
    if category:
        q = q.filter(ChatSession.category == category)
    return q.first()


def require_owned_session(
    db: Session,
    session_id: int,
    user_id: int,
    category: Optional[str] = None,
) -> ChatSession:
    session = get_owned_session(db, session_id, user_id, category)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


def create_owned_session(
    db: Session,
    *,
    user_id: int,
    title: str,
    category: str,
    server_ids: Optional[list] = None,
) -> ChatSession:
    session = ChatSession(
        title=title,
        server_ids=server_ids or [],
        category=category,
        user_id=user_id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session
