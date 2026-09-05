"""
vCenter event / alarm / task senkronizasyonu → SystemEvent (platform=virt).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.event import SystemEvent
from app.models.hypervisor import Hypervisor
from app.models.server import Server
from app.services.incident_auto import auto_create_or_link_incident
from app.services.hypervisor_credentials import hv_password

logger = logging.getLogger(__name__)

VCENTER_SOURCES = ("vcenter_event", "vcenter_alarm", "vcenter_task")

# Alarm 'Virtual machine CPU usage' on myvm ...
_TITLE_ENTITY_RE = re.compile(
    r"(?:Alarm\s+'[^']*'\s+on\s+|[\s\"]on\s+)([A-Za-z0-9][A-Za-z0-9_.:\-]{0,120})",
    re.IGNORECASE,
)
_MOR_RE = re.compile(r"^(vm|host|domain|alarm|group|resgroup|datastore|folder)-\d+$", re.I)


def _entity_name_from_title(title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    m = _TITLE_ENTITY_RE.search(title)
    if not m:
        return None
    name = (m.group(1) or "").strip().rstrip(".,;:")
    if not name or _MOR_RE.match(name):
        return None
    return name


def _friendly_label(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip()
    if not s or _MOR_RE.match(s):
        return None
    return s


def _resolve_server_id(
    db: Session,
    hypervisor_id: int,
    vm_ref: Optional[str],
    host_ref: Optional[str],
    entity_name: Optional[str] = None,
) -> Optional[int]:
    if vm_ref:
        srv = (
            db.query(Server)
            .filter(Server.hypervisor_id == hypervisor_id, Server.hypervisor_vm_id == vm_ref)
            .first()
        )
        if srv:
            return srv.id

    if host_ref:
        srv = (
            db.query(Server)
            .filter(Server.hypervisor_id == hypervisor_id, Server.hypervisor_vm_id == host_ref)
            .first()
        )
        if srv:
            return srv.id

    name = (entity_name or "").strip()
    if name:
        srv = (
            db.query(Server)
            .filter(
                Server.hypervisor_id == hypervisor_id,
                or_(
                    Server.vm_name == name,
                    Server.name == name,
                    Server.hostname == name,
                    Server.vm_guest_hostname == name,
                ),
            )
            .first()
        )
        if srv:
            return srv.id
    return None


def _enrich_item_refs(item: Dict[str, Any]) -> Dict[str, Any]:
    """entity_ref / title'dan vm_ref ve entity_name doldur."""
    out = dict(item)
    entity_type = out.get("entity_type")
    entity_ref = out.get("entity_ref")
    if not out.get("vm_ref") and entity_type == "VirtualMachine" and entity_ref:
        out["vm_ref"] = entity_ref
    if not out.get("host_ref") and entity_type == "HostSystem" and entity_ref:
        out["host_ref"] = entity_ref
    if not out.get("entity_name"):
        out["entity_name"] = _entity_name_from_title(out.get("title"))
    return out


def _build_raw_data(hypervisor: Hypervisor, item: Dict[str, Any], event_type: str, ext_key: str) -> dict:
    entity_name = _friendly_label(item.get("entity_name"))
    host_name = (
        entity_name
        or _friendly_label(item.get("host_name"))
        or _friendly_label(item.get("vm_name"))
    )
    return {
        "platform": "virt",
        "platform_label": "vCenter",
        "external_key": ext_key,
        "hypervisor_id": hypervisor.id,
        "hypervisor_name": hypervisor.name,
        "vcenter_host": hypervisor.ip_address or hypervisor.hostname,
        "event_key": item.get("event_key"),
        "chain_id": item.get("chain_id"),
        "event_type_id": item.get("event_type_id"),
        "vm_ref": item.get("vm_ref"),
        "host_ref": item.get("host_ref"),
        "host_name": host_name,
        "entity_name": entity_name,
        "user_name": item.get("user_name"),
        "alarm_ref": item.get("alarm_ref"),
        "entity_type": item.get("entity_type"),
        "entity_ref": item.get("entity_ref"),
        "overall_status": item.get("overall_status"),
        "timestamp": item.get("timestamp"),
        "category": event_type,
        "action": item.get("event_type_id") or event_type,
        "actor": item.get("user_name"),
    }


def _backfill_existing_event(
    ev: SystemEvent,
    db: Session,
    hypervisor: Hypervisor,
    item: Dict[str, Any],
    now: datetime,
) -> None:
    """Mevcut satırlarda eksik server_id / display alanlarını iyileştir."""
    item = _enrich_item_refs(item)
    updated = False
    if not ev.server_id:
        sid = _resolve_server_id(
            db,
            hypervisor.id,
            item.get("vm_ref"),
            item.get("host_ref"),
            item.get("entity_name"),
        )
        if sid:
            ev.server_id = sid
            updated = True

    raw = dict(ev.raw_data or {})
    entity_name = _friendly_label(item.get("entity_name")) or _friendly_label(raw.get("entity_name"))
    if entity_name and raw.get("entity_name") != entity_name:
        raw["entity_name"] = entity_name
        updated = True
    if not _friendly_label(raw.get("host_name")) and entity_name:
        raw["host_name"] = entity_name
        updated = True
    if not raw.get("platform_label"):
        raw["platform_label"] = "vCenter"
        updated = True
    if not raw.get("hypervisor_name") and hypervisor.name:
        raw["hypervisor_name"] = hypervisor.name
        updated = True
    if item.get("vm_ref") and not raw.get("vm_ref"):
        raw["vm_ref"] = item.get("vm_ref")
        updated = True
    if updated:
        ev.raw_data = raw
        flag_modified(ev, "raw_data")

    ev.last_seen = now
    ev.occurrence_count = (ev.occurrence_count or 1) + 1
    if item.get("severity"):
        ev.severity = item.get("severity") or ev.severity
    if item.get("severity") in ("critical", "emergency"):
        ev.resolved = False


def _upsert_vcenter_event(
    db: Session,
    hypervisor: Hypervisor,
    item: Dict[str, Any],
    source: str,
    event_type: str,
    now: datetime,
) -> bool:
    item = _enrich_item_refs(item)
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
            _backfill_existing_event(ev, db, hypervisor, item, now)
            return False

    server_id = _resolve_server_id(
        db,
        hypervisor.id,
        item.get("vm_ref"),
        item.get("host_ref"),
        item.get("entity_name"),
    )

    title = item.get("title") or "vCenter olayı"
    event = SystemEvent(
        server_id=server_id,
        event_type=event_type,
        severity=item.get("severity") or "info",
        source=source,
        title=title[:500],
        description=item.get("title"),
        raw_data=_build_raw_data(hypervisor, item, event_type, ext_key),
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
        password=hv_password(hypervisor),
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


# ── Uzun pencereli (30 gün) tip-filtreli event taraması ──────────────────────
#
# collect_platform_logs() filtresiz collector kullanır: login/logout gürültüsü
# sayfaları doldurduğu için 48 saatten geriye güvenilir kapsama vermez.
# Aşağıdaki liste EventFilterSpec.eventTypeId ile SUNUCU tarafında süzülür;
# "son 7/30 günde tekrarlayan problem", "DRS kaç kez VM taşıdı", "host bağlantı
# kaybı yaşandı mı" sorularının veri kaynağı budur.
LIFECYCLE_EVENT_TYPES: List[str] = [
    # HA / host erişilebilirlik
    "HostConnectionLostEvent",
    "HostReconnectionFailedEvent",
    "HostSyncFailedEvent",
    "HostNotRespondingEvent",
    "DasHostFailedEvent",
    "DasHostIsolatedEvent",
    "DasAgentUnavailableEvent",
    "DasClusterIsolatedEvent",
    # VM güç / HA restart / hata
    "VmFailedToPowerOnEvent",
    "VmFailedToPowerOffEvent",
    "VmDiskFailedEvent",
    "VmFailoverFailed",
    "VmDasBeingResetEvent",
    "VmDasResetFailedEvent",
    "VmPoweredOffEvent",
    "VmPoweredOnEvent",
    # DRS / migration geçmişi
    "DrsVmMigratedEvent",
    "VmMigratedEvent",
    "VmRelocatedEvent",
    "DrsVmPoweredOnEvent",
    "DrsSoftRuleViolationEvent",
    "NotEnoughResourcesToStartVmEvent",
    # Storage
    "DatastoreCapacityIncreasedEvent",
    "VmDiskConsolidatedFailedEvent",
    # Yaşam döngüsü
    "VmCreatedEvent",
    "VmRemovedEvent",
    "VmClonedEvent",
]


def sync_vcenter_lifecycle_events(
    db: Session, days: int = 30, max_events: int = 3000,
) -> Dict[str, Any]:
    """Tip filtreli GENİŞ pencere event taraması (varsayılan 30 gün).

    `sync_all_vcenter_events` ile aynı `system_events` tablosuna yazar; aynı
    external_key üretildiği için mükerrer kayıt oluşmaz (upsert davranışı).
    """
    from app.services.vmware.vcenter_client import VCenterClient

    vmware_hvs = [
        h for h in db.query(Hypervisor).all()
        if (h.hypervisor_type.value if h.hypervisor_type else "") == "vmware"
    ]
    if not vmware_hvs:
        return {"success": True, "total_saved": 0, "hypervisors": 0}

    now = datetime.utcnow()
    total_saved = 0
    fetched = 0
    errors: List[str] = []

    for hv in vmware_hvs:
        try:
            client = VCenterClient(
                host=hv.ip_address or hv.hostname,
                username=hv.username or (hv.connection_config or {}).get("username", ""),
                password=hv_password(hv),
                port=hv.port or 443,
            )
            payload = client.query_lifecycle_events(
                event_type_ids=LIFECYCLE_EVENT_TYPES,
                days=days,
                max_events=max_events,
            )
            events = payload.get("events") or []
            fetched += len(events)
            errors.extend(payload.get("errors") or [])

            for ev in events:
                kind = ev.get("kind") or "vcenter_event"
                source = kind if kind in VCENTER_SOURCES else "vcenter_event"
                if _upsert_vcenter_event(db, hv, ev, source, kind, now):
                    total_saved += 1
            db.commit()
            logger.info(
                "vCenter lifecycle event sync: %s → %s olay (%s gün, %s yeni)",
                hv.name, len(events), days, total_saved,
            )
        except Exception as exc:
            db.rollback()
            logger.error(
                "vCenter lifecycle event sync hatası (%s): %s", hv.name, exc, exc_info=True
            )
            errors.append(f"{hv.name}: {exc}")

    return {
        "success": not errors,
        "hypervisors": len(vmware_hvs),
        "days": days,
        "fetched_events": fetched,
        "total_saved": total_saved,
        "errors": errors,
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
