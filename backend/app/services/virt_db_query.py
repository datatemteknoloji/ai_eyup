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
    datastore: Optional[str] = None,
    name_filter: Optional[str] = None,
    limit: int = 100,
    fields: Optional[List[str]] = None,
    include_disks: bool = True,
) -> Dict[str, Any]:
    from app.services.entity_projection import (
        VM_DEFAULT_FIELDS,
        VM_FIELD_ALIASES,
        VM_INVENTORY_REQUIRED_FIELDS,
        normalize_fields,
        project_rows,
    )

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
    if datastore:
        # Yalnızca bu datastore'da yer alan VM'ler (kapsam daraltma — "bilgi kirliliği" önlemi).
        q = q.filter(Server.vm_datastore.ilike(f"%{datastore.strip()}%"))
    if name_filter:
        q = q.filter(Server.vm_name.ilike(f"%{name_filter.strip()}%"))

    rows = q.order_by(Server.name.asc()).limit(max(1, min(limit, 500))).all()
    hv_map = {
        h.id: h.name
        for h in db.query(Hypervisor).filter(
            Hypervisor.id.in_({r.hypervisor_id for r in rows if r.hypervisor_id})
        ).all()
    } if rows else {}

    items = []
    oldest_sync = None
    null_disk = 0
    for s in rows:
        sync = s.vm_last_sync
        if sync and (oldest_sync is None or sync < oldest_sync):
            oldest_sync = sync
        disks = s.vm_disks if isinstance(s.vm_disks, list) else (s.vm_disks or None)
        if disks is not None and not isinstance(disks, list):
            disks = None
        disk_count = len(disks) if isinstance(disks, list) else None
        if s.vm_disk_gb is None and not disks:
            null_disk += 1
        row = {
            "id": s.id,
            "name": s.vm_name or s.name,
            "ip": s.vm_guest_ip or s.ip_address,
            "power_state": s.vm_power_state,
            "vcpu": s.vm_cpu_count,
            "memory_mb": s.vm_memory_mb,
            "disk_gb": s.vm_disk_gb,
            "disk_count": disk_count,
            # host = ESXi (vm_host_name); hypervisor = vCenter label — karıştırma
            "host": s.vm_host_name,
            "esxi_host": s.vm_host_name,
            "cluster": s.vm_cluster,
            "datastore": s.vm_datastore,
            "guest_os": s.vm_guest_os_full or s.os_type,
            "hypervisor": hv_map.get(s.hypervisor_id),
            "vcenter": hv_map.get(s.hypervisor_id),
            "cpu_mhz": s.vm_cpu_usage_mhz,
            "mem_active_mb": s.vm_mem_active_mb,
            "vm_last_sync": sync.isoformat() if sync else None,
            "stats_as_of": s.vm_stats_as_of.isoformat() if s.vm_stats_as_of else None,
        }
        if include_disks:
            row["disks"] = disks
        items.append(row)

    # fields verilse bile disk çekirdek alanları düşmez; disks istendi/include ise ekle
    req = list(VM_INVENTORY_REQUIRED_FIELDS)
    if include_disks or (fields and any(
        str(f).lower() in ("disks", "disk_list", "vmdk", "hard_disks") for f in fields
    )):
        if "disks" not in req:
            req.append("disks")

    wanted = normalize_fields(
        fields,
        aliases=VM_FIELD_ALIASES,
        default=list(VM_DEFAULT_FIELDS) + (["disks"] if include_disks else []),
        required=req,
    )
    # fields verilmezse tam satır; verilirse projeksiyon (required korunur)
    if fields:
        proj = project_rows(items, wanted)
        out_vms = proj["items"]
        missing = proj["missing_fields"]
        field_list = proj["fields"]
    else:
        out_vms = items
        missing = []
        field_list = list(wanted)

    return {
        "ok": True,
        "source": "db",
        "count": len(items),
        "disk_null_count": null_disk,
        "as_of": oldest_sync.isoformat() if oldest_sync else None,
        "stale": _stale(oldest_sync, 12 * 3600),
        "fields": field_list,
        "missing_fields": missing,
        "vms": out_vms,
        "hint": (
            "disk_gb/disk_count/disks vCenter provisioned envanteridir. "
            "disk_gb dolu satıra 'toplanmadı' yazma; null ise sync enrichment gerekir. "
            "TERİM: hypervisor/vcenter = vCenter kaydı adı (örn. Office); "
            "host/esxi_host = ESXi compute host (örn. 192.168.1.101). Karıştırma."
        ),
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
            # host = ESXi; hypervisor/vcenter = vCenter label
            "host": s.vm_host_name,
            "esxi_host": s.vm_host_name,
            "host_ref": s.vm_host_ref,
            "cluster": s.vm_cluster,
            "datastore": s.vm_datastore,
            "guest_os": s.vm_guest_os_full or s.os_type,
            "hw_version": s.vm_hardware_version,
            "hypervisor": hv.name if hv else None,
            "vcenter": hv.name if hv else None,
            "vcenter_endpoint": (
                (hv.ip_address or hv.hostname or "") if hv else None
            ) or None,
            "cpu_mhz": s.vm_cpu_usage_mhz,
            "mem_active_mb": s.vm_mem_active_mb,
            "vm_last_sync": s.vm_last_sync.isoformat() if s.vm_last_sync else None,
            "stats_as_of": s.vm_stats_as_of.isoformat() if s.vm_stats_as_of else None,
        },
        "hint": (
            "hypervisor/vcenter = vCenter kaydı; host/esxi_host = ESXi. "
            "vcenter_endpoint = vCenter IP/FQDN (bağlantı ucu)."
        ),
    }


def list_datastores_db(
    db: Session,
    *,
    hypervisor: Optional[str] = None,
    name_filter: Optional[str] = None,
    max_age_min: int = 45,
    fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    from app.services.entity_projection import (
        DATASTORE_DEFAULT_FIELDS,
        DATASTORE_FIELD_ALIASES,
        normalize_fields,
        project_rows,
    )

    q = db.query(VirtDatastore)
    if hypervisor:
        hv = (
            db.query(Hypervisor)
            .filter(Hypervisor.name.ilike(f"%{hypervisor.strip()}%"))
            .first()
        )
        if hv:
            q = q.filter(VirtDatastore.hypervisor_id == hv.id)
    if name_filter:
        q = q.filter(VirtDatastore.name.ilike(f"%{name_filter.strip()}%"))
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
    items = [
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
    ]
    wanted = normalize_fields(
        fields,
        aliases=DATASTORE_FIELD_ALIASES,
        default=DATASTORE_DEFAULT_FIELDS,
    )
    if fields:
        proj = project_rows(items, wanted)
        out_ds = proj["items"]
        missing = proj["missing_fields"]
        field_list = proj["fields"]
    else:
        out_ds = items
        missing = []
        field_list = list(wanted)

    return {
        "ok": True,
        "source": "db",
        "count": len(rows),
        "as_of": newest.isoformat() if newest else None,
        "stale": _stale(newest, max_age_min * 60),
        "fields": field_list if fields else None,
        "missing_fields": missing,
        "datastores": out_ds,
    }


def list_esx_hosts_db(
    db: Session,
    *,
    hypervisor: Optional[str] = None,
    name_filter: Optional[str] = None,
    fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """ESXi host listesi — metrics ⋈ inventory join; fields ile dinamik projeksiyon.

    SoT:
      - hypervisor_host_metrics → CPU/RAM/DS/VM/state
      - hypervisor_host_inventory → IP (vnics), version, vendor/model
    """
    from sqlalchemy import func as sa_func
    from app.models.hypervisor_inventory import HypervisorHostInventory
    from app.services.entity_projection import (
        ESXI_HOST_DEFAULT_FIELDS,
        ESXI_HOST_FIELD_ALIASES,
        normalize_fields,
        pick_mgmt_ip,
        project_rows,
    )

    q = db.query(HypervisorHostMetric)
    if hypervisor:
        hv = (
            db.query(Hypervisor)
            .filter(Hypervisor.name.ilike(f"%{hypervisor.strip()}%"))
            .first()
        )
        if hv:
            q = q.filter(HypervisorHostMetric.hypervisor_id == hv.id)
    if name_filter:
        q = q.filter(HypervisorHostMetric.host_name.ilike(f"%{name_filter.strip()}%"))

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
    hv_ids = {r.hypervisor_id for r in rows}
    hv_map = {
        h.id: h.name
        for h in db.query(Hypervisor).filter(Hypervisor.id.in_(hv_ids)).all()
    } if hv_ids else {}

    # Inventory join anahtarı: (hypervisor_id, host_ref) tercih; yoksa host_name
    inv_by_ref: Dict[tuple, Any] = {}
    inv_by_name: Dict[tuple, Any] = {}
    if hv_ids:
        for inv in (
            db.query(HypervisorHostInventory)
            .filter(HypervisorHostInventory.hypervisor_id.in_(hv_ids))
            .all()
        ):
            inv_by_ref[(inv.hypervisor_id, inv.host_ref or "")] = inv
            inv_by_name[(inv.hypervisor_id, (inv.host_name or "").lower())] = inv

    joined: List[Dict[str, Any]] = []
    for r in rows:
        inv = inv_by_ref.get((r.hypervisor_id, r.host_ref or ""))
        if inv is None:
            inv = inv_by_name.get((r.hypervisor_id, (r.host_name or "").lower()))
        mgmt_ip = pick_mgmt_ip(getattr(inv, "vnics", None) if inv else None)
        version = (getattr(inv, "product_version", None) if inv else None) or None
        full_name = (getattr(inv, "product_full_name", None) if inv else None) or None
        joined.append({
            "name": r.host_name,
            "host_name": r.host_name,
            "host_ref": r.host_ref,
            "ip": mgmt_ip,
            "version": version or full_name,
            "product_version": version,
            "product_full_name": full_name,
            "vendor": getattr(inv, "vendor", None) if inv else None,
            "model": getattr(inv, "model", None) if inv else None,
            "cpu_model": getattr(inv, "cpu_model", None) if inv else None,
            "hypervisor": hv_map.get(r.hypervisor_id),
            "cpu_pct": r.cpu_usage_pct,
            "mem_pct": r.mem_usage_pct,
            "ds_pct": r.ds_usage_pct,
            "cpu_cores": r.cpu_cores,
            "vms_running": r.vms_running,
            "vms_total": r.vms_total,
            "connection_state": r.connection_state,
            "maintenance": bool(r.maintenance_mode),
            "as_of": r.timestamp.isoformat() if r.timestamp else None,
            "_inventory_joined": inv is not None,
        })

    wanted = normalize_fields(
        fields,
        aliases=ESXI_HOST_FIELD_ALIASES,
        default=ESXI_HOST_DEFAULT_FIELDS,
    )
    proj = project_rows(joined, wanted)
    newest = max((r.timestamp for r in rows if r.timestamp), default=None)
    inv_joined = sum(1 for j in joined if j.get("_inventory_joined"))
    return {
        "ok": True,
        "source": "db",
        "join": "hypervisor_host_metrics ⋈ hypervisor_host_inventory",
        "count": len(joined),
        "inventory_joined": inv_joined,
        "as_of": newest.isoformat() if newest else None,
        "stale": _stale(newest, 45 * 60),
        "fields": proj["fields"],
        "missing_fields": proj["missing_fields"],
        "hosts": proj["items"],
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


def cross_match_virt_db(
    db: Session,
    *,
    join_on: str = "host",
    include: Optional[List[str]] = None,
    hypervisor: Optional[str] = None,
    host_name: Optional[str] = None,
    fields: Optional[List[str]] = None,
    hours: int = 48,
    limit: int = 100,
) -> Dict[str, Any]:
    """READ-ONLY çapraz eşleştirme — ESXi / VM / datastore / alarm SoT'larını join et.

    join_on:
      - host: ESXi satırı eksen; VM + DS + alarm bağlanır
      - datastore: datastore eksen; o DS'teki VM'ler + ilgili host özeti
      - entity: alarm entity adı → host veya VM eşleşmesi
    """
    from app.services.entity_projection import (
        CROSS_MATCH_DEFAULT_FIELDS,
        CROSS_MATCH_FIELD_ALIASES,
        index_by_key,
        norm_join_key,
        normalize_fields,
        project_rows,
    )

    axis = (join_on or "host").strip().lower()
    if axis not in ("host", "datastore", "entity"):
        axis = "host"

    wanted_src = {
        (s or "").strip().lower()
        for s in (include or ["hosts", "vms", "datastores", "alarms"])
    }
    if not wanted_src:
        wanted_src = {"hosts", "vms", "datastores", "alarms"}

    hosts_raw: List[Dict[str, Any]] = []
    vms_raw: List[Dict[str, Any]] = []
    ds_raw: List[Dict[str, Any]] = []
    alarms_raw: List[Dict[str, Any]] = []
    as_ofs: List[Optional[str]] = []
    stale_any = False

    if "hosts" in wanted_src or axis == "host":
        hres = list_esx_hosts_db(
            db,
            hypervisor=hypervisor,
            fields=[
                "name", "ip", "version", "cpu_pct", "mem_pct",
                "connection_state", "hypervisor", "vms_total", "cluster",
            ],
        )
        hosts_raw = list(hres.get("hosts") or [])
        as_ofs.append(hres.get("as_of"))
        stale_any = stale_any or bool(hres.get("stale"))

    if "vms" in wanted_src or axis in ("host", "datastore", "entity"):
        vres = list_vms_db(
            db,
            hypervisor=hypervisor,
            host_name=host_name,
            limit=max(1, min(int(limit or 100), 500)),
        )
        vms_raw = list(vres.get("vms") or [])
        as_ofs.append(vres.get("as_of"))
        stale_any = stale_any or bool(vres.get("stale"))

    if "datastores" in wanted_src or axis == "datastore":
        dres = list_datastores_db(db, hypervisor=hypervisor)
        ds_raw = list(dres.get("datastores") or [])
        as_ofs.append(dres.get("as_of"))
        stale_any = stale_any or bool(dres.get("stale"))

    if "alarms" in wanted_src or axis == "entity":
        ares = list_virt_alarms_db(
            db,
            hours=hours,
            unresolved_only=True,
            limit=max(1, min(int(limit or 100), 200)),
        )
        alarms_raw = list(ares.get("alarms") or [])
        as_ofs.append(ares.get("as_of"))
        stale_any = stale_any or bool(ares.get("stale"))

    if host_name:
        hn = host_name.strip().lower()
        hosts_raw = [h for h in hosts_raw if hn in (h.get("name") or "").lower()]
        vms_raw = [v for v in vms_raw if hn in (v.get("host") or "").lower()]

    vms_by_host = index_by_key(vms_raw, ("host",))
    vms_by_ds = index_by_key(vms_raw, ("datastore",))
    vms_by_name = index_by_key(vms_raw, ("name",))
    hosts_by_name = index_by_key(hosts_raw, ("name", "host", "host_name"))
    ds_by_name = index_by_key(ds_raw, ("name",))
    alarms_by_entity = index_by_key(alarms_raw, ("entity",))

    joined: List[Dict[str, Any]] = []

    def _vm_names(vms: List[Dict[str, Any]], cap: int = 12) -> List[str]:
        names = [str(v.get("name") or "") for v in vms if v.get("name")]
        return names[:cap]

    def _alarm_titles(alarms: List[Dict[str, Any]], cap: int = 8) -> List[str]:
        return [str(a.get("title") or "")[:120] for a in alarms if a.get("title")][:cap]

    def _pick_ds_for_vms(vms: List[Dict[str, Any]]) -> tuple:
        """VM'lerin datastore'larından en dolu olanı seç."""
        best = None
        best_pct = -1.0
        for v in vms:
            dk = norm_join_key(str(v.get("datastore") or ""))
            for d in ds_by_name.get(dk, []):
                pct = float(d.get("usage_pct") or 0)
                if pct >= best_pct:
                    best_pct = pct
                    best = d
        if best is None and vms:
            # DS envanteri yoksa VM üzerindeki adı göster
            return (vms[0].get("datastore"), None, None)
        if best is None:
            return (None, None, None)
        return (best.get("name"), best.get("usage_pct"), best.get("free_gb"))

    if axis == "host":
        # Host listesi boşsa VM host adlarından eksen üret
        axis_keys: List[str] = []
        seen_k: set = set()
        for h in hosts_raw:
            k = norm_join_key(str(h.get("name") or ""))
            if k and k not in seen_k:
                seen_k.add(k)
                axis_keys.append(k)
        if not axis_keys:
            for k in sorted(vms_by_host.keys()):
                if k not in seen_k:
                    seen_k.add(k)
                    axis_keys.append(k)

        for k in axis_keys:
            h = (hosts_by_name.get(k) or [{}])[0]
            vms = vms_by_host.get(k, [])
            # Alarm: entity=host veya entity ∈ VM adları
            alarms = list(alarms_by_entity.get(k, []))
            for v in vms:
                vk = norm_join_key(str(v.get("name") or ""))
                alarms.extend(alarms_by_entity.get(vk, []))
            # dedupe alarm titles
            seen_t: set = set()
            uniq_alarms = []
            for a in alarms:
                t = a.get("title") or id(a)
                if t in seen_t:
                    continue
                seen_t.add(t)
                uniq_alarms.append(a)
            ds_name, ds_pct, ds_free = _pick_ds_for_vms(vms)
            joined.append({
                "match_key": h.get("name") or (vms[0].get("host") if vms else k),
                "match_axis": "host",
                "host": h.get("name") or (vms[0].get("host") if vms else k),
                "host_ip": h.get("ip"),
                "host_version": h.get("version"),
                "cpu_pct": h.get("cpu_pct"),
                "mem_pct": h.get("mem_pct"),
                "connection_state": h.get("connection_state"),
                "hypervisor": h.get("hypervisor") or (vms[0].get("hypervisor") if vms else None),
                "vm_count": len(vms),
                "vms": _vm_names(vms),
                "datastore": ds_name,
                "ds_usage_pct": ds_pct,
                "ds_free_gb": ds_free,
                "alarm_count": len(uniq_alarms),
                "alarms": _alarm_titles(uniq_alarms),
            })

    elif axis == "datastore":
        keys = sorted(set(ds_by_name.keys()) | set(vms_by_ds.keys()))
        for k in keys:
            d = (ds_by_name.get(k) or [{}])[0]
            vms = vms_by_ds.get(k, [])
            host_names = sorted({
                (v.get("host") or "").strip()
                for v in vms if (v.get("host") or "").strip()
            })
            primary_host = host_names[0] if host_names else None
            h = (hosts_by_name.get(norm_join_key(primary_host or "")) or [{}])[0]
            alarms = []
            for v in vms:
                alarms.extend(alarms_by_entity.get(norm_join_key(str(v.get("name") or "")), []))
            seen_t = set()
            uniq_alarms = []
            for a in alarms:
                t = a.get("title") or id(a)
                if t in seen_t:
                    continue
                seen_t.add(t)
                uniq_alarms.append(a)
            joined.append({
                "match_key": d.get("name") or (vms[0].get("datastore") if vms else k),
                "match_axis": "datastore",
                "host": primary_host,
                "host_ip": h.get("ip"),
                "host_version": h.get("version"),
                "cpu_pct": h.get("cpu_pct"),
                "mem_pct": h.get("mem_pct"),
                "connection_state": h.get("connection_state"),
                "hypervisor": d.get("hypervisor") or h.get("hypervisor"),
                "vm_count": len(vms),
                "vms": _vm_names(vms),
                "datastore": d.get("name") or (vms[0].get("datastore") if vms else k),
                "ds_usage_pct": d.get("usage_pct"),
                "ds_free_gb": d.get("free_gb"),
                "alarm_count": len(uniq_alarms),
                "alarms": _alarm_titles(uniq_alarms),
            })

    else:  # entity (alarm ekseni)
        for a in alarms_raw:
            ek = norm_join_key(str(a.get("entity") or ""))
            if not ek:
                continue
            host_hit = (hosts_by_name.get(ek) or [None])[0]
            vm_hit = (vms_by_name.get(ek) or [None])[0]
            host_name_out = None
            host_ip = None
            host_ver = None
            hv = a.get("hypervisor")
            vms_out: List[Dict[str, Any]] = []
            ds_name = ds_pct = ds_free = None
            if host_hit:
                host_name_out = host_hit.get("name")
                host_ip = host_hit.get("ip")
                host_ver = host_hit.get("version")
                hv = hv or host_hit.get("hypervisor")
                vms_out = vms_by_host.get(ek, [])
                ds_name, ds_pct, ds_free = _pick_ds_for_vms(vms_out)
            elif vm_hit:
                host_name_out = vm_hit.get("host")
                hv = hv or vm_hit.get("hypervisor")
                vms_out = [vm_hit]
                h2 = (hosts_by_name.get(norm_join_key(str(host_name_out or ""))) or [{}])[0]
                host_ip = h2.get("ip")
                host_ver = h2.get("version")
                ds_name, ds_pct, ds_free = _pick_ds_for_vms(vms_out)
            joined.append({
                "match_key": a.get("entity") or a.get("title"),
                "match_axis": "entity",
                "host": host_name_out,
                "host_ip": host_ip,
                "host_version": host_ver,
                "cpu_pct": (host_hit or {}).get("cpu_pct") if host_hit else None,
                "mem_pct": (host_hit or {}).get("mem_pct") if host_hit else None,
                "connection_state": (host_hit or {}).get("connection_state") if host_hit else None,
                "hypervisor": hv,
                "vm_count": len(vms_out),
                "vms": _vm_names(vms_out),
                "datastore": ds_name,
                "ds_usage_pct": ds_pct,
                "ds_free_gb": ds_free,
                "alarm_count": 1,
                "alarms": _alarm_titles([a]),
            })

    # Host ekseninde yalnız alarm/dolu filtre istenebilir — hepsini döndür; limit uygula
    joined = joined[: max(1, min(int(limit or 100), 200))]

    wanted = normalize_fields(
        fields,
        aliases=CROSS_MATCH_FIELD_ALIASES,
        default=CROSS_MATCH_DEFAULT_FIELDS,
    )
    proj = project_rows(joined, wanted)
    newest = next((x for x in as_ofs if x), None)

    return {
        "ok": True,
        "source": "db",
        "join": f"cross_match({axis})",
        "join_on": axis,
        "include": sorted(wanted_src),
        "count": len(joined),
        "as_of": newest,
        "stale": stale_any,
        "fields": proj["fields"],
        "missing_fields": proj["missing_fields"],
        "rows": proj["items"],
        "hint": (
            "READ-ONLY çapraz eşleştirme. Write/power/destroy yok. "
            "Eksik alan → ilgili sync veya (stale ise) canlı vcenter read tool."
        ),
    }
