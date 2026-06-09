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
from app.services.incident_auto import auto_create_or_link_incident

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
    action: str  # "acknowledge", "resolve", "known", "unresolve"


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
        "is_known": getattr(e, "is_known", False),
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
    from sqlalchemy import and_
    known = db.query(SystemEvent).filter(SystemEvent.is_known == True, SystemEvent.resolved == False).count()
    return {
        "total": total,
        "unresolved": unresolved,
        "critical": critical,
        "warning": warning,
        "emergency": emergency,
        "acknowledged": acknowledged,
        "known": known
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
    # Critical/emergency event -> otomatik incident
    incident_id = auto_create_or_link_incident(db, event)
    return {
        "id": event.id,
        "title": event.title,
        "severity": event.severity,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "auto_incident_id": incident_id
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
        elif data.action == "known" and not getattr(event, "is_known", False):
            event.is_known = True
            event.known_at = now
            count += 1
            # metric_anomaly için suppression kuralı da oluştur
            if event.event_type == "metric_anomaly":
                try:
                    from app.services.baseline_engine import create_suppression_rule
                    metric_name = (event.raw_data or {}).get("metric") or event.title[:200]
                    create_suppression_rule(
                        db=db,
                        server_id=event.server_id,
                        metric_name=metric_name,
                        reason=f"Bilinen olay: {event.title[:80]}",
                        created_by="known_bulk",
                        baseline_severity="warning",
                        scope="server",
                    )
                except Exception:
                    pass
        elif data.action == "resolve" and not event.resolved:
            event.resolved = True
            event.resolved_at = now
            count += 1
        elif data.action == "unresolve" and event.resolved:
            event.resolved = False
            event.resolved_at = None
            count += 1
    db.commit()
    return {"success": True, "affected": count, "message": f"{count} event güncellendi"}


@router.post("/{event_id}/known")
async def mark_event_known(
    event_id: int,
    suppress: bool = True,  # metric_anomaly için suppression kuralı da oluştur
    db: Session = Depends(get_db),
):
    """
    Event'i Bilgim Dahilinde olarak işaretle.

    suppress=True (varsayılan): metric_anomaly tipindeki eventler için
    aynı zamanda baseline suppression kuralı oluşturur — bir sonraki
    AIOps döngüsünde aynı alarm yeniden critical olarak gelmez (max warning).
    """
    event = db.query(SystemEvent).filter(SystemEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event bulunamadı")
    event.is_known = True
    event.known_at = datetime.utcnow()
    db.commit()

    suppression_created = False
    if suppress and event.event_type == "metric_anomaly":
        try:
            from app.services.baseline_engine import create_suppression_rule
            metric_name = (event.raw_data or {}).get("metric") or event.title[:200]
            create_suppression_rule(
                db=db,
                server_id=event.server_id,
                metric_name=metric_name,
                reason=f"Bilinen olay — Event #{event_id}: {event.title[:80]}",
                created_by="known_flag",
                baseline_severity="warning",  # tamamen bastırma değil, max warning
                baseline_value=(event.raw_data or {}).get("current_value"),
                scope="server",
            )
            suppression_created = True
        except Exception as ex:
            logger.warning(f"[Events] known → suppression oluşturulamadı: {ex}")

    return {
        "success": True,
        "message": "Bilgim dahilinde olarak işaretlendi",
        "suppression_created": suppression_created,
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


@router.post("/{event_id}/unresolve")
async def unresolve_event(event_id: int, db: Session = Depends(get_db)):
    """Event'i tekrar açık duruma al (çözülmedi)"""
    event = db.query(SystemEvent).filter(SystemEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event bulunamadı")
    event.resolved = False
    event.resolved_at = None
    db.commit()
    return {"success": True, "message": "Event yeniden açıldı"}


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


import re as _re


def _normalize_title(title: str) -> str:
    """Log basligından timestamp ve syslog prefix soy (gruplama icin)."""
    t = (title or "").strip()
    # ISO timestamp: 2026-02-24T05:11:14+03:00
    t = _re.sub(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}([+-]\d{2}:?\d{2}|Z)?\s+', '', t)
    # syslog date: Feb 24 05:11:14
    t = _re.sub(r'^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+', '', t)
    # hostname (word without colon) followed by service[pid]: or service:
    t = _re.sub(r'^\S+\s+\S+\[\d+\]:\s*', '', t)
    t = _re.sub(r'^\S+\s+(?=\S+:)', '', t)
    return t.strip() or (title or "").strip()


def _group_key_for_title(title: str) -> str:
    """Gruplama icin normalize edilmis key: sayilar/hex/adresler N ile replace edilir."""
    t = _normalize_title(title)
    # hex values: 0x1a2b -> 0xN
    t = _re.sub(r'0x[0-9a-fA-F]+', '0xN', t)
    # IPv4/port addresses
    t = _re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?', 'IP', t)
    # UUIDs
    t = _re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 'UUID', _re.IGNORECASE | 0 and t or t, _re.IGNORECASE)
    t = _re.sub(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', 'UUID', t)
    # remaining numbers
    t = _re.sub(r'\d+', 'N', t)
    return t.strip()


_SEVERITY_ORDER = {"emergency": 0, "critical": 1, "error": 2, "warning": 3, "info": 4}


@router.get("/grouped")
async def list_events_grouped(
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
    server_id: Optional[int] = None,
    resolved: Optional[bool] = None,
    search: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    exclude_known: bool = Query(default=True),  # Bilinen eventleri varsayılan olarak gizle
    limit: int = Query(default=50, le=100),
    offset: int = 0,
    sort_by: str = Query(default="latest_created_at"),
    sort_dir: str = Query(default="desc"),
    db: Session = Depends(get_db),
):
    """Event'leri normalize baslik + (event_type, severity, server_id) ile grupla.
    last_seen alanini 'Son Olusum' icin kullanir. Tum gruplara gore server-side sort."""
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
    if exclude_known:
        q = q.filter(SystemEvent.is_known == False)  # noqa: E712
    if search:
        q = q.filter(SystemEvent.title.ilike(f"%{search}%"))

    events = q.order_by(desc(SystemEvent.last_seen)).limit(5000).all()
    server_ids = list({e.server_id for e in events if e.server_id})
    server_map: dict = {}
    if server_ids:
        servers = db.query(Server.id, Server.name).filter(Server.id.in_(server_ids)).all()
        server_map = {s.id: s.name for s in servers}

    groups_map: dict = {}
    for e in events:
        clean_title = _normalize_title(e.title or "")
        group_key_title = _group_key_for_title(e.title or "")
        key = (e.event_type or "", group_key_title[:200], e.severity or "info", e.server_id or 0)
        last_seen_val = (e.last_seen or e.created_at)
        if key not in groups_map:
            groups_map[key] = {
                "event_type": e.event_type,
                "title": clean_title,
                "severity": e.severity,
                "server_id": e.server_id,
                "server_name": server_map.get(e.server_id) if e.server_id else None,
                "event_ids": [],
                "latest_created_at": last_seen_val.isoformat() if last_seen_val else None,
                "resolved": e.resolved,
                "is_acknowledged": e.is_acknowledged,
                "is_known": getattr(e, "is_known", False),
            }
        groups_map[key]["event_ids"].append(e.id)
        if last_seen_val:
            cur = groups_map[key].get("latest_created_at") or ""
            if last_seen_val.isoformat() > cur:
                groups_map[key]["latest_created_at"] = last_seen_val.isoformat()

    groups_list = [{**v, "count": len(v["event_ids"])} for v in groups_map.values()]

    asc = sort_dir == "asc"
    if sort_by == "severity":
        groups_list.sort(key=lambda x: _SEVERITY_ORDER.get(x["severity"] or "info", 99), reverse=not asc)
    elif sort_by == "count":
        groups_list.sort(key=lambda x: x["count"], reverse=not asc)
    elif sort_by == "title":
        groups_list.sort(key=lambda x: (x["title"] or "").lower(), reverse=not asc)
    elif sort_by == "server_name":
        groups_list.sort(key=lambda x: (x["server_name"] or "").lower(), reverse=not asc)
    elif sort_by == "event_type":
        groups_list.sort(key=lambda x: (x["event_type"] or "").lower(), reverse=not asc)
    else:  # latest_created_at (default)
        groups_list.sort(key=lambda x: x["latest_created_at"] or "", reverse=not asc)

    total_groups = len(groups_list)
    groups_list = groups_list[offset : offset + limit]
    return {"total": total_groups, "groups": groups_list}


@router.get("/occurrences")
async def list_event_occurrences(
    ids: str = Query(..., description="Virgülle ayrılmış event id'leri"),
    db: Session = Depends(get_db),
):
    """Verilen id'lerin tüm event kayıtlarını döner."""
    id_list = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
    if not id_list:
        return {"events": []}
    events = (
        db.query(SystemEvent)
        .filter(SystemEvent.id.in_(id_list))
        .order_by(desc(SystemEvent.created_at))
        .all()
    )
    server_ids = list({e.server_id for e in events if e.server_id})
    server_map: dict = {}
    if server_ids:
        servers = db.query(Server.id, Server.name).filter(Server.id.in_(server_ids)).all()
        server_map = {s.id: s.name for s in servers}
    return {"events": [_event_to_dict(e, server_map.get(e.server_id)) for e in events]}


@router.post("/scan")
async def scan_all_servers(
    only_ai_ready: bool = False,
    db: Session = Depends(get_db),
):
    """Tüm ONLINE sunucuları SSH ile tara, yeni log event'leri kaydet.
    only_ai_ready=true ise sadece AI-Ready sunucular taranır."""
    import asyncio as _aio
    from app.services.log_collector import collect_all_servers_logs

    try:
        result = await _aio.get_event_loop().run_in_executor(
            None, lambda: collect_all_servers_logs(db, only_ai_ready=only_ai_ready)
        )
        return {
            "success": True,
            "total_servers": result["total_servers"],
            "servers_with_logs": result["servers_with_logs"],
            "total_saved": result["total_saved"],
            "details": result["details"],
        }
    except Exception as e:
        logger.error(f"Manual scan error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# ── Log AI Analizi ───────────────────────────────────────────────────────────

@router.post("/{event_id}/log-analyze")
async def log_analyze_event(event_id: int, db: Session = Depends(get_db)):
    """
    Bir event için DB tabanlı AI kök neden analizi çalıştırır.

    log_entry ve metric_anomaly tipleri için log satırlarını DB'den çeker,
    Ollama ile analiz eder ve kök neden + öneriler döner.
    Loglar dışarı çıkmaz (local Ollama).
    """
    from app.services.log_analyst import analyze_event_logs
    import asyncio

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: analyze_event_logs(db, event_id)
    )

    if "error" in result:
        status_code = 404 if result["error"] == "Event bulunamadı" else 503
        raise HTTPException(status_code=status_code, detail=result["error"])

    return result
