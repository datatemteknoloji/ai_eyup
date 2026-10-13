"""Kapasite motoru için DB okuyucuları (H.0) — ek API çağrısı YOK; yalnız findings config snapshot'ları ve
envanter tabloları okunur (vCenter/OLVM/OCP'ye ek yük bindirmez)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.services import virt_insights_data as vd
from app.services.capacity.model import ResourcePoolSpec

MB = 1024.0


def _rb(db: Session) -> None:
    try:
        db.rollback()
    except Exception:  # noqa: BLE001
        pass


def olvm_cluster_cfg(db: Session, hv_id: int, cluster: str) -> Optional[Dict[str, Any]]:
    """OLVM cluster yapılandırması (config snapshot). Yoksa None."""
    try:
        for c in vd.latest_config(db, "olvm", hv_id, "cluster"):
            if c.get("name") == cluster:
                return c.get("config") or None
    except Exception:  # noqa: BLE001 — tablo/veri yoksa bilinmiyor
        _rb(db)
    return None


def vmware_topology(db: Session, hv_id: int, cluster: str) -> Dict[str, Any]:
    """{datacenter: str|None, pools: tuple[ResourcePoolSpec]|None}. pools None = OKUNAMADI.

    `cluster_topology` snapshot'ı yoksa (eski kayıtlar / okuma hatası) → datacenter None, pools None.
    Snapshot'ta pools=None → okunamadı. Boş liste → okundu, havuz yok.
    `limit` -1 = sınırsız (vSphere sözleşmesi) → mem_limit_gb None.
    """
    try:
        for c in vd.latest_config(db, "vmware", hv_id, "cluster_topology"):
            if c.get("name") != cluster:
                continue
            cfg = c.get("config") or {}
            raw = cfg.get("pools")
            if raw is None:
                return {"datacenter": cfg.get("datacenter"), "pools": None}
            pools = []
            for p in raw:
                lim = p.get("mem_limit_mb")
                pools.append(ResourcePoolSpec(
                    name=str(p.get("name")),
                    mem_reservation_gb=(p["mem_reservation_mb"] / MB) if p.get("mem_reservation_mb") is not None else None,
                    cpu_reservation_mhz=p.get("cpu_reservation_mhz"),
                    mem_limit_gb=(lim / MB) if (lim is not None and lim >= 0) else None,
                    expandable=p.get("expandable"),
                    used_mem_gb=None,   # kullanım toplanmıyor → rezervasyonun tamamı düşülür (temkinli)
                ))
            return {"datacenter": cfg.get("datacenter"), "pools": tuple(pools)}
    except Exception:  # noqa: BLE001
        _rb(db)
    return {"datacenter": None, "pools": None}


def vmware_datastore_access(db: Session, hv_id: int, cluster: str,
                            ds_rows: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """Cluster'ın gördüğü datastore'lar + host seviyesinde erişim (`mounted_hosts`). Bilinmiyorsa None.

    Kaynak: cluster snapshot `datastore_refs` ve datastore snapshot `config.mounted_hosts` (host moref'leri).
    """
    try:
        cl = {x["name"]: x for x in vd.latest_config(db, "vmware", hv_id, "cluster")}
        refs = ((cl.get(cluster) or {}).get("config") or {}).get("datastore_refs") or []
        if not refs:
            return None
        snaps = {x["ref"]: x for x in vd.latest_config(db, "vmware", hv_id, "datastore")}
    except Exception:  # noqa: BLE001
        _rb(db)
        return None
    by_ref = {d.get("ref"): d for d in ds_rows if d.get("hypervisor_id") == hv_id}
    out = []
    for r in refs:
        d = by_ref.get(r)
        if d is None:
            continue
        mh = ((snaps.get(r) or {}).get("config") or {}).get("mounted_hosts")
        out.append({"name": d["name"], "free_gb": d.get("free_gb") or 0.0, "capacity_gb": d.get("capacity_gb") or 0.0,
                    "accessible": d.get("accessible"),
                    "host_refs": set(mh) if isinstance(mh, list) else None})
    return out or None


def ocp_virt_cpu_ratio(db: Session, hv_id: int) -> Dict[str, Any]:
    """OpenShift Virtualization `vmiCPUAllocationRatio` (HCO). Her zaman bir değer + KAYNAK etiketi döner:

      • source="hco"          — HyperConverged CR'dan okundu.
      • source="hco_default"  — CR okundu ama alan ayarlı değil → platform varsayılanı (10).
      • source="default"      — CR okunamadı (RBAC/eski snapshot) → varsayılan değer 10, ölçülmedi.
    Varsayılan: Red Hat OpenShift Virtualization Cluster Sizing Guide ("default maximum of 10:1").
    """
    from app.services.capacity.engine import DEFAULT_VMI_CPU_ALLOCATION_RATIO as DEF
    ratio, source = float(DEF), "default"
    try:
        for c in vd.latest_config(db, "ocp_virt", hv_id, "platform"):
            cfg = c.get("config") or {}
            if "hco_read" not in cfg:           # eski snapshot: HCO okuması yapılmamış
                continue
            if cfg.get("hco_read"):
                v = cfg.get("vmi_cpu_allocation_ratio")
                if isinstance(v, (int, float)) and v > 0:
                    ratio, source = float(v), "hco"
                else:
                    source = "hco_default"
            break
    except Exception:  # noqa: BLE001
        _rb(db)
    label = {
        "hco": f"HyperConverged'dan okundu (vmiCPUAllocationRatio = {ratio:g})",
        "hco_default": f"HyperConverged'da ayarlı değil — platform varsayılanı {ratio:g}",
        "default": f"varsayılan değer {ratio:g} (HyperConverged okunamadı; ölçülmedi)",
    }[source]
    return {"ratio": ratio, "source": source, "label": label}
