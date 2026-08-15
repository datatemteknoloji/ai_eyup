"""HTTP stream → ChatTurn kuyruğu + Redis SSE."""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi.responses import StreamingResponse

from app.core.database import SessionLocal
from app.services.chat_orchestrator.service import (
    create_turn,
    register_pipeline,
    subscribe_sse,
)


def attach_and_stream(
    *,
    platform: str,
    payload: dict,
    message: str,
    session_id: Optional[int],
    pipeline: Callable,
    user_id: Optional[int] = None,
) -> StreamingResponse:
    register_pipeline(platform, pipeline)
    for extra in {
        "linux": ("linux", "openshift", "exadata"),
        "openshift": ("linux", "openshift", "exadata"),
        "exadata": ("linux", "openshift", "exadata"),
        "hypervisor": ("hypervisor", "virt"),
        "virt": ("hypervisor", "virt"),
    }.get(platform, ()):
        register_pipeline(extra, pipeline)
    db = SessionLocal()
    try:
        turn = create_turn(
            db,
            platform=platform,
            message=message or "",
            payload=payload or {},
            session_id=session_id,
            user_id=user_id,
        )
        turn_id = turn.id
    finally:
        db.close()

    async def gen():
        yield "data: " + __import__("json").dumps({
            "start": True,
            "turn_id": turn_id,
            "session_id": session_id,
        }) + "\n\n"
        async for line in subscribe_sse(turn_id):
            yield line

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Turn-Id": turn_id,
        },
    )
