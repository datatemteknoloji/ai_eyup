"""oVirt / OLVM engine events → SystemEvent (platform=virt)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.event import SystemEvent
from app.models.hypervisor import Hypervisor, HypervisorType
from app.services.hypervisor_credentials import hv_password
from app.services.incident_auto import auto_create_or_link_incident
from app.services.vcenter_event_collector import _resolve_server_id

logger = logging.getLogger(__name__)

OVIRT_SOURCE = "ovirt_event"


def _raw(hypervisor: Hypervisor, item: Dict[str, Any], ext_key: str) -> dict:
    return {
        "platform": "virt",
        "platform_label": "OLVM / oVirt",
        "external_key": ext_key,
        "hypervisor_id": hypervisor.id,
        "hypervisor_name": hypervisor.name,
        "event_key": item.get("event_key"),
        "event_type_id": item.get("event_type_id"),
        "vm_ref": item.get("vm_ref"),
        "host_ref": item.get("host_ref"),
        "host_name": item.get("host_name"),
        "entity_name": item.get("entity_name"),
        "user_name": item.get("user_name"),
        "timestamp": item.get("timestamp"),
        "category": "ovirt_event",
        "action": item.get("event_type_id") or "ovirt_event",
        "actor": item.get("user_name"),
    }


def _upsert(db: Session, hypervisor: Hypervisor, item: Dict[str, Any], now: datetime) -> bool:
    ext_key = f"ovirt-hv{hypervisor.id}-{item.get('id') or item.get('event_key')}"
    since = datetime.utcnow() - timedelta(days=7)
    existing_rows = (
        db.query(SystemEvent)
        .filter(SystemEvent.source == OVIRT_SOURCE, SystemEvent.created_at >= since)
        .all()
    )
    for ev in existing_rows:
        if (ev.raw_data or {}).get("external_key") == ext_key:
            ev.last_seen = now
            ev.occurrence_count = (ev.occurrence_count or 1) + 1
            return False
    server_id = _resolve_server_id(
        db, hypervisor.id, item.get("vm_ref"), item.get("host_ref"), item.get("entity_name"),
    )
    db.add(SystemEvent(
        server_id=server_id,
        event_type="ovirt_event",
        severity=item.get("severity") or "info",
        source=OVIRT_SOURCE,
        title=(item.get("title") or "oVirt olayı")[:500],
        description=item.get("title"),
        raw_data=_raw(hypervisor, item, ext_key),
        is_acknowledged=False,
        resolved=False,
        last_seen=now,
        occurrence_count=1,
    ))
    return True


def sync_ovirt_events_for_hypervisor(db: Session, hypervisor: Hypervisor, hours: int = 48) -> Dict[str, Any]:
    htype = hypervisor.hypervisor_type.value if hypervisor.hypervisor_type else ""
    if htype != "kvm":
        return {"skipped": True, "reason": "not_kvm"}
    from app.services.ovirt.ovirt_client import OVirtClient
    from app.services.ovirt.ovirt_parse import OVirtError

    client = OVirtClient(
        host=hypervisor.ip_address or hypervisor.hostname,
        username=hypervisor.username or (hypervisor.connection_config or {}).get("username", ""),
        password=hv_password(hypervisor),
        port=hypervisor.port or 443,
    )
    try:
        payload = client.collect_platform_logs(hours=hours, max_events=800)
    except OVirtError as exc:
        return {"success": False, "errors": [str(exc)], "hypervisor": hypervisor.name}

    now = datetime.utcnow()
    saved = 0
    for ev in payload.get("events") or []:
        if _upsert(db, hypervisor, ev, now):
            saved += 1
    db.commit()
    if saved:
        since = datetime.utcnow() - timedelta(seconds=5)
        for ev in db.query(SystemEvent).filter(
            SystemEvent.source == OVIRT_SOURCE,
            SystemEvent.created_at >= since,
            SystemEvent.severity.in_(["critical", "emergency"]),
        ).all():
            try:
                auto_create_or_link_incident(db, ev)
            except Exception as exc:
                logger.warning("oVirt auto-incident: %s", exc)
    return {
        "success": True,
        "hypervisor": hypervisor.name,
        "fetched": len(payload.get("events") or []),
        "total_saved": saved,
        "errors": payload.get("errors") or [],
    }


def sync_all_ovirt_events(db: Session, hours: int = 48) -> Dict[str, Any]:
    hvs = db.query(Hypervisor).filter(Hypervisor.hypervisor_type == HypervisorType.KVM).all()
    total = 0
    errors: List[str] = []
    results = []
    for hv in hvs:
        try:
            r = sync_ovirt_events_for_hypervisor(db, hv, hours=hours)
            total += r.get("total_saved") or 0
            errors.extend(r.get("errors") or [])
            results.append(r)
        except Exception as exc:
            db.rollback()
            logger.error("oVirt event sync %s: %s", hv.name, exc, exc_info=True)
            errors.append(str(exc))
            results.append({"hypervisor": hv.name, "success": False, "errors": [str(exc)]})
    return {"success": not errors, "total_saved": total, "hypervisors": results, "errors": errors}
