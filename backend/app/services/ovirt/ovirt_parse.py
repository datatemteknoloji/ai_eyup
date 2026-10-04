"""oVirt/OLVM REST yanıtlarını ainew envanter/metrik şemasına çevirir (IO yok)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

_NEXT_LINK_RE = re.compile(r'<([^>]+)>\s*;\s*rel="?next"?', re.I)

_POWER_ON = frozenset({
    "up", "powering_up", "reboot_in_progress", "migrating",
    "wait_for_launch", "saving_state", "restoring_state",
})
_POWER_OFF = frozenset({
    "down", "not_responding", "powering_down", "image_locked", "unassigned",
})
_SUSPENDED = frozenset({"suspended", "paused"})


class OVirtError(Exception):
    """Engine REST çağrısı başarısız — boş liste ile karıştırılmamalı."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def to_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def to_float(val: Any) -> Optional[float]:
    try:
        if val is None or val == "":
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def unwrap_items(data: Any, *keys: str) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return []
    for key in keys:
        raw = data.get(key)
        if raw is None:
            continue
        if isinstance(raw, dict):
            return [raw]
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
    return []


def nested_name(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    if obj.get("name"):
        return str(obj["name"])
    inner = obj.get("host") or obj.get("cluster") or obj.get("storage_domain") or obj
    if isinstance(inner, dict):
        return str(inner.get("name") or "")
    return ""


def nested_id(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    if obj.get("id"):
        return str(obj["id"])
    inner = obj.get("host") or obj.get("cluster") or obj
    if isinstance(inner, dict):
        return str(inner.get("id") or "")
    return ""


def power_fields(raw_status: Any) -> Tuple[str, str]:
    """(server.status, vm_power_state) — Server.status ONLINE/OFFLINE, güç VMware-benzeri."""
    if isinstance(raw_status, dict):
        raw_status = raw_status.get("#text") or raw_status.get("state") or "unknown"
    s = str(raw_status or "unknown").lower().replace("-", "_")
    if s in _POWER_ON:
        return "ONLINE", "POWERED_ON"
    if s in _SUSPENDED:
        return "OFFLINE", "SUSPENDED"
    if s in _POWER_OFF:
        return "OFFLINE", "POWERED_OFF"
    if s in ("online",):
        return "ONLINE", "POWERED_ON"
    if s in ("offline",):
        return "OFFLINE", "POWERED_OFF"
    return "OFFLINE", s.upper() or "UNKNOWN"


def cpu_count(vm: Dict[str, Any]) -> int:
    topo = (vm.get("cpu") or {}).get("topology") or {}
    cores = to_int(topo.get("cores", 1), 1)
    sockets = to_int(topo.get("sockets", 1), 1)
    threads = to_int(topo.get("threads", 1), 1)
    return max(1, cores * sockets * threads)


def memory_bytes(vm: Dict[str, Any]) -> int:
    return to_int(vm.get("memory", 0), 0)


def guest_os_full(vm: Dict[str, Any]) -> str:
    gos = vm.get("guest_operating_system") or {}
    if not isinstance(gos, dict):
        return ""
    ver = gos.get("version") or {}
    full = ""
    if isinstance(ver, dict):
        full = str(ver.get("full_version") or ver.get("major") or "")
    family = str(gos.get("family") or "")
    codename = str(gos.get("codename") or "")
    parts = [p for p in (family, full, codename) if p]
    if parts:
        return " ".join(parts)
    os_block = vm.get("os") or {}
    if isinstance(os_block, dict):
        return str(os_block.get("type") or "")
    return ""


def first_ipv4(devices: List[Dict[str, Any]]) -> str:
    for dev in devices:
        ip_list = ((dev.get("ips") or {}).get("ip")) or []
        if isinstance(ip_list, dict):
            ip_list = [ip_list]
        for ip_entry in ip_list:
            if not isinstance(ip_entry, dict):
                continue
            addr = ip_entry.get("address") or ""
            ver = str(ip_entry.get("version") or "v4")
            if addr and ver.lower() in ("v4", "4") and not addr.startswith(("127.", "169.254.")):
                return addr
    return ""


def nics_to_network_info(nics: List[Dict[str, Any]], devices: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    networks: List[Dict[str, Any]] = []
    for nic in nics:
        mac = ((nic.get("mac") or {}).get("address")) or ""
        networks.append({
            "name": nic.get("name") or "",
            "mac": mac,
            "ips": [],
            "plugged": nic.get("plugged"),
            "linked": nic.get("linked"),
        })
    if devices:
        by_mac = {(d.get("mac") or {}).get("address"): d for d in devices if isinstance(d, dict)}
        for net in networks:
            dev = by_mac.get(net.get("mac"))
            if not dev:
                continue
            ips = []
            ip_list = ((dev.get("ips") or {}).get("ip")) or []
            if isinstance(ip_list, dict):
                ip_list = [ip_list]
            for ip_entry in ip_list:
                if isinstance(ip_entry, dict) and ip_entry.get("address"):
                    ips.append({
                        "address": ip_entry.get("address"),
                        "version": ip_entry.get("version") or "v4",
                    })
            net["ips"] = ips
    return networks


def statistic_map(payload: Any) -> Dict[str, float]:
    items = unwrap_items(payload if isinstance(payload, dict) else {}, "statistic", "statistics")
    out: Dict[str, float] = {}
    for st in items:
        name = str(st.get("name") or "")
        if not name:
            continue
        values = st.get("values") or {}
        raw_vals = values.get("value") if isinstance(values, dict) else values
        if isinstance(raw_vals, dict):
            raw_vals = [raw_vals]
        if not isinstance(raw_vals, list) or not raw_vals:
            datum = to_float(st.get("datum"))
            if datum is not None:
                out[name] = datum
            continue
        first = raw_vals[0] if raw_vals else {}
        if isinstance(first, dict):
            datum = to_float(first.get("datum"))
        else:
            datum = to_float(first)
        if datum is not None:
            out[name] = datum
    return out


def host_address(host: Dict[str, Any]) -> str:
    raw = host.get("address")
    if isinstance(raw, dict):
        raw = raw.get("address") or raw.get("ip") or raw.get("#text")
    return str(raw or "").strip()


def host_canonical_name(host: Dict[str, Any]) -> str:
    """Dashboard/ESXi ile aynı: mümkünse yönetim IP/FQDN, yoksa kısa ad."""
    return host_address(host) or str(host.get("name") or "").strip() or "unknown"


def host_inventory_fields(host: Dict[str, Any]) -> Dict[str, Any]:
    hw = host.get("hardware") if isinstance(host.get("hardware"), dict) else {}
    cpu = host.get("cpu") if isinstance(host.get("cpu"), dict) else {}
    ver = host.get("version") if isinstance(host.get("version"), dict) else {}
    addr = host_address(host)
    name = str(host.get("name") or "").strip()
    vnics: List[Dict[str, Any]] = []
    if addr:
        vnics.append({"device": "mgmt", "portgroup": "management", "ip_address": addr})
    full = ver.get("full_version")
    if not full and ver.get("major") is not None:
        bits = [str(ver.get("major"))]
        if ver.get("minor") is not None:
            bits.append(str(ver.get("minor")))
        if ver.get("build") not in (None, ""):
            bits.append(str(ver.get("build")))
        full = ".".join(bits)
    return {
        "host_name": host_canonical_name(host),
        "short_name": name or None,
        "address": addr or None,
        "vendor": hw.get("manufacturer"),
        "model": hw.get("product_name") or hw.get("family"),
        "cpu_model": cpu.get("name"),
        "product_version": str(full) if full else None,
        "product_full_name": "OLVM / oVirt Host",
        "vnics": vnics,
        "dns": {"host_name": name or None, "address": addr or None},
    }


def host_metrics_from_stats(host: Dict[str, Any], stats: Dict[str, float]) -> Dict[str, Any]:
    cpu_user = stats.get("cpu.current.user")
    cpu_sys = stats.get("cpu.current.system")
    cpu_idle = stats.get("cpu.current.idle")
    cpu_pct = None
    if cpu_user is not None or cpu_sys is not None:
        cpu_pct = (cpu_user or 0) + (cpu_sys or 0)
    elif cpu_idle is not None:
        cpu_pct = max(0.0, min(100.0, 100.0 - cpu_idle))

    mem_total = stats.get("memory.total") or stats.get("memory.installed")
    mem_used = stats.get("memory.used")
    mem_free = stats.get("memory.free")
    if mem_used is None and mem_total is not None and mem_free is not None:
        mem_used = mem_total - mem_free
    mem_total_mb = (mem_total / (1024 * 1024)) if mem_total else None
    mem_used_mb = (mem_used / (1024 * 1024)) if mem_used else None
    mem_pct = None
    if mem_used is not None and mem_total:
        mem_pct = round(100.0 * mem_used / mem_total, 1)

    cpu_topo = (host.get("cpu") or {}).get("topology") or {}
    cores = to_int(cpu_topo.get("cores"), 0) * max(to_int(cpu_topo.get("sockets"), 1), 1)
    threads = cores * max(to_int(cpu_topo.get("threads"), 1), 1)
    speed = to_float((host.get("cpu") or {}).get("speed"))

    summary = host.get("summary") or {}
    vms_total = to_int(summary.get("total"), 0)
    vms_active = to_int(summary.get("active"), 0)

    raw_status = host.get("status")
    if isinstance(raw_status, dict):
        raw_status = raw_status.get("state") or raw_status.get("#text")
    status = str(raw_status or "").lower()
    connection_state = "connected" if status in ("up",) else (
        "maintenance" if status in ("preparing_for_maintenance", "maintenance") else
        "notResponding" if status in ("non_responsive", "down", "error") else status or "unknown"
    )
    maintenance = 1 if "maintenance" in status else 0
    power_state = "poweredOn" if status == "up" else ("standBy" if "maintenance" in status else "unknown")

    cluster_name = nested_name(host.get("cluster"))
    cluster_ref = nested_id(host.get("cluster"))

    cpu_total_mhz = (speed * cores) if speed and cores else None
    cpu_usage_mhz = (cpu_total_mhz * cpu_pct / 100.0) if cpu_total_mhz and cpu_pct is not None else None

    inv = host_inventory_fields(host)
    return {
        "host_name": inv["host_name"],
        "short_name": inv.get("short_name"),
        "address": inv.get("address"),
        "host_ref": host.get("id") or "",
        "cpu_usage_mhz": cpu_usage_mhz,
        "cpu_total_mhz": cpu_total_mhz,
        "cpu_usage_pct": round(cpu_pct, 1) if cpu_pct is not None else None,
        "cpu_cores": cores or None,
        "cpu_threads": threads or None,
        "mem_used_mb": mem_used_mb,
        "mem_total_mb": mem_total_mb,
        "mem_usage_pct": mem_pct,
        "vms_running": vms_active,
        "vms_total": vms_total,
        "connection_state": connection_state,
        "power_state": power_state,
        "maintenance_mode": maintenance,
        "cluster_name": cluster_name or None,
        "cluster_ref": cluster_ref or None,
        "overall_status": "green" if status == "up" else ("yellow" if maintenance else "red"),
        "vendor": inv.get("vendor"),
        "model": inv.get("model"),
        "cpu_model": inv.get("cpu_model"),
        "product_version": inv.get("product_version"),
        "product_full_name": inv.get("product_full_name"),
        "vnics": inv.get("vnics") or [],
        "dns": inv.get("dns") or {},
    }


_NON_DATA_STORAGE = frozenset({"iso", "export", "iso_domain", "export_domain"})


def aggregate_data_storage_usage(
    ds_list: List[Dict[str, Any]] | None,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """ISO/export hariç data storage domain toplamı → (used_gb, total_gb, usage_pct)."""
    used = 0.0
    total = 0.0
    any_data = False
    for d in ds_list or []:
        kind = str(d.get("type") or "").lower()
        if kind in _NON_DATA_STORAGE:
            continue
        cap = d.get("capacity_gb")
        if not cap:
            continue
        any_data = True
        total += float(cap)
        used += float(d.get("used_gb") or 0)
    if not any_data or total <= 0:
        return None, None, None
    return round(used, 1), round(total, 1), round(100.0 * used / total, 1)


def storage_domain_row(sd: Dict[str, Any]) -> Dict[str, Any]:
    available = to_float(sd.get("available"))
    used = to_float(sd.get("used"))
    committed = to_float(sd.get("committed"))
    capacity = None
    if available is not None and used is not None:
        capacity = available + used
    cap_gb = (capacity / (1024 ** 3)) if capacity else None
    free_gb = (available / (1024 ** 3)) if available is not None else None
    used_gb = (used / (1024 ** 3)) if used is not None else None
    usage_pct = round(100.0 * used / capacity, 1) if capacity and used is not None else None
    uncommitted_gb = (committed / (1024 ** 3)) if committed is not None else None
    status = sd.get("status")
    if isinstance(status, dict):
        status = status.get("state") or status.get("#text")
    accessible = str(status or "active").lower() in ("active", "up", "ok")
    return {
        "name": sd.get("name") or "",
        "ref": sd.get("id") or "",
        "type": sd.get("storage", {}).get("type") if isinstance(sd.get("storage"), dict) else sd.get("type"),
        "capacity_gb": cap_gb,
        "free_gb": free_gb,
        "used_gb": used_gb,
        "usage_pct": usage_pct,
        "uncommitted_gb": uncommitted_gb,
        "accessible": accessible,
        "host_count": None,
    }


def cluster_row(cluster: Dict[str, Any], host_count: int = 0) -> Dict[str, Any]:
    ha = cluster.get("ha") if isinstance(cluster.get("ha"), dict) else {}
    fencing = cluster.get("fencing_policy") if isinstance(cluster.get("fencing_policy"), dict) else {}
    mem_oc = cluster.get("memory_policy") if isinstance(cluster.get("memory_policy"), dict) else {}
    overcommit = mem_oc.get("overcommit") if isinstance(mem_oc.get("overcommit"), dict) else {}
    ha_enabled = ha.get("enabled") if ha else cluster.get("ha")
    if isinstance(ha_enabled, str):
        ha_enabled = ha_enabled.lower() in ("true", "1")
    return {
        "name": cluster.get("name") or "",
        "ref": cluster.get("id") or "",
        "hosts": host_count or None,
        "effective_hosts": host_count or None,
        "ha_enabled": bool(ha_enabled) if ha_enabled is not None else None,
        "admission_control_enabled": None,
        "drs_enabled": None,
        "overall_status": "green",
        "host_refs": [],
        "memory_overcommit_pct": to_int(overcommit.get("percent")) if overcommit else None,
        "fencing_enabled": fencing.get("enabled") if fencing else None,
    }


def next_link(headers: Dict[str, str]) -> Optional[str]:
    raw = headers.get("Link") or headers.get("link") or ""
    m = _NEXT_LINK_RE.search(raw)
    if m:
        return m.group(1)
    return None


def event_severity(raw: Any) -> str:
    s = str(raw or "normal").lower()
    if s in ("error", "alert", "critical"):
        return "critical"
    if s in ("warning", "warn"):
        return "warning"
    return "info"


def vm_stats_to_live(vm: Dict[str, Any], stats: Dict[str, float]) -> Dict[str, Any]:
    cpu_user = stats.get("cpu.current.user")
    cpu_sys = stats.get("cpu.current.system")
    cpu_guest = stats.get("cpu.current.guest")
    cpu_pct = None
    parts = [p for p in (cpu_user, cpu_sys, cpu_guest) if p is not None]
    if parts:
        cpu_pct = sum(parts)
        if cpu_pct > 100:
            cpu_pct = min(100.0, cpu_pct)
    elif stats.get("cpu.current.total") is not None:
        cpu_pct = stats.get("cpu.current.total")
    mem_installed = stats.get("memory.installed") or float(memory_bytes(vm) or 0) or None
    mem_used = stats.get("memory.used")
    mem_pct = None
    mem_used_mb = (mem_used / (1024 * 1024)) if mem_used else None
    mem_total_mb = (mem_installed / (1024 * 1024)) if mem_installed else None
    if mem_used is not None and mem_installed:
        mem_pct = round(100.0 * mem_used / mem_installed, 1)
    ncpu = cpu_count(vm)
    cpu_mhz = None
    speed = to_float((vm.get("cpu") or {}).get("speed"))
    if speed and cpu_pct is not None:
        cpu_mhz = speed * ncpu * cpu_pct / 100.0
    _, power = power_fields(vm.get("status"))
    return {
        "vm_ref": vm.get("id") or "",
        "name": vm.get("name") or "",
        "host_name": nested_name(vm.get("host")) or None,
        "cluster_name": nested_name(vm.get("cluster")) or None,
        "power_state": power,
        "num_cpu": ncpu,
        "cpu_percent": round(cpu_pct, 1) if cpu_pct is not None else None,
        "cpu_mhz": cpu_mhz,
        "cpu_usage_mhz": cpu_mhz,
        "mem_percent": mem_pct,
        "mem_used_mb": mem_used_mb,
        "mem_total_mb": mem_total_mb,
        "ballooned_mb": (stats["memory.ballooned"] / (1024 * 1024))
        if stats.get("memory.ballooned") is not None else None,
        "net_rx_kbps": (stats.get("network.current.receive") or 0) / 1024.0
        if stats.get("network.current.receive") is not None else None,
        "net_tx_kbps": (stats.get("network.current.transmit") or 0) / 1024.0
        if stats.get("network.current.transmit") is not None else None,
        "disk_read_iops": stats.get("disk.read.ops") or stats.get("disks.read.ops"),
        "disk_write_iops": stats.get("disk.write.ops") or stats.get("disks.write.ops"),
    }


def page_from_url(url: str) -> Optional[int]:
    q = parse_qs(urlparse(url).query)
    if q.get("page"):
        try:
            return int(q["page"][0])
        except (TypeError, ValueError):
            return None
    return None
