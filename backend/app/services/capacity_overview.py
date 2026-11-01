"""Kapasite dökümü: «toplam CPU / bellek / depolama nereden geliyor?» sorusunun tek cevabı.

İki ayrı kavram, ikisi de kaynak (hypervisor / platform) bazında döner:

* ``inventory`` — Dashboard «Toplam CPU / Toplam Bellek» kartlarının kaynağı: ``servers`` tablosundaki
  (VM + Linux + Windows) sunucuların atanmış vCPU / RAM toplamı. Fiziksel kapasite DEĞİLDİR.
* ``physical`` — hypervisor host'larının fiziksel kapasitesi ve anlık kullanımı (CPU çekirdek/GHz, bellek,
  tekil datastore toplamı). Paylaşımlı datastore host sayısı kadar katlanmaz.

Sahte (ZZ-FAKE) hypervisor kayıtları ``demo=True`` ile işaretlenir; toplam hem «tümü» hem «gerçek»
olarak verilir (ekran mevcut davranışı korur, gerçek rakamı ayrıca gösterir).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_TYPE_LABEL = {
    "vmware": "VMware vCenter",
    "kvm": "OLVM / oVirt (KVM)",
    "openshift_virt": "OpenShift Virtualization",
    "hyperv": "Hyper-V",
    "proxmox": "Proxmox",
    "xen": "Xen",
}


def _type_key(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").lower()


def _pct(used: Optional[float], total: Optional[float]) -> Optional[float]:
    if not total or total <= 0 or used is None:
        return None
    return round(max(0.0, min(100.0, used / total * 100.0)), 1)


def inventory_by_source(db: Session, hv_names: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    """`servers` tablosunun CPU/RAM toplamı: hypervisor başına, hypervisor dışı Linux/Windows ayrı."""
    rows = db.execute(text("""
        SELECT hypervisor_id,
               CASE WHEN lower(coalesce(os_type, '')) LIKE '%windows%' THEN 'windows' ELSE 'linux' END AS family,
               count(*) AS servers,
               coalesce(sum(cpu_cores), 0) AS cpu,
               coalesce(sum(memory_gb), 0) AS mem,
               count(*) FILTER (WHERE upper(coalesce(status::text, '')) = 'ONLINE') AS n_online,
               count(*) FILTER (WHERE upper(coalesce(status::text, '')) = 'OFFLINE') AS n_offline,
               count(*) FILTER (WHERE upper(coalesce(status::text, '')) IN ('WARNING', 'CRITICAL')) AS n_attention
        FROM servers
        GROUP BY 1, 2
    """)).mappings().all()
    sources: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        hv_id = row["hypervisor_id"]
        if hv_id is not None:
            info = hv_names.get(int(hv_id), {})
            key = f"hv:{int(hv_id)}"
            item = sources.setdefault(key, {
                "key": key, "kind": "hypervisor", "label": info.get("name") or f"Hypervisor #{hv_id}",
                "type": info.get("type", ""), "type_label": info.get("type_label", ""),
                "demo": bool(info.get("demo")), "servers": 0, "cpu_cores": 0, "memory_gb": 0.0,
                "online": 0, "offline": 0, "attention": 0,
            })
        else:
            fam = row["family"]
            key = f"free:{fam}"
            item = sources.setdefault(key, {
                "key": key, "kind": fam,
                "label": "Windows sunucular (hypervisor dışı)" if fam == "windows" else "Linux sunucular (hypervisor dışı)",
                "type": "", "type_label": "", "demo": False, "servers": 0, "cpu_cores": 0, "memory_gb": 0.0,
                "online": 0, "offline": 0, "attention": 0,
            })
        item["servers"] += int(row["servers"])
        item["cpu_cores"] += int(row["cpu"] or 0)
        item["memory_gb"] += float(row["mem"] or 0)
        item["online"] += int(row["n_online"] or 0)
        item["offline"] += int(row["n_offline"] or 0)
        item["attention"] += int(row["n_attention"] or 0)
    ordered: List[Dict[str, Any]] = sorted(sources.values(), key=lambda s: (s["demo"], -s["cpu_cores"]))
    for item in ordered:
        item["memory_gb"] = round(item["memory_gb"], 1)

    def total(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "servers": sum(s["servers"] for s in items),
            "online": sum(s["online"] for s in items),
            "offline": sum(s["offline"] for s in items),
            "attention": sum(s["attention"] for s in items),
            "cpu_cores": sum(s["cpu_cores"] for s in items),
            "memory_gb": round(sum(s["memory_gb"] for s in items), 1),
        }

    return {"sources": ordered, "total": total(ordered), "total_real": total([s for s in ordered if not s["demo"]])}


def _physical_for(hv_id: int, hosts: List[Dict[str, Any]], ds: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    def num(host: Dict[str, Any], key: str) -> float:
        value = host.get(key)
        return float(value) if value is not None else 0.0

    cores = int(sum(num(h, "cpu_cores") for h in hosts))
    mhz_total = sum(num(h, "cpu_total_mhz") for h in hosts)
    mhz_used = sum(num(h, "cpu_usage_mhz") for h in hosts)
    if mhz_total > 0:
        cpu_pct = _pct(mhz_used, mhz_total)
    else:  # OpenShift Virt gibi MHz vermeyen kaynaklar: çekirdek ağırlıklı ortalama
        weighted = [(num(h, "cpu_cores"), h.get("cpu_usage_pct")) for h in hosts if h.get("cpu_usage_pct") is not None]
        wsum = sum(w for w, _p in weighted)
        cpu_pct = round(sum(w * float(p) for w, p in weighted) / wsum, 1) if wsum > 0 else None
    mem_total = sum(num(h, "mem_total_mb") for h in hosts) / 1024.0
    mem_used = sum(num(h, "mem_used_mb") for h in hosts) / 1024.0
    st_total = float(ds["total_gb"]) if ds else None
    st_used = float(ds["used_gb"]) if ds else None
    return {
        "hosts": len(hosts),
        "cpu_cores": cores,
        "cpu_total_ghz": round(mhz_total / 1000.0, 1) if mhz_total > 0 else None,
        "cpu_used_ghz": round(mhz_used / 1000.0, 1) if mhz_total > 0 else None,
        "cpu_pct": cpu_pct,
        "mem_total_gb": round(mem_total, 1) if mem_total > 0 else None,
        "mem_used_gb": round(mem_used, 1) if mem_total > 0 else None,
        "mem_pct": _pct(mem_used, mem_total),
        "storage_total_gb": st_total,
        "storage_used_gb": st_used,
        "storage_pct": _pct(st_used, st_total),
        "datastores": int(ds["count"]) if ds and ds.get("count") is not None else 0,
    }


def capacity_overview(db: Session) -> Dict[str, Any]:
    from app.api.hypervisors import _VIRT_HOST_METRIC_TYPES, _latest_hosts_for_hypervisor, datastore_summary_by_hypervisor
    from app.models.hypervisor import Hypervisor
    from app.services.synthetic_scope import synthetic_hypervisor_ids

    demo_ids = synthetic_hypervisor_ids(db)
    all_hvs = db.query(Hypervisor).order_by(Hypervisor.name.asc()).all()
    names: Dict[int, Dict[str, Any]] = {}
    for hv in all_hvs:
        tkey = _type_key(hv.hypervisor_type)
        names[hv.id] = {"name": hv.name, "type": tkey, "type_label": _TYPE_LABEL.get(tkey, tkey), "demo": hv.id in demo_ids}

    virt = [hv for hv in all_hvs if hv.hypervisor_type in _VIRT_HOST_METRIC_TYPES]
    ds_sum = datastore_summary_by_hypervisor(db, [hv.id for hv in virt])
    physical: List[Dict[str, Any]] = []
    for hv in virt:
        try:
            hosts = _latest_hosts_for_hypervisor(db, hv.id)
        except Exception:
            logger.exception("capacity_overview host list")
            db.rollback()
            hosts = []
        row = {"hypervisor_id": hv.id, **names[hv.id]}
        row.update(_physical_for(hv.id, hosts, ds_sum.get(hv.id)))
        physical.append(row)
    physical.sort(key=lambda r: (r["demo"], r["name"].lower()))

    def total(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        cpu_total = sum(r["cpu_total_ghz"] or 0 for r in items)
        cpu_used = sum(r["cpu_used_ghz"] or 0 for r in items)
        mem_total = sum(r["mem_total_gb"] or 0 for r in items)
        mem_used = sum(r["mem_used_gb"] or 0 for r in items)
        st_items = [r for r in items if r["storage_total_gb"]]
        st_total = sum(r["storage_total_gb"] for r in st_items)
        st_used = sum(r["storage_used_gb"] or 0 for r in st_items)
        return {
            "hypervisors": len(items),
            "hosts": sum(r["hosts"] for r in items),
            "cpu_cores": sum(r["cpu_cores"] for r in items),
            "cpu_total_ghz": round(cpu_total, 1) or None,
            "cpu_used_ghz": round(cpu_used, 1) if cpu_total else None,
            "cpu_pct": _pct(cpu_used, cpu_total),
            "mem_total_gb": round(mem_total, 1) or None,
            "mem_used_gb": round(mem_used, 1) if mem_total else None,
            "mem_pct": _pct(mem_used, mem_total),
            "storage_total_gb": round(st_total, 1) or None,
            "storage_used_gb": round(st_used, 1) if st_total else None,
            "storage_pct": _pct(st_used, st_total),
        }

    return {
        "inventory": inventory_by_source(db, names),
        "physical": {
            "sources": physical,
            "total": total(physical),
            "total_real": total([r for r in physical if not r["demo"]]),
        },
        "has_demo": any(r["demo"] for r in physical) or bool(demo_ids),
    }
