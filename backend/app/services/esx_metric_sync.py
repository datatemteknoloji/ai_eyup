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

            for stat in host_stats:
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
                db.commit()
                if ds_list:
                    logger.info(
                        "Virt datastore sync: %s → %s datastore", hv.name, len(ds_list)
                    )
            except Exception as ds_e:
                db.rollback()
                errors.append(f"{hv.name} (datastore): {ds_e}")
                logger.warning("Datastore sync hatası (%s): %s", hv.name, ds_e)

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
                row.pnics       = info.get("pnics") or []
                row.vswitches   = info.get("vswitches") or []
                row.portgroups  = info.get("portgroups") or []
                row.vnics       = info.get("vnics") or []
                row.dns         = info.get("dns") or {}
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
