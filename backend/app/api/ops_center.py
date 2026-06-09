"""
Ops Command Center API — "Şu an ne yapmalıyım?" sorusuna tek endpoint'te yanıt.

GET /ops/command-center
  Açık event'leri severity + storm bilgisiyle gruplar,
  üç katmana ayırır: red (hemen bak), yellow (izle), green (ok).
  Her gruba inline aksiyonlar ekler.

GET /ops/summary
  Hafif özet — sadece sayılar, header/banner için.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.event import SystemEvent, Incident
from app.models.server import Server

logger = logging.getLogger(__name__)
router = APIRouter()

SEV_RANK = {"emergency": 4, "critical": 3, "warning": 2, "info": 1}

# Kaç dakika içindeki eventleri "aktif" sayalım
ACTIVE_WINDOW_HOURS = 24


def _server_map(db: Session) -> Dict[int, Dict[str, str]]:
    servers = db.query(Server.id, Server.name, Server.hostname, Server.ip_address,
                        Server.tier).all()  # type: ignore[attr-defined]
    return {
        s.id: {
            "name": s.name,
            "hostname": s.hostname or "",
            "ip": s.ip_address or "",
            "tier": getattr(s, "tier", "unknown") or "unknown",
        }
        for s in servers
    }


_SMAP_REF: Dict[int, Dict[str, str]] = {}


def _build_item(
    group_type: str,
    events: List[SystemEvent],
    server_info: Optional[Dict[str, str]],
    metric: str,
    storm_incident_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Tek bir aksiyon öğesi oluşturur."""
    max_sev = max(events, key=lambda e: SEV_RANK.get(e.severity, 0)).severity
    first_event = min(events, key=lambda e: e.created_at or datetime.min)
    last_event = max(events, key=lambda e: e.last_seen or datetime.min)

    actions = []
    if group_type == "storm":
        actions = ["rca", "suppress_all", "acknowledge_all"]
    elif max_sev == "critical":
        actions = ["rca", "mark_known", "acknowledge"]
    else:
        actions = ["mark_known", "acknowledge", "suppress"]

    sample_value = None
    if events:
        raw = events[0].raw_data or {}
        sample_value = raw.get("current_value")

    # Storm'da tüm etkilenen sunucuları listele
    affected_servers = None
    if group_type == "storm":
        seen_ids: set = set()
        affected_servers = []
        for ev in events:
            if ev.server_id and ev.server_id not in seen_ids:
                seen_ids.add(ev.server_id)
                # server_info parametresi storm için None olarak gelir,
                # smap'ten kendimiz bakıyoruz
                si = _SMAP_REF.get(ev.server_id) if _SMAP_REF else None
                affected_servers.append({
                    "id": ev.server_id,
                    "name": si["name"] if si else f"server#{ev.server_id}",
                    "ip": si["ip"] if si else "",
                    "tier": si["tier"] if si else "unknown",
                })

    return {
        "type": group_type,             # "storm" | "single" | "group"
        "metric": metric,
        "severity": max_sev,
        "event_count": len(events),
        "event_ids": [e.id for e in events],
        "server_count": len({e.server_id for e in events}),
        "server": server_info,
        "affected_servers": affected_servers,   # storm'da dolu, diğerlerinde None
        "storm_incident_id": storm_incident_id,
        "first_seen": first_event.created_at.isoformat() if first_event.created_at else None,
        "last_seen": last_event.last_seen.isoformat() if last_event.last_seen else None,
        "occurrence_count": sum(e.occurrence_count or 1 for e in events),
        "current_value": sample_value,
        "actions": actions,
    }


@router.get("/command-center")
async def command_center(db: Session = Depends(get_db)):
    """
    Açık, çözülmemiş event'leri üç kategoriye ayırır:
      red    → severity critical/emergency veya fırtına → hemen bak
      yellow → severity warning, tekrarlayan → izle
      green_count → bastırılmış/bilinen eventlerin sayısı
    """
    global _SMAP_REF
    since = datetime.utcnow() - timedelta(hours=ACTIVE_WINDOW_HOURS)
    smap = _server_map(db)
    _SMAP_REF = smap

    # Tüm açık, bilinmeyen, onaylanmamış eventler
    # Log entry'ler için minimum tekrar filtresi uygula
    from sqlalchemy import or_, and_
    events: List[SystemEvent] = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.resolved == False,        # noqa: E712
            SystemEvent.is_known == False,        # noqa: E712
            SystemEvent.is_acknowledged == False, # noqa: E712
            SystemEvent.last_seen >= since,
            or_(
                # Metrik anomaliler: her zaman göster
                SystemEvent.event_type != "log_entry",
                # Log entry: critical için min 3x, warning için min 2x
                and_(
                    SystemEvent.event_type == "log_entry",
                    SystemEvent.severity == "critical",
                    SystemEvent.occurrence_count >= 3,
                ),
                and_(
                    SystemEvent.event_type == "log_entry",
                    SystemEvent.severity == "warning",
                    SystemEvent.occurrence_count >= 2,
                ),
            ),
        )
        .order_by(SystemEvent.last_seen.desc())
        .limit(2000)
        .all()
    )

    # Bastırılan / bilinen / onaylanmış / çözülmüş → "Kontrol Altında"
    green_count: int = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.last_seen >= since,
            (
                (SystemEvent.resolved == True) |     # noqa: E712
                (SystemEvent.is_known == True) |     # noqa: E712
                (SystemEvent.is_acknowledged == True) # noqa: E712
            ),
        )
        .count()
    )

    # Açık storm incident'ları
    storm_incidents: List[Incident] = (
        db.query(Incident)
        .filter(
            Incident.source == "storm_detector",
            Incident.status != "resolved",
        )
        .all()
    )
    storm_event_ids: set = set()
    storm_items: List[Dict[str, Any]] = []
    for inc in storm_incidents:
        eids = set(inc.related_events or [])
        storm_event_ids.update(eids)
        related_evs = [e for e in events if e.id in eids]
        if not related_evs:
            continue
        # Metrik adını başlıktan çıkar
        metric_hint = inc.title.replace("⚡ ALARM FIRTINASI:", "").split("—")[0].strip()
        storm_items.append(_build_item(
            "storm", related_evs, None, metric_hint, storm_incident_id=inc.id
        ))

    # Storm dışı eventleri sunucu+gruplama_anahtarı bazında grupla
    by_server_metric: Dict[tuple, List[SystemEvent]] = defaultdict(list)
    for ev in events:
        if ev.id in storm_event_ids:
            continue

        if ev.event_type == "metric_anomaly":
            # Metrik anomaliler → metrik adıyla grupla
            group_key = (ev.raw_data or {}).get("metric") or ev.event_type
        else:
            # Log entry ve diğerleri → kategori veya title'ın ilk 80 karakteriyle grupla
            category = (ev.raw_data or {}).get("category") or ""
            if category and category != "General":
                group_key = f"log:{category}"
            elif ev.title and ev.title != "Log Entry":
                # Başlıktan [] tekrar sayaçlarını temizle, ilk 80 karakter
                import re
                clean = re.sub(r'\s*\[x\d+\]', '', ev.title).strip()
                group_key = clean[:80] if clean else ev.event_type
            else:
                group_key = ev.event_type or "unknown"

        by_server_metric[(ev.server_id, group_key)].append(ev)

    red_items: List[Dict[str, Any]] = []
    yellow_items: List[Dict[str, Any]] = []

    for (server_id, metric), evs in by_server_metric.items():
        max_sev = max(evs, key=lambda e: SEV_RANK.get(e.severity, 0)).severity
        sinfo = smap.get(server_id) if server_id else None

        # Production tier kritik → red; staging warning → yellow
        tier = (sinfo or {}).get("tier", "unknown")

        # Basit gruplama: aynı sunucuda birden fazla event varsa "group", yoksa "single"
        gtype = "group" if len(evs) > 1 else "single"
        item = _build_item(gtype, evs, sinfo, metric)

        if max_sev in ("critical", "emergency"):
            red_items.append(item)
        elif max_sev == "warning":
            # Production'da warning de önemli, staging'de daha az acil
            if tier == "production":
                red_items.append(item)
            else:
                yellow_items.append(item)

    # Storm item'ları red başına ekle
    red_items = storm_items + red_items

    # Severity → son görülme sırasıyla sırala
    def sort_key(item: Dict[str, Any]):
        return (
            -SEV_RANK.get(item["severity"], 0),
            -(item["server_count"] or 1),
        )

    red_items.sort(key=sort_key)
    yellow_items.sort(key=sort_key)

    return {
        "red": red_items[:50],          # max 50 kritik göster
        "yellow": yellow_items[:100],
        "red_count": len(red_items),
        "yellow_count": len(yellow_items),
        "green_count": green_count,
        "storm_count": len(storm_items),
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/summary")
async def ops_summary(db: Session = Depends(get_db)):
    """
    Hafif özet — sadece sayılar (navbar badge, dashboard kart).
    """
    since = datetime.utcnow() - timedelta(hours=24)
    critical = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.resolved == False,  # noqa: E712
            SystemEvent.is_known == False,  # noqa: E712
            SystemEvent.severity.in_(["critical", "emergency"]),
            SystemEvent.last_seen >= since,
        )
        .count()
    )
    warning = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.resolved == False,  # noqa: E712
            SystemEvent.is_known == False,  # noqa: E712
            SystemEvent.severity == "warning",
            SystemEvent.last_seen >= since,
        )
        .count()
    )
    open_incidents = (
        db.query(Incident)
        .filter(Incident.status.in_(["open", "investigating"]))
        .count()
    )
    return {
        "critical": critical,
        "warning": warning,
        "open_incidents": open_incidents,
        "action_needed": critical > 0,
    }
