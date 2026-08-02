"""
Modül bazlı altyapı raporları — Linux, Windows, Exadata.

Sanallaştırma raporları `report_engine.py` (hypervisor) üzerinden kalır.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.event import SystemEvent, Incident
from app.models.metric import MetricData
from app.models.server import Server
from app.services.platform_scope import (
    VALID_PLATFORMS,
    apply_platform_filter,
    get_exadata_server_ids,
    get_linux_module_server_ids,
    get_windows_server_ids,
    server_ids_for_platform,
)

logger = logging.getLogger(__name__)

REPORT_TITLES: Dict[str, str] = {
    "executive_summary": "Executive Summary",
    "capacity": "Kapasite Raporu",
    "operations": "Operasyon Raporu",
    "risk": "Risk Dashboard",
    "performance": "Performans Raporu",
    "patch_status": "Yama & Güncelleme Durumu",
    "security": "Güvenlik Özeti",
    "node_health": "Node Sağlık Raporu",
    "sla": "Erişilebilirlik (SLA) Raporu",
    "monitoring_coverage": "İzleme Kapsamı Raporu",
}

PLATFORM_CATALOG: Dict[str, List[str]] = {
    "linux": ["executive_summary", "capacity", "operations", "risk", "performance", "patch_status", "security", "sla", "monitoring_coverage"],
    "windows": ["executive_summary", "operations", "risk", "security", "patch_status", "sla", "monitoring_coverage"],
    "exadata": ["executive_summary", "capacity", "operations", "risk", "node_health"],
}


def _storage_key(platform: str, report_type: str) -> str:
    return f"{platform}:{report_type}"


def _parse_storage_key(storage_key: str) -> tuple[str, str]:
    if ":" in storage_key:
        p, t = storage_key.split(":", 1)
        return p, t
    return "virt", storage_key


def _servers_for_platform(db: Session, platform: str) -> List[Server]:
    ids = set(server_ids_for_platform(db, platform))
    if not ids:
        return []
    return db.query(Server).filter(Server.id.in_(list(ids))).all()


def _active_events(db: Session, platform: str, hours: int = 24) -> List[SystemEvent]:
    since = datetime.utcnow() - timedelta(hours=hours)
    q = db.query(SystemEvent).filter(
        SystemEvent.last_seen >= since,
        SystemEvent.resolved == False,  # noqa: E712
    )
    q = apply_platform_filter(q, platform, db)
    return q.all()


def _health_score(critical: int, warning: int, total: int) -> int:
    if total <= 0:
        return 100
    penalty = critical * 15 + warning * 5
    return max(0, min(100, 100 - round(penalty / max(total, 1))))


def generate_linux_executive_summary(db: Session) -> Dict[str, Any]:
    servers = _servers_for_platform(db, "linux")
    events = _active_events(db, "linux", 24)
    critical = sum(1 for e in events if e.severity in ("critical", "emergency"))
    warning = sum(1 for e in events if e.severity == "warning")
    online = sum(1 for s in servers if (s.status or "").upper() == "ONLINE")
    ai_ready = sum(1 for s in servers if s.ai_ready)
    score = _health_score(critical, warning, len(servers))

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "linux",
        "inventory": {
            "total_servers": len(servers),
            "online": online,
            "offline": len(servers) - online,
            "ai_ready": ai_ready,
        },
        "health": {"score": score, "critical_events": critical, "warning_events": warning},
        "risk_level": "Kritik" if critical > 3 else ("Yüksek" if critical > 0 else ("Orta" if warning > 5 else "Normal")),
        "recommendations": [
            f"{critical} kritik olay incelenmeli" if critical else "Kritik olay yok",
            f"{len(servers) - online} sunucu OFFLINE" if len(servers) > online else "Tüm sunucular erişilebilir",
        ],
    }


def generate_linux_capacity(db: Session) -> Dict[str, Any]:
    servers = _servers_for_platform(db, "linux")
    since = datetime.utcnow() - timedelta(hours=1)
    rows = []
    for srv in servers[:50]:
        metrics: Dict[str, float] = {}
        for name in ("cpu_usage_percent", "memory_usage_percent", "disk_root_usage_percent"):
            val = (
                db.query(MetricData.value)
                .filter(
                    MetricData.server_id == srv.id,
                    MetricData.metric_name == name,
                    MetricData.timestamp >= since,
                )
                .order_by(MetricData.timestamp.desc())
                .first()
            )
            if val:
                metrics[name] = round(float(val[0]), 1)
        if metrics:
            rows.append({"server": srv.name, "ip": srv.ip_address or "", **metrics})

    high_cpu = [r for r in rows if r.get("cpu_usage_percent", 0) >= 85]
    high_mem = [r for r in rows if r.get("memory_usage_percent", 0) >= 85]
    high_disk = [r for r in rows if r.get("disk_root_usage_percent", 0) >= 85]

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "linux",
        "sampled_servers": len(rows),
        "high_cpu_count": len(high_cpu),
        "high_memory_count": len(high_mem),
        "high_disk_count": len(high_disk),
        "top_servers": sorted(rows, key=lambda r: r.get("cpu_usage_percent", 0), reverse=True)[:15],
    }


_SEVERITY_RANK = {"emergency": 4, "critical": 4, "error": 3, "warning": 2, "info": 1}


def _worst_severity(severities: List[str]) -> str:
    if not severities:
        return "info"
    return max(severities, key=lambda s: _SEVERITY_RANK.get(s or "info", 0))


def _events_to_operations_payload(events: List[SystemEvent], period_days: int, platform: str) -> Dict[str, Any]:
    """`OperationsView` (InfraReports.tsx) için ortak şema: `event_breakdown`
    ({type,count,severity}) ve `daily_trend` ({day,total,critical}) — virt
    raporlarıyla aynı alan adları, tek bir görsel component'i paylaşabilsin."""
    by_day_total: Dict[str, int] = defaultdict(int)
    by_day_critical: Dict[str, int] = defaultdict(int)
    by_type_count: Counter = Counter()
    by_type_severities: Dict[str, List[str]] = defaultdict(list)
    servers_seen: set = set()

    for ev in events:
        day = ev.created_at.date().isoformat() if ev.created_at else "unknown"
        by_day_total[day] += 1
        sev = ev.severity or "info"
        if sev in ("critical", "emergency"):
            by_day_critical[day] += 1
        etype = ev.event_type or "unknown"
        by_type_count[etype] += 1
        by_type_severities[etype].append(sev)
        if ev.server_id:
            servers_seen.add(ev.server_id)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": platform,
        "period_days": period_days,
        "total_events": len(events),
        "unique_servers": len(servers_seen),
        "by_severity": dict(Counter((ev.severity or "info") for ev in events)),
        "event_breakdown": [
            {"type": k, "count": v, "severity": _worst_severity(by_type_severities[k])}
            for k, v in by_type_count.most_common(12)
        ],
        "daily_trend": [
            {"day": d, "total": t, "critical": by_day_critical.get(d, 0)}
            for d, t in sorted(by_day_total.items())[-14:]
        ],
    }


def generate_linux_operations(db: Session) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(days=30)
    q = apply_platform_filter(
        db.query(SystemEvent).filter(SystemEvent.created_at >= since),
        "linux",
        db,
    )
    return _events_to_operations_payload(q.all(), 30, "linux")


def generate_linux_risk(db: Session) -> Dict[str, Any]:
    events = _active_events(db, "linux", 48)
    by_server: Dict[int, List[SystemEvent]] = defaultdict(list)
    for ev in events:
        if ev.server_id:
            by_server[ev.server_id].append(ev)

    smap = {s.id: s for s in _servers_for_platform(db, "linux")}
    risky = []
    for sid, evs in by_server.items():
        srv = smap.get(sid)
        crit = sum(1 for e in evs if e.severity in ("critical", "emergency"))
        if crit == 0 and len(evs) < 3:
            continue
        risky.append({
            "server": srv.name if srv else f"#{sid}",
            "ip": srv.ip_address if srv else "",
            "event_count": len(evs),
            "critical_count": crit,
            "top_title": evs[0].title[:80] if evs else "",
        })

    risky.sort(key=lambda x: (-x["critical_count"], -x["event_count"]))

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "linux",
        "risky_servers": risky[:20],
        "total_active_events": len(events),
    }


def generate_linux_performance(db: Session) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(hours=24)
    q = apply_platform_filter(
        db.query(SystemEvent).filter(
            SystemEvent.event_type == "metric_anomaly",
            SystemEvent.created_at >= since,
        ),
        "linux",
        db,
    )
    anomalies = q.all()
    items = []
    smap = {s.id: s.name for s in _servers_for_platform(db, "linux")}
    for ev in anomalies[:25]:
        raw = ev.raw_data or {}
        items.append({
            "server": smap.get(ev.server_id, f"#{ev.server_id}"),
            "metric": raw.get("metric", "?"),
            "severity": ev.severity,
            "value": raw.get("current_value"),
        })

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "linux",
        "anomaly_count": len(anomalies),
        "anomalies": items,
    }


def generate_linux_patch_status(db: Session) -> Dict[str, Any]:
    """Sistem Güncelle modülünde oluşturulan plan/job kayıtlarından her sunucunun
    en son bilinen yama durumunu (bekleyen paket sayısı, son kontrol zamanı,
    reboot gerekliliği) türetir. Canlı SSH sorgusu YAPMAZ — hızlı ve senkron
    çalışması için yalnızca zaten toplanmış job geçmişine bakar."""
    from app.models.system_update import SystemUpdateJob

    servers = _servers_for_platform(db, "linux")
    server_ids = [s.id for s in servers]

    latest_jobs: Dict[int, SystemUpdateJob] = {}
    if server_ids:
        jobs = (
            db.query(SystemUpdateJob)
            .filter(SystemUpdateJob.server_id.in_(server_ids))
            .order_by(SystemUpdateJob.server_id, SystemUpdateJob.id.desc())
            .all()
        )
        for j in jobs:
            latest_jobs.setdefault(j.server_id, j)

    rows = []
    checked_count = 0
    pending_total = 0
    reboot_required_count = 0
    failed_count = 0

    for srv in servers:
        job = latest_jobs.get(srv.id)
        if job:
            checked_count += 1
            pending = len(job.packages_to_update or [])
            pending_total += pending
            if job.reboot_required:
                reboot_required_count += 1
            if job.status == "failed":
                failed_count += 1
            last_checked = job.completed_at or job.started_at or job.created_at
            rows.append({
                "server": srv.name,
                "os_type": srv.os_type or "",
                "os_version": srv.os_version or "",
                "kernel": srv.kernel_version or "",
                "status": srv.status or "",
                "last_checked": last_checked.isoformat() if last_checked else None,
                "pending_updates": pending,
                "last_job_status": job.status,
                "reboot_required": bool(job.reboot_required),
            })
        else:
            rows.append({
                "server": srv.name,
                "os_type": srv.os_type or "",
                "os_version": srv.os_version or "",
                "kernel": srv.kernel_version or "",
                "status": srv.status or "",
                "last_checked": None,
                "pending_updates": None,
                "last_job_status": None,
                "reboot_required": False,
            })

    # En çok bekleyen paketi olanlar / hiç kontrol edilmemiş olanlar üste
    rows.sort(key=lambda r: (0 if r["pending_updates"] is None else 1, -(r["pending_updates"] or 0)))

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "linux",
        "total_servers": len(servers),
        "checked_servers": checked_count,
        "never_checked_servers": len(servers) - checked_count,
        "pending_updates_total": pending_total,
        "reboot_required_count": reboot_required_count,
        "failed_last_run_count": failed_count,
        "servers": rows[:60],
        "note": "Yama verisi Sistem Güncelle modülündeki en son kontrol/plan sonuçlarından alınır. Hiç kontrol edilmemiş sunucular için Sistem Güncelle > Plan Oluştur ile kontrol başlatın.",
    }


def generate_linux_security(db: Session) -> Dict[str, Any]:
    """Firewall/SELinux durumu ve başarısız SSH girişleri — auto-onboarding tarafından
    periyodik SSH ile toplanan cache'den okunur (canlı sorgu YAPILMAZ)."""
    servers = _servers_for_platform(db, "linux")
    checked = [s for s in servers if s.linux_security_last_check]
    firewall_off = [s for s in checked if s.linux_firewall_active is False]
    selinux_disabled = [s for s in checked if (s.linux_selinux_status or "").lower() in ("disabled", "n/a")]
    high_failed = [s for s in checked if (s.linux_failed_logins_24h or 0) >= 5]

    rows = [
        {
            "server": s.name,
            "ip": s.ip_address or "",
            "firewall_active": s.linux_firewall_active,
            "selinux_status": s.linux_selinux_status or "—",
            "failed_logins_24h": s.linux_failed_logins_24h or 0,
            "last_checked": s.linux_security_last_check.isoformat() if s.linux_security_last_check else None,
        }
        for s in servers
    ]
    rows.sort(key=lambda r: (0 if r["last_checked"] else 1, -(r["failed_logins_24h"] or 0)))

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "linux",
        "total_servers": len(servers),
        "checked_servers": len(checked),
        "never_checked_servers": len(servers) - len(checked),
        "firewall_inactive_count": len(firewall_off),
        "selinux_disabled_count": len(selinux_disabled),
        "high_failed_login_count": len(high_failed),
        "servers": rows[:60],
        "note": "Firewall/SELinux durumu ve başarısız SSH girişleri otomatik onboarding tarafından SSH ile periyodik toplanır (6 saatte bir).",
    }


def _sla_items(db: Session, servers: List[Server], days: int = 30) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(days=days)
    server_ids = [s.id for s in servers]
    events_by_server: Dict[int, List[SystemEvent]] = defaultdict(list)
    if server_ids:
        rows = (
            db.query(SystemEvent)
            .filter(SystemEvent.server_id.in_(server_ids), SystemEvent.created_at >= since)
            .all()
        )
        for ev in rows:
            events_by_server[ev.server_id].append(ev)

    sla_items = []
    for srv in servers:
        evs = events_by_server.get(srv.id, [])
        crit = sum(1 for e in evs if e.severity in ("critical", "error", "emergency"))
        estimated_uptime = max(0.0, 100 - crit * 0.5)
        sla_items.append({
            "server": srv.name,
            "current_status": srv.status or "UNKNOWN",
            "critical_events_30d": crit,
            "total_events_30d": len(evs),
            "estimated_uptime_pct": round(min(100.0, estimated_uptime), 2),
            "sla_met": estimated_uptime >= 99.0,
        })

    met = sum(1 for s in sla_items if s["sla_met"])
    return {
        "period_days": days,
        "sla_target_pct": 99.0,
        "servers_meeting_sla": met,
        "servers_missing_sla": len(sla_items) - met,
        "overall_sla_compliance_pct": round(met / len(sla_items) * 100, 1) if sla_items else 100,
        "sla_items": sorted(sla_items, key=lambda x: x["estimated_uptime_pct"])[:30],
        "note": "SLA hesabı olay yoğunluğundan tahmin edilmiştir. Kesin ölçüm için monitoring entegrasyonu gereklidir.",
    }


def generate_linux_sla(db: Session) -> Dict[str, Any]:
    servers = _servers_for_platform(db, "linux")
    return {"generated_at": datetime.utcnow().isoformat(), "platform": "linux", **_sla_items(db, servers)}


def _monitoring_coverage(servers: List[Server], exporter_installed_attr: str, exporter_running_attr: str) -> Dict[str, Any]:
    total = len(servers)
    ai_ready = sum(1 for s in servers if s.ai_ready)
    exp_installed = sum(1 for s in servers if getattr(s, exporter_installed_attr, False))
    exp_running = sum(1 for s in servers if getattr(s, exporter_running_attr, False))
    gaps = [
        {
            "server": s.name,
            "ip": s.ip_address or "",
            "status": s.status or "",
            "ai_ready": bool(s.ai_ready),
            "exporter_installed": bool(getattr(s, exporter_installed_attr, False)),
            "exporter_running": bool(getattr(s, exporter_running_attr, False)),
        }
        for s in servers
        if not s.ai_ready or not getattr(s, exporter_running_attr, False)
    ]
    fully_covered = [
        {"server": s.name, "ip": s.ip_address or ""}
        for s in servers
        if s.ai_ready and getattr(s, exporter_running_attr, False)
    ]
    return {
        "total_servers": total,
        "ai_ready_count": ai_ready,
        "ai_not_ready_count": total - ai_ready,
        "exporter_installed_count": exp_installed,
        "exporter_running_count": exp_running,
        "fully_covered_count": len(fully_covered),
        "coverage_pct": round(exp_running / total * 100, 1) if total else 100,
        # NOT: 'gaps' SADECE eksik (AI Ready olmayan VEYA exporter çalışmayan) sunucuları listeler.
        # AI Ready + exporter çalışan sunucular burada GÖRÜNMEZ — bkz. 'fully_covered' listesi.
        "gaps": sorted(gaps, key=lambda r: r["server"])[:60],
        "fully_covered": sorted(fully_covered, key=lambda r: r["server"])[:60],
        "note": (
            f"Toplam {ai_ready} sunucu AI Ready; bunlardan {len(fully_covered)}'i exporter da çalıştığı için "
            f"tam kapsamda ve aşağıdaki tabloda GÖRÜNMEZ. Tablo sadece eksik/kapsam dışı {len(gaps)} sunucuyu listeler. "
            "Kapsam dışı sunucular için AI Ready testi ve exporter kurulumu otomatik onboarding tarafından periyodik denenir; "
            "manuel müdahale gerekiyorsa Canlı Metrikler modülünü kullanın."
        ),
    }


def generate_linux_monitoring_coverage(db: Session) -> Dict[str, Any]:
    servers = _servers_for_platform(db, "linux")
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "linux",
        **_monitoring_coverage(servers, "node_exporter_installed", "node_exporter_running"),
    }


def generate_windows_executive_summary(db: Session) -> Dict[str, Any]:
    servers = _servers_for_platform(db, "windows")
    events = _active_events(db, "windows", 24)
    critical = sum(1 for e in events if e.severity in ("critical", "emergency"))
    warning = sum(1 for e in events if e.severity == "warning")
    online = sum(1 for s in servers if (s.status or "").upper() == "ONLINE")

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "windows",
        "inventory": {"total_servers": len(servers), "online": online},
        "health": {
            "score": _health_score(critical, warning, len(servers)),
            "critical_events": critical,
            "warning_events": warning,
        },
        "risk_level": "Kritik" if critical > 2 else ("Yüksek" if critical else "Normal"),
    }


def generate_windows_operations(db: Session) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(days=30)
    events = apply_platform_filter(
        db.query(SystemEvent).filter(SystemEvent.created_at >= since),
        "windows",
        db,
    ).all()
    return _events_to_operations_payload(events, 30, "windows")


def generate_windows_risk(db: Session) -> Dict[str, Any]:
    events = _active_events(db, "windows", 48)
    smap = {s.id: s for s in _servers_for_platform(db, "windows")}
    by_server: Dict[int, int] = defaultdict(int)
    for ev in events:
        if ev.server_id:
            by_server[ev.server_id] += 1
    risky = sorted(
        [
            {
                "server": smap[sid].name if sid in smap else f"#{sid}",
                "events": cnt,
            }
            for sid, cnt in by_server.items()
        ],
        key=lambda x: -x["events"],
    )[:20]
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "windows",
        "risky_servers": risky,
        "total_active_events": len(events),
    }


def generate_windows_security(db: Session) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(days=7)
    q = apply_platform_filter(
        db.query(SystemEvent).filter(SystemEvent.created_at >= since),
        "windows",
        db,
    )
    events = q.all()
    security_kw = ("auth", "login", "security", "audit", "failed", "denied", "4625", "4648")
    security_events = [
        ev for ev in events
        if any(k in (ev.title or "").lower() or k in (ev.event_type or "").lower() for k in security_kw)
    ]

    # Windows Defender durumu — auto-onboarding tarafından WinRM ile periyodik toplanan cache
    servers = _servers_for_platform(db, "windows")
    defender_checked = [s for s in servers if s.win_defender_enabled is not None]
    defender_gaps = [
        {
            "server": s.name,
            "defender_enabled": s.win_defender_enabled,
            "defender_up_to_date": s.win_defender_up_to_date,
        }
        for s in defender_checked
        if not s.win_defender_enabled or not s.win_defender_up_to_date
    ]

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "windows",
        "period_days": 7,
        "security_event_count": len(security_events),
        "samples": [
            {"server_id": ev.server_id, "title": ev.title[:100], "severity": ev.severity}
            for ev in security_events[:15]
        ],
        "defender_checked_servers": len(defender_checked),
        "defender_disabled_count": sum(1 for s in defender_checked if not s.win_defender_enabled),
        "defender_outdated_count": sum(1 for s in defender_checked if s.win_defender_enabled and not s.win_defender_up_to_date),
        "defender_gaps": defender_gaps[:30],
    }


def generate_windows_patch_status(db: Session) -> Dict[str, Any]:
    """WinRM üzerinden auto-onboarding tarafından periyodik toplanan bekleyen
    güncelleme/reboot cache'inden okunur (canlı WinRM sorgusu YAPILMAZ)."""
    servers = _servers_for_platform(db, "windows")
    checked = [s for s in servers if s.win_updates_last_checked]
    pending_total = sum((s.win_updates_pending or 0) for s in checked)
    reboot_count = sum(1 for s in checked if s.win_reboot_pending)

    rows = []
    for s in servers:
        rows.append({
            "server": s.name,
            "os_type": s.os_type or "",
            "os_version": s.os_version or "",
            "kernel": "",
            "status": s.status or "",
            "last_checked": s.win_updates_last_checked.isoformat() if s.win_updates_last_checked else None,
            "pending_updates": s.win_updates_pending if s.win_updates_last_checked else None,
            "last_job_status": None,
            "reboot_required": bool(s.win_reboot_pending),
            "defender_enabled": s.win_defender_enabled,
        })
    rows.sort(key=lambda r: (0 if r["pending_updates"] is None else 1, -(r["pending_updates"] or 0)))

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "windows",
        "total_servers": len(servers),
        "checked_servers": len(checked),
        "never_checked_servers": len(servers) - len(checked),
        "pending_updates_total": pending_total,
        "reboot_required_count": reboot_count,
        "servers": rows[:60],
        "note": "Yama verisi WinRM üzerinden auto-onboarding tarafından periyodik (6 saatte bir) toplanır. Hiç kontrol edilmemiş sunucular için Windows modülünde WinRM kimlik bilgisi (sunucu veya global) tanımlı olduğundan emin olun.",
    }


def generate_windows_sla(db: Session) -> Dict[str, Any]:
    servers = _servers_for_platform(db, "windows")
    return {"generated_at": datetime.utcnow().isoformat(), "platform": "windows", **_sla_items(db, servers)}


def generate_windows_monitoring_coverage(db: Session) -> Dict[str, Any]:
    servers = _servers_for_platform(db, "windows")
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "windows",
        **_monitoring_coverage(servers, "windows_exporter_installed", "windows_exporter_running"),
    }


def generate_exadata_executive_summary(db: Session) -> Dict[str, Any]:
    from app.models.exadata import ExadataRack, ExadataNode

    racks = db.query(ExadataRack).all()
    nodes = db.query(ExadataNode).all()
    compute = sum(1 for n in nodes if (n.role.value if hasattr(n.role, "value") else str(n.role)) == "compute_node")
    cells = sum(1 for n in nodes if (n.role.value if hasattr(n.role, "value") else str(n.role)) == "storage_cell")
    events = _active_events(db, "exadata", 24)
    critical = sum(1 for e in events if e.severity in ("critical", "emergency"))
    warning = sum(1 for e in events if e.severity == "warning")
    unhealthy_racks = sum(1 for r in racks if (r.status or "").lower() in ("critical", "warning", "degraded", "offline"))

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "exadata",
        "inventory": {
            "rack_count": len(racks),
            "node_count": len(nodes),
            "compute_nodes": compute,
            "storage_cells": cells,
        },
        "health": {
            "score": _health_score(critical, warning, max(len(nodes), 1)),
            "critical_events": critical,
            "warning_events": warning,
        },
        "risk_level": "Kritik" if critical or unhealthy_racks else "Normal",
    }


def generate_exadata_capacity(db: Session) -> Dict[str, Any]:
    from app.models.exadata import ExadataNode

    nodes = db.query(ExadataNode).all()
    rows = []
    for n in nodes:
        rows.append({
            "name": n.name,
            "role": n.role.value if hasattr(n.role, "value") else str(n.role),
            "rack": n.rack.name if n.rack else "",
            "status": n.status or "",
            "cpu_cores": n.cpu_cores or 0,
            "memory_gb": n.memory_gb or 0,
        })
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "exadata",
        "nodes": rows,
    }


def generate_exadata_operations(db: Session) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(days=30)
    events = apply_platform_filter(
        db.query(SystemEvent).filter(SystemEvent.created_at >= since),
        "exadata",
        db,
    ).all()
    return _events_to_operations_payload(events, 30, "exadata")


def generate_exadata_risk(db: Session) -> Dict[str, Any]:
    from app.models.exadata import ExadataRack

    racks = db.query(ExadataRack).all()
    unhealthy = [
        {"rack": r.name, "health": r.status or "unknown", "datacenter": r.datacenter or ""}
        for r in racks
        if (r.status or "").lower() in ("critical", "warning", "degraded", "offline")
    ]
    events = _active_events(db, "exadata", 48)
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "exadata",
        "unhealthy_racks": unhealthy,
        "active_events": len(events),
    }


def generate_exadata_node_health(db: Session) -> Dict[str, Any]:
    from app.models.exadata import ExadataNode

    nodes = db.query(ExadataNode).order_by(ExadataNode.rack_id, ExadataNode.name).all()
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "platform": "exadata",
        "nodes": [
            {
                "name": n.name,
                "role": n.role.value if hasattr(n.role, "value") else str(n.role),
                "status": n.status or "unknown",
                "linked_server_id": n.server_id,
            }
            for n in nodes
        ],
    }


GENERATORS: Dict[str, Dict[str, Callable[[Session], Dict[str, Any]]]] = {
    "linux": {
        "executive_summary": generate_linux_executive_summary,
        "capacity": generate_linux_capacity,
        "operations": generate_linux_operations,
        "risk": generate_linux_risk,
        "performance": generate_linux_performance,
        "patch_status": generate_linux_patch_status,
        "security": generate_linux_security,
        "sla": generate_linux_sla,
        "monitoring_coverage": generate_linux_monitoring_coverage,
    },
    "windows": {
        "executive_summary": generate_windows_executive_summary,
        "operations": generate_windows_operations,
        "risk": generate_windows_risk,
        "security": generate_windows_security,
        "patch_status": generate_windows_patch_status,
        "sla": generate_windows_sla,
        "monitoring_coverage": generate_windows_monitoring_coverage,
    },
    "exadata": {
        "executive_summary": generate_exadata_executive_summary,
        "capacity": generate_exadata_capacity,
        "operations": generate_exadata_operations,
        "risk": generate_exadata_risk,
        "node_health": generate_exadata_node_health,
    },
}


def generate_platform_report(db: Session, platform: str, report_type: str, save: bool = True) -> Dict[str, Any]:
    plat = platform.lower()
    if plat not in PLATFORM_CATALOG:
        raise ValueError(f"Desteklenmeyen platform: {platform}")
    registry = GENERATORS.get(plat, {})
    fn = registry.get(report_type)
    if not fn:
        raise ValueError(f"Platform {platform} için bilinmeyen rapor: {report_type}")

    data = fn(db)
    title = REPORT_TITLES.get(report_type, report_type)
    storage_key = _storage_key(plat, report_type)

    if save:
        from app.models.infrastructure_report import InfrastructureReport

        obj = InfrastructureReport(
            report_type=storage_key,
            report_title=f"[{plat.upper()}] {title}",
            data=data,
            status="ready",
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        data["_report_id"] = obj.id
        data["_report_title"] = obj.report_title

    data["report_type"] = report_type
    data["platform"] = plat
    return data


def get_latest_platform_report(db: Session, platform: str, report_type: str) -> Optional[Dict[str, Any]]:
    from app.models.infrastructure_report import InfrastructureReport

    storage_key = _storage_key(platform, report_type)
    rpt = (
        db.query(InfrastructureReport)
        .filter(InfrastructureReport.report_type == storage_key)
        .order_by(InfrastructureReport.generated_at.desc())
        .first()
    )
    if not rpt:
        return None
    return {
        **rpt.data,
        "_report_id": rpt.id,
        "_report_title": rpt.report_title,
        "_generated_at": rpt.generated_at.isoformat() if rpt.generated_at else None,
        "report_type": report_type,
        "platform": platform,
    }


def format_platform_report_markdown(platform: str, report_type: str, data: Dict[str, Any]) -> str:
    title = REPORT_TITLES.get(report_type, report_type)
    ts = (data.get("generated_at") or "")[:16]
    lines = [f"# [{platform.upper()}] {title}", f"*Oluşturulma: {ts}*", ""]

    def section(name: str, rows: List[List[Any]]) -> None:
        if not rows:
            return
        lines.append(f"## {name}")
        lines.append("| " + " | ".join(str(h) for h in rows[0]) + " |")
        lines.append("| " + " | ".join("---" for _ in rows[0]) + " |")
        for row in rows[1:]:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")
        lines.append("")

    if report_type == "executive_summary":
        inv = data.get("inventory", {})
        health = data.get("health", {})
        lines.append(f"**Risk:** {data.get('risk_level', '?')}")
        lines.append(f"**Sağlık Skoru:** {health.get('score', health.get('critical_events', '—'))}")
        section("Envanter", [
            ["Metrik", "Değer"],
            *[[k, v] for k, v in inv.items()],
        ])
    elif report_type == "capacity":
        tops = data.get("top_servers") or data.get("nodes") or []
        if tops:
            keys = list(tops[0].keys()) if tops else []
            section("Kapasite", [[k.replace("_", " ").title() for k in keys]] + [[r.get(k, "") for k in keys] for r in tops[:15]])
    elif report_type == "operations":
        lines.append(f"**Toplam olay:** {data.get('total_events', 0)}")
        tops = data.get("event_breakdown") or []
        if tops:
            section("Olay Tipleri", [["Tip", "Adet", "Önem"]] + [[t["type"], t["count"], t.get("severity", "")] for t in tops])
    elif report_type == "risk":
        risky = data.get("risky_servers") or data.get("unhealthy_racks") or []
        if risky:
            keys = list(risky[0].keys())
            section("Risk", [[k.title() for k in keys]] + [[r.get(k, "") for k in keys] for r in risky[:15]])
    else:
        for key, val in data.items():
            if key.startswith("_") or key in ("generated_at", "platform", "report_type"):
                continue
            if isinstance(val, list) and val and isinstance(val[0], dict):
                keys = list(val[0].keys())
                section(key.replace("_", " ").title(), [[k.title() for k in keys]] + [[r.get(k, "") for k in keys] for r in val[:20]])
            elif not isinstance(val, (dict, list)):
                lines.append(f"- **{key}:** {val}")

    recs = data.get("recommendations")
    if recs:
        lines.append("## Öneriler")
        lines.extend(f"- {r}" for r in recs)

    note = data.get("note")
    if note:
        lines.append(f"\n*{note}*")

    return "\n".join(lines)
