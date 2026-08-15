"""Reconnectable chat turn API — tüm platformlar."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.chat_turn import ChatTurn
from app.services.chat_orchestrator.service import cancel_turn, get_turn, subscribe_sse
from app.services.chat_orchestrator import events

router = APIRouter()


class TurnOut(BaseModel):
    turn_id: str
    session_id: Optional[int] = None
    platform: str
    status: str
    error: Optional[str] = None
    plan: Optional[dict] = None


@router.get("/{turn_id}", response_model=TurnOut)
def get_turn_status(turn_id: str, db: Session = Depends(get_db)):
    row = get_turn(db, turn_id)
    if not row:
        raise HTTPException(status_code=404, detail="Turn bulunamadı")
    return TurnOut(
        turn_id=row.id,
        session_id=row.session_id,
        platform=row.platform,
        status=row.status,
        error=row.error,
        plan=row.source_plan if isinstance(row.source_plan, dict) else None,
    )


@router.get("/{turn_id}/events")
async def turn_events(turn_id: str, after: str = "0-0", db: Session = Depends(get_db)):
    row = get_turn(db, turn_id)
    if not row:
        raise HTTPException(status_code=404, detail="Turn bulunamadı")

    async def gen():
        async for line in subscribe_sse(turn_id, after_id=after or "0-0"):
            yield line

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{turn_id}/snapshot")
def turn_snapshot(turn_id: str, after: str = "0-0", db: Session = Depends(get_db)):
    row = get_turn(db, turn_id)
    if not row:
        raise HTTPException(status_code=404, detail="Turn bulunamadı")
    return {
        "turn_id": row.id,
        "status": row.status,
        "session_id": row.session_id,
        "partial_response": row.partial_response or "",
        "error": row.error,
        "events": events.snapshot_events(turn_id, after_id=after),
    }


@router.post("/{turn_id}/cancel")
def turn_cancel(turn_id: str, db: Session = Depends(get_db)):
    if not cancel_turn(db, turn_id):
        raise HTTPException(status_code=404, detail="Turn iptal edilemedi")
    return {"ok": True, "turn_id": turn_id}
