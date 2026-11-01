"""HTTP stream → ChatTurn kuyruğu + Redis SSE."""
from __future__ import annotations

import uuid
from typing import Any, Callable, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.core.database import SessionLocal
from app.services.chat_orchestrator import ai_gate
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
    loop: Any = None,
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
    # Adım 13: kuyruk dolu / kullanıcı başına eşzamanlı tur sınırı → tur OLUŞTURULMADAN HTTP 429 (beklemeden)
    turn_id = str(uuid.uuid4())
    try:
        ai_gate.admit(turn_id, user_id)
    except ai_gate.AdmissionError as e:
        raise HTTPException(status_code=e.status, detail=e.detail, headers={"Retry-After": "30"})
    db = SessionLocal()
    try:
        turn = create_turn(
            db,
            platform=platform,
            message=message or "",
            payload=payload or {},
            session_id=session_id,
            user_id=user_id,
            loop=loop,
            turn_id=turn_id,
        )
        turn_id = turn.id
    except Exception:
        ai_gate.turn_finished(turn_id)
        raise
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


async def attach_and_stream_async(**kwargs: Any) -> StreamingResponse:
    """`attach_and_stream`'in event döngüsünü bloklamayan sürümü (Adım 11).

    `create_turn` → `plan_sources` yönlendirme ipucu LLM'ini (senkron, ≤8 sn) ve DB yazımlarını sohbete ayrılmış
    iş parçacığı havuzunda çalıştırır; `run_turn` yine ana event döngüsünde başlar.
    """
    import asyncio

    from app.core.chat_executor import run_chat_io

    return await run_chat_io(attach_and_stream, loop=asyncio.get_running_loop(), **kwargs)
