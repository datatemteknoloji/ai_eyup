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

GET /ops/executive-summary
  Yönetici Ekranı — Linux, Windows ve Sanallaştırma ortamlarını tek ekranda
  birleştiren üst düzey KPI özeti (genel sağlık skoru, platform bazlı kritik/
  uyarı sayıları, envanter ve en kritik olaylar).
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
    get_linux_module_server_ids,
    get_windows_server_ids,
    get_exadata_server_ids,
)
from app.services.event_filters import apply_actionable_event_filters, apply_hide_routine_virt

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


def _active_events(db: Session, since: datetime, platform: Optional[str] = None, show_routine: bool = False) -> List[SystemEvent]:
    """Aktif, bilinmeyen, onaylanmamış, snooze'suz eventler."""
    q = db.query(SystemEvent).filter(SystemEvent.last_seen >= since)
    q = apply_actionable_event_filters(q)
    if platform == "virt" and not show_routine:
        q = apply_hide_routine_virt(q, show_routine=False)
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
        linux_ids = set(get_linux_module_server_ids(db))
        smap = {k: v for k, v in smap.items() if k in linux_ids}
    elif platform == "virt":
        smap = {}
    elif platform == "exadata":
        exadata_ids = set(get_exadata_server_ids(db))
        smap = {k: v for k, v in smap.items() if k in exadata_ids}
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
        if server_id and platform in ("linux", "windows", "exadata") and server_id not in smap:
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

    event_critical = sum(1 for e in events if e.severity in ("critical", "emergency"))
    event_warning = sum(1 for e in events if e.severity == "warning")

    return {
        "health": health,
        "storms": storms,
        "critical_servers": critical_servers[:30],
        "warning_servers": warning_servers[:50],
        # Sunucu kartı sayıları (liste ile birebir)
        "critical_count": len(critical_servers),
        "warning_count": len(warning_servers),
        "storm_count": len(storms),
        # Event sayıları — navbar / Events KPI ile aynı tanım
        "event_critical": event_critical,
        "event_warning": event_warning,
        "event_total": event_critical + event_warning,
        "green_count": green_count,
        "generated_at": datetime.utcnow().isoformat(),
    }


def _handle_status(ev: SystemEvent) -> str:
    """Öncelik: çözüldü > bilinen > onaylandı."""
    if ev.resolved:
        return "resolved"
    if getattr(ev, "is_known", False):
        return "known"
    if ev.is_acknowledged:
        return "acknowledged"
    return "other"


@router.get("/handled-events")
async def handled_events(
    platform: Optional[str] = Query(default=None),
    status: Optional[str] = Query(
        default=None,
        description="acknowledged | known | resolved — boşsa hepsi",
    ),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=300),
    db: Session = Depends(get_db),
):
    """
    Son 24 saatte işlenen (onaylanan / bilinen / çözülen) eventler.
    Komuta Merkezi'nden düşen alarmların kaybolmaması için.
    """
    since = datetime.utcnow() - timedelta(hours=ACTIVE_WINDOW_HOURS)
    smap = _server_map(db)

    q = db.query(SystemEvent).filter(
        SystemEvent.last_seen >= since,
        or_(
            SystemEvent.resolved == True,  # noqa: E712
            SystemEvent.is_known == True,  # noqa: E712
            SystemEvent.is_acknowledged == True,  # noqa: E712
        ),
    )
    q = apply_platform_filter(q, platform, db)
    if platform == "virt":
        q = apply_hide_routine_virt(q, show_routine=False)
    if search:
        matching_ids = [
            s.id for s in db.query(Server.id).filter(Server.name.ilike(f"%{search}%")).all()
        ]
        conds = [SystemEvent.title.ilike(f"%{search}%")]
        if matching_ids:
            conds.append(SystemEvent.server_id.in_(matching_ids))
        q = q.filter(or_(*conds))

    rows: List[SystemEvent] = q.order_by(SystemEvent.last_seen.desc()).limit(800).all()

    items: List[Dict[str, Any]] = []
    counts = {"acknowledged": 0, "known": 0, "resolved": 0, "total": 0}
    for ev in rows:
        hs = _handle_status(ev)
        if hs == "other":
            continue
        counts[hs] = counts.get(hs, 0) + 1
        counts["total"] += 1
        if status and hs != status:
            continue
        si = smap.get(ev.server_id) if ev.server_id else None
        raw = ev.raw_data or {}
        items.append({
            "id": ev.id,
            "title": ev.title,
            "severity": ev.severity,
            "event_type": ev.event_type,
            "handle_status": hs,
            "is_acknowledged": bool(ev.is_acknowledged),
            "is_known": bool(getattr(ev, "is_known", False)),
            "resolved": bool(ev.resolved),
            "server_id": ev.server_id,
            "server_name": (si or {}).get("name") or raw.get("host_name") or "—",
            "server_ip": (si or {}).get("ip") or "",
            "occurrence_count": ev.occurrence_count or 1,
            "last_seen": ev.last_seen.isoformat() if ev.last_seen else None,
            "acknowledged_at": ev.acknowledged_at.isoformat() if getattr(ev, "acknowledged_at", None) else None,
            "known_at": ev.known_at.isoformat() if getattr(ev, "known_at", None) else None,
            "resolved_at": ev.resolved_at.isoformat() if ev.resolved_at else None,
        })

    return {
        "counts": counts,
        "events": items[:limit],
        "total": len(items),
        "window_hours": ACTIVE_WINDOW_HOURS,
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/summary")
async def ops_summary(
    platform: Optional[str] = Query(default=None),
    fresh: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """Navbar badge — Komuta Merkezi / Events ile aynı actionable event sayıları.

    critical = critical + emergency event adedi
    warning  = warning event adedi
    total    = critical + warning

    Redis TTL önbellek (varsayılan ~45s) — multi-worker / restart dostu.
    fresh=1 ile bypass.
    """
    import json
    import time as _time

    cache_key = f"ainew:ops:summary:{platform or 'all'}"
    if not fresh:
        try:
            from app.core.redis_client import get_redis

            r = get_redis()
            if r is not None:
                cached = r.get(cache_key)
                if cached:
                    return json.loads(cached)
        except Exception:
            pass
        # Process-local fallback (Redis yoksa)
        mem = getattr(ops_summary, "_cache", None)
        if mem is None:
            ops_summary._cache = {}
            mem = ops_summary._cache
        hit = mem.get(cache_key)
        now = _time.monotonic()
        if hit and hit[0] > now:
            return hit[1]

    since = datetime.utcnow() - timedelta(hours=ACTIVE_WINDOW_HOURS)
    events = _active_events(db, since, platform=platform)
    critical = sum(1 for e in events if e.severity in ("critical", "emergency"))
    warning = sum(1 for e in events if e.severity == "warning")
    from app.services.platform_scope import filter_incidents_for_platform
    # Yalnızca açık incident'lar — .all() + Python filtre yerine önce status filtresi
    open_incidents_q = (
        db.query(Incident)
        .filter(Incident.status.in_(["open", "investigating"]))
        .limit(500)
        .all()
    )
    open_incidents = len(filter_incidents_for_platform(open_incidents_q, platform, db))
    total = critical + warning
    result = {
        "critical": critical,
        "warning": warning,
        "total": total,
        "open_incidents": open_incidents,
        "action_needed": total > 0,
    }

    try:
        from app.services.runtime_settings import get_setting

        ttl = int(get_setting("ops_summary_cache_ttl_sec") or 45)
    except Exception:
        ttl = 45

    try:
        from app.core.redis_client import get_redis

        r = get_redis()
        if r is not None and ttl > 0:
            r.setex(cache_key, ttl, json.dumps(result, ensure_ascii=False, default=str))
    except Exception:
        pass

    mem = getattr(ops_summary, "_cache", None)
    if mem is None:
        ops_summary._cache = {}
        mem = ops_summary._cache
    mem[cache_key] = (_time.monotonic() + float(ttl), result)
    return result


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


# ── Yönetici Ekranı (Executive Dashboard) ────────────────────────────────────

def _grade_for_score(score: int) -> Dict[str, str]:
    if score >= 90:
        return {"grade": "A", "label": "Sağlıklı"}
    if score >= 75:
        return {"grade": "B", "label": "İyi"}
    if score >= 55:
        return {"grade": "C", "label": "Dikkat"}
    if score >= 35:
        return {"grade": "D", "label": "Sorunlu"}
    return {"grade": "F", "label": "Kritik"}


@router.get("/executive-summary")
async def executive_summary(db: Session = Depends(get_db)):
    """
    Yönetici Ekranı özeti — Linux, Windows ve Sanallaştırma ortamlarını
    tek yanıtta birleştirir: genel sağlık skoru, platform bazlı envanter/
    kritik-uyarı sayıları ve en kritik 10 olay (platform etiketiyle).
    """
    from sqlalchemy import func as sa_func
    from app.models.hypervisor import Hypervisor
    from app.services.virt_ops_center import virt_ops_summary
    from app.services.platform_scope import (
        get_linux_module_server_ids, get_windows_server_ids, vm_filter_condition, infer_event_platform,
    )

    since = datetime.utcnow() - timedelta(hours=ACTIVE_WINDOW_HOURS)

    linux_ids = set(get_linux_module_server_ids(db))
    windows_ids = set(get_windows_server_ids(db))

    linux_events = _active_events(db, since, platform="linux")
    windows_events = _active_events(db, since, platform="windows")
    virt_events = _active_events(db, since, platform="virt")

    linux_health = _calc_health_score(linux_events, len(linux_ids))
    windows_health = _calc_health_score(windows_events, len(windows_ids))

    def _sev_counts(events: List[SystemEvent]) -> tuple:
        crit = sum(1 for e in events if e.severity in ("critical", "emergency"))
        warn = sum(1 for e in events if e.severity == "warning")
        return crit, warn

    linux_crit, linux_warn = _sev_counts(linux_events)
    windows_crit, windows_warn = _sev_counts(windows_events)

    linux_ai_ready = (
        db.query(Server).filter(Server.id.in_(linux_ids), Server.ai_ready == True).count()  # noqa: E712
        if linux_ids else 0
    )
    windows_ai_ready = (
        db.query(Server).filter(Server.id.in_(windows_ids), Server.ai_ready == True).count()  # noqa: E712
        if windows_ids else 0
    )
    node_exporter_running = (
        db.query(Server).filter(Server.id.in_(linux_ids), Server.node_exporter_running == True).count()  # noqa: E712
        if linux_ids else 0
    )
    windows_exporter_running = (
        db.query(Server).filter(Server.id.in_(windows_ids), Server.windows_exporter_running == True).count()  # noqa: E712
        if windows_ids else 0
    )

    try:
        virt_summary = virt_ops_summary(db)
    except Exception:
        logger.exception("Yönetici özeti: virt_ops_summary alınamadı")
        virt_summary = {"critical": 0, "warning": 0, "health_score": 100, "action_needed": False}

    hypervisor_count = db.query(Hypervisor).count()
    vm_q = db.query(Server).filter(vm_filter_condition())
    vm_count = vm_q.count()
    vm_running_count = vm_q.filter(sa_func.lower(Server.vm_power_state).in_(["poweredon", "up", "running"])).count()

    open_incidents = db.query(Incident).filter(Incident.status.in_(["open", "investigating"])).count()

    total_servers = len(linux_ids) + len(windows_ids)
    total_critical = linux_crit + windows_crit + virt_summary.get("critical", 0)
    total_warning = linux_warn + windows_warn + virt_summary.get("warning", 0)

    weights = [
        (linux_health["score"], max(len(linux_ids), 1)),
        (windows_health["score"], max(len(windows_ids), 1)),
        (virt_summary.get("health_score", 100), max(hypervisor_count, 1)),
    ]
    total_weight = sum(w for _, w in weights)
    overall_score = round(sum(s * w for s, w in weights) / total_weight) if total_weight else 100

    smap = _server_map(db)
    all_active = linux_events + windows_events + virt_events
    top_events = sorted(
        all_active,
        key=lambda e: (-SEV_RANK.get(e.severity, 0), -(e.last_seen.timestamp() if e.last_seen else 0)),
    )[:10]

    top_alerts = []
    for ev in top_events:
        platform = infer_event_platform(ev, linux_ids, windows_ids)
        server_info = smap.get(ev.server_id) if ev.server_id else None
        raw = ev.raw_data or {}
        server_name = (
            server_info["name"] if server_info
            else (raw.get("host_name") or raw.get("platform_label") or "—")
        )
        top_alerts.append({
            "event_id": ev.id,
            "platform": "virtualization" if platform == "virt" else platform,
            "server_name": server_name,
            "severity": ev.severity,
            "title": ev.title,
            "last_seen": ev.last_seen.isoformat() if ev.last_seen else None,
        })

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "overall": {
            "health_score": overall_score,
            **_grade_for_score(overall_score),
            "critical_total": total_critical,
            "warning_total": total_warning,
            "open_incidents": open_incidents,
            "total_servers": total_servers,
        },
        "platforms": {
            "linux": {
                "server_count": len(linux_ids),
                "ai_ready_count": linux_ai_ready,
                "node_exporter_running": node_exporter_running,
                "critical": linux_crit,
                "warning": linux_warn,
                "health_score": linux_health["score"],
                **_grade_for_score(linux_health["score"]),
            },
            "windows": {
                "server_count": len(windows_ids),
                "ai_ready_count": windows_ai_ready,
                "windows_exporter_running": windows_exporter_running,
                "critical": windows_crit,
                "warning": windows_warn,
                "health_score": windows_health["score"],
                **_grade_for_score(windows_health["score"]),
            },
            "virtualization": {
                "hypervisor_count": hypervisor_count,
                "vm_count": vm_count,
                "vm_running_count": vm_running_count,
                "critical": virt_summary.get("critical", 0),
                "warning": virt_summary.get("warning", 0),
                "health_score": virt_summary.get("health_score", 100),
                **_grade_for_score(virt_summary.get("health_score", 100)),
            },
        },
        "top_alerts": top_alerts,
    }
