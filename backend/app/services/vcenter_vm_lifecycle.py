"""
vCenter VM yaşam döngüsü sorguları — restart / oluşturma / silme / migration.

`vcenter_event_collector.py` periyodik olarak TÜM event stream'i (login/logout
dahil) 48 saatlik pencerede system_events tablosuna yazar; bu, VM restart /
created / removed gibi düşük hacimli ama önemli event'lerin yoğun login-logout
trafiği arasında kaybolmasına ve 7-30 günlük soruların DB'den güvenilir
cevaplanamamasına yol açar.

Bu modül, `VCenterClient.query_lifecycle_events()` ile SUNUCU TARAFINDA
event-type filtreli SOAP sorguları yaparak istenen tarih aralığını (7/30 gün)
gürültüsüz ve az sayfa ile canlı olarak tarar. AI chat / Q&A katmanı bu
fonksiyonları "deterministic handler" olarak kullanır.
"""
from __future__ import annotations

import contextvars
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor
from app.models.server import Server
from app.services.hypervisor_credentials import hv_password

logger = logging.getLogger(__name__)

# ── Event tipi grupları ──────────────────────────────────────────────────────
RESTART_TYPES = [
    "VmPoweredOffEvent", "VmPoweredOnEvent", "VmResettingEvent",
    "VmGuestRebootEvent", "VmGuestShutdownEvent", "VmSuspendedEvent",
    "VmResumingEvent", "VmFailedToPowerOnEvent",
]
CREATE_TYPES = [
    "VmCreatedEvent", "VmClonedEvent", "VmDeployedEvent", "VmRegisteredEvent",
    "VmBeingCreatedEvent", "VmBeingClonedEvent", "VmBeingDeployedEvent",
]
REMOVE_TYPES = [
    "VmRemovedEvent", "VmBeingUnregisteredEvent", "VmUnregisteredEvent",
]
MIGRATE_TYPES = [
    "VmMigratedEvent", "DrsVmMigratedEvent", "VmBeingMigratedEvent",
    "VmBeingHotMigratedEvent", "VmFailedMigrateEvent", "DrsVmPoweredOnEvent",
]
HOST_LIFECYCLE_TYPES = [
    "HostConnectedEvent", "HostDisconnectedEvent", "HostConnectionLostEvent",
    "HostShutdownEvent", "HostRebootedEvent", "HostNotRespondingEvent",
    "HostNoRedundantManagementNetworkEvent",
]
MAINTENANCE_TYPES = [
    "EnteringMaintenanceModeEvent", "EnteredMaintenanceModeEvent",
    "ExitMaintenanceModeEvent", "ExitingMaintenanceModeEvent",
]
HA_TYPES = [
    "DasHostFailedEvent", "DasEnabledEvent", "DasDisabledEvent",
    "DasClusterIsolatedEvent", "DasAdmissionControlDisabledEvent",
]

RESTART_OFF_TYPES = {"VmPoweredOffEvent", "VmGuestShutdownEvent", "VmSuspendedEvent"}
RESTART_ON_TYPES = {"VmPoweredOnEvent", "VmResumingEvent"}

POWER_ON_STATES = ("poweredon", "up", "running", "powered_on")
POWER_OFF_STATES = ("poweredoff", "down", "off", "powered_off")


def _vmware_hypervisors(db: Session) -> List[Hypervisor]:
    return [
        hv for hv in db.query(Hypervisor).all()
        if (hv.hypervisor_type.value if hv.hypervisor_type else "") == "vmware"
    ]


def _build_client(hv: Hypervisor):
    from app.services.vmware.vcenter_client import VCenterClient
    return VCenterClient(
        host=hv.ip_address or hv.hostname,
        username=hv.username or (hv.connection_config or {}).get("username", ""),
        password=hv_password(hv),
        port=hv.port or 443,
    )


# vCenter fullFormattedMessage kalıpları — en spesifikten en genele sıralı.
# Not: "Created virtual machine X on ..." ve "Creating X on ..." aynı oluşturma
# işleminin iki ayrı event'i olduğundan, ikisi de aynı VM adına çözülür (bu,
# creation_events()'teki isim bazlı dedup'ın bunları tek satıra indirmesini sağlar).
_TITLE_PATTERNS = [
    re.compile(r"^Created\s+virtual\s+machine\s+(.+?)\s+on\s+", re.IGNORECASE),
    re.compile(r"^Creating\s+(.+?)\s+on\s+", re.IGNORECASE),
    re.compile(r"^.+?\s+cloned\s+to\s+(.+?)\s+on\s+", re.IGNORECASE),
    re.compile(r"^Cloning\s+(.+?)\s+on\s+", re.IGNORECASE),
    re.compile(r"^Removed\s+(.+)$", re.IGNORECASE),
    re.compile(r"^([\w\-.\s]+?)\s+(?:on|in)\s+"),
]


def _vm_name_from_event(ev: Dict[str, Any], server_by_ref: Dict[str, str]) -> str:
    vm_ref = ev.get("vm_ref")
    if vm_ref and vm_ref in server_by_ref:
        return server_by_ref[vm_ref]
    title = (ev.get("title") or "").strip()
    for pattern in _TITLE_PATTERNS:
        m = pattern.match(title)
        if m:
            return m.group(1).strip()
    return vm_ref or title or "Bilinmeyen VM"


def _event_ts(ev: Dict[str, Any]):
    """Olay zamanı → tz'li datetime (naif = UTC); ayrıştırılamazsa None."""
    from datetime import datetime as _dt, timezone as _tz
    raw = ev.get("timestamp")
    if not raw:
        return None
    try:
        t = _dt.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=_tz.utc)


def filter_window(events: List[Dict[str, Any]], window: Any) -> List[Dict[str, Any]]:
    """[start, end) dışındaki olayları at (Adım 5c). `window`: chat_quality.time_window.Window."""
    if window is None:
        return events
    out = []
    for ev in events:
        t = _event_ts(ev)
        if t is not None and window.start <= t.astimezone(window.start.tzinfo) < window.end:
            out.append(ev)
    return out


_TRUNCATED: "contextvars.ContextVar[Optional[List[Dict[str, Any]]]]" = contextvars.ContextVar(
    "vcenter_events_truncated", default=None,
)


def pop_truncation() -> List[Dict[str, Any]]:
    """Bu bağlamda `fetch_events` çağrılarında `max_events` sınırına takılan hypervisor'lar (okur ve temizler)."""
    out = _TRUNCATED.get() or []
    _TRUNCATED.set(None)
    return out


def fetch_events(
    db: Session,
    event_type_ids: List[str],
    days: int = 7,
    max_events: int = 3000,
    window: Any = None,
) -> Dict[str, Any]:
    """Tüm VMware hypervisor'lardan verilen tip listesini canlı sorgular.

    `window` verilirse (Adım 5c) olaylar [start, end) ile süzülür; `days` en az pencere başına yetecek kadar olmalı.
    """
    hvs = _vmware_hypervisors(db)
    if not hvs:
        return {"events": [], "errors": ["Tanımlı VMware hypervisor yok"], "hypervisors": 0}

    server_by_ref: Dict[str, str] = {
        s.hypervisor_vm_id: s.name
        for s in db.query(Server).filter(Server.hypervisor_vm_id.isnot(None)).all()
        if s.hypervisor_vm_id
    }

    all_events: List[Dict[str, Any]] = []
    errors: List[str] = []
    truncated: List[Dict[str, Any]] = []
    for hv in hvs:
        client = _build_client(hv)
        try:
            result = client.query_lifecycle_events(event_type_ids, days=days, max_events=max_events)
        except Exception as exc:
            logger.error("query_lifecycle_events failed for %s: %s", hv.name, exc, exc_info=True)
            errors.append(f"{hv.name}: {exc}")
            continue
        errors.extend(f"{hv.name}: {e}" for e in result.get("errors", []))
        if result.get("truncated"):
            truncated.append({"hypervisor": hv.name, "max_events": result.get("max_events") or max_events})
        for ev in result.get("events", []):
            ev["hypervisor"] = hv.name
            ev["vm_name"] = _vm_name_from_event(ev, server_by_ref)
            all_events.append(ev)

    all_events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
    all_events = filter_window(all_events, window)
    if truncated:
        _TRUNCATED.set((_TRUNCATED.get() or []) + truncated)
    return {"events": all_events, "errors": errors, "hypervisors": len(hvs), "truncated": truncated}


def restart_report(db: Session, days: int = 7, window: Any = None) -> Dict[str, Any]:
    """Son N günde restart/power-cycle geçiren VM'ler + sayaç."""
    result = fetch_events(db, RESTART_TYPES, days=days, window=window)
    events = result["events"]

    per_vm: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ev in events:
        per_vm[ev["vm_name"]].append(ev)

    restarts: List[Dict[str, Any]] = []
    for vm_name, evs in per_vm.items():
        evs.sort(key=lambda e: e.get("timestamp") or "")
        cycles = 0
        last_off = None
        for ev in evs:
            etype = ev.get("event_type_id")
            if etype in RESTART_OFF_TYPES:
                last_off = ev
            elif etype in RESTART_ON_TYPES and last_off is not None:
                cycles += 1
                last_off = None
            elif etype == "VmResettingEvent":
                cycles += 1
        if cycles > 0:
            restarts.append({
                "vm_name": vm_name,
                "restart_count": cycles,
                "last_event_at": evs[-1].get("timestamp"),
                "hypervisor": evs[-1].get("hypervisor"),
            })

    restarts.sort(key=lambda r: -r["restart_count"])
    return {
        "days": days,
        "total_restart_events": sum(r["restart_count"] for r in restarts),
        "vm_count": len(restarts),
        "restarts": restarts,
        "raw_event_count": len(events),
        "errors": result["errors"],
        "hypervisors": result.get("hypervisors", 0),
    }


def power_toggle_last_24h(db: Session, days: float = 1, window: Any = None) -> Dict[str, Any]:
    """Verilen pencerede kapatılıp açılan (veya en az bir power-state değişikliği olan) VM'ler."""
    result = fetch_events(db, RESTART_TYPES, days=days, window=window)
    events = result["events"]
    per_vm: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ev in events:
        per_vm[ev["vm_name"]].append(ev)

    toggled = []
    for vm_name, evs in per_vm.items():
        types = {e.get("event_type_id") for e in evs}
        if (types & RESTART_OFF_TYPES) and (types & RESTART_ON_TYPES):
            toggled.append({"vm_name": vm_name, "event_count": len(evs)})
        elif "VmResettingEvent" in types:
            toggled.append({"vm_name": vm_name, "event_count": len(evs)})

    return {"toggled": toggled, "raw_event_count": len(events), "errors": result["errors"]}


def power_state_changes(db: Session, days: int = 7, window: Any = None) -> Dict[str, Any]:
    result = fetch_events(db, RESTART_TYPES, days=days, window=window)
    events = result["events"]
    per_vm: Dict[str, int] = defaultdict(int)
    for ev in events:
        per_vm[ev["vm_name"]] += 1
    changed = sorted(per_vm.items(), key=lambda x: -x[1])
    return {"days": days, "changed": changed, "raw_event_count": len(events), "errors": result["errors"]}


def last_reboot_times(db: Session, days: int = 90, window: Any = None) -> Dict[str, Any]:
    """VM başına son PoweredOn/Reset zamanı (en fazla `days` gün geriye bakar)."""
    result = fetch_events(db, list(RESTART_ON_TYPES) + ["VmResettingEvent"], days=days, window=window)
    events = result["events"]
    last_seen: Dict[str, str] = {}
    for ev in events:
        vm_name = ev["vm_name"]
        ts = ev.get("timestamp") or ""
        if vm_name not in last_seen or ts > last_seen[vm_name]:
            last_seen[vm_name] = ts
    return {"days": days, "last_reboot": last_seen, "raw_event_count": len(events), "errors": result["errors"]}


def creation_events(db: Session, days: int = 30, window: Any = None) -> Dict[str, Any]:
    result = fetch_events(db, CREATE_TYPES, days=days, window=window)
    events = result["events"]
    seen = {}
    for ev in events:
        vm_name = ev["vm_name"]
        if vm_name not in seen:
            seen[vm_name] = ev
    created = sorted(seen.values(), key=lambda e: e.get("timestamp") or "", reverse=True)
    return {"days": days, "created": created, "errors": result["errors"]}


def removal_events(db: Session, days: int = 30, window: Any = None) -> Dict[str, Any]:
    result = fetch_events(db, REMOVE_TYPES, days=days, window=window)
    events = result["events"]
    seen = {}
    for ev in events:
        vm_name = ev["vm_name"]
        if vm_name not in seen:
            seen[vm_name] = ev
    removed = sorted(seen.values(), key=lambda e: e.get("timestamp") or "", reverse=True)
    return {"days": days, "removed": removed, "errors": result["errors"]}


def migration_events(db: Session, days: int = 30, window: Any = None) -> Dict[str, Any]:
    result = fetch_events(db, MIGRATE_TYPES, days=days, window=window)
    events = result["events"]
    failed = [e for e in events if "fail" in (e.get("event_type_id") or "").lower()]
    ok = [e for e in events if e not in failed]
    return {"days": days, "migrations": ok, "failed": failed, "errors": result["errors"]}


def host_lifecycle_events(db: Session, days: int = 30, window: Any = None) -> Dict[str, Any]:
    result = fetch_events(db, HOST_LIFECYCLE_TYPES + MAINTENANCE_TYPES + HA_TYPES, days=days, window=window)
    return {"days": days, "events": result["events"], "errors": result["errors"]}
