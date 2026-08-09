"""
Platform Durumu API — container listesi, loglar (SSE), yeniden başlatma.
Yalnızca admin.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.auth import require_role
from app.models.user import User
from app.services import docker_engine as docker
from app.services import platform_status as ps
from app.services.audit import record_audit

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/capability")
def platform_capability(_admin: User = Depends(require_role("admin"))):
    return ps.capability()


@router.get("/containers")
def platform_containers(_admin: User = Depends(require_role("admin"))):
    return ps.list_stack_status()


@router.get("/containers/{name}/logs")
def platform_container_logs_tail(
    name: str,
    tail: int = Query(200, ge=1, le=2000),
    _admin: User = Depends(require_role("admin")),
):
    try:
        cid = ps.resolve_container_id(name)
        text = docker.container_logs_tail(cid, tail=tail)
        return {"name": name, "tail": tail, "logs": text}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(503, f"Log okunamadı: {e}")


@router.get("/containers/{name}/logs/stream")
async def platform_container_logs_stream(
    name: str,
    request: Request,
    tail: int = Query(100, ge=1, le=1000),
    _admin: User = Depends(require_role("admin")),
):
    """SSE canlı log akışı."""
    try:
        cid = ps.resolve_container_id(name)
    except ValueError as e:
        raise HTTPException(404, str(e))

    def event_gen():
        try:
            yield f"event: meta\ndata: {name}\n\n"
            for line in docker.iter_container_logs(cid, tail=tail, follow=True):
                # SSE: her satır
                safe = line.rstrip("\n").replace("\r", "")
                yield f"data: {safe}\n\n"
        except GeneratorExit:
            return
        except Exception as e:
            yield f"event: error\ndata: {str(e)[:300]}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class RestartBody(BaseModel):
    confirm: bool = Field(False, description="true olmalı")


@router.post("/containers/{name}/restart")
def platform_container_restart(
    name: str,
    body: RestartBody,
    request: Request,
    admin: User = Depends(require_role("admin")),
):
    if not body.confirm:
        raise HTTPException(400, "confirm=true gerekli")
    if not docker.docker_sock_writable():
        raise HTTPException(503, "Docker soketi yazılamıyor — yeniden başlatma kapalı")
    try:
        cid = ps.resolve_container_id(name)
        docker.restart_container(cid, timeout_sec=20)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        record_audit(
            None,
            category="platform",
            action="container_restart",
            status="failed",
            actor=admin,
            summary=f"Restart başarısız: {name}",
            target_type="container",
            target_id=name,
            detail={"error": str(e)[:300]},
            ip_address=request.client.host if request.client else None,
        )
        raise HTTPException(503, f"Yeniden başlatılamadı: {e}")

    record_audit(
        None,
        category="platform",
        action="container_restart",
        status="success",
        actor=admin,
        summary=f"Container yeniden başlatıldı: {name}",
        target_type="container",
        target_id=name,
        ip_address=request.client.host if request.client else None,
    )
    return {"ok": True, "name": name, "message": f"{name} yeniden başlatıldı"}
