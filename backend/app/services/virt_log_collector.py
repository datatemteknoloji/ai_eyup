"""
Sanallaştırma log/olay senkronizasyonu — virt_ops_center verisini SystemEvent'e yazar.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.event import SystemEvent
from app.services.incident_auto import auto_create_or_link_incident
from app.services.virt_ops_center import build_virt_command_center

logger = logging.getLogger(__name__)


def _external_key(log: Dict[str, Any]) -> str:
    return str(log.get("id") or f"{log.get('source')}-{log.get('title', '')[:80]}")


def _upsert_virt_event(db: Session, log: Dict[str, Any], event_type: str, now: datetime) -> bool:
    ext_key = _external_key(log)
    since = datetime.utcnow() - timedelta(hours=48)

    existing = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.event_type == event_type,
            SystemEvent.source.in_(["virt_collector", "virt_resource"]),
            SystemEvent.created_at >= since,
        )
        .all()
    )
    for ev in existing:
        raw = ev.raw_data or {}
        if raw.get("external_key") == ext_key:
            ev.last_seen = now
            ev.occurrence_count = (ev.occurrence_count or 1) + 1
            ev.severity = log.get("severity") or ev.severity
            if not ev.resolved and log.get("severity") in ("critical", "emergency"):
                ev.resolved = False
            return False

    title = log.get("title") or log.get("action") or "Sanallaştırma olayı"
    sev = log.get("severity") or "warning"
    event = SystemEvent(
        server_id=None,
        event_type=event_type,
        severity=sev,
        source="virt_resource" if log.get("source") == "resource_monitor" else "virt_collector",
        title=title[:500],
        description=log.get("detail") or log.get("title"),
        raw_data={
            "platform": "virt",
            "external_key": ext_key,
            "hypervisor_id": log.get("hypervisor_id"),
            "host_name": log.get("host_name"),
            "platform_label": log.get("platform"),
            "category": log.get("category"),
            "action": log.get("action"),
            "actor": log.get("actor"),
            "timestamp": log.get("timestamp"),
        },
        is_acknowledged=False,
        resolved=False,
        last_seen=now,
        occurrence_count=1,
    )
    db.add(event)
    return True


_LIFECYCLE_STATE_KEY = "vcenter_lifecycle_last_sync"


def _run_lifecycle_scan_if_due(db: Session) -> Dict[str, Any]:
    """Tip filtreli 30 günlük event taramasını günde bir kez çalıştırır.

    Son çalışma zamanı AppSettings'te tutulur; modül değişkeni kullanılmaz ki
    backend restart'ta tarama gereksiz yere tekrar tetiklenmesin.
    """
    from app.models.app_settings import AppSettings
    from app.services.vcenter_event_collector import sync_vcenter_lifecycle_events

    try:
        row = (
            db.query(AppSettings)
            .filter(AppSettings.key == _LIFECYCLE_STATE_KEY)
            .first()
        )
        if row and row.value:
            try:
                last = datetime.fromisoformat(str(row.value))
                if datetime.utcnow() - last < timedelta(hours=24):
                    return {"skipped": True, "reason": "not_due", "last_run": row.value}
            except ValueError:
                pass

        result = sync_vcenter_lifecycle_events(db, days=30)

        stamp = datetime.utcnow().isoformat()
        if row is None:
            db.add(AppSettings(key=_LIFECYCLE_STATE_KEY, value=stamp))
        else:
            row.value = stamp
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        logger.warning("Lifecycle event taraması atlandı: %s", exc)
        return {"success": False, "total_saved": 0, "errors": [str(exc)]}


def sync_virt_logs_to_db(db: Session) -> Dict[str, Any]:
    """Virt komuta merkezi + vCenter/OpenShift Virtualization event/alarm kaynaklarından SystemEvent oluştur/güncelle."""
    from app.services.vcenter_event_collector import sync_all_vcenter_events
    from app.services.openshift_virt_event_collector import sync_all_openshift_virt_events

    vcenter_result = sync_all_vcenter_events(db, hours=48)

    # 48 saatlik filtresiz tarama "son 7/30 gün" sorularını karşılamıyor
    # (login/logout gürültüsü sayfaları dolduruyor). Tip filtreli geniş pencere
    # taraması günde bir kez çalışır — son çalışma zamanı AppSettings'te tutulur.
    lifecycle_result = _run_lifecycle_scan_if_due(db)

    try:
        openshift_virt_result = sync_all_openshift_virt_events(db, hours=48)
    except Exception as exc:
        logger.warning("OpenShift Virtualization event sync atlandı: %s", exc)
        openshift_virt_result = {"success": False, "total_saved": 0, "errors": [str(exc)]}
    data = build_virt_command_center(db)
    now = datetime.utcnow()
    saved = 0

    for host in data.get("critical_hosts", []) + data.get("warning_hosts", []):
        for issue in host.get("issues", []):
            log = {
                "id": f"host-{host['hypervisor_id']}-{host['host_name']}-{issue.get('category')}",
                "source": "resource_monitor",
                "severity": issue.get("severity", "warning"),
                "category": issue.get("category"),
                "title": issue.get("title"),
                "detail": issue.get("detail"),
                "hypervisor_id": host.get("hypervisor_id"),
                "host_name": host.get("host_name"),
                "platform": host.get("platform"),
                "timestamp": issue.get("timestamp") or now.isoformat(),
            }
            if _upsert_virt_event(db, log, "virt_resource", now):
                saved += 1

    for log in data.get("platform_logs", []):
        if _upsert_virt_event(db, log, "virt_log", now):
            saved += 1

    db.commit()

    if saved > 0:
        since_batch = datetime.utcnow() - timedelta(seconds=5)
        new_events = db.query(SystemEvent).filter(
            SystemEvent.source.in_(["virt_collector", "virt_resource"]),
            SystemEvent.created_at >= since_batch,
            SystemEvent.severity.in_(["critical", "emergency"]),
        ).all()
        for ev in new_events:
            try:
                auto_create_or_link_incident(db, ev)
            except Exception as exc:
                logger.warning("[AutoIncident] Virt event #%s: %s", ev.id, exc)

    return {
        "total_saved": (
            saved
            + vcenter_result.get("total_saved", 0)
            + openshift_virt_result.get("total_saved", 0)
            + (lifecycle_result.get("total_saved") or 0)
        ),
        "virt_saved": saved,
        "vcenter_saved": vcenter_result.get("total_saved", 0),
        "lifecycle_saved": lifecycle_result.get("total_saved") or 0,
        "openshift_virt_saved": openshift_virt_result.get("total_saved", 0),
        "critical_hosts": len(data.get("critical_hosts", [])),
        "platform_logs": len(data.get("platform_logs", [])),
        "vcenter_sync": vcenter_result,
        "lifecycle_sync": lifecycle_result,
        "openshift_virt_sync": openshift_virt_result,
    }
