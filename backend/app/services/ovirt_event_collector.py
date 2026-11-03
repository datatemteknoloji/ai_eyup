"""oVirt / OLVM engine events → SystemEvent (platform=virt)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from app.core.timeutil import utc_now
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.event import SystemEvent
from app.models.hypervisor import Hypervisor, HypervisorType
from app.services.event_dedupe import ExternalKeyIndex, find_existing_event
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


def _upsert(db: Session, hypervisor: Hypervisor, item: Dict[str, Any], now: datetime,
            index: Optional[ExternalKeyIndex] = None) -> bool:
    ext_key = f"ovirt-hv{hypervisor.id}-{item.get('id') or item.get('event_key')}"
    ev = find_existing_event(db, OVIRT_SOURCE, ext_key, index)  # Adım 11: tüm satırları yükleme yok
    if ev is not None:
        # Aynı oVirt olay id'si akış penceresinde yeniden görünür — tekrar değildir; last_seen/occurrence
        # artırılmaz (aksi halde olay pencere bitene kadar «aktif» kalır, bkz. event_lifecycle.py).
        return False
    server_id = _resolve_server_id(
        db, hypervisor.id, item.get("vm_ref"), item.get("host_ref"), item.get("entity_name"),
    )
    new_ev = SystemEvent(
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
    )
    db.add(new_ev)
    if index is not None:
        index.add(OVIRT_SOURCE, ext_key, new_ev)
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

    now = utc_now()
    saved = 0
    index = ExternalKeyIndex(db)
    for ev in payload.get("events") or []:
        if _upsert(db, hypervisor, ev, now, index):
            saved += 1
    db.commit()
    if saved:
        since = utc_now() - timedelta(seconds=5)
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
