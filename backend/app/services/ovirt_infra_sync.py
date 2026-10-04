"""oVirt / OLVM host, storage domain ve cluster → mevcut virt tabloları."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_inventory import HypervisorHostInventory
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.server import Server
from app.models.virt_cluster import VirtCluster
from app.models.virt_datastore import VirtDatastore
from app.models.virt_metric import VirtDatastoreMetric
from app.services.hypervisor_credentials import hv_password

logger = logging.getLogger(__name__)


def sync_ovirt_infra(db: Session) -> Dict[str, Any]:
    hvs = (
        db.query(Hypervisor)
        .filter(Hypervisor.hypervisor_type == HypervisorType.KVM)
        .all()
    )
    if not hvs:
        return {"hypervisors": 0, "hosts": 0, "errors": []}

    from app.services.ovirt.ovirt_client import OVirtClient
    from app.services.ovirt.ovirt_parse import OVirtError

    total_hosts = 0
    errors: list = []
    now = datetime.now(timezone.utc)

    for hv in hvs:
        host = (hv.ip_address or hv.hostname or "").strip()
        user = (hv.username or "").strip()
        if not host or not user:
            errors.append(f"{hv.name}: IP/kullanıcı bilgisi eksik")
            continue
        try:
            client = OVirtClient(
                host=host,
                username=user,
                password=hv_password(hv),
                port=hv.port or 443,
                verify_ssl=False,
            )
            ok, detail = client.test_connection()
            if not ok:
                errors.append(f"{hv.name}: {detail or 'bağlantı başarısız'}")
                continue

            host_stats = client.get_all_host_stats() or []
            ds_list = client.list_datastores_status() or []
            from app.services.ovirt.ovirt_parse import aggregate_data_storage_usage
            sd_used, sd_total, sd_pct = aggregate_data_storage_usage(ds_list)
            for stat in host_stats:
                db.add(HypervisorHostMetric(
                    timestamp=now,
                    hypervisor_id=hv.id,
                    host_name=stat.get("host_name") or "unknown",
                    host_ref=stat.get("host_ref"),
                    cpu_usage_mhz=stat.get("cpu_usage_mhz"),
                    cpu_total_mhz=stat.get("cpu_total_mhz"),
                    cpu_usage_pct=stat.get("cpu_usage_pct"),
                    cpu_cores=stat.get("cpu_cores"),
                    cpu_threads=stat.get("cpu_threads"),
                    mem_used_mb=stat.get("mem_used_mb"),
                    mem_total_mb=stat.get("mem_total_mb"),
                    mem_usage_pct=stat.get("mem_usage_pct"),
                    ds_used_gb=stat.get("ds_used_gb") if stat.get("ds_used_gb") is not None else sd_used,
                    ds_total_gb=stat.get("ds_total_gb") if stat.get("ds_total_gb") is not None else sd_total,
                    ds_usage_pct=stat.get("ds_usage_pct") if stat.get("ds_usage_pct") is not None else sd_pct,
                    vms_running=stat.get("vms_running"),
                    vms_total=stat.get("vms_total"),
                    connection_state=stat.get("connection_state"),
                    power_state=stat.get("power_state"),
                    maintenance_mode=stat.get("maintenance_mode") or 0,
                    cluster_name=stat.get("cluster_name"),
                    cluster_ref=stat.get("cluster_ref"),
                    overall_status=stat.get("overall_status"),
                ))
                href = (stat.get("host_ref") or "").strip()
                if href:
                    inv = (
                        db.query(HypervisorHostInventory)
                        .filter(
                            HypervisorHostInventory.hypervisor_id == hv.id,
                            HypervisorHostInventory.host_ref == href,
                        )
                        .first()
                    )
                    if inv is None:
                        inv = HypervisorHostInventory(
                            hypervisor_id=hv.id, host_ref=href,
                        )
                        db.add(inv)
                    inv.host_name = stat.get("host_name") or inv.host_name or "unknown"
                    inv.vendor = stat.get("vendor")
                    inv.model = stat.get("model")
                    inv.cpu_model = stat.get("cpu_model")
                    inv.product_version = stat.get("product_version")
                    inv.product_full_name = stat.get("product_full_name")
                    inv.vnics = stat.get("vnics") or []
                    inv.dns = stat.get("dns") or {}
                    inv.cluster_name = stat.get("cluster_name")
                    inv.cluster_ref = stat.get("cluster_ref")
                    inv.overall_status = stat.get("overall_status")
                    inv.last_synced_at = now
                total_hosts += 1
            db.commit()

            for d in ds_list:
                name = (d.get("name") or "").strip()
                if not name:
                    continue
                row = (
                    db.query(VirtDatastore)
                    .filter(VirtDatastore.hypervisor_id == hv.id, VirtDatastore.name == name)
                    .first()
                )
                if row is None:
                    row = VirtDatastore(hypervisor_id=hv.id, name=name)
                    db.add(row)
                row.ds_ref = d.get("ref")
                row.ds_type = d.get("type")
                row.capacity_gb = d.get("capacity_gb")
                row.free_gb = d.get("free_gb")
                row.used_gb = d.get("used_gb")
                row.usage_pct = d.get("usage_pct")
                row.uncommitted_gb = d.get("uncommitted_gb")
                row.accessible = bool(d.get("accessible", True))
                row.host_count = d.get("host_count")
                row.as_of = now
            ds_rows = [
                {
                    "timestamp": now,
                    "hypervisor_id": hv.id,
                    "name": (d.get("name") or "").strip(),
                    "ds_ref": d.get("ref"),
                    "ds_type": d.get("type"),
                    "capacity_gb": d.get("capacity_gb"),
                    "free_gb": d.get("free_gb"),
                    "used_gb": d.get("used_gb"),
                    "usage_pct": d.get("usage_pct"),
                    "uncommitted_gb": d.get("uncommitted_gb"),
                    "accessible": 1 if d.get("accessible", True) else 0,
                    "host_count": d.get("host_count"),
                }
                for d in ds_list
                if (d.get("name") or "").strip()
            ]
            if ds_rows:
                db.bulk_insert_mappings(VirtDatastoreMetric, ds_rows)
            db.commit()

            for c in client.list_clusters_status() or []:
                cname = (c.get("name") or "").strip()
                if not cname:
                    continue
                row = (
                    db.query(VirtCluster)
                    .filter(VirtCluster.hypervisor_id == hv.id, VirtCluster.name == cname)
                    .first()
                )
                if row is None:
                    row = VirtCluster(hypervisor_id=hv.id, name=cname)
                    db.add(row)
                row.cluster_ref = c.get("ref")
                row.hosts = c.get("hosts")
                row.effective_hosts = c.get("effective_hosts")
                row.ha_enabled = c.get("ha_enabled")
                row.overall_status = c.get("overall_status")
                row.host_refs = c.get("host_refs") or []
                row.as_of = now
            db.commit()

            live = client.get_all_vm_live_stats() or []
            servers = db.query(Server).filter(Server.hypervisor_id == hv.id).all()
            by_ref = {str(s.hypervisor_vm_id): s for s in servers if s.hypervisor_vm_id}
            vm_rows = []
            for stats in live:
                ref = str(stats.get("vm_ref") or "")
                if not ref:
                    continue
                srv = by_ref.get(ref)
                name = (srv.vm_name or srv.name) if srv else stats.get("name")
                if not name:
                    continue
                vm_rows.append({
                    "timestamp": now,
                    "hypervisor_id": hv.id,
                    "vm_ref": ref,
                    "vm_name": name,
                    "server_id": srv.id if srv else None,
                    "host_name": (srv.vm_host_name if srv else None) or stats.get("host_name"),
                    "cluster_name": (srv.vm_cluster if srv else None) or stats.get("cluster_name"),
                    "datastore": (srv.vm_datastore if srv else None),
                    "power_state": stats.get("power_state"),
                    "num_cpu": stats.get("num_cpu") or (srv.vm_cpu_count if srv else None),
                    "mem_total_mb": stats.get("mem_total_mb") or (srv.vm_memory_mb if srv else None),
                    "cpu_usage_mhz": stats.get("cpu_usage_mhz"),
                    "cpu_usage_pct": stats.get("cpu_percent"),
                    "mem_used_mb": stats.get("mem_used_mb"),
                    "mem_usage_pct": stats.get("mem_percent"),
                    "balloon_mb": stats.get("ballooned_mb"),
                    "net_rx_kbps": stats.get("net_rx_kbps"),
                    "net_tx_kbps": stats.get("net_tx_kbps"),
                    "disk_read_iops": stats.get("disk_read_iops"),
                    "disk_write_iops": stats.get("disk_write_iops"),
                })
            if vm_rows:
                from app.models.virt_metric import VirtVmMetric
                db.bulk_insert_mappings(VirtVmMetric, vm_rows)
                db.commit()

            logger.info(
                "oVirt infra sync: %s → %s host, %s storage domain, %s VM metrik",
                hv.name, len(host_stats), len(ds_list), len(vm_rows),
            )
        except OVirtError as exc:
            db.rollback()
            errors.append(f"{hv.name}: {exc}")
            logger.error("oVirt infra sync API (%s): %s", hv.name, exc)
        except Exception as exc:
            db.rollback()
            errors.append(f"{hv.name}: {exc}")
            logger.error("oVirt infra sync (%s): %s", hv.name, exc, exc_info=True)

    return {"hypervisors": len(hvs), "hosts": total_hosts, "errors": errors}
