"""Collect read-only inventory facts from a target host."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.models.server import TargetServer
from app.services.target_ssh import run_ssh

FACTS_SCRIPT = r"""
set +e
echo "HOST=$(hostname -f 2>/dev/null || hostname)"
echo "SHORT=$(hostname -s 2>/dev/null || hostname)"
echo "KERNEL=$(uname -r 2>/dev/null)"
echo "ARCH=$(uname -m 2>/dev/null)"
echo "UPTIME_SEC=$(cut -d. -f1 /proc/uptime 2>/dev/null)"
echo "UPTIME_HUMAN=$(uptime -p 2>/dev/null || uptime)"
echo "CPUS=$(nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo 2>/dev/null)"
echo "MEM_TOTAL_KB=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null)"
echo "MEM_AVAIL_KB=$(awk '/MemAvailable/ {print $2}' /proc/meminfo 2>/dev/null)"
echo "LOAD=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)"
# virt
V=$(systemd-detect-virt 2>/dev/null)
if [ -z "$V" ] || [ "$V" = "none" ]; then
  V=$(hostnamectl 2>/dev/null | awk -F: '/Virtualization/ {gsub(/^ +/,"",$2); print $2; exit}')
fi
if [ -z "$V" ] || [ "$V" = "none" ]; then
  if grep -qi hypervisor /proc/cpuinfo 2>/dev/null; then V=vm; else V=physical; fi
fi
echo "VIRT=$V"
# OS
if [ -f /etc/os-release ]; then
  . /etc/os-release
  echo "OS_NAME=${NAME:-}"
  echo "OS_VERSION=${VERSION_ID:-}"
  echo "OS_PRETTY=${PRETTY_NAME:-}"
fi
echo "CHASSIS=$(hostnamectl 2>/dev/null | awk -F: '/Chassis/ {gsub(/^ +/,"",$2); print $2; exit}')"
"""


def collect_server_facts(session: Session, server: TargetServer) -> dict[str, Any]:
    r = run_ssh(session, server, FACTS_SCRIPT, timeout=25)
    raw: dict[str, str] = {}
    for line in r.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            raw[k.strip()] = v.strip()

    virt = (raw.get("VIRT") or "").lower()
    if virt in {"", "none", "physical"}:
        machine_type = "physical" if virt in {"", "none", "physical"} else virt
        if virt in {"", "none"}:
            machine_type = "physical"
    else:
        machine_type = "virtual"

    def _i(key: str) -> int | None:
        try:
            return int(raw.get(key) or "")
        except ValueError:
            return None

    mem_total = _i("MEM_TOTAL_KB")
    mem_avail = _i("MEM_AVAIL_KB")
    uptime_sec = _i("UPTIME_SEC")
    cpus = _i("CPUS")

    return {
        "ok": r.ok or bool(raw),
        "error": "" if (r.ok or raw) else (r.stderr or "facts okunamadı"),
        "hostname": raw.get("HOST") or server.hostname,
        "short_hostname": raw.get("SHORT") or "",
        "ip": server.ip,
        "machine_type": machine_type,
        "virtualization": raw.get("VIRT") or "",
        "chassis": raw.get("CHASSIS") or "",
        "os_name": raw.get("OS_NAME") or "",
        "os_version": raw.get("OS_VERSION") or "",
        "os_pretty": raw.get("OS_PRETTY") or "",
        "kernel": raw.get("KERNEL") or "",
        "arch": raw.get("ARCH") or "",
        "uptime_sec": uptime_sec,
        "uptime_human": raw.get("UPTIME_HUMAN") or "",
        "cpus": cpus,
        "memory_total_mb": round(mem_total / 1024) if mem_total else None,
        "memory_avail_mb": round(mem_avail / 1024) if mem_avail else None,
        "loadavg": raw.get("LOAD") or "",
        "reachable": bool(raw),
    }
