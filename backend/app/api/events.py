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


class EventResponse(BaseModel):
    id: int
    server_id: Optional[int]
    event_type: str
    severity: str
    source: Optional[str]
    title: str
    description: Optional[str]
    is_acknowledged: bool
    resolved: bool
    created_at: Optional[str]


@router.get("/")
async def list_events(
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
    server_id: Optional[int] = None,
    resolved: Optional[bool] = None,
    limit: int = Query(default=100, le=500),
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

    total = q.count()
    events = q.order_by(desc(SystemEvent.created_at)).offset(offset).limit(limit).all()

    return {
        "total": total,
        "events": [{
            "id": e.id,
            "server_id": e.server_id,
            "event_type": e.event_type,
            "severity": e.severity,
            "source": e.source,
            "title": e.title,
            "description": e.description,
            "raw_data": e.raw_data,
            "is_acknowledged": e.is_acknowledged,
            "resolved": e.resolved,
            "created_at": e.created_at.isoformat() if e.created_at else None
        } for e in events]
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


@router.get("/stats")
async def event_stats(db: Session = Depends(get_db)):
    """Event istatistikleri"""
    total = db.query(SystemEvent).count()
    unresolved = db.query(SystemEvent).filter(SystemEvent.resolved == False).count()
    critical = db.query(SystemEvent).filter(SystemEvent.severity == "critical", SystemEvent.resolved == False).count()
    warning = db.query(SystemEvent).filter(SystemEvent.severity == "warning", SystemEvent.resolved == False).count()
    return {
        "total": total,
        "unresolved": unresolved,
        "critical": critical,
        "warning": warning
    }
