"""
OpenShift Virtualization (KubeVirt) event senkronizasyonu → SystemEvent (platform=virt).
vcenter_event_collector.py deseninin sadeleştirilmiş sürümü.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.event import SystemEvent
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.server import Server
from app.services.incident_auto import auto_create_or_link_incident

logger = logging.getLogger(__name__)

OPENSHIFT_VIRT_SOURCE = "openshift_virt_event"


def _resolve_server_id(db: Session, hypervisor_id: int, source_object: str) -> "int | None":
    if not source_object or "/" not in source_object:
        return None
    _, name = source_object.split("/", 1)
    srv = (
        db.query(Server)
        .filter(Server.hypervisor_id == hypervisor_id, Server.name == name)
        .first()
    )
    return srv.id if srv else None


def _upsert_openshift_virt_event(
    db: Session, hypervisor: Hypervisor, item: Dict[str, Any], now: datetime
) -> bool:
    ext_key = f"hv{hypervisor.id}-{item.get('source_object')}-{item.get('reason')}-{item.get('timestamp')}"
    since = datetime.utcnow() - timedelta(days=7)

    existing_rows = (
        db.query(SystemEvent)
        .filter(SystemEvent.source == OPENSHIFT_VIRT_SOURCE, SystemEvent.created_at >= since)
        .all()
    )
    for ev in existing_rows:
        raw = ev.raw_data or {}
        if raw.get("external_key") == ext_key:
            ev.last_seen = now
            ev.occurrence_count = (ev.occurrence_count or 1) + 1
            if item.get("severity"):
                ev.severity = item["severity"]
            return False

    server_id = _resolve_server_id(db, hypervisor.id, item.get("source_object", ""))
    title = item.get("title") or "OpenShift Virtualization olayı"
    event = SystemEvent(
        server_id=server_id,
        event_type="openshift_virt_event",
        severity=item.get("severity") or "info",
        source=OPENSHIFT_VIRT_SOURCE,
        title=title[:500],
        description=item.get("description"),
        raw_data={
            "platform": "virt",
            "platform_label": "OpenShift Virtualization",
            "external_key": ext_key,
            "hypervisor_id": hypervisor.id,
            "hypervisor_name": hypervisor.name,
            "namespace": item.get("namespace"),
            "source_object": item.get("source_object"),
            "reason": item.get("reason"),
            "timestamp": item.get("timestamp"),
        },
        is_acknowledged=False,
        resolved=False,
        last_seen=now,
        occurrence_count=1,
    )
    db.add(event)
    return True


def sync_openshift_virt_events_for_hypervisor(db: Session, hypervisor: Hypervisor, hours: int = 48) -> Dict[str, Any]:
    """Tek OpenShift Virtualization hypervisor'ı için event sync."""
    from app.services.openshift.kubevirt_client import KubeVirtClient

    htype = hypervisor.hypervisor_type.value if hypervisor.hypervisor_type else ""
    if htype != "openshift_virt":
        return {"skipped": True, "reason": "not_openshift_virt"}

    cc = hypervisor.connection_config or {}
    use_creds = bool(cc.get("username")) and bool(cc.get("password"))
    client = KubeVirtClient(
        api_url=cc.get("api_url") or hypervisor.hostname or hypervisor.ip_address,
        token="" if use_creds else (cc.get("token") or hypervisor.password or ""),
        username=cc.get("username") or "",
        password=cc.get("password") or "",
        verify_ssl=bool(cc.get("verify_ssl", False)),
    )

    try:
        items = client.list_events(hours=hours)
    except Exception as e:
        logger.exception("OpenShift Virtualization event sync error (hv=%s)", hypervisor.id)
        return {"success": False, "errors": [str(e)]}
    finally:
        client.logout()

    now = datetime.utcnow()
    saved = 0
    for item in items:
        if _upsert_openshift_virt_event(db, hypervisor, item, now):
            saved += 1

    db.commit()

    if saved > 0:
        since_batch = datetime.utcnow() - timedelta(seconds=5)
        new_events = db.query(SystemEvent).filter(
            SystemEvent.source == OPENSHIFT_VIRT_SOURCE,
            SystemEvent.created_at >= since_batch,
            SystemEvent.severity.in_(["critical", "emergency"]),
        ).all()
        for ev in new_events:
            try:
                auto_create_or_link_incident(db, ev)
            except Exception as exc:
                logger.warning("[AutoIncident] OpenShift Virt event #%s: %s", ev.id, exc)

    return {"success": True, "hypervisor": hypervisor.name, "total_saved": saved, "total_events": len(items)}


def sync_all_openshift_virt_events(db: Session, hours: int = 48) -> Dict[str, Any]:
    """Tüm OpenShift Virtualization hypervisor'larından event sync."""
    hvs = db.query(Hypervisor).filter(Hypervisor.hypervisor_type == HypervisorType.OPENSHIFT_VIRT).all()
    results: List[Dict[str, Any]] = []
    total_saved = 0
    for hv in hvs:
        try:
            r = sync_openshift_virt_events_for_hypervisor(db, hv, hours=hours)
            results.append(r)
            total_saved += r.get("total_saved", 0)
        except Exception as e:
            logger.exception("OpenShift Virt event sync failed for %s", hv.name)
            results.append({"success": False, "hypervisor": hv.name, "errors": [str(e)]})
    return {"success": True, "total_saved": total_saved, "hypervisors": results}
