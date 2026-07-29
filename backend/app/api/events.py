"""
Events API - AIOps Event Management
"""
import logging
import re as _re
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional, List
from pydantic import BaseModel
from sqlalchemy import desc, func
from app.core.database import get_db
from app.models.event import SystemEvent
from app.models.server import Server
from app.services.incident_auto import auto_create_or_link_incident
from app.services.platform_scope import apply_platform_filter, VALID_PLATFORMS
from app.services.event_filters import apply_actionable_event_filters, apply_hide_routine_virt

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


def _event_display_server_name(e: SystemEvent, server_map: Optional[dict] = None) -> Optional[str]:
    """SUNUCU kolonu: bağlı sunucu → entity/host_name → başlıktan VM → platform/hypervisor."""
    if e.server_id and server_map is not None:
        name = server_map.get(e.server_id)
        if name:
            return name
    raw = e.raw_data or {}
    mor_re = _re.compile(r"^(vm|host|domain|alarm|group|resgroup|datastore|folder)-\d+$", _re.I)
    for key in ("entity_name", "vm_name", "host_name"):
        val = raw.get(key)
        if val and str(val).strip() and not mor_re.match(str(val).strip()):
            return str(val).strip()
    title = e.title or ""
    m = _re.search(r"Alarm\s+'[^']*'\s+on\s+(\S+)", title, _re.I)
    if m:
        return m.group(1).rstrip(".,;:")
    m = _re.search(r"\bon\s+([A-Za-z0-9][\w.:\-]+)", title, _re.I)
    if m:
        cand = m.group(1).rstrip(".,;:")
        if cand and not mor_re.match(cand):
            return cand
    for key in ("platform_label", "hypervisor_name"):
        val = raw.get(key)
        if val and str(val).strip():
            return str(val).strip()
    if (e.source or "").startswith("vcenter_") or (e.event_type or "").startswith("vcenter_"):
        return "vCenter"
    return None


def _event_to_dict(e: SystemEvent, server_name: Optional[str] = None) -> dict:
    if not server_name:
        server_name = _event_display_server_name(e)
    last_seen = e.last_seen or e.created_at
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
        "occurrence_count": getattr(e, "occurrence_count", None) or 1,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "first_seen": e.created_at.isoformat() if e.created_at else None,
        "last_seen": last_seen.isoformat() if last_seen else None,
    }


@router.get("/stats")
async def event_stats(
    platform: Optional[str] = None,
    show_routine: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """Event istatistikleri — kritik/uyarı/acil sayaçları Komuta Merkezi ile tutarlı."""
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(hours=24)

    q = db.query(SystemEvent)
    q = apply_platform_filter(q, platform, db)
    if platform == "virt" and not show_routine:
        q = apply_hide_routine_virt(q, show_routine=False)

    total = q.count()
    unresolved = q.filter(SystemEvent.resolved == False).count()  # noqa: E712
    acknowledged = q.filter(SystemEvent.is_acknowledged == True, SystemEvent.resolved == False).count()  # noqa: E712
    known = q.filter(SystemEvent.is_known == True, SystemEvent.resolved == False).count()  # noqa: E712

    actionable = apply_platform_filter(
        apply_actionable_event_filters(
            db.query(SystemEvent).filter(SystemEvent.last_seen >= since)
        ),
        platform,
        db,
    )
    if platform == "virt" and not show_routine:
        actionable = apply_hide_routine_virt(actionable, show_routine=False)

    critical = actionable.filter(SystemEvent.severity == "critical").count()
    warning = actionable.filter(SystemEvent.severity == "warning").count()
    emergency = actionable.filter(SystemEvent.severity == "emergency").count()
    # Navbar / Komuta Merkezi ile aynı: critical rozeti = critical + emergency
    critical_badge = critical + emergency

    return {
        "total": total,
        "unresolved": unresolved,
        "critical": critical_badge,
        "critical_only": critical,
        "warning": warning,
        "emergency": emergency,
        "actionable_total": critical_badge + warning,
        "acknowledged": acknowledged,
        "known": known
    }


@router.get("/types")
async def event_types(
    platform: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Mevcut event tiplerini listele (platform verilirse yalnızca o platformdaki eventlerden)."""
    from sqlalchemy import distinct
    q = db.query(distinct(SystemEvent.event_type))
    # distinct + filter: SystemEvent üzerinden platform kapsamı
    q = apply_platform_filter(q, platform, db)
    types = q.all()
    return sorted(t[0] for t in types if t[0])


@router.get("/")
async def list_events(
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
    server_id: Optional[int] = None,
    resolved: Optional[bool] = None,
    search: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    known: Optional[bool] = None,
    online_only: Optional[bool] = None,
    platform: Optional[str] = None,
    show_routine: bool = Query(default=False),
    limit: int = Query(default=50, le=500),
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Event'leri listele (filtreleme destekli)"""
    q = db.query(SystemEvent)
    q = apply_platform_filter(q, platform, db)
    if platform == "virt" and not show_routine:
        q = apply_hide_routine_virt(q, show_routine=False)
    if severity:
        sevs = [s.strip() for s in severity.split(",") if s.strip()]
        if len(sevs) == 1:
            q = q.filter(SystemEvent.severity == sevs[0])
        elif sevs:
            q = q.filter(SystemEvent.severity.in_(sevs))
    if event_type:
        q = q.filter(SystemEvent.event_type == event_type)
    if server_id:
        q = q.filter(SystemEvent.server_id == server_id)
    if resolved is not None:
        q = q.filter(SystemEvent.resolved == resolved)
    if acknowledged is not None:
        q = q.filter(SystemEvent.is_acknowledged == acknowledged)
    if known is not None:
        q = q.filter(SystemEvent.is_known == known)
    if search:
        # Başlık VEYA sunucu adında ara
        from sqlalchemy import or_
        matching_server_ids = [
            s.id for s in db.query(Server.id).filter(Server.name.ilike(f"%{search}%")).all()
        ]
        conditions = [SystemEvent.title.ilike(f"%{search}%")]
        if matching_server_ids:
            conditions.append(SystemEvent.server_id.in_(matching_server_ids))
        q = q.filter(or_(*conditions))
    if online_only:
        # OFFLINE durumdaki sunucuların eventlerini hariç tut
        offline_ids = [
            s.id for s in db.query(Server.id).filter(Server.status == 'OFFLINE').all()
        ]
        if offline_ids:
            q = q.filter(~SystemEvent.server_id.in_(offline_ids))

    total = q.count()
    events = (
        q.order_by(desc(SystemEvent.last_seen), desc(SystemEvent.created_at))
        .offset(offset).limit(limit).all()
    )

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
        elif data.action == "unacknowledge" and event.is_acknowledged:
            event.is_acknowledged = False
            event.acknowledged_at = None
            count += 1
        elif data.action == "unknown" and getattr(event, "is_known", False):
            event.is_known = False
            event.known_at = None
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


@router.post("/{event_id}/unacknowledge")
async def unacknowledge_event(event_id: int, db: Session = Depends(get_db)):
    """Onayı kaldır — event tekrar Komuta Merkezi actionable listesine döner."""
    event = db.query(SystemEvent).filter(SystemEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event bulunamadı")
    event.is_acknowledged = False
    event.acknowledged_at = None
    db.commit()
    return {"success": True, "message": "Onay kaldırıldı — event yeniden aktif"}


@router.post("/{event_id}/unknown")
async def unmark_event_known(event_id: int, db: Session = Depends(get_db)):
    """Bilinen işaretini kaldır."""
    event = db.query(SystemEvent).filter(SystemEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event bulunamadı")
    event.is_known = False
    event.known_at = None
    db.commit()
    return {"success": True, "message": "Bilinen işareti kaldırıldı"}


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
    known: Optional[bool] = None,
    exclude_known: bool = Query(default=True),  # Bilinen eventleri varsayılan olarak gizle
    platform: Optional[str] = None,
    show_routine: bool = Query(default=False),
    limit: int = Query(default=50, le=100),
    offset: int = 0,
    sort_by: str = Query(default="latest_created_at"),
    sort_dir: str = Query(default="desc"),
    db: Session = Depends(get_db),
):
    """Event'leri normalize baslik + (event_type, severity, server_id) ile grupla.
    last_seen alanini 'Son Olusum' icin kullanir. Tum gruplara gore server-side sort."""
    q = db.query(SystemEvent)
    q = apply_platform_filter(q, platform, db)
    if platform == "virt" and not show_routine:
        q = apply_hide_routine_virt(q, show_routine=False)
    if severity:
        sevs = [s.strip() for s in severity.split(",") if s.strip()]
        if len(sevs) == 1:
            q = q.filter(SystemEvent.severity == sevs[0])
        elif sevs:
            q = q.filter(SystemEvent.severity.in_(sevs))
    if event_type:
        q = q.filter(SystemEvent.event_type == event_type)
    if server_id:
        q = q.filter(SystemEvent.server_id == server_id)
    if resolved is not None:
        q = q.filter(SystemEvent.resolved == resolved)
    if acknowledged is not None:
        q = q.filter(SystemEvent.is_acknowledged == acknowledged)
    if known is not None:
        q = q.filter(SystemEvent.is_known == known)
        exclude_known = False
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
                "server_name": _event_display_server_name(e, server_map),
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
    only_ai_ready: bool = True,
    platform: Optional[str] = Query(default="linux"),
    db: Session = Depends(get_db),
):
    """Platforma göre log taraması (arka plan + ilerleme).

    Linux/Exadata: varsayılan yalnız AI Ready (only_ai_ready=True).
    HTTP hemen ``job_id`` döner; UI ``GET /servers/bulk-jobs/{job_id}`` ile poll eder.
    """
    import threading
    from app.core.database import ThreadSessionLocal as SessionLocal
    from app.services import bulk_job_tracker as jobs
    from app.services.runtime_settings import get_bool

    plat = (platform or "linux").lower()
    if plat not in VALID_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Geçersiz platform: {platform}")

    # Güvenlik ağı: ayar açıksa Linux/Exadata tarama AI Ready'e zorlanır
    if plat in ("linux", "exadata") and get_bool("log_scan_ai_ready_only"):
        only_ai_ready = True

    titles = {
        "linux": "Linux log taraması",
        "windows": "Windows Event Log taraması",
        "virt": "Sanallaştırma olay sync",
        "exadata": "Exadata log taraması",
    }
    job_id = jobs.create_job(
        f"events_scan_{plat}",
        titles.get(plat, "Log taraması"),
        total=0,
        message="Tarama kuyruğa alındı...",
    )

    def _progress(done: int, total: int, name: str, saved: int) -> None:
        jobs.tick(
            job_id,
            done=done,
            total=total,
            ok_delta=1 if saved > 0 else 0,
            fail_delta=0,
            message=f"{done}/{total} — {name}" + (f" (+{saved})" if saved else ""),
        )

    def _bg() -> None:
        thread_db = SessionLocal()
        try:
            jobs.update_job(job_id, message="Sunucular taranıyor...")
            if plat == "windows":
                from app.services.windows_log_collector import collect_all_windows_logs
                result = collect_all_windows_logs(thread_db, progress_cb=_progress)
            elif plat == "virt":
                from app.services.virt_log_collector import sync_virt_logs_to_db
                jobs.update_job(job_id, percent=20, message="vCenter / hypervisor olayları alınıyor...")
                result = sync_virt_logs_to_db(thread_db)
                # virt sync often returns counts without per-host ticks
                if isinstance(result, dict):
                    tot = int(result.get("total_servers") or result.get("synced") or 1)
                    jobs.tick(job_id, done=tot, total=tot, message="Sync tamamlandı")
            elif plat == "exadata":
                from app.services.log_collector import collect_exadata_servers_logs
                result = collect_exadata_servers_logs(
                    thread_db,
                    only_ai_ready=only_ai_ready,
                    progress_cb=_progress,
                    batch_mode=False,
                )
            else:
                from app.services.log_collector import collect_all_servers_logs
                result = collect_all_servers_logs(
                    thread_db,
                    only_ai_ready=only_ai_ready,
                    progress_cb=_progress,
                    batch_mode=False,
                )

            saved = int((result or {}).get("total_saved") or 0)
            servers = int((result or {}).get("total_servers") or 0)
            with_logs = int((result or {}).get("servers_with_logs") or 0)
            jobs.finish(
                job_id,
                status="done",
                message=(
                    f"Tamamlandı: {saved} yeni event · {with_logs}/{servers} sunucuda log"
                    if servers
                    else "Tarama tamamlandı (adet yok)"
                ),
                result={"success": True, "platform": plat, **(result or {})},
            )
        except Exception as e:
            logger.error(f"Manual scan error ({plat}): {e}", exc_info=True)
            jobs.finish(
                job_id,
                status="error",
                message="Tarama hatası",
                error=str(e),
                result={"success": False, "platform": plat, "error": str(e)},
            )
        finally:
            thread_db.close()

    threading.Thread(target=_bg, daemon=True, name=f"events-scan-{plat}").start()
    return {
        "queued": True,
        "job_id": job_id,
        "success": True,
        "platform": plat,
        "message": "Log taraması arka planda başladı",
    }


@router.get("/coverage")
async def event_server_coverage(
    platform: Optional[str] = Query(default="linux"),
    hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
):
    """AI Ready sunucularda son N saatte event gelen / gelmeyen ayrımı."""
    from app.services.platform_scope import (
        get_linux_module_server_ids,
        get_windows_server_ids,
        get_exadata_server_ids,
    )

    plat = (platform or "linux").lower()
    if plat == "linux":
        ids = set(get_linux_module_server_ids(db))
    elif plat == "windows":
        ids = set(get_windows_server_ids(db))
    elif plat == "exadata":
        ids = set(get_exadata_server_ids(db))
    else:
        return {"with_events": [], "without_events": [], "hours": hours, "platform": plat}

    servers = []
    if ids:
        servers = (
            db.query(Server)
            .filter(Server.id.in_(list(ids)), Server.ai_ready == True)  # noqa: E712
            .order_by(Server.name)
            .all()
        )

    since = datetime.utcnow() - timedelta(hours=hours)
    counts: dict = {}
    if servers:
        counts = dict(
            db.query(SystemEvent.server_id, func.count(SystemEvent.id))
            .filter(
                SystemEvent.server_id.in_([s.id for s in servers]),
                SystemEvent.last_seen >= since,
            )
            .group_by(SystemEvent.server_id)
            .all()
        )

    with_events = []
    without_events = []
    for s in servers:
        row = {
            "id": s.id,
            "name": s.name,
            "ip": s.ip_address,
            "status": s.status,
            "event_count": int(counts.get(s.id) or 0),
        }
        if row["event_count"] > 0:
            with_events.append(row)
        else:
            without_events.append(row)

    return {
        "platform": plat,
        "hours": hours,
        "with_events": with_events,
        "without_events": without_events,
        "with_count": len(with_events),
        "without_count": len(without_events),
    }


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
