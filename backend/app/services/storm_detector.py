"""
Storm Detector — Alarm Fırtınası Tespiti ve Eritme.

Senaryo: 500 sunucu aynı anda "CPU yüksek" bildiriyor.
Sonuç: 500 event yerine 1 "storm incident" + bireysel eventler warning'e düşürülür.

Storm kriteri:
  Aynı metric_name için son STORM_WINDOW_MINUTES içinde
  STORM_THRESHOLD_SERVERS farklı sunucu event oluşturduysa → STORM.

Tier tabanlı filtreleme:
  production  → tüm severity geçer
  staging     → max warning (critical → warning)
  development → max info (warning/critical → info) veya tamamen bastır
  unknown     → production gibi davranır (güvenli taraf)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.event import SystemEvent, Incident
from app.models.server import Server

logger = logging.getLogger(__name__)

# ── Sabitler ──────────────────────────────────────────────────────────────────
STORM_WINDOW_MINUTES = 10         # Kaç dakika içinde
STORM_THRESHOLD_SERVERS = 5       # Kaç farklı sunucu
STORM_COOLDOWN_HOURS = 1          # Aynı metrik için storm incident tekrar oluşturma süresi

TIER_MAX_SEVERITY: Dict[str, Optional[str]] = {
    "production": None,            # Kısıtlama yok
    "staging": "warning",          # Max warning
    "development": "info",         # Max info
    "unknown": None,               # Production gibi
}

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2, "emergency": 3}
RANK_TO_SEV = {v: k for k, v in SEVERITY_RANK.items()}


# ── Tier bazlı severity filtresi ─────────────────────────────────────────────

def apply_tier_filter(
    db: Session,
    server_id: Optional[int],
    severity: str,
) -> str:
    """
    Sunucunun tier'ına göre severity'yi kısıtlar.
    server_id yoksa veya tier bilinmiyorsa değiştirmez.
    """
    if not server_id:
        return severity

    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        return severity

    tier = getattr(server, "tier", "unknown") or "unknown"
    max_sev = TIER_MAX_SEVERITY.get(tier)

    if max_sev is None:
        return severity  # kısıtlama yok

    current_rank = SEVERITY_RANK.get(severity, 0)
    max_rank = SEVERITY_RANK.get(max_sev, 0)

    if current_rank > max_rank:
        logger.debug(
            f"[Storm] Tier '{tier}' downgrade: {severity}→{max_sev} server={server_id}"
        )
        return max_sev

    return severity


# ── Storm tespiti ─────────────────────────────────────────────────────────────

def detect_storm(
    db: Session,
    metric_name: str,
    window_minutes: int = STORM_WINDOW_MINUTES,
    threshold_servers: int = STORM_THRESHOLD_SERVERS,
) -> Optional[Dict[str, Any]]:
    """
    Son window_minutes içinde threshold_servers'dan fazla sunucu aynı metriği
    bildirdiyse storm bilgisi döndürür, yoksa None.
    """
    since = datetime.utcnow() - timedelta(minutes=window_minutes)
    events = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.event_type == "metric_anomaly",
            SystemEvent.created_at >= since,
            SystemEvent.title.ilike(f"%{metric_name}%"),
        )
        .all()
    )

    server_ids = {e.server_id for e in events if e.server_id}
    if len(server_ids) < threshold_servers:
        return None

    severities = [e.severity for e in events]
    max_sev = max(severities, key=lambda s: SEVERITY_RANK.get(s, 0), default="warning")

    return {
        "metric": metric_name,
        "server_count": len(server_ids),
        "event_count": len(events),
        "max_severity": max_sev,
        "server_ids": list(server_ids),
        "event_ids": [e.id for e in events],
        "since": since.isoformat(),
    }


def get_or_create_storm_incident(
    db: Session,
    storm: Dict[str, Any],
) -> Optional[int]:
    """
    Storm için incident oluşturur. Son STORM_COOLDOWN_HOURS içinde aynı
    metrik için storm incident varsa yenisini açmaz.
    """
    metric = storm["metric"]
    cooldown_since = datetime.utcnow() - timedelta(hours=STORM_COOLDOWN_HOURS)

    existing = (
        db.query(Incident)
        .filter(
            Incident.source == "storm_detector",
            Incident.title.ilike(f"%{metric}%"),
            Incident.created_at >= cooldown_since,
            Incident.status != "resolved",
        )
        .first()
    )
    if existing:
        # Mevcut storm incident'ı güncelle
        existing.affected_servers = list(set(
            (existing.affected_servers or []) + storm["server_ids"]
        ))
        existing.related_events = list(set(
            (existing.related_events or []) + storm["event_ids"]
        ))
        db.commit()
        logger.info(
            f"[Storm] Mevcut incident #{existing.id} güncellendi: "
            f"{storm['server_count']} sunucu, metrik={metric}"
        )
        return existing.id

    incident = Incident(
        title=f"⚡ ALARM FIRTINASI: {metric} — {storm['server_count']} sunucu",
        description=(
            f"Son {STORM_WINDOW_MINUTES} dakikada {storm['server_count']} farklı sunucu "
            f"'{metric}' anomalisi bildirdi.\n"
            f"Toplam event: {storm['event_count']}\n"
            f"Sunucular: {', '.join(str(s) for s in storm['server_ids'][:20])}"
            + ("..." if len(storm['server_ids']) > 20 else "")
        ),
        severity=storm["max_severity"],
        status="open",
        source="storm_detector",
        affected_servers=storm["server_ids"],
        related_events=storm["event_ids"],
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)

    logger.warning(
        f"[Storm] YENİ FIRTINA incident #{incident.id}: "
        f"metric={metric} servers={storm['server_count']} events={storm['event_count']}"
    )
    return incident.id


def check_and_handle_storm(
    db: Session,
    metric_name: str,
    new_event: SystemEvent,
) -> bool:
    """
    Yeni event storm tetikliyor mu kontrol eder.
    Storm varsa incident oluşturur, event'i warning'e düşürür.
    Returns True if storm was detected.
    """
    storm = detect_storm(db, metric_name)
    if not storm:
        return False

    # Storm incident oluştur
    get_or_create_storm_incident(db, storm)

    # Bireysel event'i warning'e düşür (storm tek incident'ta)
    if new_event.severity == "critical":
        new_event.severity = "warning"
        if new_event.raw_data is None:
            new_event.raw_data = {}
        new_event.raw_data = {**new_event.raw_data, "storm_detected": True, "storm_servers": storm["server_count"]}
        logger.debug(
            f"[Storm] Event #{new_event.id} critical→warning (storm: {storm['server_count']} sunucu)"
        )

    return True


# ── Auto TTL ─────────────────────────────────────────────────────────────────

TTL_HOURS: Dict[str, int] = {
    "emergency": 48,
    "critical": 24,
    "warning": 8,
    "info": 2,
}


def auto_resolve_by_ttl(db: Session) -> int:
    """
    Severity bazlı TTL ile eski eventleri otomatik kapat.
    last_seen'i TTL_HOURS'dan eski ve hâlâ açık olanları çözer.
    """
    resolved_count = 0
    now = datetime.utcnow()

    for severity, hours in TTL_HOURS.items():
        cutoff = now - timedelta(hours=hours)
        stale = (
            db.query(SystemEvent)
            .filter(
                SystemEvent.severity == severity,
                SystemEvent.resolved == False,  # noqa: E712
                SystemEvent.last_seen <= cutoff,
                SystemEvent.event_type == "metric_anomaly",
            )
            .all()
        )
        for ev in stale:
            ev.resolved = True
            ev.resolved_at = now
            resolved_count += 1

    if resolved_count:
        db.commit()
        logger.info(f"[Storm/TTL] {resolved_count} event TTL ile otomatik kapatıldı")

    return resolved_count


# ── Günlük Özet ───────────────────────────────────────────────────────────────

def generate_daily_digest(db: Session, date: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Belirtilen gün (varsayılan: bugün) için alarm özeti üretir.

    Dashboard kartı ve sabah bildirimi için kullanılır.
    """
    if date is None:
        date = datetime.utcnow()

    day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    events = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.created_at >= day_start,
            SystemEvent.created_at < day_end,
        )
        .all()
    )

    incidents = (
        db.query(Incident)
        .filter(
            Incident.created_at >= day_start,
            Incident.created_at < day_end,
        )
        .all()
    )

    # Metrik bazında sayım
    metric_counts: Dict[str, int] = defaultdict(int)
    server_ids: set = set()
    severity_counts: Dict[str, int] = defaultdict(int)

    for ev in events:
        metric = (ev.raw_data or {}).get("metric") or "unknown"
        metric_counts[metric] += 1
        if ev.server_id:
            server_ids.add(ev.server_id)
        severity_counts[ev.severity] += 1

    top_metrics = sorted(metric_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Kritik ve çözümsüz eventler
    unresolved_critical = [
        {
            "id": ev.id,
            "title": ev.title,
            "server_id": ev.server_id,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
        for ev in events
        if ev.severity in ("critical", "emergency") and not ev.resolved
    ][:10]

    storm_incidents = [i for i in incidents if i.source == "storm_detector"]

    return {
        "date": day_start.date().isoformat(),
        "total_events": len(events),
        "severity_breakdown": dict(severity_counts),
        "affected_servers": len(server_ids),
        "new_incidents": len(incidents),
        "storm_incidents": len(storm_incidents),
        "resolved_count": sum(1 for e in events if e.resolved),
        "unresolved_critical_count": len([e for e in events if e.severity in ("critical", "emergency") and not e.resolved]),
        "top_metrics": [{"metric": m, "count": c} for m, c in top_metrics],
        "unresolved_critical_sample": unresolved_critical,
        "action_required": len(unresolved_critical) > 0 or len(storm_incidents) > 0,
        "noise_ratio": round(
            sum(1 for e in events if e.is_known or e.resolved) / len(events) * 100
            if events else 0,
            1
        ),
        "generated_at": datetime.utcnow().isoformat(),
    }
