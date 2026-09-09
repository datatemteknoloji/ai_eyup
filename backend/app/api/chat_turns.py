"""Reconnectable chat turn API — tüm platformlar."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user_optional
from app.core.database import get_db
from app.models.chat_turn import ChatTurn
from app.models.user import User
from app.services.chat_orchestrator.service import cancel_turn, get_turn, subscribe_sse
from app.services.chat_orchestrator import events

router = APIRouter()


def _authorize_turn(row: ChatTurn, user: Optional[User]) -> None:
    """Tur sahipliği kontrolü.

    Bu uçlar (events/snapshot/cancel) turn_id dışında hiçbir doğrulama
    istemiyordu: geçerli bir turn_id'yi ele geçiren herkes sohbet içeriğini
    okuyabiliyor veya turu iptal edebiliyordu.

    `user_id` boş olan turlar için zorlama YAPILMAZ — sohbet uçları uzun süre
    kimlik doğrulaması olmadan çalıştı ve eski turlarda sahip bilgisi yok;
    bunları reddetmek çalışan sayfaları kırardı. Sahip bilgisi yazılmış
    turlarda (istemci token gönderdiğinde) kural katıdır.
    """
    if row.user_id is None:
        return
    if user is None:
        raise HTTPException(status_code=401, detail="Kimlik doğrulaması gerekli")
    if user.id == row.user_id:
        return
    if getattr(user, "role", None) == "admin":
        return
    raise HTTPException(status_code=403, detail="Bu sohbet turu size ait değil")


class TurnOut(BaseModel):
    turn_id: str
    session_id: Optional[int] = None
    platform: str
    status: str
    error: Optional[str] = None
    plan: Optional[dict] = None


@router.get("/{turn_id}", response_model=TurnOut)
def get_turn_status(
    turn_id: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    row = get_turn(db, turn_id)
    if not row:
        raise HTTPException(status_code=404, detail="Turn bulunamadı")
    _authorize_turn(row, user)
    return TurnOut(
        turn_id=row.id,
        session_id=row.session_id,
        platform=row.platform,
        status=row.status,
        error=row.error,
        plan=row.source_plan if isinstance(row.source_plan, dict) else None,
    )


@router.get("/{turn_id}/events")
async def turn_events(
    turn_id: str,
    after: str = "0-0",
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    row = get_turn(db, turn_id)
    if not row:
        raise HTTPException(status_code=404, detail="Turn bulunamadı")
    _authorize_turn(row, user)

    async def gen():
        async for line in subscribe_sse(turn_id, after_id=after or "0-0"):
            yield line

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{turn_id}/snapshot")
def turn_snapshot(
    turn_id: str,
    after: str = "0-0",
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    row = get_turn(db, turn_id)
    if not row:
        raise HTTPException(status_code=404, detail="Turn bulunamadı")
    _authorize_turn(row, user)
    return {
        "turn_id": row.id,
        "status": row.status,
        "session_id": row.session_id,
        "partial_response": row.partial_response or "",
        "error": row.error,
        "events": events.snapshot_events(turn_id, after_id=after),
    }


@router.post("/{turn_id}/cancel")
def turn_cancel(
    turn_id: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    row = get_turn(db, turn_id)
    if not row:
        raise HTTPException(status_code=404, detail="Turn bulunamadı")
    _authorize_turn(row, user)
    if not cancel_turn(db, turn_id):
        raise HTTPException(status_code=404, detail="Turn iptal edilemedi")
    return {"ok": True, "turn_id": turn_id}
