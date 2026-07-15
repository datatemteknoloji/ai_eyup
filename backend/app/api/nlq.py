"""
Linux NL Inventory Query API
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import SessionLocal, get_db
from app.models.linux_inventory import LinuxInventory, NlqQueryAudit
from app.models.module import UserModule
from app.models.server import Server
from app.models.user import User
from app.services.nlq.linux_inventory_collector import (
    get_collector_status,
    run_linux_inventory_collection,
)
from app.services.nlq.pipeline import run_nlq
from app.services.nlq.validator import QueryValidationError, validate_query
from app.services.platform_scope import is_linux_server
from app.services.runtime_settings import get_int

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_linux_access(user: User, db: Session) -> None:
    if (user.role or "") == "admin":
        return
    mods = [r.module_id for r in db.query(UserModule).filter(UserModule.user_id == user.id).all()]
    # if no module assignments, allow (legacy); if assigned, need linux or ai_automation
    if mods and "linux" not in mods and "ai_automation" not in mods:
        raise HTTPException(status_code=403, detail="Linux / AI Automation modül yetkisi gerekli")


class AiQueryBody(BaseModel):
    question: str = Field(..., min_length=1)
    live_check: Optional[bool] = None
    model: Optional[str] = None


class ValidateBody(BaseModel):
    query: Optional[Dict[str, Any]] = None
    question: Optional[str] = None


class LiveCheckBody(BaseModel):
    question: Optional[str] = None
    server_ids: Optional[List[int]] = None


class CollectorRunBody(BaseModel):
    workers: Optional[int] = None
    only_ai_ready: bool = True
    server_ids: Optional[List[int]] = None
    force: bool = True  # True → throttle yok (manuel tur)


@router.post("/ai/query")
def ai_query(body: AiQueryBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_linux_access(user, db)
    return run_nlq(
        db,
        body.question,
        user=user,
        live_check=body.live_check,
        model=body.model,
    )


@router.post("/ai/query/validate")
def ai_query_validate(body: ValidateBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_linux_access(user, db)
    from app.services.nlq.parser import parse_question
    from app.services.nlq.pipeline import _user_allowed_tiers

    raw = body.query
    if raw is None:
        if not body.question:
            raise HTTPException(400, "query veya question gerekli")
        raw = parse_question(body.question)
    try:
        validated = validate_query(raw, allowed_tiers=_user_allowed_tiers(user))
        return {"status": "ok", "query": validated}
    except QueryValidationError as e:
        return e.as_dict()


@router.post("/ai/live-check")
def ai_live_check(body: LiveCheckBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_linux_access(user, db)
    if body.question:
        return run_nlq(db, body.question, user=user, live_check=True)
    if not body.server_ids:
        raise HTTPException(400, "question veya server_ids gerekli")
    from app.services.nlq.live_checker import live_check_servers
    fake_rows = []
    for sid in body.server_ids[:50]:
        srv = db.query(Server).filter(Server.id == sid).first()
        if not srv:
            continue
        inv = db.query(LinuxInventory).filter(LinuxInventory.server_id == sid).first()
        uptime_s = inv.uptime_seconds if inv else None
        fake_rows.append({
            "server_id": sid,
            "hostname": srv.hostname or srv.name,
            "uptime_days": round(uptime_s / 86400.0, 1) if uptime_s else None,
            "uptime_seconds": uptime_s,
            "cpu_usage_percent": float(inv.cpu_usage_percent) if inv and inv.cpu_usage_percent is not None else None,
            "memory_usage_percent": float(inv.memory_usage_percent) if inv and inv.memory_usage_percent is not None else None,
            "disk_usage_percent": float(inv.disk_usage_percent) if inv and inv.disk_usage_percent is not None else None,
            "collection_status": inv.collection_status if inv else None,
        })
    diffs = live_check_servers(db, fake_rows)
    return {"status": "success", "live_diff": diffs, "checked": len(fake_rows)}


def _run_collector_bg(
    workers: int,
    only_ai_ready: bool,
    server_ids: Optional[List[int]],
    throttled: bool = True,
):
    db = SessionLocal()
    try:
        run_linux_inventory_collection(
            db,
            workers=workers,
            only_ai_ready=only_ai_ready,
            server_ids=server_ids,
            throttled=throttled,
        )
    finally:
        db.close()


@router.post("/collectors/linux-inventory/run")
def collector_run(
    body: CollectorRunBody,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_linux_access(user, db)
    if get_collector_status().get("running"):
        return {"ok": False, "message": "Collector zaten çalışıyor", "status": get_collector_status()}
    try:
        workers = int(body.workers) if body.workers else get_int("nlq_collector_workers")
    except Exception:
        workers = 50
    throttled = not bool(body.force)
    background.add_task(_run_collector_bg, workers, body.only_ai_ready, body.server_ids, throttled)
    return {"ok": True, "message": "Collector başlatıldı", "workers": workers, "throttled": throttled}


@router.get("/collectors/linux-inventory/status")
def collector_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_linux_access(user, db)
    return get_collector_status()


# Aliases matching plan paths
@router.post("/collectors/run")
def collectors_run_alias(body: CollectorRunBody, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return collector_run(body, background, db, user)


@router.get("/collectors/status")
def collectors_status_alias(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return collector_status(user, db)


@router.get("/ai/servers")
def list_ai_servers(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    environment: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    _require_linux_access(user, db)
    q = (
        db.query(Server, LinuxInventory)
        .outerjoin(LinuxInventory, LinuxInventory.server_id == Server.id)
        .filter(Server.ai_ready == True)  # noqa: E712
    )
    servers = []
    for srv, inv in q.limit(limit * 2).all():
        if not is_linux_server(srv):
            continue
        if environment and (srv.tier or "").lower() != environment.lower():
            continue
        tiers = getattr(user, "allowed_tiers", None)
        if user.role != "admin" and isinstance(tiers, list) and tiers:
            if (srv.tier or "").lower() not in {t.lower() for t in tiers}:
                continue
        uptime_s = inv.uptime_seconds if inv else None
        servers.append({
            "id": srv.id,
            "hostname": srv.hostname or srv.name,
            "ip_address": srv.ip_address,
            "environment": srv.tier,
            "uptime_days": round(uptime_s / 86400.0, 1) if uptime_s else None,
            "collection_status": inv.collection_status if inv else None,
            "collection_time": inv.collection_time.isoformat() if inv and inv.collection_time else None,
        })
        if len(servers) >= limit:
            break
    return {"servers": servers, "total": len(servers)}


@router.get("/ai/servers/{server_id}")
def get_ai_server(server_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_linux_access(user, db)
    srv = db.query(Server).filter(Server.id == server_id).first()
    if not srv:
        raise HTTPException(404, "Sunucu yok")
    inv = db.query(LinuxInventory).filter(LinuxInventory.server_id == server_id).first()
    from app.models.linux_inventory import FilesystemMetric, ServiceStatus, OpenPort
    return {
        "server": {
            "id": srv.id,
            "hostname": srv.hostname or srv.name,
            "ip_address": srv.ip_address,
            "environment": srv.tier,
            "os_type": srv.os_type,
            "os_version": srv.os_version,
            "kernel_version": srv.kernel_version,
        },
        "inventory": None if not inv else {
            "uptime_seconds": inv.uptime_seconds,
            "uptime_days": round(inv.uptime_seconds / 86400.0, 1) if inv.uptime_seconds else None,
            "boot_time": inv.boot_time.isoformat() if inv.boot_time else None,
            "cpu_usage_percent": float(inv.cpu_usage_percent) if inv.cpu_usage_percent is not None else None,
            "memory_usage_percent": float(inv.memory_usage_percent) if inv.memory_usage_percent is not None else None,
            "disk_usage_percent": float(inv.disk_usage_percent) if inv.disk_usage_percent is not None else None,
            "collection_time": inv.collection_time.isoformat() if inv.collection_time else None,
            "collection_status": inv.collection_status,
            "collection_error": inv.collection_error,
        },
        "filesystems": [
            {
                "mount_point": f.mount_point,
                "usage_percent": float(f.usage_percent) if f.usage_percent is not None else None,
                "total_bytes": f.total_bytes,
            }
            for f in db.query(FilesystemMetric).filter(FilesystemMetric.server_id == server_id).all()
        ],
        "services": [
            {"service_name": s.service_name, "active_state": s.active_state, "enabled": s.enabled}
            for s in db.query(ServiceStatus).filter(ServiceStatus.server_id == server_id).limit(100).all()
        ],
        "ports": [
            {"protocol": p.protocol, "port": p.port, "local_address": p.local_address}
            for p in db.query(OpenPort).filter(OpenPort.server_id == server_id).limit(100).all()
        ],
    }


@router.get("/ai/query-history")
def query_history(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
):
    _require_linux_access(user, db)
    q = db.query(NlqQueryAudit).order_by(NlqQueryAudit.id.desc())
    if (user.role or "") != "admin":
        q = q.filter(NlqQueryAudit.user_id == user.id)
    rows = q.limit(limit).all()
    return {
        "items": [
            {
                "id": r.id,
                "username": r.username,
                "question": r.original_question,
                "status": r.status,
                "result_count": r.result_count,
                "live_check_requested": r.live_check_requested,
                "execution_duration_ms": r.execution_duration_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "error_message": r.error_message,
            }
            for r in rows
        ]
    }
