"""
Sanallaştırma Katmanı Komuta Merkezi — vCenter, OLVM/oVirt, ESX host kaynak ve platform logları.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func as sa_func, or_
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.event import SystemEvent
from app.models.hypervisor import Hypervisor
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.server import Server

logger = logging.getLogger(__name__)

SEV_RANK = {"critical": 3, "warning": 2, "info": 1}
PLATFORM_LABELS = {
    "vmware": "vCenter",
    "kvm": "OLVM / oVirt",
    "hyperv": "Hyper-V",
    "proxmox": "Proxmox",
    "xen": "Xen",
    "openshift_virt": "OpenShift Virtualization",
}


def _sev_from_pct(pct: Optional[float], crit: float, warn: float) -> Optional[str]:
    if pct is None:
        return None
    if pct >= crit:
        return "critical"
    if pct >= warn:
        return "warning"
    return None


def _health_score(critical: int, warning: int, host_count: int, manager_count: int) -> Dict[str, Any]:
    if manager_count == 0 and host_count == 0:
        return {"score": 100, "grade": "A", "label": "Veri Yok", "color": "slate"}

    penalty = critical * 15 + warning * 5
    denom = max(host_count + manager_count, 1)
    score = max(0, min(100, round(100 - penalty / denom)))
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
    return {"score": score, "grade": grade, "label": label, "color": color}


def _latest_host_metrics(db: Session, hypervisor_id: int) -> List[HypervisorHostMetric]:
    subq = (
        db.query(
            HypervisorHostMetric.host_name,
            sa_func.max(HypervisorHostMetric.timestamp).label("last_ts"),
        )
        .filter(HypervisorHostMetric.hypervisor_id == hypervisor_id)
        .group_by(HypervisorHostMetric.host_name)
        .subquery()
    )
    return (
        db.query(HypervisorHostMetric)
        .join(
            subq,
            (HypervisorHostMetric.host_name == subq.c.host_name)
            & (HypervisorHostMetric.timestamp == subq.c.last_ts),
        )
        .filter(HypervisorHostMetric.hypervisor_id == hypervisor_id)
        .all()
    )


def _host_issues(host: HypervisorHostMetric, hv_name: str, platform: str) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    ts = host.timestamp.isoformat() if host.timestamp else None

    conn = (host.connection_state or "").lower()
    if conn and conn not in ("connected", "up"):
        issues.append({
            "severity": "critical",
            "category": "connectivity",
            "title": f"Host bağlantısı: {host.connection_state}",
            "detail": f"{host.host_name} yönetim platformuna bağlı değil",
            "timestamp": ts,
        })

    if host.maintenance_mode:
        issues.append({
            "severity": "warning",
            "category": "maintenance",
            "title": "Bakım modu aktif",
            "detail": host.host_name,
            "timestamp": ts,
        })

    for label, pct, crit, warn, cat in [
        ("CPU", host.cpu_usage_pct, 90, 75, "cpu"),
        ("RAM", host.mem_usage_pct, 93, 82, "memory"),
        ("Disk", host.ds_usage_pct, 90, 80, "disk"),
    ]:
        sev = _sev_from_pct(pct, crit, warn)
        if sev:
            issues.append({
                "severity": sev,
                "category": cat,
                "title": f"{label} doluluk %{pct:.0f}",
                "detail": f"{host.host_name} — {hv_name} ({platform})",
                "value": round(pct, 1),
                "timestamp": ts,
            })

    return issues


def _manager_status(hv: Hypervisor, hosts: List[HypervisorHostMetric], vm_stats: Dict[str, int]) -> Dict[str, Any]:
    htype = hv.hypervisor_type.value if hv.hypervisor_type else "unknown"
    platform = PLATFORM_LABELS.get(htype, htype.upper())
    issues: List[Dict[str, Any]] = []

    last_metric_ts = max((h.timestamp for h in hosts if h.timestamp), default=None)
    stale_minutes: Optional[int] = None
    if last_metric_ts:
        stale_minutes = int((datetime.now(timezone.utc) - last_metric_ts.replace(tzinfo=timezone.utc)).total_seconds() / 60)
        if stale_minutes > 30:
            issues.append({
                "severity": "warning" if stale_minutes < 120 else "critical",
                "title": "Metrik sync gecikmesi",
                "detail": f"Son metrik {stale_minutes} dk önce",
            })
    elif htype == "vmware":
        issues.append({
            "severity": "warning",
            "title": "Host metrik verisi yok",
            "detail": "ESX metrik sync henüz çalışmamış olabilir",
        })

    disconnected = sum(
        1 for h in hosts
        if (h.connection_state or "").lower() not in ("connected", "up", "")
        and h.connection_state
    )
    if disconnected:
        issues.append({
            "severity": "critical",
            "title": f"{disconnected} host bağlantı sorunu",
            "detail": "connection_state != connected",
        })

    max_sev = max((SEV_RANK.get(i["severity"], 0) for i in issues), default=0)
    sev_label = "ok" if max_sev == 0 else ("critical" if max_sev >= 3 else "warning")

    return {
        "id": hv.id,
        "name": hv.name,
        "type": htype,
        "platform": platform,
        "hostname": hv.hostname,
        "ip_address": hv.ip_address,
        "port": hv.port,
        "host_count": len(hosts),
        "vm_total": vm_stats.get("total", 0),
        "vm_running": vm_stats.get("running", 0),
        "vm_offline": vm_stats.get("offline", 0),
        "avg_cpu_pct": round(sum(h.cpu_usage_pct or 0 for h in hosts) / len(hosts), 1) if hosts else 0,
        "avg_mem_pct": round(sum(h.mem_usage_pct or 0 for h in hosts) / len(hosts), 1) if hosts else 0,
        "avg_disk_pct": round(sum(h.ds_usage_pct or 0 for h in hosts) / len(hosts), 1) if hosts else 0,
        "last_metric_at": last_metric_ts.isoformat() if last_metric_ts else None,
        "status": sev_label,
        "issues": issues,
    }


def _platform_logs(db: Session, hours: int = 24, limit: int = 40) -> List[Dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.created_at >= since,
            or_(
                AuditLog.category == "snapshot",
                AuditLog.action.ilike("%sync%"),
                AuditLog.action.ilike("%hypervisor%"),
                AuditLog.action.ilike("%snapshot%"),
                AuditLog.summary.ilike("%hypervisor%"),
                AuditLog.summary.ilike("%vcenter%"),
                AuditLog.summary.ilike("%olvm%"),
                AuditLog.summary.ilike("%oVirt%"),
                AuditLog.summary.ilike("%esx%"),
                AuditLog.summary.ilike("%vmware%"),
                AuditLog.summary.ilike("%snapshot%"),
                AuditLog.summary.ilike("%sanallaştır%"),
                AuditLog.summary.ilike("%virtual%"),
            ),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    logs = []
    for r in rows:
        sev = "info"
        if r.status in ("failure", "blocked", "rejected"):
            sev = "critical"
        elif r.status == "pending":
            sev = "warning"
        logs.append({
            "id": r.id,
            "source": "audit",
            "severity": sev,
            "category": r.category,
            "action": r.action,
            "title": r.summary or r.action,
            "actor": r.actor_name,
            "status": r.status,
            "timestamp": r.created_at.isoformat() if r.created_at else None,
        })
    return logs


def _vcenter_logs_from_db(db: Session, hours: int = 24, limit: int = 50) -> List[Dict[str, Any]]:
    """DB'deki vCenter event/alarm/task kayıtlarını komuta merkezi log formatına çevirir."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.source.in_(["vcenter_event", "vcenter_alarm", "vcenter_task"]),
            SystemEvent.created_at >= since,
        )
        .order_by(SystemEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    logs = []
    for r in rows:
        raw = r.raw_data or {}
        source_label = {
            "vcenter_event": "vCenter Event",
            "vcenter_alarm": "vCenter Alarm",
            "vcenter_task": "vCenter Task",
        }.get(r.source or "", "vCenter")
        logs.append({
            "id": f"vcenter-{r.id}",
            "source": r.source,
            "source_label": source_label,
            "severity": r.severity or "info",
            "category": raw.get("category") or r.event_type,
            "action": raw.get("action") or raw.get("event_type_id"),
            "title": r.title,
            "detail": r.description,
            "actor": raw.get("actor") or raw.get("user_name"),
            "platform": raw.get("platform_label") or "vCenter",
            "host_name": raw.get("host_name") or raw.get("host_ref"),
            "hypervisor_id": raw.get("hypervisor_id"),
            "timestamp": raw.get("timestamp") or (r.created_at.isoformat() if r.created_at else None),
        })
    return logs


def build_virt_command_center(db: Session) -> Dict[str, Any]:
    """Sanallaştırma komuta merkezi verisi."""
    hypervisors = db.query(Hypervisor).all()
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    vm_rows = (
        db.query(Server)
        .filter(Server.hypervisor_id.isnot(None))  # noqa: E711
        .all()
    )
    vm_by_hv: Dict[int, Dict[str, int]] = defaultdict(lambda: {"total": 0, "running": 0, "offline": 0})
    for vm in vm_rows:
        hid = vm.hypervisor_id
        if not hid:
            continue
        vm_by_hv[hid]["total"] += 1
        st = (vm.status or "").upper()
        ps = (vm.vm_power_state or "").lower()
        if st == "ONLINE" or "on" in ps:
            vm_by_hv[hid]["running"] += 1
        else:
            vm_by_hv[hid]["offline"] += 1

    platforms: List[Dict[str, Any]] = []
    critical_hosts: List[Dict[str, Any]] = []
    warning_hosts: List[Dict[str, Any]] = []
    resource_logs: List[Dict[str, Any]] = []
    crit_count = warn_count = 0

    for hv in hypervisors:
        hosts = _latest_host_metrics(db, hv.id)
        htype = hv.hypervisor_type.value if hv.hypervisor_type else "unknown"
        platform = PLATFORM_LABELS.get(htype, htype.upper())
        stats = vm_by_hv.get(hv.id, {"total": 0, "running": 0, "offline": 0})
        platforms.append(_manager_status(hv, hosts, stats))

        for host in hosts:
            issues = _host_issues(host, hv.name, platform)
            if not issues:
                continue
            max_sev = max(SEV_RANK.get(i["severity"], 0) for i in issues)
            card = {
                "alert_type": "host",
                "hypervisor_id": hv.id,
                "hypervisor_name": hv.name,
                "platform": platform,
                "host_name": host.host_name,
                "max_severity": "critical" if max_sev >= 3 else "warning",
                "cpu_usage_pct": host.cpu_usage_pct,
                "mem_usage_pct": host.mem_usage_pct,
                "ds_usage_pct": host.ds_usage_pct,
                "vms_running": host.vms_running,
                "vms_total": host.vms_total,
                "connection_state": host.connection_state,
                "maintenance_mode": bool(host.maintenance_mode),
                "last_updated": host.timestamp.isoformat() if host.timestamp else None,
                "issues": issues,
                "suggested_actions": _suggest_host_actions(issues, platform),
            }
            if card["max_severity"] == "critical":
                critical_hosts.append(card)
                crit_count += 1
            else:
                warning_hosts.append(card)
                warn_count += 1

            for issue in issues:
                resource_logs.append({
                    "id": f"res-{hv.id}-{host.host_name}-{issue['category']}",
                    "source": "resource_monitor",
                    "severity": issue["severity"],
                    "category": issue.get("category", "resource"),
                    "action": "metric.threshold",
                    "title": issue["title"],
                    "detail": issue.get("detail"),
                    "platform": platform,
                    "host_name": host.host_name,
                    "timestamp": issue.get("timestamp"),
                })

    for p in platforms:
        if p["status"] == "critical":
            critical_hosts.append(_platform_alert_card(p))
        elif p["status"] == "warning":
            warning_hosts.append(_platform_alert_card(p))

    critical_hosts.sort(key=lambda c: (-SEV_RANK.get(c["max_severity"], 0), -(c["mem_usage_pct"] or 0)))
    warning_hosts.sort(key=lambda c: (-(c["mem_usage_pct"] or 0),))

    platform_logs = _platform_logs(db)
    vcenter_logs = _vcenter_logs_from_db(db, hours=24, limit=50)
    all_logs = sorted(
        platform_logs + vcenter_logs + resource_logs,
        key=lambda x: x.get("timestamp") or "",
        reverse=True,
    )[:80]

    total_hosts = sum(p["host_count"] for p in platforms)

    health = _health_score(
        len(critical_hosts),
        len(warning_hosts),
        total_hosts,
        len(platforms),
    )

    totals = {
        "hypervisor_count": len(platforms),
        "host_count": total_hosts,
        "vm_total": sum(p["vm_total"] for p in platforms),
        "vm_running": sum(p["vm_running"] for p in platforms),
        "avg_cpu_pct": round(
            sum(p["avg_cpu_pct"] for p in platforms if p["host_count"] > 0)
            / max(sum(1 for p in platforms if p["host_count"] > 0), 1),
            1,
        ),
        "avg_mem_pct": round(
            sum(p["avg_mem_pct"] for p in platforms if p["host_count"] > 0)
            / max(sum(1 for p in platforms if p["host_count"] > 0), 1),
            1,
        ),
    }

    return {
        "health": health,
        "totals": totals,
        "platforms": platforms,
        "critical_hosts": critical_hosts[:20],
        "warning_hosts": warning_hosts[:30],
        "critical_count": len(critical_hosts),
        "warning_count": len(warning_hosts),
        "critical_host_count": crit_count,
        "critical_platform_count": sum(1 for p in platforms if p["status"] == "critical"),
        "warning_host_count": warn_count,
        "warning_platform_count": sum(1 for p in platforms if p["status"] == "warning"),
        "platform_logs": all_logs,
        "vcenter_log_count": len(vcenter_logs),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": 24,
    }


def _suggest_platform_actions(issues: List[Dict[str, Any]], platform: str) -> List[str]:
    actions: List[str] = []
    titles = {i.get("title", "") for i in issues}
    if any("Metrik sync" in t for t in titles):
        actions.append("ESX/host metrik senkronizasyonunu çalıştırın")
    if any("host bağlantı" in t for t in titles):
        actions.append(f"{platform} bağlantısını ve etkilenen host'ları kontrol edin")
    if any("metrik verisi yok" in t for t in titles):
        actions.append("Hypervisor metrik toplayıcısının çalıştığını doğrulayın")
    if not actions:
        actions.append(f"{platform} yönetim konsolunu ve API erişimini kontrol edin")
    return actions[:4]


def _platform_alert_card(p: Dict[str, Any]) -> Dict[str, Any]:
    """Yönetim platformu (vCenter/OLVM) uyarısını host listesinde gösterilebilir karta çevirir."""
    return {
        "alert_type": "platform",
        "hypervisor_id": p["id"],
        "hypervisor_name": p["name"],
        "platform": p["platform"],
        "host_name": p["name"],
        "max_severity": p["status"],
        "cpu_usage_pct": p.get("avg_cpu_pct") or 0,
        "mem_usage_pct": p.get("avg_mem_pct") or 0,
        "ds_usage_pct": p.get("avg_disk_pct") or 0,
        "vms_running": p.get("vm_running", 0),
        "vms_total": p.get("vm_total", 0),
        "connection_state": None,
        "maintenance_mode": False,
        "last_updated": p.get("last_metric_at"),
        "issues": p.get("issues") or [],
        "suggested_actions": _suggest_platform_actions(p.get("issues") or [], p["platform"]),
    }


def _suggest_host_actions(issues: List[Dict[str, Any]], platform: str) -> List[str]:
    actions: List[str] = []
    cats = {i.get("category") for i in issues}
    if "connectivity" in cats:
        actions.append(f"{platform} üzerinde host bağlantı durumunu kontrol et")
    if "memory" in cats:
        actions.append("VM bellek tahsislerini gözden geçir, overcommit kontrol et")
    if "cpu" in cats:
        actions.append("Yoğun VM'leri tespit et (CPU ready / co-stop)")
    if "disk" in cats:
        actions.append("Datastore kullanımını ve snapshot birikimini kontrol et")
    if "maintenance" in cats:
        actions.append("Bakım modundaki host'u operasyon planına al")
    if not actions:
        actions.append("Altyapı Analizi → Kapasite raporu üret")
    return actions[:4]


def virt_ops_summary(db: Session) -> Dict[str, Any]:
    """Navbar badge için hafif özet — full command center üretmez.

    Eski yol `build_virt_command_center` çağırıyordu (kartlar, resource_logs,
    platform listeleri); her 30 sn'de Layout'tan çağrıldığında ana sayfayı
    yavaşlatıyordu. Burada yalnızca kritik/uyarı host sayıları hesaplanır.
    """
    hypervisors = db.query(Hypervisor).all()
    crit_count = warn_count = 0
    for hv in hypervisors:
        htype = hv.hypervisor_type.value if hv.hypervisor_type else "unknown"
        platform = PLATFORM_LABELS.get(htype, htype.upper())
        hosts = _latest_host_metrics(db, hv.id)
        for host in hosts:
            issues = _host_issues(host, hv.name, platform)
            if not issues:
                continue
            max_sev = max(SEV_RANK.get(i["severity"], 0) for i in issues)
            if max_sev >= 3:
                crit_count += 1
            else:
                warn_count += 1
    return {
        "critical": crit_count,
        "warning": warn_count,
        "total": crit_count + warn_count,
        "action_needed": crit_count > 0 or warn_count > 0,
    }
