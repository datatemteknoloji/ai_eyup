"""
Virt DB-first sorgular — chat tool kataloğu L1.

Freshness: as_of / vm_last_sync / vm_stats_as_of ile stale bayrağı.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.server import Server
from app.models.virt_datastore import VirtDatastore
from app.models.event import SystemEvent
from app.services.platform_scope import vm_filter_condition


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _age_seconds(ts: Optional[datetime]) -> Optional[int]:
    if not ts:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return int((_utc_now() - ts).total_seconds())


def _stale(ts: Optional[datetime], max_age_sec: int) -> bool:
    age = _age_seconds(ts)
    if age is None:
        return True
    return age > max_age_sec


def list_vms_db(
    db: Session,
    *,
    hypervisor: Optional[str] = None,
    power_state: Optional[str] = None,
    host_name: Optional[str] = None,
    cluster: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    q = db.query(Server).filter(vm_filter_condition())
    if hypervisor:
        hv = (
            db.query(Hypervisor)
            .filter(Hypervisor.name.ilike(f"%{hypervisor.strip()}%"))
            .first()
        )
        if hv:
            q = q.filter(Server.hypervisor_id == hv.id)
    if power_state:
        # "poweredOn" / "powered_on" / "on" → DB'deki POWERED_ON ile eşleşsin
        # (önceden poweredon, POWERED_ON'daki alt çizgi yüzünden 0 sonuç dönüyordu)
        import re as _re
        from sqlalchemy import func as _sqfn

        ps_norm = _re.sub(r"[\s_\-]+", "", str(power_state).strip().lower())
        aliases = {
            "on": "poweredon",
            "poweredon": "poweredon",
            "poweron": "poweredon",
            "running": "poweredon",
            "acik": "poweredon",
            "açık": "poweredon",
            "off": "poweredoff",
            "poweredoff": "poweredoff",
            "poweroff": "poweredoff",
            "kapali": "poweredoff",
            "kapalı": "poweredoff",
            "suspended": "suspended",
            "suspend": "suspended",
        }
        ps_norm = aliases.get(ps_norm, ps_norm)
        q = q.filter(
            _sqfn.replace(_sqfn.lower(Server.vm_power_state), "_", "").like(f"%{ps_norm}%")
        )
    if host_name:
        q = q.filter(Server.vm_host_name.ilike(f"%{host_name.strip()}%"))
    if cluster:
        q = q.filter(Server.vm_cluster.ilike(f"%{cluster.strip()}%"))

    rows = q.order_by(Server.name.asc()).limit(max(1, min(limit, 500))).all()
    hv_map = {
        h.id: h.name
        for h in db.query(Hypervisor).filter(
            Hypervisor.id.in_({r.hypervisor_id for r in rows if r.hypervisor_id})
        ).all()
    } if rows else {}

    items = []
    oldest_sync = None
    for s in rows:
        sync = s.vm_last_sync
        if sync and (oldest_sync is None or sync < oldest_sync):
            oldest_sync = sync
        items.append({
            "id": s.id,
            "name": s.vm_name or s.name,
            "ip": s.vm_guest_ip or s.ip_address,
            "power_state": s.vm_power_state,
            "vcpu": s.vm_cpu_count,
            "memory_mb": s.vm_memory_mb,
            "disk_gb": s.vm_disk_gb,
            "host": s.vm_host_name,
            "cluster": s.vm_cluster,
            "datastore": s.vm_datastore,
            "guest_os": s.vm_guest_os_full or s.os_type,
            "hypervisor": hv_map.get(s.hypervisor_id),
            "cpu_mhz": s.vm_cpu_usage_mhz,
            "mem_active_mb": s.vm_mem_active_mb,
            "vm_last_sync": sync.isoformat() if sync else None,
            "stats_as_of": s.vm_stats_as_of.isoformat() if s.vm_stats_as_of else None,
        })

    return {
        "ok": True,
        "source": "db",
        "count": len(items),
        "as_of": oldest_sync.isoformat() if oldest_sync else None,
        "stale": _stale(oldest_sync, 12 * 3600),
        "vms": items,
    }


def vm_detail_db(db: Session, *, name: Optional[str] = None, server_id: Optional[int] = None) -> Dict[str, Any]:
    q = db.query(Server).filter(vm_filter_condition())
    if server_id:
        s = q.filter(Server.id == int(server_id)).first()
    elif name:
        n = name.strip()
        s = (
            q.filter(
                (Server.vm_name.ilike(n))
                | (Server.name.ilike(n))
                | (Server.vm_guest_hostname.ilike(n))
            ).first()
        )
    else:
        return {"ok": False, "error": "name veya server_id gerekli"}
    if not s:
        return {"ok": False, "error": "VM bulunamadı"}
    hv = db.query(Hypervisor).filter(Hypervisor.id == s.hypervisor_id).first() if s.hypervisor_id else None
    return {
        "ok": True,
        "source": "db",
        "stale": _stale(s.vm_last_sync, 12 * 3600),
        "vm": {
            "id": s.id,
            "name": s.vm_name or s.name,
            "vm_id": s.hypervisor_vm_id,
            "ip": s.vm_guest_ip or s.ip_address,
            "power_state": s.vm_power_state,
            "tools": s.vm_tools_status,
            "vcpu": s.vm_cpu_count,
            "memory_mb": s.vm_memory_mb,
            "disk_gb": s.vm_disk_gb,
            "disks": s.vm_disks,
            "networks": s.vm_network_info,
            "host": s.vm_host_name,
            "host_ref": s.vm_host_ref,
            "cluster": s.vm_cluster,
            "datastore": s.vm_datastore,
            "guest_os": s.vm_guest_os_full or s.os_type,
            "hw_version": s.vm_hardware_version,
            "hypervisor": hv.name if hv else None,
            "cpu_mhz": s.vm_cpu_usage_mhz,
            "mem_active_mb": s.vm_mem_active_mb,
            "vm_last_sync": s.vm_last_sync.isoformat() if s.vm_last_sync else None,
            "stats_as_of": s.vm_stats_as_of.isoformat() if s.vm_stats_as_of else None,
        },
    }


def list_datastores_db(
    db: Session,
    *,
    hypervisor: Optional[str] = None,
    max_age_min: int = 45,
) -> Dict[str, Any]:
    q = db.query(VirtDatastore)
    hv_id = None
    if hypervisor:
        hv = (
            db.query(Hypervisor)
            .filter(Hypervisor.name.ilike(f"%{hypervisor.strip()}%"))
            .first()
        )
        if hv:
            hv_id = hv.id
            q = q.filter(VirtDatastore.hypervisor_id == hv.id)
    rows = q.order_by(VirtDatastore.usage_pct.desc().nullslast()).all()
    if not rows:
        return {
            "ok": True,
            "source": "db",
            "count": 0,
            "stale": True,
            "datastores": [],
            "hint": "virt_datastores boş — ESX metric sync veya canlı vcenter tool kullanın",
        }
    newest = max((r.as_of for r in rows if r.as_of), default=None)
    hv_map = {
        h.id: h.name
        for h in db.query(Hypervisor).filter(
            Hypervisor.id.in_({r.hypervisor_id for r in rows})
        ).all()
    }
    return {
        "ok": True,
        "source": "db",
        "count": len(rows),
        "as_of": newest.isoformat() if newest else None,
        "stale": _stale(newest, max_age_min * 60),
        "datastores": [
            {
                "name": r.name,
                "type": r.ds_type,
                "capacity_gb": r.capacity_gb,
                "free_gb": r.free_gb,
                "used_gb": r.used_gb,
                "usage_pct": r.usage_pct,
                "accessible": r.accessible,
                "host_count": r.host_count,
                "hypervisor": hv_map.get(r.hypervisor_id),
                "as_of": r.as_of.isoformat() if r.as_of else None,
            }
            for r in rows
        ],
    }


def list_esx_hosts_db(db: Session, *, hypervisor: Optional[str] = None) -> Dict[str, Any]:
    """Her host için en son hypervisor_host_metrics satırı."""
    from sqlalchemy import func as sa_func

    q = db.query(HypervisorHostMetric)
    if hypervisor:
        hv = (
            db.query(Hypervisor)
            .filter(Hypervisor.name.ilike(f"%{hypervisor.strip()}%"))
            .first()
        )
        if hv:
            q = q.filter(HypervisorHostMetric.hypervisor_id == hv.id)

    subq = (
        q.with_entities(
            HypervisorHostMetric.hypervisor_id,
            HypervisorHostMetric.host_name,
            sa_func.max(HypervisorHostMetric.timestamp).label("last_ts"),
        )
        .group_by(HypervisorHostMetric.hypervisor_id, HypervisorHostMetric.host_name)
        .subquery()
    )
    rows = (
        db.query(HypervisorHostMetric)
        .join(
            subq,
            (HypervisorHostMetric.hypervisor_id == subq.c.hypervisor_id)
            & (HypervisorHostMetric.host_name == subq.c.host_name)
            & (HypervisorHostMetric.timestamp == subq.c.last_ts),
        )
        .order_by(HypervisorHostMetric.host_name.asc())
        .all()
    )
    hv_map = {
        h.id: h.name
        for h in db.query(Hypervisor).filter(
            Hypervisor.id.in_({r.hypervisor_id for r in rows})
        ).all()
    } if rows else {}
    newest = max((r.timestamp for r in rows if r.timestamp), default=None)
    return {
        "ok": True,
        "source": "db",
        "count": len(rows),
        "as_of": newest.isoformat() if newest else None,
        "stale": _stale(newest, 45 * 60),
        "hosts": [
            {
                "host_name": r.host_name,
                "host_ref": r.host_ref,
                "hypervisor": hv_map.get(r.hypervisor_id),
                "cpu_pct": r.cpu_usage_pct,
                "mem_pct": r.mem_usage_pct,
                "ds_pct": r.ds_usage_pct,
                "vms_running": r.vms_running,
                "vms_total": r.vms_total,
                "connection_state": r.connection_state,
                "maintenance": bool(r.maintenance_mode),
                "as_of": r.timestamp.isoformat() if r.timestamp else None,
            }
            for r in rows
        ],
    }


def list_virt_alarms_db(
    db: Session,
    *,
    hours: int = 48,
    unresolved_only: bool = True,
    limit: int = 50,
) -> Dict[str, Any]:
    since = _utc_now() - timedelta(hours=max(1, min(hours, 168)))
    q = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.source.in_(("vcenter_alarm", "vcenter_event")),
            SystemEvent.created_at >= since,
        )
    )
    if unresolved_only:
        q = q.filter(SystemEvent.resolved.is_(False))
    q = q.filter(
        (SystemEvent.event_type == "vcenter_alarm")
        | (SystemEvent.source == "vcenter_alarm")
    )
    rows = q.order_by(SystemEvent.last_seen.desc().nullslast()).limit(max(1, min(limit, 200))).all()
    newest = max((r.last_seen or r.created_at for r in rows if (r.last_seen or r.created_at)), default=None)
    return {
        "ok": True,
        "source": "db",
        "count": len(rows),
        "as_of": newest.isoformat() if newest else None,
        "stale": _stale(newest, 2 * 3600) if rows else True,
        "alarms": [
            {
                "title": r.title,
                "severity": r.severity,
                "description": (r.description or "")[:300],
                "entity": (r.raw_data or {}).get("entity_name") if isinstance(r.raw_data, dict) else None,
                "hypervisor": (r.raw_data or {}).get("hypervisor_name") if isinstance(r.raw_data, dict) else None,
                "last_seen": (r.last_seen or r.created_at).isoformat() if (r.last_seen or r.created_at) else None,
                "resolved": r.resolved,
            }
            for r in rows
        ],
        "hint": "Boşsa sync-vcenter-events veya vcenter_live_alarms kullanın",
    }
