"""Dinamik alan seçimi — sorudan istenen field'ları SoT join sonucundan projekte et.

Desen (tüm modüller):
  1) Model sorudan entity + fields çıkarır
  2) Tool birden fazla SoT'u join edip tek satır üretir
  3) Yalnız istenen alanlar döner (uydurma yok; yoksa null + missing_fields)

ESXi örneği: metrics (CPU…) ⋈ inventory (IP, version, vendor…)
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set


# Canonical alan → kabul edilen kullanıcı/alias adları
ESXI_HOST_FIELD_ALIASES: Dict[str, tuple] = {
    "name": ("name", "host_name", "hostname", "host", "esxi", "esx"),
    "ip": ("ip", "mgmt_ip", "management_ip", "ip_address", "address"),
    "version": ("version", "esxi_version", "product_version", "build", "esx_version"),
    "vendor": ("vendor", "üretici", "uretici"),
    "model": ("model",),
    "cpu_pct": ("cpu_pct", "cpu", "cpu_usage"),
    "mem_pct": ("mem_pct", "mem", "memory", "ram"),
    "ds_pct": ("ds_pct", "disk", "datastore_pct", "storage"),
    "vms_running": ("vms_running", "running_vms"),
    "vms_total": ("vms_total", "vms"),
    "connection_state": ("connection_state", "state", "status", "connection"),
    "maintenance": ("maintenance", "maintenance_mode", "bakim"),
    "hypervisor": ("hypervisor", "vcenter", "vcenter_name"),
    "cluster": ("cluster",),
    "cpu_cores": ("cpu_cores", "cores"),
    "cpu_model": ("cpu_model",),
}

# Varsayılan kısa özet (fields verilmezse)
ESXI_HOST_DEFAULT_FIELDS: tuple = ("name", "ip", "version", "connection_state", "hypervisor")

VM_FIELD_ALIASES: Dict[str, tuple] = {
    "name": ("name", "vm", "vm_name", "guest"),
    "ip": ("ip", "guest_ip", "ip_address"),
    "power_state": ("power_state", "power", "state", "status"),
    "vcpu": ("vcpu", "cpu", "cpu_count", "vcpus"),
    "memory_mb": ("memory_mb", "mem_mb", "ram", "memory"),
    "disk_gb": ("disk_gb", "disk", "storage_gb", "disk_size", "boyut"),
    "disk_count": ("disk_count", "disks_count", "n_disks", "adet", "disk_adet"),
    "disks": ("disks", "disk_list", "vmdk", "hard_disks"),
    "host": ("host", "esxi", "esx", "host_name", "vm_host", "esxi_host"),
    "esxi_host": ("esxi_host", "host", "esxi", "esx", "vm_host"),
    "cluster": ("cluster",),
    "datastore": ("datastore", "ds", "datastore_name"),
    "guest_os": ("guest_os", "os", "os_type"),
    "hypervisor": ("hypervisor", "vcenter", "vcenter_name"),
    "vcenter": ("vcenter", "hypervisor", "vcenter_name"),
    "vcenter_endpoint": ("vcenter_endpoint", "vcenter_ip", "vcenter_host"),
    "cpu_mhz": ("cpu_mhz",),
    "mem_active_mb": ("mem_active_mb", "mem_active"),
}

# Varsayılan özet — disk toplamı her zaman (model fields ile düşüremesin diye
# list_vms_db ayrıca VM_INVENTORY_REQUIRED ile birleştirir)
VM_DEFAULT_FIELDS: tuple = (
    "name", "ip", "power_state", "host", "cluster", "datastore", "hypervisor",
    "disk_gb", "disk_count",
)

# fields projeksiyonunda asla düşürülmeyen çekirdek envanter alanları
VM_INVENTORY_REQUIRED_FIELDS: tuple = (
    "name", "ip", "disk_gb", "disk_count",
)

DATASTORE_FIELD_ALIASES: Dict[str, tuple] = {
    "name": ("name", "datastore", "ds", "datastore_name"),
    "type": ("type", "ds_type"),
    "capacity_gb": ("capacity_gb", "capacity", "size_gb"),
    "free_gb": ("free_gb", "free"),
    "used_gb": ("used_gb", "used"),
    "usage_pct": ("usage_pct", "usage", "pct", "doluluk"),
    "accessible": ("accessible", "access"),
    "host_count": ("host_count", "hosts"),
    "hypervisor": ("hypervisor", "vcenter"),
}

DATASTORE_DEFAULT_FIELDS: tuple = (
    "name", "usage_pct", "free_gb", "capacity_gb", "accessible", "hypervisor",
)

# Çapraz eşleştirme satırı — anahtar + özet alanlar
CROSS_MATCH_FIELD_ALIASES: Dict[str, tuple] = {
    "match_key": ("match_key", "key", "join_key"),
    "match_axis": ("match_axis", "axis", "join_on"),
    "host": ("host", "esxi", "host_name", "name"),
    "host_ip": ("host_ip", "ip", "mgmt_ip"),
    "host_version": ("host_version", "version", "esxi_version"),
    "cpu_pct": ("cpu_pct", "cpu"),
    "mem_pct": ("mem_pct", "mem", "memory"),
    "connection_state": ("connection_state", "state"),
    "hypervisor": ("hypervisor", "vcenter"),
    "vm_count": ("vm_count", "vms_count", "n_vms"),
    "vms": ("vms", "vm_names"),
    "datastore": ("datastore", "ds"),
    "ds_usage_pct": ("ds_usage_pct", "datastore_pct"),
    "ds_free_gb": ("ds_free_gb",),
    "alarm_count": ("alarm_count", "alarms_count", "n_alarms"),
    "alarms": ("alarms", "alarm_titles"),
}

CROSS_MATCH_DEFAULT_FIELDS: tuple = (
    "match_key", "host", "host_ip", "vm_count", "vms",
    "datastore", "ds_usage_pct", "alarm_count", "alarms", "hypervisor",
)


def normalize_fields(
    requested: Optional[Sequence[str]],
    *,
    aliases: Dict[str, tuple],
    default: Sequence[str],
    required: Optional[Sequence[str]] = None,
) -> List[str]:
    """Kullanıcı/model alan adlarını kanonik listeye çevir; boşsa default.

    required: projeksiyonda her zaman korunacak alanlar (model düşüremez).
    """
    if not requested:
        base = list(default)
    else:
        alias_to_canon: Dict[str, str] = {}
        for canon, alts in aliases.items():
            for a in alts:
                alias_to_canon[a.lower()] = canon
            alias_to_canon[canon.lower()] = canon

        out: List[str] = []
        seen: Set[str] = set()
        for raw in requested:
            key = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
            if not key:
                continue
            canon = alias_to_canon.get(key)
            if not canon:
                # bilinmeyen alanı olduğu gibi geç (ileri uyumluluk)
                canon = key
            if canon not in seen:
                seen.add(canon)
                out.append(canon)
        base = out or list(default)

    if required:
        seen = set(base)
        for r in required:
            if r not in seen:
                base.append(r)
                seen.add(r)
    return base


def project_rows(
    rows: Iterable[Dict[str, Any]],
    fields: Sequence[str],
) -> Dict[str, Any]:
    """Satırlardan yalnız istenen alanları al; eksikleri missing_fields'ta topla."""
    projected: List[Dict[str, Any]] = []
    missing_global: Set[str] = set()
    for row in rows:
        item: Dict[str, Any] = {}
        for f in fields:
            val = row.get(f)
            item[f] = val
            if val is None or val == "" or val == []:
                missing_global.add(f)
        projected.append(item)
    return {
        "fields": list(fields),
        "items": projected,
        "missing_fields": sorted(missing_global),
    }


def pick_mgmt_ip(vnics: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    """VMkernel NIC listesinden yönetim IP'si seç (Management / vmk0 / ilk dolu)."""
    if not vnics:
        return None
    scored = []
    for vn in vnics:
        if not isinstance(vn, dict):
            continue
        ip = (vn.get("ip_address") or "").strip()
        if not ip:
            continue
        device = (vn.get("device") or "").lower()
        pg = (vn.get("portgroup") or "").lower()
        score = 0
        if "management" in pg or "mgmt" in pg:
            score += 20
        if device in ("vmk0", "vmk0."):
            score += 10
        if device.startswith("vmk"):
            score += 5
        scored.append((score, ip))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def norm_join_key(value: Optional[str]) -> str:
    """Çapraz eşleştirme anahtarı — trim + lower."""
    return (value or "").strip().lower()


def index_by_key(
    rows: Iterable[Dict[str, Any]],
    key_fields: Sequence[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Satırları verilen alanlardan birine göre indeksle (ilk dolu alan)."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        key = ""
        for f in key_fields:
            key = norm_join_key(str(row.get(f) or ""))
            if key:
                break
        if not key:
            continue
        out.setdefault(key, []).append(row)
    return out
