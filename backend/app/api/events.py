"""
Events API - AIOps Event Management
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
from app.core.database import get_db
from app.models.event import SystemEvent
from app.models.server import Server

logger = logging.getLogger(__name__)
router = APIRouter()


class EventCreate(BaseModel):
    server_id: Optional[int] = None
    event_type: str
    severity: str = "info"
    source: str = "manual"
    title: str
    description: Optional[str] = None
    raw_data: Optional[dict] = None


class BulkActionRequest(BaseModel):
    event_ids: List[int]
    action: str  # "acknowledge", "resolve"


def _event_to_dict(e: SystemEvent, server_name: Optional[str] = None) -> dict:
    return {
        "id": e.id,
        "server_id": e.server_id,
        "server_name": server_name,
        "event_type": e.event_type,
        "severity": e.severity,
        "source": e.source,
        "title": e.title,
        "description": e.description,
        "raw_data": e.raw_data,
        "is_acknowledged": e.is_acknowledged,
        "resolved": e.resolved,
        "created_at": e.created_at.isoformat() if e.created_at else None
    }


@router.get("/stats")
async def event_stats(db: Session = Depends(get_db)):
    """Event istatistikleri"""
    total = db.query(SystemEvent).count()
    unresolved = db.query(SystemEvent).filter(SystemEvent.resolved == False).count()
    critical = db.query(SystemEvent).filter(SystemEvent.severity == "critical", SystemEvent.resolved == False).count()
    warning = db.query(SystemEvent).filter(SystemEvent.severity == "warning", SystemEvent.resolved == False).count()
    emergency = db.query(SystemEvent).filter(SystemEvent.severity == "emergency", SystemEvent.resolved == False).count()
    acknowledged = db.query(SystemEvent).filter(SystemEvent.is_acknowledged == True, SystemEvent.resolved == False).count()
    return {
        "total": total,
        "unresolved": unresolved,
        "critical": critical,
        "warning": warning,
        "emergency": emergency,
        "acknowledged": acknowledged
    }


@router.get("/types")
async def event_types(db: Session = Depends(get_db)):
    """Mevcut event tiplerini listele"""
    from sqlalchemy import distinct
    types = db.query(distinct(SystemEvent.event_type)).all()
    return [t[0] for t in types if t[0]]


@router.get("/")
async def list_events(
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
    server_id: Optional[int] = None,
    resolved: Optional[bool] = None,
    search: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Event'leri listele (filtreleme destekli)"""
    q = db.query(SystemEvent)
    if severity:
        q = q.filter(SystemEvent.severity == severity)
    if event_type:
        q = q.filter(SystemEvent.event_type == event_type)
    if server_id:
        q = q.filter(SystemEvent.server_id == server_id)
    if resolved is not None:
        q = q.filter(SystemEvent.resolved == resolved)
    if acknowledged is not None:
        q = q.filter(SystemEvent.is_acknowledged == acknowledged)
    if search:
        q = q.filter(SystemEvent.title.ilike(f"%{search}%"))

    total = q.count()
    events = q.order_by(desc(SystemEvent.created_at)).offset(offset).limit(limit).all()

    # Server adlarını tek sorguda getir
    server_ids = list({e.server_id for e in events if e.server_id})
    server_map: dict = {}
    if server_ids:
        servers = db.query(Server.id, Server.name).filter(Server.id.in_(server_ids)).all()
        server_map = {s.id: s.name for s in servers}

    return {
        "total": total,
        "events": [_event_to_dict(e, server_map.get(e.server_id)) for e in events]
    }


@router.post("/", status_code=201)
async def create_event(data: EventCreate, db: Session = Depends(get_db)):
    """Yeni event oluştur"""
    event = SystemEvent(
        server_id=data.server_id,
        event_type=data.event_type,
        severity=data.severity,
        source=data.source,
        title=data.title,
        description=data.description,
        raw_data=data.raw_data or {}
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {
        "id": event.id,
        "title": event.title,
        "severity": event.severity,
        "created_at": event.created_at.isoformat() if event.created_at else None
    }


@router.post("/bulk-action")
async def bulk_action(data: BulkActionRequest, db: Session = Depends(get_db)):
    """Toplu event işlemi (acknowledge/resolve)"""
    events = db.query(SystemEvent).filter(SystemEvent.id.in_(data.event_ids)).all()
    if not events:
        raise HTTPException(status_code=404, detail="Event bulunamadı")

    now = datetime.utcnow()
    count = 0
    for event in events:
        if data.action == "acknowledge" and not event.is_acknowledged:
            event.is_acknowledged = True
            event.acknowledged_at = now
            count += 1
        elif data.action == "resolve" and not event.resolved:
            event.resolved = True
            event.resolved_at = now
            count += 1
    db.commit()
    return {"success": True, "affected": count, "message": f"{count} event güncellendi"}


@router.post("/{event_id}/acknowledge")
async def acknowledge_event(event_id: int, db: Session = Depends(get_db)):
    """Event'i onayla"""
    event = db.query(SystemEvent).filter(SystemEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event bulunamadı")
    event.is_acknowledged = True
    event.acknowledged_at = datetime.utcnow()
    db.commit()
    return {"success": True, "message": "Event onaylandı"}


@router.post("/{event_id}/resolve")
async def resolve_event(event_id: int, db: Session = Depends(get_db)):
    """Event'i çözüldü olarak işaretle"""
    event = db.query(SystemEvent).filter(SystemEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event bulunamadı")
    event.resolved = True
    event.resolved_at = datetime.utcnow()
    db.commit()
    return {"success": True, "message": "Event çözüldü olarak işaretlendi"}


@router.delete("/{event_id}")
async def delete_event(event_id: int, db: Session = Depends(get_db)):
    """Event'i sil"""
    event = db.query(SystemEvent).filter(SystemEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event bulunamadı")
    db.delete(event)
    db.commit()
    return {"success": True, "message": "Event silindi"}


@router.post("/bulk-delete")
async def bulk_delete(data: BulkActionRequest, db: Session = Depends(get_db)):
    """Toplu event silme"""
    count = db.query(SystemEvent).filter(SystemEvent.id.in_(data.event_ids)).delete(synchronize_session=False)
    db.commit()
    return {"success": True, "deleted": count}
