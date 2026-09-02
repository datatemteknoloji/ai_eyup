"""Dinamik vCenter READ-ONLY performans sorgusu — katalog + QueryPerf + envanter join.

Mutate SOAP method çağırmaz. Kullanıcı yalnızca istediği metrikleri alır.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_inventory import HypervisorHostInventory
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.server import Server
from app.services.platform_scope import vm_filter_condition
from app.services.vmware.perf_catalog import (
    METRIC_BUNDLES,
    catalog_summary,
    resolve_metric_keys,
)

logger = logging.getLogger(__name__)


def _resolve_hv(db: Session, hypervisor: Optional[str] = None) -> Optional[Hypervisor]:
    q = db.query(Hypervisor).filter(Hypervisor.hypervisor_type == HypervisorType.VMWARE)
    if hypervisor:
        name = hypervisor.strip().lower()
        for hv in q.all():
            if (hv.name and hv.name.lower() == name) or (hv.ip_address and hv.ip_address == name):
                return hv
            if hv.hostname and hv.hostname.lower() == name:
                return hv
    return q.first()


def _build_client(hv: Hypervisor):
    from app.services.vmware.vcenter_client import VCenterClient
    from app.services.hypervisor_credentials import hv_password
    cc = hv.connection_config or {}
    return VCenterClient(
        host=hv.ip_address or hv.hostname,
        username=hv.username or cc.get("username", ""),
        password=hv_password(hv),
        port=hv.port or 443,
        verify_ssl=False,
    )


def _host_inventory_row(db: Session, hv_id: int, host_name: Optional[str], host_ref: Optional[str]):
    q = db.query(HypervisorHostInventory).filter(HypervisorHostInventory.hypervisor_id == hv_id)
    if host_ref:
        row = q.filter(HypervisorHostInventory.host_ref == host_ref).first()
        if row:
            return row
    if host_name:
        return q.filter(HypervisorHostInventory.host_name.ilike(host_name.strip())).first()
    return None


def _latest_host_metric(db: Session, hv_id: int, host_name: Optional[str]):
    if not host_name:
        return None
    return (
        db.query(HypervisorHostMetric)
        .filter(
            HypervisorHostMetric.hypervisor_id == hv_id,
            HypervisorHostMetric.host_name.ilike(host_name.strip()),
        )
        .order_by(HypervisorHostMetric.timestamp.desc())
        .first()
    )


def run_virt_perf_query(
    db: Session,
    *,
    entity: str = "host",
    target: Optional[str] = None,
    metrics: Optional[Sequence[str]] = None,
    hypervisor: Optional[str] = None,
    top_n: int = 10,
    max_sample: int = 1,
    interval_id: int = 20,
    list_catalog: bool = False,
) -> Dict[str, Any]:
    """Ana giriş — asistan tool handler bunu çağırır."""
    if list_catalog:
        ent = "host" if (entity or "host").lower() in ("host", "esx", "esxi") else "vm"
        return {
            "ok": True,
            "read_only": True,
            "catalog": catalog_summary(entity=ent),
            "bundles": {k: list(v) for k, v in METRIC_BUNDLES.items()},
            "hint": "metrics argümanına key veya bundle adı geçin (örn. disk_rate, cpu, overview)",
        }

    hv = _resolve_hv(db, hypervisor)
    if not hv:
        return {"ok": False, "error": "Tanımlı VMware vCenter bulunamadı"}

    ent_raw = (entity or "host").strip().lower()
    default_metrics = ("overview",) if ent_raw in ("host", "esx", "esxi") else ("cpu", "vdisk", "net")
    resolved = resolve_metric_keys(metrics, entity=ent_raw, default=default_metrics)
    defs = resolved["defs"]
    if not defs:
        return {
            "ok": False,
            "error": "Geçerli metrik seçilemedi",
            "unknown": resolved.get("unknown") or [],
            "hint": "list_catalog=true ile kataloğa bakın; örn. metrics=[disk_rate,disk_requests]",
        }

    client = _build_client(hv)
    target_name = (target or "").strip()
    entity_ref = None
    entity_type = "HostSystem"
    join_meta: Dict[str, Any] = {
        "hypervisor": hv.name,
        "hypervisor_id": hv.id,
    }

    # Kullanıcı target olarak vCenter/hypervisor adı vermiş olabilir ("OFFICE")
    # — host bulunamazsa hypervisor eşleşmesiyle o VC altındaki host'a düş.
    if target_name and not (hypervisor or "").strip():
        tlow = target_name.lower()
        for cand in (
            db.query(Hypervisor)
            .filter(Hypervisor.hypervisor_type == HypervisorType.VMWARE)
            .all()
        ):
            if (cand.name and cand.name.lower() == tlow) or (
                cand.hostname and cand.hostname.lower() == tlow
            ):
                if cand.id != hv.id:
                    hv = cand
                    client = _build_client(hv)
                    join_meta["hypervisor"] = hv.name
                    join_meta["hypervisor_id"] = hv.id
                # Host adı değil VC adı → tek-host shortcut'a düş
                target_name = ""
                join_meta["target_resolved_as"] = "hypervisor_name"
                break

    if resolved["entity"] == "vm":
        entity_type = "VirtualMachine"
        if not target_name:
            return {"ok": False, "error": "VM sorgusu için target (VM adı) gerekli"}
        vm = (
            db.query(Server)
            .filter(vm_filter_condition())
            .filter(
                (Server.vm_name.ilike(target_name))
                | (Server.name.ilike(target_name))
                | (Server.vm_guest_hostname.ilike(target_name))
            )
            .first()
        )
        if not vm or not vm.hypervisor_vm_id:
            return {
                "ok": False,
                "error": f"VM bulunamadı veya hypervisor_vm_id yok: {target_name}",
                "hint": "Önce VM sync çalıştırın",
            }
        entity_ref = vm.hypervisor_vm_id
        join_meta.update({
            "vm_name": vm.vm_name or vm.name,
            "vm_ip": vm.vm_guest_ip or vm.ip_address,
            "host": vm.vm_host_name,
            "cluster": vm.vm_cluster,
            "datastore": vm.vm_datastore,
            "power_state": vm.vm_power_state,
        })
    else:
        entity_type = "HostSystem"
        # target yoksa tek host varsa onu kullan; çoksa hata
        host_hit = None
        if target_name:
            # DB inventory / metrics önce
            inv = (
                db.query(HypervisorHostInventory)
                .filter(
                    HypervisorHostInventory.hypervisor_id == hv.id,
                    HypervisorHostInventory.host_name.ilike(f"%{target_name}%"),
                )
                .first()
            )
            if inv and inv.host_ref:
                host_hit = {"host_name": inv.host_name, "host_ref": inv.host_ref}
            else:
                met = (
                    db.query(HypervisorHostMetric)
                    .filter(
                        HypervisorHostMetric.hypervisor_id == hv.id,
                        HypervisorHostMetric.host_name.ilike(f"%{target_name}%"),
                    )
                    .order_by(HypervisorHostMetric.timestamp.desc())
                    .first()
                )
                if met and met.host_ref:
                    host_hit = {"host_name": met.host_name, "host_ref": met.host_ref}
            if not host_hit:
                host_hit = client.find_host_ref_by_name(target_name)
        else:
            # tek host shortcut
            names = (
                db.query(HypervisorHostMetric.host_name, HypervisorHostMetric.host_ref)
                .filter(HypervisorHostMetric.hypervisor_id == hv.id)
                .distinct()
                .all()
            )
            # distinct may not work well with two cols — fallback list
            if not names:
                stats = client.get_all_host_stats() or []
                if len(stats) == 1:
                    host_hit = {
                        "host_name": stats[0].get("host_name"),
                        "host_ref": stats[0].get("host_ref"),
                    }
                elif len(stats) > 1:
                    return {
                        "ok": False,
                        "error": "Birden fazla ESXi host var — target ile host adı belirtin",
                        "hosts": [s.get("host_name") for s in stats[:30]],
                    }
            else:
                uniq = {}
                for n, r in names:
                    if n and r:
                        uniq[n] = r
                if len(uniq) == 1:
                    n, r = next(iter(uniq.items()))
                    host_hit = {"host_name": n, "host_ref": r}
                elif len(uniq) > 1:
                    return {
                        "ok": False,
                        "error": "Birden fazla ESXi host var — target ile host adı belirtin",
                        "hosts": list(uniq.keys())[:30],
                    }

        if not host_hit or not host_hit.get("host_ref"):
            return {
                "ok": False,
                "error": f"ESXi host bulunamadı: {target_name or '(target boş)'}",
                "hint": "ESX metric sync sonrası host_ref dolu olur; veya target=host adı verin",
            }

        entity_ref = host_hit["host_ref"]
        hname = host_hit.get("host_name")
        inv = _host_inventory_row(db, hv.id, hname, entity_ref)
        met = _latest_host_metric(db, hv.id, hname)
        from app.services.entity_projection import pick_mgmt_ip
        join_meta.update({
            "host": hname,
            "host_ref": entity_ref,
            "host_ip": pick_mgmt_ip(getattr(inv, "vnics", None) if inv else None),
            "version": getattr(inv, "product_version", None) if inv else None,
            "vendor": getattr(inv, "vendor", None) if inv else None,
            "model": getattr(inv, "model", None) if inv else None,
            "cpu_pct_db": getattr(met, "cpu_usage_pct", None) if met else None,
            "mem_pct_db": getattr(met, "mem_usage_pct", None) if met else None,
            "connection_state": getattr(met, "connection_state", None) if met else None,
        })

    # Disk rate/requests → per-device instance (*) + top_n
    metric_keys = {d.key for d in defs}
    wants_per_device = bool(metric_keys & {
        "disk_read_kbps", "disk_write_kbps",
        "disk_read_requests", "disk_write_requests",
    })

    perf = client.query_perf_metrics(
        entity_type=entity_type,
        entity_ref=entity_ref,
        metric_defs=defs,
        max_sample=max_sample,
        interval_id=interval_id,
        instance="*",
        top_n=top_n if wants_per_device else None,
    )
    if not perf.get("ok"):
        return {
            "ok": False,
            "error": perf.get("error") or "QueryPerf başarısız",
            "detail": perf.get("detail"),
            "missing_counters": perf.get("missing_counters"),
            "join": join_meta,
            "requested_metrics": resolved["keys"],
            "unknown_metrics": resolved.get("unknown") or [],
        }

    return {
        "ok": True,
        "read_only": True,
        "mutate": False,
        "join": join_meta,
        "requested_metrics": resolved["keys"],
        "unknown_metrics": resolved.get("unknown") or [],
        "missing_counters": perf.get("missing_counters") or [],
        "summary": perf.get("summary") or {},
        "series": perf.get("series") or [],
        "series_count": perf.get("series_count") or 0,
        "interval_id": perf.get("interval_id"),
        "max_sample": perf.get("max_sample"),
        "entity_type": perf.get("entity_type"),
        "hint": (
            "READ-ONLY QueryPerf. Yalnız istenen metrikler. "
            "Disk Rate/Requests için series satırlarında instance=naa.*/t10.* görünür."
        ),
    }
