"""
Ops Command Center API — Verimli, sunucu odaklı alarm yönetimi.

GET /ops/command-center
  Sunucu bazlı gruplama: her sunucunun tüm açık alarmları tek kart.
  Storm grupları ayrı blok. Sağlık skoru dahil.

GET /ops/summary
  Hafif özet — navbar badge, dashboard kart.

POST /ops/snooze
  Event veya sunucu bazında belirtilen süre snooze.

GET /ops/health-score
  0-100 altyapı sağlık skoru + kategori breakdown.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.event import SystemEvent, Incident
from app.models.server import Server
from app.services.platform_scope import (
    apply_platform_filter,
    get_linux_server_ids,
    get_windows_server_ids,
)

logger = logging.getLogger(__name__)
router = APIRouter()

SEV_RANK = {"emergency": 4, "critical": 3, "warning": 2, "info": 1}
SEV_SCORE = {"emergency": 25, "critical": 15, "warning": 5, "info": 1}

ACTIVE_WINDOW_HOURS = 24

# ── Snoozed event ID seti (in-memory, process-içi) ───────────────────────────
# Daha kalıcı çözüm için DB column eklenebilir.
_snoozed: Dict[int, datetime] = {}   # event_id → snooze_until


def _is_snoozed(event_id: int) -> bool:
    until = _snoozed.get(event_id)
    if until is None:
        return False
    if datetime.utcnow() >= until:
        del _snoozed[event_id]
        return False
    return True


def _server_map(db: Session) -> Dict[int, Dict[str, Any]]:
    servers = db.query(
        Server.id, Server.name, Server.hostname, Server.ip_address, Server.tier  # type: ignore[attr-defined]
    ).all()
    return {
        s.id: {
            "id": s.id,
            "name": s.name,
            "hostname": s.hostname or "",
            "ip": s.ip_address or "",
            "tier": getattr(s, "tier", "unknown") or "unknown",
        }
        for s in servers
    }


def _active_events(db: Session, since: datetime, platform: Optional[str] = None) -> List[SystemEvent]:
    """Aktif, bilinmeyen, onaylanmamış, snooze'suz eventler."""
    q = db.query(SystemEvent).filter(
        SystemEvent.resolved == False,        # noqa: E712
        SystemEvent.is_known == False,        # noqa: E712
        SystemEvent.is_acknowledged == False, # noqa: E712
        SystemEvent.last_seen >= since,
        or_(
            SystemEvent.event_type != "log_entry",
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
    # apply_platform_filter .filter() çağırır — SQLAlchemy, LIMIT/OFFSET
    # uygulanmış bir Query üzerinde .filter() çağrılmasına izin vermiyor,
    # bu yüzden platform filtresi order_by/limit'ten ÖNCE uygulanmalı.
    q = apply_platform_filter(q, platform, db)
    rows: List[SystemEvent] = q.order_by(SystemEvent.last_seen.desc()).limit(3000).all()
    return [e for e in rows if not _is_snoozed(e.id)]


# ── Sağlık Skoru ─────────────────────────────────────────────────────────────

def _calc_health_score(events: List[SystemEvent], server_count: int) -> Dict[str, Any]:
    """
    0-100 sağlık skoru. 100 = mükemmel, 0 = felaket.
    Formül: max(0, 100 - penalty), penalty = weighted alarm sum / server_count
    """
    if server_count == 0:
        return {"score": 100, "grade": "A", "label": "Veri Yok"}

    penalty = sum(SEV_SCORE.get(e.severity, 1) for e in events)
    # Normalize by server count — büyük altyapıda tek sorun skoru çok düşürmesin
    normalized = min(penalty / max(server_count, 1), 100)
    score = max(0, round(100 - normalized))

    if score >= 90:
        grade, label, color = "A", "Sağlıklı", "green"
    elif score >= 75:
        grade, label, color = "B", "İyi", "blue"
    elif score >= 55:
        grade, label, color = "C", "Dikkat", "yellow"
    elif score >= 35:
        grade, label, color = "D", "Sorunlu", "orange"
    else:
        grade, label, color = "F", "Kritik", "red"

    by_sev: Dict[str, int] = defaultdict(int)
    for e in events:
        by_sev[e.severity] += 1

    return {
        "score": score, "grade": grade, "label": label, "color": color,
        "penalty": round(normalized, 1),
        "severity_breakdown": dict(by_sev),
        "event_count": len(events),
        "server_count": server_count,
    }


# ── Sunucu bazlı gruplama ─────────────────────────────────────────────────────

def _build_server_card(
    server_info: Dict[str, Any],
    events: List[SystemEvent],
    platform: Optional[str] = None,
) -> Dict[str, Any]:
    max_sev = max(events, key=lambda e: SEV_RANK.get(e.severity, 0)).severity
    last_ev = max(events, key=lambda e: e.last_seen or datetime.min)

    # Metrik özetleri
    metrics: List[Dict[str, Any]] = []
    for ev in sorted(events, key=lambda e: -SEV_RANK.get(e.severity, 0))[:8]:
        raw = ev.raw_data or {}
        m = raw.get("metric") or ev.event_type
        val = raw.get("current_value")
        # log_entry için başlıktan oku
        import re
        display = m
        if ev.event_type == "log_entry":
            cat = raw.get("category", "")
            if cat and cat != "General":
                display = cat
            elif ev.title and ev.title != "Log Entry":
                display = re.sub(r'\s*\[x\d+\]', '', ev.title).strip()[:60]
            else:
                display = "Log Girişi"
        metrics.append({
            "event_id": ev.id,
            "metric": display,
            "severity": ev.severity,
            "value": round(val, 1) if val is not None else None,
            "occurrence_count": ev.occurrence_count or 1,
            "last_seen": ev.last_seen.isoformat() if ev.last_seen else None,
            "event_type": ev.event_type,
        })

    all_event_ids = [e.id for e in events]

    return {
        "server": server_info,
        "max_severity": max_sev,
        "event_count": len(events),
        "event_ids": all_event_ids,
        "metrics": metrics,
        "last_seen": last_ev.last_seen.isoformat() if last_ev.last_seen else None,
        # Aksiyon önerileri
        "suggested_actions": _suggest_actions(events, server_info, platform),
    }


def _suggest_actions(events: List[SystemEvent], server: Dict[str, Any], platform: Optional[str] = None) -> List[str]:
    if platform == "windows":
        actions = []
        if any(e.event_type == "log_entry" for e in events):
            actions.append("Event Viewer → System/Application kritik kayıtları incele")
        if any("service" in (e.title or "").lower() for e in events):
            actions.append("Get-Service | Where Status -eq Stopped")
        if any("disk" in (e.title or "").lower() or "storage" in (e.title or "").lower() for e in events):
            actions.append("Get-PSDrive -PSProvider FileSystem")
        if not actions:
            actions.append("Get-WinEvent -LogName System -MaxEvents 20 | Where Level -le 3")
        return actions[:4]

    if platform == "virt":
        actions = []
        for ev in events:
            cat = (ev.raw_data or {}).get("category", "")
            if cat == "memory":
                actions.append("VM bellek overcommit ve balloon kontrolü")
            elif cat == "cpu":
                actions.append("Host CPU ready time / co-stop metriklerini incele")
            elif cat == "disk":
                actions.append("Datastore ve snapshot birikimini kontrol et")
        if not actions:
            actions.append("Hypervisor yönetim konsolunda host/task loglarını incele")
        return actions[:4]

    actions = []
    metrics = {(ev.raw_data or {}).get("metric") or ev.event_type for ev in events}

    has_cpu = any("cpu" in (m or "") for m in metrics)
    has_mem = any("memory" in (m or "") or "swap" in (m or "") for m in metrics)
    has_disk = any("disk" in (m or "") for m in metrics)
    has_load = any("load" in (m or "") or "procs_blocked" in (m or "") for m in metrics)
    has_log = any(e.event_type == "log_entry" for e in events)

    if has_cpu and has_load:
        actions.append("top -b -n1 ile süreçleri kontrol et")
    elif has_cpu:
        actions.append("ps aux --sort=-%cpu | head -10")
    if has_mem:
        actions.append("free -h && swapon --show")
    if has_disk:
        actions.append("df -h && iostat -x 1 3")
    if has_log:
        actions.append("journalctl -p err --since '1 hour ago' | tail -50")
    if not actions:
        actions.append("dmesg | tail -20 ve journal kontrol et")

    tier = server.get("tier", "unknown")
    if tier == "production" and len(events) >= 3:
        actions.insert(0, "⚠ Production sunucu — eskalasyon değerlendir")

    return actions[:4]


# ── API Endpoint'leri ─────────────────────────────────────────────────────────

@router.get("/command-center")
async def command_center(
    platform: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Sunucu odaklı alarm merkezi:
      - storms: ortak metrik fırtınaları
      - critical_servers: sunucu bazlı kart listesi (critical/emergency)
      - warning_servers: sunucu bazlı kart listesi (warning)
      - health_score: altyapı sağlık skoru
      - green_count: bastırılan / çözülen sayısı
    """
    since = datetime.utcnow() - timedelta(hours=ACTIVE_WINDOW_HOURS)
    smap = _server_map(db)
    if platform == "windows":
        win_ids = set(get_windows_server_ids(db))
        smap = {k: v for k, v in smap.items() if k in win_ids}
    elif platform == "linux":
        linux_ids = set(get_linux_server_ids(db))
        smap = {k: v for k, v in smap.items() if k in linux_ids}
    elif platform == "virt":
        smap = {}
    total_servers = len(smap)

    events = _active_events(db, since, platform=platform)

    green_q = db.query(SystemEvent).filter(
        SystemEvent.last_seen >= since,
        or_(
            SystemEvent.resolved == True,       # noqa: E712
            SystemEvent.is_known == True,       # noqa: E712
            SystemEvent.is_acknowledged == True, # noqa: E712
        ),
    )
    green_count: int = apply_platform_filter(green_q, platform, db).count()

    # ── Storm tespiti ─────────────────────────────────────────────────────────
    storm_incidents: List[Incident] = (
        db.query(Incident)
        .filter(Incident.source == "storm_detector", Incident.status != "resolved")
        .all()
    )
    storm_event_ids: set = set()
    storms: List[Dict[str, Any]] = []

    for inc in storm_incidents:
        eids = set(inc.related_events or [])
        storm_event_ids.update(eids)
        related_evs = [e for e in events if e.id in eids]
        if not related_evs:
            continue

        metric_hint = inc.title.replace("⚡ ALARM FIRTINASI:", "").split("—")[0].strip()
        max_sev = max(related_evs, key=lambda e: SEV_RANK.get(e.severity, 0)).severity

        affected_servers = []
        seen_sids: set = set()
        for ev in related_evs:
            if ev.server_id and ev.server_id not in seen_sids:
                seen_sids.add(ev.server_id)
                si = smap.get(ev.server_id, {})
                affected_servers.append({
                    "id": ev.server_id,
                    "name": si.get("name", f"server#{ev.server_id}"),
                    "ip": si.get("ip", ""),
                    "tier": si.get("tier", "unknown"),
                })

        storms.append({
            "incident_id": inc.id,
            "metric": metric_hint,
            "severity": max_sev,
            "server_count": len(seen_sids),
            "event_count": len(related_evs),
            "event_ids": [e.id for e in related_evs],
            "affected_servers": affected_servers,
            "last_seen": inc.updated_at.isoformat() if inc.updated_at else inc.created_at.isoformat() if inc.created_at else None,
        })

    # ── Sunucu bazlı gruplama ─────────────────────────────────────────────────
    by_server: Dict[Optional[int], List[SystemEvent]] = defaultdict(list)
    for ev in events:
        if ev.id not in storm_event_ids:
            by_server[ev.server_id].append(ev)

    critical_servers: List[Dict[str, Any]] = []
    warning_servers: List[Dict[str, Any]] = []

    for server_id, sevs in by_server.items():
        if platform == "virt" and server_id is not None:
            continue
        if server_id and platform in ("linux", "windows") and server_id not in smap:
            continue

        if server_id:
            si = smap.get(server_id, {
                "id": server_id, "name": f"server#{server_id}",
                "hostname": "", "ip": "", "tier": "unknown",
            })
        elif platform == "virt":
            raw = sevs[0].raw_data or {} if sevs else {}
            si = {
                "id": None,
                "name": raw.get("host_name") or raw.get("platform_label") or "Hypervisor",
                "hostname": raw.get("host_name") or "",
                "ip": "",
                "tier": "infrastructure",
            }
        else:
            si = {"id": None, "name": "Bilinmeyen", "hostname": "", "ip": "", "tier": "unknown"}

        card = _build_server_card(si, sevs, platform)
        max_sev = card["max_severity"]
        tier = si.get("tier", "unknown")

        if max_sev in ("critical", "emergency") or (max_sev == "warning" and tier == "production"):
            critical_servers.append(card)
        else:
            warning_servers.append(card)

    # Severity'ye göre sırala (critical > warning, sonra event sayısı)
    def sort_key(c: Dict[str, Any]) -> tuple:
        return (-SEV_RANK.get(c["max_severity"], 0), -c["event_count"])

    critical_servers.sort(key=sort_key)
    warning_servers.sort(key=sort_key)

    health = _calc_health_score(events, total_servers)

    return {
        "health": health,
        "storms": storms,
        "critical_servers": critical_servers[:30],
        "warning_servers": warning_servers[:50],
        "critical_count": len(critical_servers),
        "warning_count": len(warning_servers),
        "storm_count": len(storms),
        "green_count": green_count,
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/summary")
async def ops_summary(
    platform: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Hafif özet — navbar badge."""
    since = datetime.utcnow() - timedelta(hours=24)
    crit_q = apply_platform_filter(
        db.query(SystemEvent).filter(
            SystemEvent.resolved == False,        # noqa: E712
            SystemEvent.is_known == False,        # noqa: E712
            SystemEvent.severity.in_(["critical", "emergency"]),
            SystemEvent.last_seen >= since,
        ),
        platform,
        db,
    )
    critical = crit_q.count()
    warn_q = apply_platform_filter(
        db.query(SystemEvent).filter(
            SystemEvent.resolved == False,        # noqa: E712
            SystemEvent.is_known == False,        # noqa: E712
            SystemEvent.severity == "warning",
            SystemEvent.last_seen >= since,
        ),
        platform,
        db,
    )
    warning = warn_q.count()
    open_incidents = (
        db.query(Incident)
        .filter(Incident.status.in_(["open", "investigating"]))
        .count()
    )
    return {"critical": critical, "warning": warning, "open_incidents": open_incidents, "action_needed": critical > 0}


# ── Snooze ────────────────────────────────────────────────────────────────────

class SnoozeRequest(BaseModel):
    event_ids: List[int]
    minutes: int = 60   # Kaç dakika ertele


@router.post("/snooze")
async def snooze_events(req: SnoozeRequest, db: Session = Depends(get_db)):
    """
    Belirtilen event'leri X dakika erteler (snooze).
    Bu süre zarfında komuta merkezinde görünmez.
    """
    if req.minutes < 1 or req.minutes > 1440:
        raise HTTPException(status_code=400, detail="1-1440 dakika aralığında olmalı")

    until = datetime.utcnow() + timedelta(minutes=req.minutes)
    for eid in req.event_ids:
        _snoozed[eid] = until

    logger.info(f"[OpsCenter] Snooze: {len(req.event_ids)} event, {req.minutes}dk")
    return {
        "snoozed": len(req.event_ids),
        "until": until.isoformat(),
        "minutes": req.minutes,
    }


@router.get("/health-score")
async def health_score(db: Session = Depends(get_db)):
    """Anlık altyapı sağlık skoru."""
    since = datetime.utcnow() - timedelta(hours=ACTIVE_WINDOW_HOURS)
    smap = _server_map(db)
    events = _active_events(db, since)
    return _calc_health_score(events, len(smap))
