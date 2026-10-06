"""
Auto-Incident — critical/emergency eventlarda otomatik incident açar.

Aynı problem_key (sunucu + olay tipi / normalize başlık) için çözülene kadar
tek açık kayıt tutulur; tekrarlar related_events ve updated_at ile bağlanır.
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.event import Incident, SystemEvent
from app.services.event_grouping import event_problem_key

logger = logging.getLogger(__name__)

AUTO_SEVERITIES = {"critical", "emergency"}


def auto_create_or_link_incident(db: Session, event: SystemEvent) -> Optional[int]:
    """Açık incident varsa bağla; yoksa oluştur. Süre penceresi yok."""
    if event.severity not in AUTO_SEVERITIES:
        return None

    server_id = event.server_id
    event_type = event.event_type
    key = event_problem_key(event)

    matched: Optional[Incident] = (
        db.query(Incident)
        .filter(
            Incident.status.in_(["open", "investigating"]),
            Incident.problem_key == key,
        )
        .order_by(Incident.updated_at.desc().nullslast(), Incident.created_at.desc())
        .first()
    )

    if matched is None:
        expected_source = f"auto_{event_type}"
        existing = (
            db.query(Incident)
            .filter(
                Incident.status.in_(["open", "investigating"]),
                Incident.source == expected_source,
                Incident.problem_key.is_(None),
            )
            .all()
        )
        for inc in existing:
            affected = inc.affected_servers or []
            if server_id is not None:
                same_server = server_id in affected
            else:
                same_server = not affected
            if same_server:
                matched = inc
                break

    if matched:
        related = list(dict.fromkeys((matched.related_events or []) + [event.id]))
        affected = list(matched.affected_servers or [])
        if server_id and server_id not in affected:
            affected.append(server_id)
        matched.related_events = related
        matched.affected_servers = affected
        matched.problem_key = key
        matched.updated_at = datetime.utcnow()
        if event.severity == "emergency":
            matched.severity = "critical"
        db.commit()
        logger.info(
            "[AutoIncident] Event #%s mevcut incident #%s üzerine eklendi (key=%s)",
            event.id, matched.id, key[:80],
        )
        return matched.id

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
        problem_key=key,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    logger.warning(
        "[AutoIncident] Yeni incident #%s: '%s' (event #%s)",
        incident.id, incident.title, event.id,
    )
    return incident.id
