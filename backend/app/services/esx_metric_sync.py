"""
ESX Host Kaynak Metrik Senkronizasyonu
--------------------------------------
Tüm VMware hypervisor'lar vCenter üzerinden sorgulanır;
her ESX host'un anlık CPU / RAM / Datastore / VM sayısı
hypervisor_host_metrics tablosuna yazılır (15 dk'da bir).
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any

from sqlalchemy.orm import Session
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.hypervisor_inventory import HypervisorHostInventory

logger = logging.getLogger(__name__)


def sync_esx_metrics(db: Session) -> Dict[str, Any]:
    """
    DB'deki tüm VMware hypervisor'lardan ESX host metriklerini çeker
    ve hypervisor_host_metrics tablosuna yazar.

    Döner: {"hypervisors": int, "hosts": int, "errors": list}
    """
    vmware_hvs = (
        db.query(Hypervisor)
        .filter(Hypervisor.hypervisor_type == HypervisorType.VMWARE)
        .all()
    )

    if not vmware_hvs:
        logger.debug("ESX metric sync: VMware hypervisor kaydı yok, atlanıyor.")
        return {"hypervisors": 0, "hosts": 0, "errors": []}

    total_hosts = 0
    errors = []
    now = datetime.now(timezone.utc)

    for hv in vmware_hvs:
        host    = (hv.ip_address or hv.hostname or "").strip()
        port    = hv.port or 443
        user    = (hv.username or "").strip()
        from app.services.hypervisor_credentials import hv_password
        passwd  = hv_password(hv)

        if not host or not user:
            errors.append(f"{hv.name}: IP/kullanıcı bilgisi eksik")
            continue

        try:
            from app.services.vmware.vcenter_client import VCenterClient
            client = VCenterClient(
                host=host, username=user, password=passwd,
                port=port, verify_ssl=False,
            )

            host_stats = client.get_all_host_stats()
            if not host_stats:
                logger.warning(f"ESX metric sync: {hv.name} için host verisi dönmedi")
                errors.append(f"{hv.name}: host verisi alınamadı")
                continue

            # Donanım sağlığı ayrı SOAP çağrısı — hata verirse metrikler yazılmaya
            # devam eder (sensor listesi büyük olabildiği için metrik sorgusuna
            # eklenmedi).
            health_by_ref: Dict[str, Any] = {}
            try:
                health_by_ref = client.get_all_host_health() or {}
            except Exception as h_e:
                logger.warning("Host health sorgusu başarısız (%s): %s", hv.name, h_e)

            for stat in host_stats:
                _health = health_by_ref.get(stat.get("host_ref")) or {}
                record = HypervisorHostMetric(
                    timestamp        = now,
                    hypervisor_id    = hv.id,
                    host_name        = stat.get("host_name", "unknown"),
                    host_ref         = stat.get("host_ref"),
                    cpu_usage_mhz    = stat.get("cpu_usage_mhz"),
                    cpu_total_mhz    = stat.get("cpu_total_mhz"),
                    cpu_usage_pct    = stat.get("cpu_usage_pct"),
                    cpu_cores        = stat.get("cpu_cores"),
                    cpu_threads      = stat.get("cpu_threads"),
                    mem_used_mb      = stat.get("mem_used_mb"),
                    mem_total_mb     = stat.get("mem_total_mb"),
                    mem_usage_pct    = stat.get("mem_usage_pct"),
                    ds_used_gb       = stat.get("ds_used_gb"),
                    ds_total_gb      = stat.get("ds_total_gb"),
                    ds_usage_pct     = stat.get("ds_usage_pct"),
                    net_rx_kbps      = stat.get("net_rx_kbps"),
                    net_tx_kbps      = stat.get("net_tx_kbps"),
                    vms_running      = stat.get("vms_running"),
                    vms_total        = stat.get("vms_total"),
                    connection_state = stat.get("connection_state"),
                    power_state      = stat.get("power_state"),
                    maintenance_mode = stat.get("maintenance_mode", 0),
                    cluster_name     = stat.get("cluster_name"),
                    cluster_ref      = stat.get("cluster_ref"),
                    overall_status   = _health.get("overall_status") or stat.get("overall_status"),
                    sensor_bad_count = _health.get("sensor_bad_count"),
                )
                db.add(record)
                total_hosts += 1

            db.commit()
            logger.info(
                f"ESX metric sync: {hv.name} → {len(host_stats)} host kaydedildi"
            )

            # ── Datastore envanteri (isim bazlı kapasite) ────────────────────
            try:
                from app.models.virt_datastore import VirtDatastore
                ds_list = client.list_datastores_status() or []
                seen_names = set()
                for d in ds_list:
                    name = (d.get("name") or "").strip()
                    if not name:
                        continue
                    seen_names.add(name.lower())
                    row = (
                        db.query(VirtDatastore)
                        .filter(
                            VirtDatastore.hypervisor_id == hv.id,
                            VirtDatastore.name == name,
                        )
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
                    row.accessible = bool(d.get("accessible", True))
                    row.host_count = d.get("host_count")
                    row.as_of = now
                # Artık vCenter'da olmayan datastore'ları silme — tarihçe kalsın;
                # erişilemeyenler accessible=false ile gelir.
                #
                # Doluluk zaman serisi: virt_datastores UPSERT edildiği için
                # "datastore ne zaman dolar" sorusuna cevap verecek geçmiş
                # yoktu. Her turda ayrıca hypertable'a bir satır yazılır.
                from app.models.virt_metric import VirtDatastoreMetric
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
                if ds_list:
                    logger.info(
                        "Virt datastore sync: %s → %s datastore", hv.name, len(ds_list)
                    )
            except Exception as ds_e:
                db.rollback()
                errors.append(f"{hv.name} (datastore): {ds_e}")
                logger.warning("Datastore sync hatası (%s): %s", hv.name, ds_e)

            # ── Cluster envanteri (HA/DRS + effective kapasite + slot) ───────
            try:
                from app.models.virt_cluster import VirtCluster
                cl_list = client.list_clusters_status() or []
                for c in cl_list:
                    cname = (c.get("name") or "").strip()
                    if not cname:
                        continue
                    row = (
                        db.query(VirtCluster)
                        .filter(
                            VirtCluster.hypervisor_id == hv.id,
                            VirtCluster.name == cname,
                        )
                        .first()
                    )
                    if row is None:
                        row = VirtCluster(hypervisor_id=hv.id, name=cname)
                        db.add(row)
                    row.cluster_ref = c.get("ref")
                    row.hosts = c.get("hosts")
                    row.effective_hosts = c.get("effective_hosts")
                    row.cpu_cores = c.get("cpu_cores")
                    row.cpu_total_mhz = c.get("cpu_total_mhz")
                    row.cpu_effective_mhz = c.get("cpu_effective_mhz")
                    row.memory_gb = c.get("memory_gb")
                    row.memory_effective_gb = c.get("memory_effective_gb")
                    row.ha_enabled = c.get("ha_enabled")
                    row.admission_control_enabled = c.get("admission_control_enabled")
                    row.policy_type = c.get("policy_type")
                    row.policy_label = c.get("policy_label")
                    row.failover_level = c.get("failover_level")
                    row.cpu_failover_pct = c.get("cpu_failover_pct")
                    row.mem_failover_pct = c.get("mem_failover_pct")
                    row.current_failover_level = c.get("current_failover_level")
                    row.host_monitoring = c.get("host_monitoring")
                    row.vm_monitoring = c.get("vm_monitoring")
                    row.total_slots = c.get("total_slots")
                    row.used_slots = c.get("used_slots")
                    row.unreserved_slots = c.get("unreserved_slots")
                    row.slot_cpu_mhz = c.get("slot_cpu_mhz")
                    row.slot_memory_mb = c.get("slot_memory_mb")
                    row.total_good_hosts = c.get("total_good_hosts")
                    row.drs_enabled = c.get("drs_enabled")
                    row.drs_behavior = c.get("drs_behavior")
                    row.drs_migration_threshold = c.get("drs_migration_threshold")
                    row.vmotions = c.get("vmotions")
                    row.overall_status = c.get("overall_status")
                    row.host_refs = c.get("host_refs") or []
                    row.as_of = now
                db.commit()
                if cl_list:
                    logger.info(
                        "Virt cluster sync: %s → %s cluster", hv.name, len(cl_list)
                    )
            except Exception as cl_e:
                db.rollback()
                errors.append(f"{hv.name} (cluster): {cl_e}")
                logger.warning("Cluster sync hatası (%s): %s", hv.name, cl_e)

        except Exception as e:
            db.rollback()
            errors.append(f"{hv.name}: {e}")
            logger.error(f"ESX metric sync hatası ({hv.name}): {e}", exc_info=True)
            continue

        # ── Donanım/ağ envanteri — nadiren değişir, ayrı tabloya upsert edilir ──
        try:
            cpu_model_by_ref = {
                stat.get("host_ref"): stat.get("cpu_model") for stat in host_stats
            }
            stat_by_ref = {stat.get("host_ref"): stat for stat in host_stats}
            net_info = client.get_all_host_network_info()
            for host_ref, info in net_info.items():
                row = (
                    db.query(HypervisorHostInventory)
                    .filter(
                        HypervisorHostInventory.hypervisor_id == hv.id,
                        HypervisorHostInventory.host_ref == host_ref,
                    )
                    .first()
                )
                if row is None:
                    row = HypervisorHostInventory(hypervisor_id=hv.id, host_ref=host_ref)
                    db.add(row)

                row.host_name   = info.get("host_name") or row.host_name or "unknown"
                row.vendor      = info.get("vendor")
                row.model       = info.get("model")
                row.uuid        = info.get("uuid")
                row.cpu_model   = cpu_model_by_ref.get(host_ref)
                row.product_version = info.get("product_version")
                row.product_full_name = info.get("product_full_name")
                row.pnics       = info.get("pnics") or []
                row.vswitches   = info.get("vswitches") or []
                row.portgroups  = info.get("portgroups") or []
                row.vnics       = info.get("vnics") or []
                row.dns         = info.get("dns") or {}

                _stat = stat_by_ref.get(host_ref) or {}
                row.cluster_name = _stat.get("cluster_name")
                row.cluster_ref  = _stat.get("cluster_ref")
                row.parent_name  = _stat.get("parent_name")

                _health = (health_by_ref or {}).get(host_ref) or {}
                if _health:
                    row.overall_status    = _health.get("overall_status")
                    row.sensor_total      = _health.get("sensor_total")
                    row.sensor_bad_count  = _health.get("sensor_bad_count")
                    row.health_sensors    = _health.get("bad_sensors") or []
                    row.config_issues     = _health.get("config_issues") or []
                    row.health_checked_at = now

                row.last_synced_at = now

            db.commit()
            if net_info:
                logger.info(
                    f"ESX network envanteri: {hv.name} → {len(net_info)} host güncellendi"
                )

        except Exception as e:
            db.rollback()
            errors.append(f"{hv.name} (network envanteri): {e}")
            logger.warning(f"ESX network envanteri hatası ({hv.name}): {e}")

    return {
        "hypervisors": len(vmware_hvs),
        "hosts":       total_hosts,
        "errors":      errors,
    }
