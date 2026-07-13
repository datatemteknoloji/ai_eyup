"""
vCenter VM canlı performans/durum verisi — DB'de saklanmayan ama VM'lerin kendi
QuickStats yapısından anlık okunabilen metrikler: CPU/RAM gerçek kullanım,
memory ballooning/swap, uptime (boot time), snapshot sayısı ve en eski snapshot.

`VCenterClient.get_all_vm_live_stats()` tek SOAP çağrısıyla TÜM VM'leri döner;
bu modül sonucu `Server` kayıtlarıyla eşleştirir ve AI Q&A handler'larının
kullanacağı normalize edilmiş liste üretir.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor
from app.models.server import Server

logger = logging.getLogger(__name__)


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
        password=hv.password or (hv.connection_config or {}).get("password", ""),
        port=hv.port or 443,
    )


def fetch_live_vm_stats(db: Session) -> Dict[str, Any]:
    """Tüm VMware hypervisor'lardan canlı VM istatistiklerini toplar ve Server ile eşleştirir."""
    hvs = _vmware_hypervisors(db)
    if not hvs:
        return {"vms": [], "errors": ["Tanımlı VMware hypervisor yok"]}

    server_by_ref: Dict[str, Server] = {
        s.hypervisor_vm_id: s
        for s in db.query(Server).filter(Server.hypervisor_vm_id.isnot(None)).all()
        if s.hypervisor_vm_id
    }

    vms: List[Dict[str, Any]] = []
    errors: List[str] = []
    for hv in hvs:
        client = _build_client(hv)
        try:
            raw_stats = client.get_all_vm_live_stats()
        except Exception as exc:
            logger.error("get_all_vm_live_stats failed for %s: %s", hv.name, exc, exc_info=True)
            errors.append(f"{hv.name}: {exc}")
            continue

        # Host başına per-core MHz — VM CPU% hesaplamak için (host_ref → mhz/core)
        host_mhz_per_core: Dict[str, float] = {}
        try:
            for h in client.get_all_host_stats():
                cores = h.get("cpu_cores") or 0
                total_mhz = h.get("cpu_total_mhz") or 0
                if cores and total_mhz:
                    host_mhz_per_core[h.get("host_ref")] = total_mhz / cores
        except Exception as exc:
            logger.warning("get_all_host_stats (VM cpu%% için) başarısız: %s", exc)

        for r in raw_stats:
            srv = server_by_ref.get(r.get("vm_ref"))
            num_cpu = r.get("num_cpu") or (srv.vm_cpu_count if srv else None) or 1
            cpu_mhz = r.get("cpu_usage_mhz")
            mem_used_mb = r.get("guest_mem_usage_mb") or r.get("host_mem_usage_mb")
            mem_total_mb = (srv.vm_memory_mb if srv else None) or 0

            uptime_s = r.get("uptime_seconds")
            if not uptime_s and r.get("boot_time"):
                # QuickStats.uptimeSeconds bazı vCenter sürümlerinde/VM'lerde boş
                # dönebiliyor (opsiyonel alan) — bootTime üzerinden hesapla.
                try:
                    boot_dt = datetime.fromisoformat(str(r["boot_time"]).replace("Z", "+00:00"))
                    uptime_s = (datetime.now(timezone.utc) - boot_dt).total_seconds()
                except Exception:
                    uptime_s = None
            uptime_days = round(uptime_s / 86400, 1) if uptime_s and uptime_s > 0 else None

            mhz_per_core = host_mhz_per_core.get(r.get("host_ref"))
            cpu_pct = None
            if cpu_mhz is not None and mhz_per_core and num_cpu:
                cpu_pct = round(cpu_mhz / (num_cpu * mhz_per_core) * 100, 1)

            vms.append({
                "vm_ref": r.get("vm_ref"),
                "name": r.get("name"),
                "server_id": srv.id if srv else None,
                "hypervisor": hv.name,
                "power_state": r.get("power_state"),
                "boot_time": r.get("boot_time"),
                "uptime_days": uptime_days,
                "num_cpu": num_cpu,
                "cpu_usage_mhz": cpu_mhz,
                "cpu_usage_pct": cpu_pct,
                "mem_used_mb": mem_used_mb,
                "mem_total_mb": mem_total_mb,
                "mem_usage_pct": round(mem_used_mb / mem_total_mb * 100, 1) if mem_used_mb and mem_total_mb else None,
                "ballooned_mb": r.get("ballooned_mb") or 0,
                "swapped_mb": r.get("swapped_mb") or 0,
                "snapshot_count": r.get("snapshot_count") or 0,
                "snapshot_oldest": r.get("snapshot_oldest"),
            })

    return {"vms": vms, "errors": errors, "hypervisors": len(hvs)}
