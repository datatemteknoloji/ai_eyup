"""Sahte (test) envanter için metrik tazeleme — `scripts/fake_virt_seed.py` kayıtları.

Sahte hypervisor/cluster gerçek bir API'ye bağlanamaz; periyodik metrik turları onları atlar. Metrikler
tazelenmezse kapasite (host metriği 6 sa), OpenShift monitoring (45 dk) pencereleri dolar ve sahte envanter
bir süre sonra "veri yok" görünür. Bu modül, sahte kayıtların SON örneğini şimdiki zamanla (küçük rastgele
sapmayla) çoğaltır — gerçek sync turunun yaptığı gibi her turda yeni satır ekler.

Yalnız `meta_data.fake_seed == True` kayıtlara dokunur; gerçek kayıtlara asla.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Son örnek bundan yeniyse tekrar yazılmaz (yoğun tetiklemede satır şişmesin)
MIN_AGE_MIN = 5

_HOST_SQL = """
INSERT INTO hypervisor_host_metrics (
    timestamp, hypervisor_id, host_name, host_ref, cpu_usage_mhz, cpu_total_mhz, cpu_usage_pct, cpu_cores, cpu_threads,
    mem_used_mb, mem_total_mb, mem_usage_pct, ds_used_gb, ds_total_gb, ds_usage_pct, vms_running, vms_total,
    connection_state, power_state, maintenance_mode, cluster_name, cluster_ref, overall_status)
SELECT now(), hypervisor_id, host_name, host_ref, cpu_usage_mhz, cpu_total_mhz,
       LEAST(99, GREATEST(1, cpu_usage_pct + (random() - 0.5) * 6)), cpu_cores, cpu_threads,
       mem_total_mb * LEAST(97, GREATEST(2, mem_usage_pct + (random() - 0.5) * 4)) / 100.0, mem_total_mb,
       LEAST(97, GREATEST(2, mem_usage_pct + (random() - 0.5) * 4)), ds_used_gb, ds_total_gb, ds_usage_pct,
       vms_running, vms_total, connection_state, power_state, maintenance_mode, cluster_name, cluster_ref, overall_status
  FROM (SELECT DISTINCT ON (host_name) * FROM hypervisor_host_metrics WHERE hypervisor_id = :hid
         ORDER BY host_name, timestamp DESC) last
 WHERE last.timestamp < now() - make_interval(mins => :age)
"""

_VM_SQL = """
INSERT INTO virt_vm_metrics (
    timestamp, hypervisor_id, vm_ref, vm_name, server_id, host_name, cluster_name, datastore, power_state,
    num_cpu, mem_total_mb, cpu_usage_pct, mem_usage_pct, cpu_ready_pct, disk_latency_ms)
SELECT now(), hypervisor_id, vm_ref, vm_name, server_id, host_name, cluster_name, datastore, power_state,
       num_cpu, mem_total_mb,
       CASE WHEN power_state ILIKE '%on%' THEN LEAST(100, GREATEST(0, cpu_usage_pct + (random() - 0.5) * 10)) ELSE 0 END,
       CASE WHEN power_state ILIKE '%on%' THEN LEAST(100, GREATEST(0, mem_usage_pct + (random() - 0.5) * 6)) ELSE 0 END,
       cpu_ready_pct, disk_latency_ms
  FROM (SELECT DISTINCT ON (vm_ref) * FROM virt_vm_metrics WHERE hypervisor_id = :hid
         ORDER BY vm_ref, timestamp DESC) last
 WHERE last.timestamp < now() - make_interval(mins => :age)
"""

_OCP_SQL = """
INSERT INTO ocp_resource_metrics (
    timestamp, cluster_id, kind, object_key, name, namespace, role, status, node_name, cpu_used_cores,
    memory_used_gb, cpu_allocatable, memory_allocatable_gb, cpu_pct, memory_pct, restarts)
SELECT now(), cluster_id, kind, object_key, name, namespace, role, status, node_name,
       round((cpu_allocatable * np.cpu / 100.0)::numeric, 3)::float,
       round((memory_allocatable_gb * np.mem / 100.0)::numeric, 2)::float,
       cpu_allocatable, memory_allocatable_gb, round(np.cpu::numeric, 1)::float, round(np.mem::numeric, 1)::float, restarts
  FROM (SELECT DISTINCT ON (kind, object_key) * FROM ocp_resource_metrics WHERE cluster_id = :cid
         ORDER BY kind, object_key, timestamp DESC) last
 CROSS JOIN LATERAL (SELECT LEAST(98, GREATEST(1, COALESCE(last.cpu_pct, 20) + (random() - 0.5) * 8)) AS cpu,
                            LEAST(98, GREATEST(1, COALESCE(last.memory_pct, 40) + (random() - 0.5) * 4)) AS mem) np
 WHERE last.timestamp < now() - make_interval(mins => :age)
"""


def refresh_cluster(db: Session, cluster_id: int) -> Dict[str, Any]:
    r = db.execute(text(_OCP_SQL), {"cid": int(cluster_id), "age": MIN_AGE_MIN})
    db.commit()
    return {"cluster_id": cluster_id, "rows": r.rowcount or 0, "fake": True}


def refresh_all(db: Session) -> Dict[str, Any]:
    """Tüm sahte hypervisor ve OpenShift cluster'larının metriklerini tazele. Hata fırlatmaz."""
    from app.models.hypervisor import Hypervisor, HypervisorType
    from app.models.openshift import OpenShiftCluster

    out: Dict[str, Any] = {"hosts": 0, "vms": 0, "ocp_rows": 0}
    try:
        for hv in db.query(Hypervisor).all():
            if not (hv.meta_data or {}).get("fake_seed"):
                continue
            out["hosts"] += db.execute(text(_HOST_SQL), {"hid": hv.id, "age": MIN_AGE_MIN}).rowcount or 0
            if hv.hypervisor_type == HypervisorType.VMWARE:
                out["vms"] += db.execute(text(_VM_SQL), {"hid": hv.id, "age": MIN_AGE_MIN}).rowcount or 0
        db.commit()
        for c in db.query(OpenShiftCluster).all():
            if (c.meta_data or {}).get("fake_seed"):
                out["ocp_rows"] += refresh_cluster(db, c.id)["rows"]
    except Exception as exc:
        db.rollback()
        logger.warning("sahte envanter metrik tazeleme başarısız: %s", exc)
        out["error"] = str(exc)[:200]
    return out
