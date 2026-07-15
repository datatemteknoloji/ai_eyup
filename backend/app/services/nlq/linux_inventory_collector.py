"""
Linux inventory collector — allowlisted SSH (+ optional Prom/metric_data), bounded concurrency.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.credential import GlobalCredential
from app.models.linux_inventory import (
    FilesystemMetric, LinuxInventory, OpenPort, PackageInventory, ServiceStatus,
)
from app.models.server import Server
from app.services.platform_scope import get_linux_module_server_ids, is_linux_server
from app.services.ssh_manager import SSHManager

logger = logging.getLogger(__name__)

# Fixed allowlisted commands — never interpolate user input
CMD_UPTIME = "cat /proc/uptime 2>/dev/null | awk '{print $1}'"
CMD_BOOT = "uptime -s 2>/dev/null || who -b 2>/dev/null | awk '{print $3\" \"$4}'"
CMD_UNAME = "uname -r 2>/dev/null"
CMD_OS = "grep -E '^(NAME|VERSION_ID|PRETTY_NAME)=' /etc/os-release 2>/dev/null | head -6"
CMD_LOAD = "cat /proc/loadavg 2>/dev/null"
CMD_MEM = (
    "awk '/MemTotal/{t=$2} /MemAvailable/{a=$2} END{if(t>0) printf \"%.2f\", (t-a)/t*100}' "
    "/proc/meminfo 2>/dev/null"
)
CMD_DF = (
    "df -B1 -P -x tmpfs -x devtmpfs -x squashfs 2>/dev/null | "
    "awk 'NR>1 {print $1\"|\"$2\"|\"$3\"|\"$4\"|\"$5\"|\"$6}'"
)
CMD_SERVICES = (
    "systemctl list-units --type=service --state=running,failed --no-pager --no-legend 2>/dev/null | "
    "awk '{print $1\"|\"$3\"|\"$4}' | head -80"
)
CMD_FAILED = "systemctl list-units --type=service --state=failed --no-pager --no-legend 2>/dev/null | awk '{print $1}' | head -40"
CMD_CHRONYD = "systemctl is-active chronyd 2>/dev/null; systemctl is-enabled chronyd 2>/dev/null"
CMD_NTP = "systemctl is-active ntpd 2>/dev/null; systemctl is-enabled ntpd 2>/dev/null"
CMD_PATCH = (
    "rpm -qa --last 2>/dev/null | head -1 | "
    "sed -E 's/.*([A-Z][a-z]{2}[ ]+[0-9]+[ ]+[0-9]{4}).*/\\1/' || true"
)
CMD_SS = "ss -lntuH 2>/dev/null | awk '{print $1\"|\"$5}' | head -60"

_collector_status: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "total": 0,
    "done": 0,
    "success": 0,
    "failed": 0,
    "message": "",
}


def get_collector_status() -> Dict[str, Any]:
    return dict(_collector_status)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ssh_for(server: Server, global_cred: Optional[GlobalCredential]) -> Optional[SSHManager]:
    conn = server.connection_config or {}
    username = conn.get("username") or (global_cred.username if global_cred else None)
    password = conn.get("password") or (global_cred.password if global_cred else None)
    private_key = conn.get("private_key") or (global_cred.private_key if global_cred else None)
    port = conn.get("port", 22) or 22
    if not username or not (server.ip_address or server.hostname):
        return None
    ssh = SSHManager(
        host=server.ip_address or server.hostname,
        username=username,
        password=password,
        private_key=private_key,
        port=port,
        sudo_password=conn.get("sudo_password") or password,
    )
    if not ssh.connect():
        return None
    return ssh


def _run(ssh: SSHManager, cmd: str, timeout: int = 20) -> str:
    ok, out, _err = ssh.execute_command(cmd, timeout=timeout)
    return (out or "").strip() if ok else ""


def _parse_boot(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%b %d %Y"):
        try:
            dt = datetime.strptime(s[:19] if len(s) >= 19 and fmt.startswith("%Y") else s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_patch_date(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        # e.g. Tue 15 Jul 2025 or Jul 15 2025 variants from rpm --last
        return datetime.strptime(s[:16].strip(), "%a %d %b %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.strptime(s.strip()[:11], "%b %d %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


# metric_data → linux_inventory core field
_METRIC_CORE_MAP = {
    "cpu_usage_percent": "cpu_usage_percent",
    "cpu_usage": "cpu_usage_percent",
    "memory_usage_percent": "memory_usage_percent",
    "memory_usage": "memory_usage_percent",
    "disk_usage_percent": "disk_usage_percent",
    "disk_usage": "disk_usage_percent",
    "disk_root_usage_percent": "disk_usage_percent",
    "load_average_1m": "load_average_1m",
    "load_average_5m": "load_average_5m",
    "load_average_15m": "load_average_15m",
    "load1": "load_average_1m",
    "load5": "load_average_5m",
    "load15": "load_average_15m",
}

# metric_data → dedicated inventory columns
_METRIC_COLUMN_MAP = {
    "swap_usage_percent": "swap_usage_percent",
    "cpu_iowait_percent": "cpu_iowait_percent",
    "disk_io_utilization_percent": "disk_io_utilization_percent",
    "network_rx_bytes_per_sec": "network_rx_bytes_per_sec",
    "network_tx_bytes_per_sec": "network_tx_bytes_per_sec",
}

# Known Prom sync names stored in metrics_extra (not core/column)
_METRIC_EXTRA_NAMES = frozenset({
    "cpu_system_percent", "cpu_user_percent", "cpu_steal_percent", "cpu_softirq_percent",
    "memory_available_bytes", "memory_total_bytes", "memory_cached_bytes", "memory_buffers_bytes",
    "swap_total_bytes", "swap_free_bytes",
    "disk_root_avail_bytes", "fd_allocated", "fd_maximum",
    "disk_read_bytes_per_sec", "disk_write_bytes_per_sec",
    "disk_read_iops", "disk_write_iops",
    "network_rx_packets_per_sec", "network_tx_packets_per_sec",
    "network_rx_errors_per_sec", "network_tx_errors_per_sec",
    "network_rx_drops_per_sec", "network_tx_drops_per_sec",
    "procs_running", "procs_blocked",
    "context_switches_total", "context_switches_per_sec",
})


def _enrich_from_metric_data(db: Session, server_id: int, base: Dict[str, Any]) -> None:
    """metric_data (Prometheus sync) → snapshot core/column/extra alanları."""
    try:
        from app.models.metric import MetricData
        from app.services.runtime_settings import get_bool, get_int
    except Exception:
        return

    try:
        if not get_bool("nlq_metric_enrich_enabled"):
            return
        max_age_min = max(5, int(get_int("nlq_metric_max_age_min")))
        prefer = bool(get_bool("nlq_prefer_metric_over_ssh"))
    except Exception:
        max_age_min = 30
        prefer = True

    names = (
        list(_METRIC_CORE_MAP.keys())
        + list(_METRIC_COLUMN_MAP.keys())
        + list(_METRIC_EXTRA_NAMES)
    )
    cutoff = _now() - timedelta(minutes=max_age_min)
    rows = (
        db.query(MetricData)
        .filter(
            MetricData.server_id == server_id,
            MetricData.metric_name.in_(names),
            MetricData.timestamp >= cutoff,
        )
        .order_by(MetricData.timestamp.desc())
        .limit(120)
        .all()
    )
    seen: set = set()
    extra: Dict[str, float] = {}
    for r in rows:
        name = r.metric_name or ""
        if name in seen or r.value is None:
            continue
        seen.add(name)
        try:
            val = float(r.value)
        except (TypeError, ValueError):
            continue

        if name in _METRIC_CORE_MAP:
            dest = _METRIC_CORE_MAP[name]
            if prefer or base.get(dest) is None:
                base[dest] = val
            continue
        if name in _METRIC_COLUMN_MAP:
            dest = _METRIC_COLUMN_MAP[name]
            if prefer or base.get(dest) is None:
                base[dest] = val
            continue
        if name in _METRIC_EXTRA_NAMES:
            extra[name] = val

    if extra:
        merged = dict(base.get("metrics_extra") or {})
        merged.update(extra)
        base["metrics_extra"] = merged


def collect_one_server(
    server: Server,
    global_cred: Optional[GlobalCredential],
    *,
    timeout: int = 25,
) -> Dict[str, Any]:
    """Returns canonical JSON snapshot for one host."""
    now = _now()
    base: Dict[str, Any] = {
        "server_id": server.id,
        "hostname": server.hostname or server.name,
        "ip_address": server.ip_address,
        "environment": server.tier,
        "operating_system": server.os_type,
        "os_version": server.os_version,
        "kernel_version": server.kernel_version,
        "uptime_seconds": None,
        "boot_time": None,
        "cpu_usage_percent": None,
        "memory_usage_percent": None,
        "disk_usage_percent": None,
        "load_average_1m": None,
        "load_average_5m": None,
        "load_average_15m": None,
        "swap_usage_percent": None,
        "cpu_iowait_percent": None,
        "disk_io_utilization_percent": None,
        "network_rx_bytes_per_sec": None,
        "network_tx_bytes_per_sec": None,
        "metrics_extra": {},
        "last_patch_date": None,
        "last_reboot_date": None,
        "collection_time": now.isoformat(),
        "collection_status": "failed",
        "collection_error": None,
        "filesystems": [],
        "services": [],
        "ports": [],
        "packages": [],
    }

    ssh = None
    try:
        ssh = _ssh_for(server, global_cred)
        if not ssh:
            base["collection_status"] = "unreachable"
            base["collection_error"] = "SSH bağlantısı kurulamadı"
            return base

        up = _run(ssh, CMD_UPTIME, timeout)
        if up:
            try:
                base["uptime_seconds"] = int(float(up.split()[0]))
            except (ValueError, IndexError):
                pass

        boot = _parse_boot(_run(ssh, CMD_BOOT, timeout))
        if boot:
            base["boot_time"] = boot.isoformat()
            base["last_reboot_date"] = boot.isoformat()

        uname = _run(ssh, CMD_UNAME, timeout)
        if uname:
            base["kernel_version"] = uname.split()[0]

        os_out = _run(ssh, CMD_OS, timeout)
        for line in os_out.splitlines():
            if line.startswith("NAME="):
                base["operating_system"] = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("VERSION_ID="):
                base["os_version"] = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("PRETTY_NAME=") and not base.get("operating_system"):
                base["operating_system"] = line.split("=", 1)[1].strip().strip('"')

        load = _run(ssh, CMD_LOAD, timeout).split()
        if len(load) >= 3:
            try:
                base["load_average_1m"] = float(load[0])
                base["load_average_5m"] = float(load[1])
                base["load_average_15m"] = float(load[2])
            except ValueError:
                pass

        mem = _run(ssh, CMD_MEM, timeout)
        if mem:
            try:
                base["memory_usage_percent"] = float(mem)
            except ValueError:
                pass

        max_disk = 0.0
        for line in _run(ssh, CMD_DF, timeout).splitlines():
            parts = line.split("|")
            if len(parts) < 6:
                continue
            try:
                total_b, used_b, avail_b = int(parts[1]), int(parts[2]), int(parts[3])
                pct = float(parts[4].replace("%", ""))
            except ValueError:
                continue
            fs = {
                "device": parts[0],
                "total_bytes": total_b,
                "used_bytes": used_b,
                "available_bytes": avail_b,
                "usage_percent": pct,
                "mount_point": parts[5],
                "filesystem_type": None,
            }
            base["filesystems"].append(fs)
            if parts[5] == "/" or pct > max_disk:
                max_disk = max(max_disk, pct)
        if max_disk:
            base["disk_usage_percent"] = max_disk

        # services
        seen = set()
        for line in _run(ssh, CMD_SERVICES, timeout).splitlines():
            p = line.split("|")
            if len(p) < 2:
                continue
            name = p[0].replace(".service", "")
            if name in seen:
                continue
            seen.add(name)
            base["services"].append({
                "service_name": name,
                "active_state": p[1] if len(p) > 1 else None,
                "sub_state": p[2] if len(p) > 2 else None,
                "enabled": None,
            })
        for name in _run(ssh, CMD_FAILED, timeout).splitlines():
            name = name.replace(".service", "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            base["services"].append({
                "service_name": name,
                "active_state": "failed",
                "sub_state": "failed",
                "enabled": None,
            })

        # chronyd / ntpd explicit
        for label, cmd in (("chronyd", CMD_CHRONYD), ("ntpd", CMD_NTP)):
            out = _run(ssh, cmd, timeout).splitlines()
            active = (out[0].strip() if out else "unknown")
            enabled_raw = (out[1].strip() if len(out) > 1 else "")
            base["services"].append({
                "service_name": label,
                "active_state": active,
                "sub_state": None,
                "enabled": enabled_raw == "enabled",
            })

        patch = _parse_patch_date(_run(ssh, CMD_PATCH, timeout))
        if patch:
            base["last_patch_date"] = patch.isoformat()

        for line in _run(ssh, CMD_SS, timeout).splitlines():
            p = line.split("|")
            if len(p) < 2:
                continue
            proto = p[0]
            addr = p[1]
            m = re.search(r":(\d+)$", addr)
            if not m:
                continue
            base["ports"].append({
                "protocol": proto,
                "local_address": addr,
                "port": int(m.group(1)),
                "process_name": None,
                "pid": None,
            })

        # rough CPU from load vs nproc if available
        nproc = _run(ssh, "nproc 2>/dev/null", timeout)
        if nproc and base.get("load_average_1m") is not None:
            try:
                cores = max(1, int(nproc.strip()))
                base["cpu_usage_percent"] = round(min(100.0, float(base["load_average_1m"]) / cores * 100), 2)
            except ValueError:
                pass

        base["collection_status"] = "success"
        base["collection_error"] = None
        return base
    except Exception as e:
        base["collection_status"] = "failed"
        base["collection_error"] = str(e)[:500]
        return base
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def _upsert_snapshot(db: Session, snap: Dict[str, Any]) -> None:
    sid = snap["server_id"]
    now = _now()
    try:
        ct = datetime.fromisoformat(snap["collection_time"].replace("Z", "+00:00"))
    except Exception:
        ct = now

    inv = db.query(LinuxInventory).filter(LinuxInventory.server_id == sid).first()
    if not inv:
        inv = LinuxInventory(server_id=sid, collection_time=ct)
        db.add(inv)

    inv.uptime_seconds = snap.get("uptime_seconds")
    inv.boot_time = datetime.fromisoformat(snap["boot_time"].replace("Z", "+00:00")) if snap.get("boot_time") else None
    inv.last_reboot_date = datetime.fromisoformat(snap["last_reboot_date"].replace("Z", "+00:00")) if snap.get("last_reboot_date") else inv.boot_time
    inv.last_patch_date = datetime.fromisoformat(snap["last_patch_date"].replace("Z", "+00:00")) if snap.get("last_patch_date") else None
    inv.cpu_usage_percent = snap.get("cpu_usage_percent")
    inv.memory_usage_percent = snap.get("memory_usage_percent")
    inv.disk_usage_percent = snap.get("disk_usage_percent")
    inv.load_average_1m = snap.get("load_average_1m")
    inv.load_average_5m = snap.get("load_average_5m")
    inv.load_average_15m = snap.get("load_average_15m")
    inv.swap_usage_percent = snap.get("swap_usage_percent")
    inv.cpu_iowait_percent = snap.get("cpu_iowait_percent")
    inv.disk_io_utilization_percent = snap.get("disk_io_utilization_percent")
    inv.network_rx_bytes_per_sec = snap.get("network_rx_bytes_per_sec")
    inv.network_tx_bytes_per_sec = snap.get("network_tx_bytes_per_sec")
    inv.metrics_extra = snap.get("metrics_extra") or None
    inv.collection_time = ct
    inv.collection_status = snap.get("collection_status")
    inv.collection_error = snap.get("collection_error")
    inv.updated_at = now

    # Replace child rows for this server (latest snapshot)
    db.query(FilesystemMetric).filter(FilesystemMetric.server_id == sid).delete()
    for fs in snap.get("filesystems") or []:
        db.add(FilesystemMetric(
            server_id=sid,
            device=fs.get("device"),
            mount_point=fs.get("mount_point"),
            filesystem_type=fs.get("filesystem_type"),
            total_bytes=fs.get("total_bytes"),
            used_bytes=fs.get("used_bytes"),
            available_bytes=fs.get("available_bytes"),
            usage_percent=fs.get("usage_percent"),
            collection_time=ct,
        ))

    db.query(ServiceStatus).filter(ServiceStatus.server_id == sid).delete()
    for svc in snap.get("services") or []:
        db.add(ServiceStatus(
            server_id=sid,
            service_name=svc.get("service_name") or "unknown",
            active_state=svc.get("active_state"),
            sub_state=svc.get("sub_state"),
            enabled=svc.get("enabled"),
            collection_time=ct,
        ))

    db.query(OpenPort).filter(OpenPort.server_id == sid).delete()
    for p in snap.get("ports") or []:
        db.add(OpenPort(
            server_id=sid,
            protocol=p.get("protocol"),
            local_address=p.get("local_address"),
            port=p.get("port"),
            process_name=p.get("process_name"),
            pid=p.get("pid"),
            collection_time=ct,
        ))

    # Sync lightweight OS fields back to servers when collected
    srv = db.query(Server).filter(Server.id == sid).first()
    if srv:
        if snap.get("kernel_version"):
            srv.kernel_version = snap["kernel_version"][:100]
        if snap.get("operating_system"):
            srv.os_type = (snap["operating_system"] or "")[:50]
        if snap.get("os_version"):
            srv.os_version = (snap["os_version"] or "")[:255]


def run_linux_inventory_collection(
    db: Session,
    *,
    workers: int = 50,
    only_ai_ready: bool = True,
    server_ids: Optional[List[int]] = None,
    throttled: bool = True,
) -> Dict[str, Any]:
    global _collector_status
    if _collector_status.get("running"):
        return {"ok": False, "message": "Collector zaten çalışıyor", **get_collector_status()}

    from app.services.runtime_settings import get_int
    from app.services.scan_throttle import should_recheck_nlq_snapshot

    linux_ids = get_linux_module_server_ids(db)
    q = db.query(Server)
    if server_ids:
        q = q.filter(Server.id.in_(server_ids))
    elif linux_ids:
        q = q.filter(Server.id.in_(linux_ids))
    servers = [s for s in q.all() if is_linux_server(s)]
    if only_ai_ready:
        servers = [s for s in servers if s.ai_ready]

    # Manuel server_ids veya throttled=False → tüm adaylar; aksi halde success/fail aralığı
    if throttled and not server_ids:
        success_sec = get_int("nlq_success_recheck_sec")
        failed_sec = get_int("nlq_failed_recheck_sec")
        now = _now()
        inv_by_sid = {
            inv.server_id: inv
            for inv in db.query(LinuxInventory).filter(
                LinuxInventory.server_id.in_([s.id for s in servers])
            ).all()
        } if servers else {}
        before = len(servers)
        kept = []
        for s in servers:
            inv = inv_by_sid.get(s.id)
            if should_recheck_nlq_snapshot(
                collection_status=inv.collection_status if inv else None,
                collection_time=inv.collection_time if inv else None,
                success_recheck_sec=success_sec,
                failed_recheck_sec=failed_sec,
                now=now,
            ):
                kept.append(s)
        servers = kept
        logger.info(
            "NLQ collector throttle: %s/%s sunucu (success=%ss failed=%ss)",
            len(servers), before, success_sec, failed_sec,
        )

    global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()  # noqa: E712
    if not global_cred:
        global_cred = db.query(GlobalCredential).first()

    workers = max(1, min(int(workers), 100))
    _collector_status = {
        "running": True,
        "started_at": _now().isoformat(),
        "finished_at": None,
        "total": len(servers),
        "done": 0,
        "success": 0,
        "failed": 0,
        "message": "running",
    }

    snaps: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(collect_one_server, s, global_cred): s.id for s in servers}
        for fut in as_completed(futs):
            try:
                snap = fut.result()
            except Exception as e:
                snap = {
                    "server_id": futs[fut],
                    "collection_time": _now().isoformat(),
                    "collection_status": "failed",
                    "collection_error": str(e)[:500],
                    "filesystems": [], "services": [], "ports": [], "packages": [],
                }
            snaps.append(snap)
            _collector_status["done"] += 1
            if snap.get("collection_status") == "success":
                _collector_status["success"] += 1
            else:
                _collector_status["failed"] += 1

    for snap in snaps:
        try:
            sid = snap.get("server_id")
            if sid:
                _enrich_from_metric_data(db, int(sid), snap)
            _upsert_snapshot(db, snap)
        except Exception as e:
            logger.warning("inventory upsert failed server=%s: %s", snap.get("server_id"), e)
            db.rollback()
            continue
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("inventory commit failed: %s", e)

    _collector_status["running"] = False
    _collector_status["finished_at"] = _now().isoformat()
    _collector_status["message"] = "done"
    return {
        "ok": True,
        "total": len(servers),
        "success": _collector_status["success"],
        "failed": _collector_status["failed"],
    }
