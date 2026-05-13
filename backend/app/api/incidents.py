"""
Incidents API - AIOps Incident Management + RCA
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
import httpx
from app.core.database import get_db
from app.core.config import settings, get_active_model
from app.models.event import Incident, SystemEvent
from app.models.server import Server

logger = logging.getLogger(__name__)
router = APIRouter()


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


@router.get("/stats")
async def incident_stats(db: Session = Depends(get_db)):
    """Incident istatistikleri"""
    total = db.query(Incident).count()
    open_count = db.query(Incident).filter(Incident.status == "open").count()
    investigating = db.query(Incident).filter(Incident.status == "investigating").count()
    resolved = db.query(Incident).filter(Incident.status.in_(["resolved", "closed"])).count()
    critical = db.query(Incident).filter(Incident.severity == "critical", Incident.status == "open").count()
    return {
        "total": total,
        "open": open_count,
        "investigating": investigating,
        "resolved": resolved,
        "critical": critical
    }


@router.get("/")
async def list_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Incident'ları listele"""
    q = db.query(Incident)
    if status:
        q = q.filter(Incident.status == status)
    if severity:
        q = q.filter(Incident.severity == severity)
    if search:
        q = q.filter(Incident.title.ilike(f"%{search}%"))

    total = q.count()
    incidents = q.order_by(desc(Incident.created_at)).offset(offset).limit(limit).all()

    result = []
    for inc in incidents:
        # Affected server isimlerini getir
        server_names = []
        if inc.affected_servers:
            servers = db.query(Server).filter(Server.id.in_(inc.affected_servers)).all()
            server_names = [{"id": s.id, "name": s.name, "ip": s.ip_address} for s in servers]

        result.append({
            "id": inc.id,
            "title": inc.title,
            "description": inc.description,
            "severity": inc.severity,
            "status": inc.status,
            "source": inc.source,
            "affected_servers": inc.affected_servers or [],
            "affected_server_details": server_names,
            "related_events": inc.related_events or [],
            "root_cause": inc.root_cause,
            "resolution": inc.resolution,
            "rca_result": inc.rca_result,
            "assigned_to": inc.assigned_to,
            "created_at": inc.created_at.isoformat() if inc.created_at else None,
            "updated_at": inc.updated_at.isoformat() if inc.updated_at else None,
            "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None
        })

    return {"total": total, "incidents": result}


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

    if data.status:
        inc.status = data.status
        if data.status in ("resolved", "closed"):
            inc.resolved_at = datetime.utcnow()
    if data.severity:
        inc.severity = data.severity
    if data.assigned_to is not None:
        inc.assigned_to = data.assigned_to
    if data.resolution:
        inc.resolution = data.resolution

    db.commit()
    db.refresh(inc)
    return {"success": True, "message": "Incident güncellendi"}


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
async def run_rca(incident_id: int, db: Session = Depends(get_db)):
    """AI ile Root Cause Analysis çalıştır"""
    inc = db.query(Incident).filter(Incident.id == incident_id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident bulunamadı")

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
            response = await client.post(
                f"{settings.OLLAMA_URL}/api/generate",
                json={"model": get_active_model(db), "prompt": prompt, "stream": False}
            )
            if response.status_code == 200:
                rca_text = response.json().get("response", "Analiz yapılamadı")
                inc.rca_result = {
                    "analysis": rca_text,
                    "model": get_active_model(db),
                    "analyzed_at": datetime.utcnow().isoformat()
                }
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
