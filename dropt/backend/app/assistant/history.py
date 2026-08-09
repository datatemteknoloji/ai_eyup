from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session, col, select

from app.models.assistant_history import AssistantChatMessage

HISTORY_TTL = timedelta(hours=24)
MAX_CONTEXT_TURNS = 8
MAX_CONTENT = 2000


def purge_expired(session: Session, user_id: int | None = None) -> int:
    cutoff = datetime.now(UTC) - HISTORY_TTL
    q = select(AssistantChatMessage).where(AssistantChatMessage.created_at < cutoff)
    if user_id is not None:
        q = q.where(AssistantChatMessage.user_id == user_id)
    rows = list(session.exec(q).all())
    for row in rows:
        session.delete(row)
    if rows:
        session.commit()
    return len(rows)


def list_history(session: Session, user_id: int, *, limit: int = 50) -> list[AssistantChatMessage]:
    purge_expired(session, user_id)
    cutoff = datetime.now(UTC) - HISTORY_TTL
    rows = session.exec(
        select(AssistantChatMessage)
        .where(AssistantChatMessage.user_id == user_id)
        .where(AssistantChatMessage.created_at >= cutoff)
        .order_by(col(AssistantChatMessage.created_at).asc())
        .limit(limit)
    ).all()
    return list(rows)


def clear_history(session: Session, user_id: int) -> None:
    rows = list(
        session.exec(select(AssistantChatMessage).where(AssistantChatMessage.user_id == user_id)).all()
    )
    for row in rows:
        session.delete(row)
    session.commit()


def append_turn(
    session: Session,
    user_id: int,
    *,
    user_text: str,
    assistant_text: str,
    result: dict[str, Any],
) -> None:
    purge_expired(session, user_id)
    now = datetime.now(UTC)
    op = str(result.get("operation_id") or "")[:64]
    slim = {
        "operation_id": result.get("operation_id"),
        "title_tr": result.get("title_tr"),
        "route": result.get("route"),
        "deep_link": result.get("deep_link"),
        "server_ids": result.get("server_ids") or [],
        "server_hostnames": result.get("server_hostnames") or [],
        "confidence": result.get("confidence"),
        "checklist_tr": (result.get("checklist_tr") or [])[:6],
        "clarifying_questions": (result.get("clarifying_questions") or [])[:3],
        "source": result.get("source"),
    }
    session.add(
        AssistantChatMessage(
            user_id=user_id,
            role="user",
            content=(user_text or "")[:MAX_CONTENT],
            operation_id="",
            result_json="",
            created_at=now,
        )
    )
    session.add(
        AssistantChatMessage(
            user_id=user_id,
            role="assistant",
            content=(assistant_text or "")[:MAX_CONTENT],
            operation_id=op,
            result_json=json.dumps(slim, ensure_ascii=False)[:4000],
            created_at=now,
        )
    )
    session.commit()


def context_for_prompt(session: Session, user_id: int) -> str:
    rows = list_history(session, user_id, limit=MAX_CONTEXT_TURNS * 2)
    if not rows:
        return ""
    lines: list[str] = []
    for r in rows[-MAX_CONTEXT_TURNS * 2 :]:
        prefix = "Kullanıcı" if r.role == "user" else "Asistan"
        extra = f" [op={r.operation_id}]" if r.role == "assistant" and r.operation_id else ""
        lines.append(f"{prefix}{extra}: {r.content[:400]}")
    return "\n".join(lines)
