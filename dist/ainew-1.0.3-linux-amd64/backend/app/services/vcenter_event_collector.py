"""
vCenter event / alarm / task senkronizasyonu → SystemEvent (platform=virt).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.event import SystemEvent
from app.models.hypervisor import Hypervisor
from app.models.server import Server
from app.services.incident_auto import auto_create_or_link_incident

logger = logging.getLogger(__name__)

VCENTER_SOURCES = ("vcenter_event", "vcenter_alarm", "vcenter_task")


def _resolve_server_id(
    db: Session,
    hypervisor_id: int,
    vm_ref: Optional[str],
    host_ref: Optional[str],
) -> Optional[int]:
    if vm_ref:
        srv = (
            db.query(Server)
            .filter(Server.hypervisor_id == hypervisor_id, Server.hypervisor_vm_id == vm_ref)
            .first()
        )
        if srv:
            return srv.id
    return None


def _upsert_vcenter_event(
    db: Session,
    hypervisor: Hypervisor,
    item: Dict[str, Any],
    source: str,
    event_type: str,
    now: datetime,
) -> bool:
    ext_key = f"hv{hypervisor.id}-{item.get('id') or item.get('event_key')}"
    since = datetime.utcnow() - timedelta(days=7)

    existing_rows = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.source == source,
            SystemEvent.created_at >= since,
        )
        .all()
    )
    for ev in existing_rows:
        raw = ev.raw_data or {}
        if raw.get("external_key") == ext_key:
            ev.last_seen = now
            ev.occurrence_count = (ev.occurrence_count or 1) + 1
            ev.severity = item.get("severity") or ev.severity
            if item.get("severity") in ("critical", "emergency"):
                ev.resolved = False
            return False

    server_id = _resolve_server_id(
        db,
        hypervisor.id,
        item.get("vm_ref"),
        item.get("host_ref"),
    )

    title = item.get("title") or "vCenter olayı"
    event = SystemEvent(
        server_id=server_id,
        event_type=event_type,
        severity=item.get("severity") or "info",
        source=source,
        title=title[:500],
        description=item.get("title"),
        raw_data={
            "platform": "virt",
            "external_key": ext_key,
            "hypervisor_id": hypervisor.id,
            "hypervisor_name": hypervisor.name,
            "vcenter_host": hypervisor.ip_address or hypervisor.hostname,
            "event_key": item.get("event_key"),
            "chain_id": item.get("chain_id"),
            "event_type_id": item.get("event_type_id"),
            "vm_ref": item.get("vm_ref"),
            "host_ref": item.get("host_ref"),
            "host_name": item.get("host_ref"),
            "user_name": item.get("user_name"),
            "alarm_ref": item.get("alarm_ref"),
            "entity_type": item.get("entity_type"),
            "entity_ref": item.get("entity_ref"),
            "overall_status": item.get("overall_status"),
            "timestamp": item.get("timestamp"),
            "category": event_type,
            "action": item.get("event_type_id") or event_type,
            "actor": item.get("user_name"),
        },
        is_acknowledged=False,
        resolved=False,
        last_seen=now,
        occurrence_count=1,
    )
    db.add(event)
    return True


def sync_vcenter_events_for_hypervisor(db: Session, hypervisor: Hypervisor, hours: int = 48) -> Dict[str, Any]:
    """Tek VMware hypervisor için vCenter event/alarm sync."""
    from app.services.vmware.vcenter_client import VCenterClient

    htype = hypervisor.hypervisor_type.value if hypervisor.hypervisor_type else ""
    if htype != "vmware":
        return {"skipped": True, "reason": "not_vmware"}

    client = VCenterClient(
        host=hypervisor.ip_address or hypervisor.hostname,
        username=hypervisor.username or (hypervisor.connection_config or {}).get("username", ""),
        password=hypervisor.password or (hypervisor.connection_config or {}).get("password", ""),
        port=hypervisor.port or 443,
    )
    if not client.login():
        return {"success": False, "errors": ["vCenter login failed"]}

    try:
        payload = client.collect_platform_logs(hours=hours, max_events=800)
    finally:
        client.logout()

    now = datetime.utcnow()
    saved = 0
    stats = {"events": 0, "alarms": 0, "tasks": 0}

    for ev in payload.get("events", []):
        kind = ev.get("kind") or "vcenter_event"
        source = kind if kind in VCENTER_SOURCES else "vcenter_event"
        if _upsert_vcenter_event(db, hypervisor, ev, source, kind, now):
            saved += 1
            if kind == "vcenter_task":
                stats["tasks"] += 1
            else:
                stats["events"] += 1

    for alarm in payload.get("alarms", []):
        if _upsert_vcenter_event(db, hypervisor, alarm, "vcenter_alarm", "vcenter_alarm", now):
            saved += 1
            stats["alarms"] += 1

    db.commit()

    if saved > 0:
        since_batch = datetime.utcnow() - timedelta(seconds=5)
        new_events = db.query(SystemEvent).filter(
            SystemEvent.source.in_(VCENTER_SOURCES),
            SystemEvent.created_at >= since_batch,
            SystemEvent.severity.in_(["critical", "emergency"]),
        ).all()
        for ev in new_events:
            try:
                auto_create_or_link_incident(db, ev)
            except Exception as exc:
                logger.warning("[AutoIncident] vCenter event #%s: %s", ev.id, exc)

    return {
        "success": len(payload.get("errors", [])) == 0,
        "hypervisor": hypervisor.name,
        "total_saved": saved,
        "fetched_events": len(payload.get("events", [])),
        "fetched_alarms": len(payload.get("alarms", [])),
        "stats": stats,
        "errors": payload.get("errors", []),
    }


def sync_all_vcenter_events(db: Session, hours: int = 48) -> Dict[str, Any]:
    """Tüm VMware hypervisor'lardan vCenter event/alarm sync."""
    hypervisors = db.query(Hypervisor).all()
    vmware_hvs = [
        h for h in hypervisors
        if (h.hypervisor_type.value if h.hypervisor_type else "") == "vmware"
    ]
    if not vmware_hvs:
        return {"success": True, "total_saved": 0, "hypervisors": []}

    results = []
    total_saved = 0
    all_errors: List[str] = []

    for hv in vmware_hvs:
        try:
            r = sync_vcenter_events_for_hypervisor(db, hv, hours=hours)
            total_saved += r.get("total_saved", 0)
            all_errors.extend(r.get("errors") or [])
            results.append(r)
        except Exception as exc:
            logger.error("vCenter event sync error for %s: %s", hv.name, exc, exc_info=True)
            db.rollback()
            results.append({"hypervisor": hv.name, "success": False, "errors": [str(exc)]})
            all_errors.append(str(exc))

    return {
        "success": len(all_errors) == 0,
        "total_saved": total_saved,
        "hypervisors": results,
    }
