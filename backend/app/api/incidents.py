"""
Incidents API - AIOps Incident Management + RCA
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, case, desc, func
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
import httpx
from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.config import settings, get_active_model
from app.models.event import Incident, SystemEvent
from app.models.server import Server
from app.models.user import User
from app.services.platform_scope import (
    incident_affected_server_clause,
    incident_platform_clause,
)
from app.services import llm_gateway

logger = logging.getLogger(__name__)
router = APIRouter()


def _touch_stats() -> None:
    try:
        from app.services.dashboard_stats_cache import invalidate_dashboard_stats
        invalidate_dashboard_stats()
    except Exception:
        pass


class IncidentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    severity: str = "medium"
    source: str = "manual"
    assigned_to: Optional[str] = None
    affected_servers: Optional[List[int]] = None
    related_events: Optional[List[int]] = None


class IncidentUpdate(BaseModel):
    status: Optional[str] = None
    severity: Optional[str] = None
    assigned_to: Optional[str] = None
    resolution: Optional[str] = None


class IncidentBulkAction(BaseModel):
    incident_ids: List[int]
    action: str  # investigating | resolved | closed | delete


def _filtered_incidents(
    db: Session,
    *,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    platform: Optional[str] = None,
    server_id: Optional[int] = None,
):
    q = db.query(Incident)
    if status:
        q = q.filter(Incident.status == status)
    if severity:
        q = q.filter(Incident.severity == severity)
    if search:
        q = q.filter(Incident.title.ilike(f"%{search}%"))
    if server_id:
        q = q.filter(incident_affected_server_clause(server_id))
    clause = incident_platform_clause(platform, db)
    if clause is not None:
        q = q.filter(clause)
    return q


def _resolve_linked_events(db: Session, inc: Incident) -> int:
    """Çözülmemiş bağlı event'leri çöz. Incident silinince çağrılmaz."""
    if not inc.related_events:
        return 0
    now = datetime.utcnow()
    events = db.query(SystemEvent).filter(
        SystemEvent.id.in_(inc.related_events),
        SystemEvent.resolved == False,  # noqa: E712
    ).all()
    for e in events:
        e.resolved = True
        e.resolved_at = now
    return len(events)


def _apply_status(db: Session, inc: Incident, status: str) -> int:
    inc.status = status
    if status in ("resolved", "closed"):
        inc.resolved_at = datetime.utcnow()
        return _resolve_linked_events(db, inc)
    return 0


def compute_incident_stats(db: Session, platform: Optional[str] = None) -> dict:
    """Incident sayaçları. Dashboard önbelleği bunu arka planda çağırır."""
    q = _filtered_incidents(db, platform=platform)
    total, open_count, investigating, resolved, critical = q.with_entities(
        func.count(Incident.id),
        func.coalesce(func.sum(case((Incident.status == "open", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Incident.status == "investigating", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Incident.status.in_(("resolved", "closed")), 1), else_=0)), 0),
        func.coalesce(func.sum(case((
            and_(Incident.status == "open", Incident.severity == "critical"), 1
        ), else_=0)), 0),
    ).one()
    return {
        "total": int(total or 0),
        "open": int(open_count or 0),
        "investigating": int(investigating or 0),
        "resolved": int(resolved or 0),
        "critical": int(critical or 0),
    }


@router.get("/stats")
async def incident_stats(
    platform: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Incident istatistikleri — platform filtresi SQL'de, sonuç önbellekte."""
    from app.services.dashboard_stats_cache import get_or_compute

    return get_or_compute(
        "incidents",
        platform,
        "",
        lambda: compute_incident_stats(db, platform),
    )


_LIST_DESC_MAX = 200


def _has_rca(rca_result) -> bool:
    if not rca_result or not isinstance(rca_result, dict):
        return False
    analysis = rca_result.get("analysis")
    return bool(analysis and str(analysis).strip())


def _incident_list_item(inc: Incident, server_map: dict) -> dict:
    """Liste kartı — ağır alanlar (rca_result / root_cause / resolution) yok."""
    desc = inc.description or ""
    if len(desc) > _LIST_DESC_MAX:
        desc = desc[:_LIST_DESC_MAX] + "…"
    server_names = []
    for sid in (inc.affected_servers or []):
        s = server_map.get(sid)
        if s:
            server_names.append(s)
    related = inc.related_events or []
    return {
        "id": inc.id,
        "title": inc.title,
        "description": desc or None,
        "severity": inc.severity,
        "status": inc.status,
        "source": inc.source,
        "affected_servers": inc.affected_servers or [],
        "affected_server_details": server_names,
        "related_events": related,
        "related_event_count": len(related),
        "has_rca": _has_rca(inc.rca_result),
        "assigned_to": inc.assigned_to,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
        "updated_at": inc.updated_at.isoformat() if inc.updated_at else None,
        "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
    }


@router.get("/servers")
async def incident_servers(
    platform: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Bu platformdaki incident'lerde geçen sunucular (filtre kutusu)."""
    q = db.query(Incident.affected_servers)
    clause = incident_platform_clause(platform, db)
    if clause is not None:
        q = q.filter(clause)
    ids: set = set()
    for (arr,) in q.all():
        if not isinstance(arr, list):
            continue
        for raw in arr:
            if isinstance(raw, int):
                ids.add(raw)
            elif isinstance(raw, str) and raw.isdigit():
                ids.add(int(raw))
    if not ids:
        return []
    rows = (
        db.query(Server.id, Server.name)
        .filter(Server.id.in_(list(ids)))
        .order_by(Server.name.asc())
        .all()
    )
    return [{"id": r.id, "name": r.name} for r in rows]


@router.post("/bulk-action")
async def bulk_action(data: IncidentBulkAction, db: Session = Depends(get_db)):
    """Toplu incele / çöz / kapat / sil.

    Çöz ve kapat bağlı açık event'leri de çözer. Silme event'lere dokunmaz.
    """
    action = (data.action or "").strip()
    if action not in ("investigating", "resolved", "closed", "delete"):
        raise HTTPException(status_code=400, detail="Geçersiz işlem")
    ids = list(dict.fromkeys(data.incident_ids or []))[:500]
    if not ids:
        raise HTTPException(status_code=400, detail="Incident seçilmedi")
    incidents = db.query(Incident).filter(Incident.id.in_(ids)).all()
    if not incidents:
        raise HTTPException(status_code=404, detail="Incident bulunamadı")

    affected = 0
    resolved_events = 0
    if action == "delete":
        for inc in incidents:
            db.delete(inc)
            affected += 1
        db.commit()
        _touch_stats()
        return {"success": True, "affected": affected, "resolved_events": 0}

    changed: List[Incident] = []
    for inc in incidents:
        if action == "investigating" and inc.status == "open":
            _apply_status(db, inc, "investigating")
            affected += 1
        elif action == "resolved" and inc.status in ("open", "investigating"):
            resolved_events += _apply_status(db, inc, "resolved")
            affected += 1
            changed.append(inc)
        elif action == "closed" and inc.status in ("open", "investigating", "resolved"):
            resolved_events += _apply_status(db, inc, "closed")
            affected += 1
            changed.append(inc)
    db.commit()
    _touch_stats()
    for inc in changed:
        try:
            from app.services.runbook_candidates import maybe_create_runbook_candidate
            maybe_create_runbook_candidate(db, inc)
        except Exception as e:
            logger.debug("Runbook candidate atlandı: %s", e)
    return {"success": True, "affected": affected, "resolved_events": resolved_events}


@router.get("/")
async def list_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    platform: Optional[str] = None,
    server_id: Optional[int] = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    """Incident listesi (slim). Platform ve sunucu filtresi SQL'de; sayfa LIMIT/OFFSET."""
    q = _filtered_incidents(
        db,
        status=status,
        severity=severity,
        search=search,
        platform=platform,
        server_id=server_id,
    )
    total = q.count()
    incidents = (
        q.order_by(desc(Incident.created_at), desc(Incident.id))
        .offset(offset)
        .limit(limit)
        .all()
    )

    all_server_ids: set = set()
    for inc in incidents:
        all_server_ids.update(inc.affected_servers or [])
    server_map: dict = {}
    if all_server_ids:
        for s in db.query(Server).filter(Server.id.in_(list(all_server_ids))).all():
            server_map[s.id] = {"id": s.id, "name": s.name, "ip": s.ip_address}

    return {
        "total": total,
        "incidents": [_incident_list_item(inc, server_map) for inc in incidents],
    }


@router.post("/", status_code=201)
async def create_incident(data: IncidentCreate, db: Session = Depends(get_db)):
    """Yeni incident oluştur"""
    incident = Incident(
        title=data.title,
        description=data.description,
        severity=data.severity,
        source=data.source,
        assigned_to=data.assigned_to,
        affected_servers=data.affected_servers or [],
        related_events=data.related_events or []
    )
    db.add(incident)
    db.commit()
    _touch_stats()
    db.refresh(incident)
    return {
        "id": incident.id,
        "title": incident.title,
        "status": incident.status,
        "created_at": incident.created_at.isoformat() if incident.created_at else None
    }


@router.put("/{incident_id}")
async def update_incident(incident_id: int, data: IncidentUpdate, db: Session = Depends(get_db)):
    """Incident güncelle"""
    inc = db.query(Incident).filter(Incident.id == incident_id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident bulunamadı")

    resolved_events = 0
    if data.status:
        resolved_events = _apply_status(db, inc, data.status)
    if data.severity:
        inc.severity = data.severity
    if data.assigned_to is not None:
        inc.assigned_to = data.assigned_to
    if data.resolution:
        inc.resolution = data.resolution

    db.commit()
    _touch_stats()
    db.refresh(inc)

    # Dalga C1: resolved + çözüm metni → runbook adayı (Chroma'ya otomatik yazılmaz)
    if (data.status and data.status in ("resolved", "closed")) or data.resolution:
        try:
            from app.services.runbook_candidates import maybe_create_runbook_candidate
            maybe_create_runbook_candidate(db, inc)
        except Exception as e:
            logger.debug("Runbook candidate atlandı: %s", e)

    return {"success": True, "message": "Incident güncellendi", "resolved_events": resolved_events}


@router.get("/{incident_id}")
async def get_incident(incident_id: int, db: Session = Depends(get_db)):
    """Incident detayını getir (ilgili eventler dahil)"""
    inc = db.query(Incident).filter(Incident.id == incident_id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident bulunamadı")

    server_names = []
    if inc.affected_servers:
        servers = db.query(Server).filter(Server.id.in_(inc.affected_servers)).all()
        server_names = [{"id": s.id, "name": s.name, "ip": s.ip_address, "status": s.status} for s in servers]

    related_event_details = []
    if inc.related_events:
        events = db.query(SystemEvent).filter(SystemEvent.id.in_(inc.related_events)).order_by(desc(SystemEvent.created_at)).all()
        related_event_details = [{
            "id": e.id, "title": e.title, "severity": e.severity,
            "event_type": e.event_type, "source": e.source,
            "resolved": e.resolved, "is_acknowledged": e.is_acknowledged,
            "created_at": e.created_at.isoformat() if e.created_at else None
        } for e in events]

    return {
        "id": inc.id,
        "title": inc.title,
        "description": inc.description,
        "severity": inc.severity,
        "status": inc.status,
        "source": inc.source,
        "affected_servers": inc.affected_servers or [],
        "affected_server_details": server_names,
        "related_events": inc.related_events or [],
        "related_event_details": related_event_details,
        "root_cause": inc.root_cause,
        "resolution": inc.resolution,
        "rca_result": inc.rca_result,
        "assigned_to": inc.assigned_to,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
        "updated_at": inc.updated_at.isoformat() if inc.updated_at else None,
        "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None
    }


@router.delete("/{incident_id}")
async def delete_incident(incident_id: int, db: Session = Depends(get_db)):
    """Incident sil"""
    inc = db.query(Incident).filter(Incident.id == incident_id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident bulunamadı")
    db.delete(inc)
    db.commit()
    _touch_stats()
    return {"success": True, "message": "Incident silindi"}


@router.post("/{incident_id}/link-events")
async def link_events(incident_id: int, event_ids: List[int], db: Session = Depends(get_db)):
    """Event'leri incident'a bağla"""
    inc = db.query(Incident).filter(Incident.id == incident_id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident bulunamadı")
    existing = set(inc.related_events or [])
    existing.update(event_ids)
    inc.related_events = list(existing)
    db.commit()
    return {"success": True, "related_events": inc.related_events}


@router.post("/{incident_id}/rca")
async def run_rca(incident_id: int, db: Session = Depends(get_db),
                  user: "User" = Depends(get_current_user)):
    """AI ile Root Cause Analysis çalıştır"""
    inc = db.query(Incident).filter(Incident.id == incident_id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident bulunamadı")
    from app.services.audit import record_audit
    record_audit(db, category="rca", action="rca.run", actor=user,
                 target_type="incident", target_id=incident_id,
                 summary=f"Manuel RCA çalıştırıldı: {inc.title}"[:200])

    # İlgili event'leri topla
    event_details = []
    if inc.related_events:
        events = db.query(SystemEvent).filter(SystemEvent.id.in_(inc.related_events)).all()
        for e in events:
            event_details.append(f"- [{e.severity}] {e.title}: {e.description or 'N/A'}")

    # İlgili sunucu bilgilerini topla
    server_details = []
    if inc.affected_servers:
        servers = db.query(Server).filter(Server.id.in_(inc.affected_servers)).all()
        for s in servers:
            server_details.append(f"- {s.name} ({s.ip_address}): {s.status}, OS: {s.os_type}, CPU: {s.cpu_cores}, RAM: {s.memory_gb}GB")

    prompt = f"""Sen bir AIOps Root Cause Analysis (Kök Neden Analizi) uzmanısın.
Aşağıdaki incident için kök neden analizi yap. TÜRKÇE yanıt ver.

INCIDENT: {inc.title}
Açıklama: {inc.description or 'Yok'}
Önem Derecesi: {inc.severity}

İLGİLİ EVENTLER:
{chr(10).join(event_details) if event_details else 'Henüz ilgili event yok'}

ETKİLENEN SUNUCULAR:
{chr(10).join(server_details) if server_details else 'Bilgi yok'}

Lütfen şu formatta analiz yap:
1. OLASI KÖK NEDEN: En olası kök nedeni belirt
2. ETKİ ANALİZİ: Hangi sistemler etkileniyor
3. ÇÖZÜM ÖNERİLERİ: Adım adım çözüm öner
4. ÖNLEME: Gelecekte nasıl önlenebilir"""

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            data = await llm_gateway.generate_async(client, model=get_active_model(db), prompt=prompt)
            if not data.get("error"):
                rca_text = data.get("response", "Analiz yapılamadı")
                from app.services.rca_store import store_incident_rca
                store_incident_rca(
                    inc,
                    {
                        "analysis": rca_text,
                        "model": get_active_model(db),
                        "analyzed_at": datetime.utcnow().isoformat(),
                        "auto": False,
                    },
                )
                inc.root_cause = rca_text[:500]  # İlk 500 karakter özet
                db.commit()
                return {"success": True, "rca": inc.rca_result}
            else:
                raise HTTPException(status_code=502, detail="AI servisi yanıt veremedi")
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="AI servisine (Ollama) bağlanılamadı")
    except Exception as e:
        logger.error(f"RCA error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
