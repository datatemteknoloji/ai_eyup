"""Karar katmanı için ortak veri erişimi (yalnız DB okur).

Üç platform aynı tablolara yazar:
  hypervisor_host_metrics — VMware (esx_metric_sync), OLVM (ovirt_infra_sync),
                            OCP Virt (openshift_virt_host_metrics; host = node)
  virt_clusters / virt_datastores / virt_datastore_metrics / virt_vm_metrics
  servers (VM envanteri; vm_cluster / vm_host_name / vm_memory_mb …)
Platform `Hypervisor.hypervisor_type` ile ayrılır.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor, HypervisorType

PLATFORM_BY_TYPE = {
    HypervisorType.VMWARE: "vmware",
    HypervisorType.KVM: "olvm",
    HypervisorType.OPENSHIFT_VIRT: "ocp_virt",
}
VIRT_TYPES = tuple(PLATFORM_BY_TYPE.keys())
PLATFORM_LABEL = {"vmware": "VMware", "olvm": "OLVM", "ocp_virt": "OpenShift Virtualization", "ocp": "OpenShift"}


def platform_of(hv: Hypervisor) -> Optional[str]:
    t = hv.hypervisor_type
    if not isinstance(t, HypervisorType):
        try:
            t = HypervisorType(str(t))
        except ValueError:
            return None
    return PLATFORM_BY_TYPE.get(t)


def virt_hypervisors(db: Session, platform: Optional[str] = None,
                     hypervisor_id: Optional[int] = None) -> List[Hypervisor]:
    q = db.query(Hypervisor).filter(Hypervisor.hypervisor_type.in_(list(VIRT_TYPES)))
    if hypervisor_id:
        q = q.filter(Hypervisor.id == int(hypervisor_id))
    rows = q.order_by(Hypervisor.name).all()
    if platform:
        rows = [h for h in rows if platform_of(h) == platform]
    return rows


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def latest_hosts(db: Session, hypervisor_ids: Iterable[int], max_age_hours: int = 6) -> List[Dict[str, Any]]:
    ids = [int(i) for i in hypervisor_ids]
    if not ids:
        return []
    rows = db.execute(text("""
        SELECT DISTINCT ON (m.hypervisor_id, m.host_name)
               m.hypervisor_id, m.host_name, m.host_ref, m.timestamp,
               m.cpu_usage_mhz, m.cpu_total_mhz, m.cpu_usage_pct, m.cpu_cores,
               m.mem_used_mb, m.mem_total_mb, m.mem_usage_pct,
               m.net_rx_kbps, m.net_tx_kbps, m.cpu_ready_pct, m.disk_latency_ms,
               m.vms_running, m.vms_total, m.connection_state, m.maintenance_mode,
               m.cluster_name, m.overall_status, m.sensor_bad_count
          FROM hypervisor_host_metrics m
         WHERE m.hypervisor_id = ANY(:ids)
           AND m.timestamp > now() - make_interval(hours => :h)
         ORDER BY m.hypervisor_id, m.host_name, m.timestamp DESC
    """), {"ids": ids, "h": int(max_age_hours)}).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["mem_total_gb"] = round((_f(d["mem_total_mb"]) or 0) / 1024, 2)
        d["mem_used_gb"] = round((_f(d["mem_used_mb"]) or 0) / 1024, 2)
        cores = _f(d["cpu_cores"]) or 0
        d["cpu_used_cores"] = round(cores * (_f(d["cpu_usage_pct"]) or 0) / 100.0, 2)
        conn = str(d.get("connection_state") or "").lower()
        d["usable"] = conn in ("connected", "up", "") and not bool(d.get("maintenance_mode"))
        out.append(d)
    return out


def host_p95(db: Session, hypervisor_ids: Iterable[int], hours: int = 24) -> Dict[Tuple[int, str], Dict[str, Any]]:
    ids = [int(i) for i in hypervisor_ids]
    if not ids:
        return {}
    rows = db.execute(text("""
        SELECT hypervisor_id, host_name,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY cpu_ready_pct) AS ready_p95,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY disk_latency_ms) AS lat_p95,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY cpu_usage_pct) AS cpu_p95,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY mem_usage_pct) AS mem_p95,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY COALESCE(net_rx_kbps,0)+COALESCE(net_tx_kbps,0)) AS net_p95
          FROM hypervisor_host_metrics
         WHERE hypervisor_id = ANY(:ids) AND timestamp > now() - make_interval(hours => :h)
         GROUP BY hypervisor_id, host_name
    """), {"ids": ids, "h": int(hours)}).mappings().all()
    return {(int(r["hypervisor_id"]), r["host_name"]): dict(r) for r in rows}


def worker_filter(db: Session, hv: Hypervisor, hosts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OCP Virt: control-plane node'ları VM taşımaz (compact cluster hariç)."""
    if platform_of(hv) != "ocp_virt":
        return hosts
    from app.models.hypervisor_inventory import HypervisorHostInventory
    roles = {}
    for inv in db.query(HypervisorHostInventory).filter(HypervisorHostInventory.hypervisor_id == hv.id).all():
        r = str(((inv.dns or {}) if isinstance(inv.dns, dict) else {}).get("roles") or "")
        roles[inv.host_name] = r.lower()
    out = []
    for h in hosts:
        r = roles.get(h["host_name"], "")
        if not r or "worker" in r or ("master" not in r and "control" not in r):
            out.append(h)
    return out or hosts


def vm_allocations(db: Session, hypervisor_ids: Iterable[int]) -> List[Dict[str, Any]]:
    from app.models.server import Server
    ids = [int(i) for i in hypervisor_ids]
    if not ids:
        return []
    out = []
    for s in db.query(Server).filter(Server.hypervisor_id.in_(ids)).all():
        ps = str(s.vm_power_state or "").lower().replace("_", "")
        on = ps in ("poweredon", "on", "up", "running") or (not ps and str(s.status or "").upper() == "ONLINE")
        out.append({
            "id": s.id, "name": s.vm_name or s.name, "hypervisor_id": s.hypervisor_id,
            "cluster": s.vm_cluster, "host": s.vm_host_name, "ref": s.hypervisor_vm_id,
            "vcpu": int(s.vm_cpu_count or 0), "memory_gb": round((s.vm_memory_mb or 0) / 1024, 2),
            "disk_gb": float(s.vm_disk_gb or 0), "powered_on": on, "datastore": s.vm_datastore,
            "tier": getattr(s, "tier", None),
        })
    return out


def daily_cluster_series(db: Session, hypervisor_id: int, cluster_name: Optional[str],
                         host_names: List[str], days: int = 90) -> Dict[str, List[Optional[float]]]:
    """Günlük cluster Memory/CPU doluluk serisi (eski → yeni)."""
    if not host_names:
        return {"mem_pct": [], "cpu_pct": []}
    rows = db.execute(text("""
        WITH d AS (
          SELECT date_trunc('day', timestamp) AS day, host_name,
                 avg(mem_used_mb) AS mu, avg(mem_total_mb) AS mt,
                 avg(cpu_usage_pct * COALESCE(cpu_cores, 0)) AS cu, avg(COALESCE(cpu_cores, 0)) AS ct
            FROM hypervisor_host_metrics
           WHERE hypervisor_id = :hv AND host_name = ANY(:hosts)
             AND timestamp > now() - make_interval(days => :days)
             AND COALESCE(maintenance_mode, 0) = 0
           GROUP BY 1, 2
        )
        SELECT day, sum(mu) AS mu, sum(mt) AS mt, sum(cu) AS cu, sum(ct) AS ct
          FROM d GROUP BY day ORDER BY day
    """), {"hv": int(hypervisor_id), "hosts": list(host_names), "days": int(days)}).mappings().all()
    mem, cpu = [], []
    for r in rows:
        mt, mu, ct, cu = _f(r["mt"]), _f(r["mu"]), _f(r["ct"]), _f(r["cu"])
        mem.append(round(100.0 * mu / mt, 2) if mt and mu is not None else None)
        cpu.append(round(cu / ct, 2) if ct and cu is not None else None)
    return {"mem_pct": mem, "cpu_pct": cpu}


def latest_datastores(db: Session, hypervisor_ids: Iterable[int]) -> List[Dict[str, Any]]:
    from app.models.virt_datastore import VirtDatastore
    ids = [int(i) for i in hypervisor_ids]
    if not ids:
        return []
    out = []
    for d in db.query(VirtDatastore).filter(VirtDatastore.hypervisor_id.in_(ids)).all():
        out.append({
            "hypervisor_id": d.hypervisor_id, "name": d.name, "ref": d.ds_ref, "type": d.ds_type,
            "capacity_gb": _f(d.capacity_gb), "free_gb": _f(d.free_gb), "used_gb": _f(d.used_gb),
            "usage_pct": _f(d.usage_pct), "uncommitted_gb": _f(d.uncommitted_gb),
            "accessible": d.accessible, "host_count": d.host_count,
            "as_of": d.as_of.isoformat() if d.as_of else None,
        })
    return out


def daily_datastore_series(db: Session, hypervisor_id: int, name: str, days: int = 90) -> List[Optional[float]]:
    rows = db.execute(text("""
        SELECT date_trunc('day', timestamp) AS day, avg(usage_pct) AS u
          FROM virt_datastore_metrics
         WHERE hypervisor_id = :hv AND name = :n AND timestamp > now() - make_interval(days => :d)
         GROUP BY 1 ORDER BY 1
    """), {"hv": int(hypervisor_id), "n": name, "d": int(days)}).mappings().all()
    return [_f(r["u"]) for r in rows]


def virt_cluster_rows(db: Session, hypervisor_ids: Iterable[int]) -> Dict[Tuple[int, str], Any]:
    from app.models.virt_cluster import VirtCluster
    ids = [int(i) for i in hypervisor_ids]
    if not ids:
        return {}
    return {(c.hypervisor_id, c.name): c for c in db.query(VirtCluster).filter(VirtCluster.hypervisor_id.in_(ids)).all()}


def latest_config(db: Session, platform: str, source_id: int, entity_kind: str) -> List[Dict[str, Any]]:
    from app.services.findings.store import latest_snapshots
    out = []
    for s in latest_snapshots(db, platform=platform, source_id=source_id, entity_kind=entity_kind):
        p = s.payload or {}
        out.append({
            "ref": s.entity_ref, "name": s.entity_name, "cluster": s.cluster_name,
            "config": p.get("config") or {}, "state": p.get("state") or {},
            "captured_at": s.captured_at, "last_seen_at": s.last_seen_at,
        })
    return out


def group_hosts_by_cluster(hosts: List[Dict[str, Any]]) -> Dict[Tuple[int, str], List[Dict[str, Any]]]:
    g: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
    for h in hosts:
        g[(int(h["hypervisor_id"]), h.get("cluster_name") or "(cluster yok)")].append(h)
    return g


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ago(days: int) -> datetime:
    return utcnow() - timedelta(days=days)
