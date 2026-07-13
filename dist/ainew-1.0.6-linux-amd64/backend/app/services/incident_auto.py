"""
Auto-Incident Service — critical/emergency eventlarda otomatik incident açar.

Kurallar:
- Severity "critical" veya "emergency" olan yeni eventlerde tetiklenir.
- Aynı sunucu + event_type kombinasyonu için son 2 saat içinde açık bir incident
  varsa o incident'a event eklenir (yeni açılmaz).
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.models.event import Incident, SystemEvent

logger = logging.getLogger(__name__)

AUTO_SEVERITIES = {"critical", "emergency"}
DEDUP_WINDOW_HOURS = 2


def auto_create_or_link_incident(db: Session, event: SystemEvent) -> Optional[int]:
    """
    Verilen event için gerekirse otomatik incident oluşturur veya mevcut açık
    incident'a bağlar. Incident ID döner, işlem yapılmadıysa None döner.
    """
    if event.severity not in AUTO_SEVERITIES:
        return None

    server_id = event.server_id
    event_type = event.event_type
    since = datetime.utcnow() - timedelta(hours=DEDUP_WINDOW_HOURS)

    # Aynı sunucu + event_type için son 2 saat içinde açık incident var mı?
    existing = (
        db.query(Incident)
        .filter(
            Incident.status.in_(["open", "investigating"]),
            Incident.created_at >= since,
        )
        .all()
    )

    matched: Optional[Incident] = None
    expected_source = f"auto_{event_type}"
    for inc in existing:
        inc_source = inc.source or ""
        if inc_source != expected_source:
            continue
        affected = inc.affected_servers or []
        if server_id is not None:
            same_server = (server_id in affected) or (not affected)
        else:
            same_server = True
        if same_server:
            matched = inc
            break

    if matched:
        related = list(set(matched.related_events or []) | {event.id})
        affected = list(set(matched.affected_servers or []))
        if server_id and server_id not in affected:
            affected.append(server_id)
        matched.related_events = related
        matched.affected_servers = affected
        db.commit()
        logger.info(
            f"[AutoIncident] Event #{event.id} ({event.severity}) mevcut "
            f"incident #{matched.id} '{matched.title}' uzerine eklendi"
        )
        return matched.id

    # Yeni incident oluştur
    server_name = ""
    if server_id:
        from app.models.server import Server
        srv = db.query(Server).filter(Server.id == server_id).first()
        server_name = f" [{srv.name}]" if srv else f" [#{server_id}]"

    sev_icon = "🔴" if event.severity == "emergency" else "🚨"
    title = f"{sev_icon} {event.title[:120]}{server_name}"

    incident = Incident(
        title=title,
        description=(
            f"Otomatik olusturuldu — {event.severity.upper()} seviyeli event tetikledi.\n\n"
            f"Ilk event: {event.title}\n"
            f"Kaynak: {event.source or 'bilinmiyor'}\n"
            f"Tip: {event_type}"
        ),
        severity="critical",
        status="open",
        source=f"auto_{event_type}",
        affected_servers=[server_id] if server_id else [],
        related_events=[event.id],
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    logger.warning(
        f"[AutoIncident] Yeni incident #{incident.id} otomatik acildi: "
        f"'{incident.title}' (event #{event.id}, {event.severity})"
    )
    return incident.id
