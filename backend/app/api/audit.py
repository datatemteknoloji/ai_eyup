"""
Audit Log API — filtreli sorgulama ve özet istatistikler.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import require_role
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.user import User

router = APIRouter()


def _row(a: AuditLog) -> dict:
    return {
        "id": a.id,
        "actor_id": a.actor_id,
        "actor_name": a.actor_name,
        "category": a.category,
        "action": a.action,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "server_id": a.server_id,
        "status": a.status,
        "summary": a.summary,
        "detail": a.detail,
        "ip_address": a.ip_address,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("")
@router.get("/")
def list_audit(
    db: Session = Depends(get_db),
    _user: User = Depends(require_role("admin")),
    actor: Optional[str] = None,
    category: Optional[str] = None,
    action: Optional[str] = None,
    status: Optional[str] = None,
    server_id: Optional[int] = None,
    q: Optional[str] = None,
    days: Optional[int] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    query = db.query(AuditLog)
    if actor:
        query = query.filter(AuditLog.actor_name.ilike(f"%{actor}%"))
    if category:
        query = query.filter(AuditLog.category == category)
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    if status:
        query = query.filter(AuditLog.status == status)
    if server_id is not None:
        query = query.filter(AuditLog.server_id == server_id)
    if q:
        query = query.filter(AuditLog.summary.ilike(f"%{q}%"))
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.filter(AuditLog.created_at >= since)

    total = query.count()
    rows = (query.order_by(AuditLog.created_at.desc())
            .offset(max(offset, 0)).limit(min(limit, 500)).all())
    return {"total": total, "limit": limit, "offset": offset,
            "logs": [_row(r) for r in rows]}


@router.get("/stats")
def audit_stats(db: Session = Depends(get_db),
                _user: User = Depends(require_role("admin")),
                days: int = 7):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    base = db.query(AuditLog).filter(AuditLog.created_at >= since)

    by_category = dict(
        db.query(AuditLog.category, func.count(AuditLog.id))
        .filter(AuditLog.created_at >= since)
        .group_by(AuditLog.category).all()
    )
    by_status = dict(
        db.query(AuditLog.status, func.count(AuditLog.id))
        .filter(AuditLog.created_at >= since)
        .group_by(AuditLog.status).all()
    )
    by_actor = dict(
        db.query(AuditLog.actor_name, func.count(AuditLog.id))
        .filter(AuditLog.created_at >= since)
        .group_by(AuditLog.actor_name)
        .order_by(func.count(AuditLog.id).desc()).limit(10).all()
    )
    return {
        "days": days,
        "total": base.count(),
        "by_category": by_category,
        "by_status": by_status,
        "top_actors": by_actor,
    }


@router.get("/categories")
def audit_categories(db: Session = Depends(get_db),
                     _user: User = Depends(require_role("admin"))):
    cats = [c[0] for c in db.query(AuditLog.category).distinct().all()]
    return {"categories": sorted(cats)}
