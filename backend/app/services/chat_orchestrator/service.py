"""Chat orchestrator — turn yaşam döngüsü ve arka plan runner."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.chat_turn import ChatTurn
from app.services.chat_orchestrator import ai_gate, events
from app.services.chat_source_planner import plan_sources, build_followup_suggestions

logger = logging.getLogger(__name__)

PipelineFn = Callable[[dict, Session], AsyncIterator[Any]]

_PIPELINES: Dict[str, PipelineFn] = {}
_consumer_started = False


def register_pipeline(platform: str, fn: PipelineFn) -> None:
    _PIPELINES[platform] = fn


def _now():
    return datetime.now(timezone.utc)


def create_turn(
    db: Session,
    *,
    platform: str,
    message: str,
    payload: dict,
    session_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> ChatTurn:
    plan = plan_sources(
        message,
        scope=platform,
        skip_ctx=bool(payload.get("skip_server_context")),
        use_rag=payload.get("use_rag", True) is not False,
    )
    turn = ChatTurn(
        id=str(uuid.uuid4()),
        session_id=session_id,
        user_id=user_id,
        platform=platform,
        status="queued",
        message=message,
        payload=payload or {},
        source_plan=plan.to_dict(),
        partial_response="",
        last_seq=0,
    )
    db.add(turn)
    db.commit()
    db.refresh(turn)
    events.publish_event(turn.id, {
        "queued": True,
        "turn_id": turn.id,
        "session_id": session_id,
        "position": ai_gate.queue_position(),
        "plan": plan.to_dict(),
    })
    events.enqueue_job(turn.id)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(run_turn(turn.id))
    except RuntimeError:
        pass
    return turn


def get_turn(db: Session, turn_id: str) -> Optional[ChatTurn]:
    return db.query(ChatTurn).filter(ChatTurn.id == turn_id).first()


def cancel_turn(db: Session, turn_id: str) -> bool:
    row = get_turn(db, turn_id)
    if not row or row.status in ("completed", "failed", "cancelled"):
        return False
    row.status = "cancelled"
    row.finished_at = _now()
    db.commit()
    events.publish_event(turn_id, {"error": "İptal edildi", "done": True, "cancelled": True})
    return True


def _parse_sse_chunk(raw: Any) -> Optional[dict]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    line = raw.strip()
    if line.startswith("data: "):
        line = line[6:]
    try:
        obj = json.loads(line)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


async def run_turn(turn_id: str) -> None:
    if not events.acquire_turn_lock(turn_id):
        return
    db = SessionLocal()
    try:
        row = get_turn(db, turn_id)
        if not row or row.status in ("completed", "failed", "cancelled"):
            return
        if row.status == "cancelled":
            return
        pipeline = _PIPELINES.get(row.platform)
        if pipeline is None:
            row.status = "failed"
            row.error = f"pipeline yok: {row.platform}"
            row.finished_at = _now()
            db.commit()
            events.publish_event(turn_id, {"error": row.error, "done": True})
            return

        row.status = "running"
        db.commit()
        events.publish_event(turn_id, {"phase": "collecting", "turn_id": turn_id})

        pos = ai_gate.queue_position()
        if pos > 0:
            events.publish_event(turn_id, {
                "queued": True,
                "position": pos,
                "message": f"Sıradasınız: {pos}",
            })
        ok, wait_pos = await asyncio.to_thread(ai_gate.try_acquire, 180.0)
        if not ok:
            row.status = "failed"
            row.error = "AI kuyruğu zaman aşımı"
            row.finished_at = _now()
            db.commit()
            events.publish_event(turn_id, {"error": row.error, "done": True})
            return

        full = []
        token_n = 0
        try:
            payload = dict(row.payload or {})
            payload.setdefault("message", row.message)
            payload.setdefault("session_id", row.session_id)
            async for raw in pipeline(payload, db):
                events.refresh_turn_lock(turn_id)
                chunk = _parse_sse_chunk(raw)
                if not chunk:
                    continue
                if row.session_id is None and chunk.get("session_id"):
                    try:
                        row.session_id = int(chunk["session_id"])
                        db.commit()
                    except Exception:
                        db.rollback()
                if chunk.get("token"):
                    full.append(str(chunk["token"]))
                    token_n += 1
                    if token_n == 1:
                        row.status = "streaming"
                    if token_n % 24 == 0:
                        row.partial_response = "".join(full)
                        db.commit()
                if chunk.get("error") and not chunk.get("done"):
                    events.publish_event(turn_id, chunk)
                    continue
                if chunk.get("done"):
                    break
                events.publish_event(turn_id, chunk)
        finally:
            ai_gate.release()

        text = "".join(full).strip()
        row.partial_response = text
        if row.status != "cancelled":
            row.status = "completed"
        row.finished_at = _now()
        plan = row.source_plan if isinstance(row.source_plan, dict) else {}
        try:
            suggestions = build_followup_suggestions(
                plan_sources(row.message, scope=row.platform),
                used_sources=plan.get("sources"),
            )
        except Exception:
            suggestions = []
        db.commit()
        events.publish_event(turn_id, {
            "done": True,
            "session_id": row.session_id,
            "turn_id": turn_id,
            "suggestions": suggestions,
        })
    except Exception as e:
        logger.error("run_turn failed %s: %s", turn_id, e, exc_info=True)
        try:
            db.rollback()
            row = get_turn(db, turn_id)
            if row:
                row.status = "failed"
                row.error = str(e)
                row.finished_at = _now()
                db.commit()
            events.publish_event(turn_id, {"error": str(e), "done": True})
        except Exception:
            pass
    finally:
        events.release_turn_lock(turn_id)
        db.close()


async def subscribe_sse(turn_id: str, after_id: str = "0-0") -> AsyncIterator[str]:
    last = after_id or "0-0"
    idle_rounds = 0
    db = SessionLocal()
    try:
        row = get_turn(db, turn_id)
        terminal = row and row.status in ("completed", "failed", "cancelled")
    finally:
        db.close()

    # önce snapshot replay
    for ev in events.snapshot_events(turn_id, after_id=last):
        eid = ev.pop("_id", last)
        last = eid
        yield "data: " + json.dumps(ev, ensure_ascii=False, default=str) + "\n\n"
        if ev.get("done"):
            return

    while True:
        batch = await asyncio.to_thread(events.read_new_events, turn_id, last, 1500, 50)
        if batch:
            idle_rounds = 0
            for eid, ev in batch:
                last = eid
                ev.pop("_id", None)
                yield "data: " + json.dumps(ev, ensure_ascii=False, default=str) + "\n\n"
                if ev.get("done"):
                    return
            continue
        idle_rounds += 1
        db = SessionLocal()
        try:
            row = get_turn(db, turn_id)
            if row and row.status in ("completed", "failed", "cancelled"):
                extra = {"done": True, "session_id": row.session_id, "turn_id": turn_id}
                if row.error:
                    extra["error"] = row.error
                yield "data: " + json.dumps(extra, ensure_ascii=False) + "\n\n"
                return
        finally:
            db.close()
        if idle_rounds > 240:
            yield "data: " + json.dumps({"error": "Turn zaman aşımı", "done": True}) + "\n\n"
            return


async def consumer_loop() -> None:
    logger.info("Chat turn consumer başladı")
    while True:
        try:
            turn_id = await asyncio.to_thread(events.dequeue_job, 2)
            if turn_id:
                asyncio.create_task(run_turn(turn_id))
            else:
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("chat consumer: %s", e)
            await asyncio.sleep(1.0)


def start_consumer_if_needed() -> None:
    global _consumer_started
    if _consumer_started:
        return
    role = ""
    try:
        import os
        role = (os.getenv("AINEW_SERVICE_ROLE") or "all").strip().lower()
    except Exception:
        role = "all"
    if role not in ("chat",):
        logger.info("Chat Redis consumer atlandı (AINEW_SERVICE_ROLE=%s; iş kabul eden worker çalıştırır)", role)
        return
    _consumer_started = True
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(consumer_loop())
    except Exception as e:
        logger.warning("chat consumer start failed: %s", e)
