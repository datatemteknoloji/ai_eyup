"""Virt filo performans kaynağı — merdiven, reddetme yok.

Filo sıralama / eşik (QA_RULES):
  1) Timescale ``virt_vm_metrics`` son sync satırı (vCenter'ı yormaz)
  2) Satır yok veya istenen kolonların hepsi NULL → canlı QueryPerf/QuickStats
  3) Kullanıcı açıkça anlık/canlı/şimdi istediyse → doğrudan canlı

DB'de olmayan alanlar (hot-add, rezervasyon, NIC disconnect, snapshot yaşı,
uptime, custom attr) bu yardımcıya verilmez — çağıran canlı API kullanır.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_LIVE_KW = (
    "anlık", "anlik", "canlı", "canli", "şu an", "su an", "şimdi", "simdi",
    "right now", "realtime", "real-time", "real time", "quickstats",
    "şuanda", "suanda", "immediately",
)


def wants_live_virt_sample(question: str) -> bool:
    """Yalnız açık anlık niyeti — 'CPU kullanımı' tek başına canlı sayılmaz
    (aksi halde tüm filo QA yine QueryPerf olur).

    'anlık demiyorum' / 'canlı SSH' (guest OS) virt QueryPerf değildir.
    """
    from app.services.intent_text import any_keyword_hit, keyword_hit, regex_hit

    q = question or ""
    if not q.strip():
        return False
    if not any_keyword_hit(q, _LIVE_KW):
        return False
    os_ctx = any_keyword_hit(
        q,
        ("ssh", "systemd", "systemctl", "journalctl", "journal", "mdstat", "mdadm"),
    )
    virt_ctx = any_keyword_hit(
        q,
        ("vcenter", "vsphere", "esxi", "vmware", "queryperf", "quickstats", "ready", "sanal"),
    ) or regex_hit(
        q,
        r"(?<![a-z0-9_])vm(?:s|ler|leri|lerin|lerde|lerdeki|ye|yi|nin|nın|nün|'s|’s)?(?![a-z0-9_])",
    ) or keyword_hit(q, "cpu")
    if os_ctx and not virt_ctx:
        return False
    return True


def _has_coverage(vms: Sequence[Dict[str, Any]], required_any: Sequence[str]) -> bool:
    if not vms:
        return False
    keys = [k for k in required_any if k]
    if not keys:
        return True
    for row in vms:
        for k in keys:
            if row.get(k) is not None:
                return True
    return False


def list_latest_vm_perf_db(db: Session, *, hours: int = 6, limit: int = 4000) -> Dict[str, Any]:
    """VM başına en yeni virt_vm_metrics satırı — canlı sözleşme anahtarları."""
    sql = text(
        """
        SELECT DISTINCT ON (m.hypervisor_id, m.vm_ref)
               m.vm_ref, m.vm_name, m.server_id, m.host_name, m.power_state,
               m.num_cpu, m.cpu_usage_mhz, m.cpu_usage_pct,
               m.cpu_ready_ms, m.cpu_ready_pct,
               m.mem_used_mb, m.mem_total_mb, m.mem_usage_pct,
               m.balloon_mb, m.swapped_mb,
               m.disk_read_iops, m.disk_write_iops, m.disk_latency_ms,
               m.net_rx_kbps, m.net_tx_kbps,
               m.guest_disk_pct, m.snapshot_count, m.snapshot_space_gb,
               m.timestamp, h.name AS hypervisor
        FROM virt_vm_metrics m
        LEFT JOIN hypervisors h ON h.id = m.hypervisor_id
        WHERE m.timestamp >= now() - (:hours * interval '1 hour')
        ORDER BY m.hypervisor_id, m.vm_ref, m.timestamp DESC
        LIMIT :lim
        """
    )
    vms: List[Dict[str, Any]] = []
    as_of: Optional[datetime] = None
    try:
        rows = db.execute(sql, {"hours": max(1, int(hours or 6)), "lim": max(1, int(limit))})
    except Exception as e:
        logger.warning("virt_fleet_perf DB okunamadı: %s", e)
        return {"vms": [], "errors": [str(e)], "source": "db", "as_of": None}

    for r in rows:
        m = dict(r._mapping)
        ts = m.get("timestamp")
        if isinstance(ts, datetime):
            if as_of is None or ts > as_of:
                as_of = ts
        vms.append({
            "vm_ref": m.get("vm_ref"),
            "name": m.get("vm_name"),
            "server_id": m.get("server_id"),
            "hypervisor": m.get("hypervisor"),
            "host": m.get("host_name"),
            "power_state": m.get("power_state"),
            "num_cpu": m.get("num_cpu"),
            "cpu_usage_mhz": m.get("cpu_usage_mhz"),
            "cpu_usage_pct": m.get("cpu_usage_pct"),
            "cpu_ready_ms": m.get("cpu_ready_ms"),
            "cpu_ready_pct": m.get("cpu_ready_pct"),
            "mem_used_mb": m.get("mem_used_mb"),
            "mem_total_mb": m.get("mem_total_mb"),
            "mem_usage_pct": m.get("mem_usage_pct"),
            "ballooned_mb": m.get("balloon_mb"),
            "swapped_mb": m.get("swapped_mb"),
            "disk_read_iops": m.get("disk_read_iops"),
            "disk_write_iops": m.get("disk_write_iops"),
            "disk_latency_ms": m.get("disk_latency_ms"),
            "net_rx_kbps": m.get("net_rx_kbps"),
            "net_tx_kbps": m.get("net_tx_kbps"),
            "guest_disk_pct": m.get("guest_disk_pct"),
            "snapshot_count": m.get("snapshot_count"),
            "snapshot_space_gb": m.get("snapshot_space_gb"),
        })
    return {"vms": vms, "errors": [], "source": "db", "as_of": as_of, "hypervisors": None}


def fetch_fleet_vm_stats(
    db: Session,
    question: str = "",
    *,
    required_any: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Filo VM perf — DB sonra gerekirse canlı. Reddetmez."""
    keys = tuple(required_any or ())
    force_live = wants_live_virt_sample(question)
    if not force_live:
        db_pack = list_latest_vm_perf_db(db)
        if _has_coverage(db_pack.get("vms") or [], keys):
            return db_pack
        logger.info(
            "virt_fleet_perf: DB yetersiz (rows=%s keys=%s) → canlı",
            len(db_pack.get("vms") or []), keys,
        )

    from app.services import vcenter_vm_performance as perf
    live = perf.fetch_live_vm_stats(db)
    live = dict(live or {})
    live.setdefault("vms", [])
    live.setdefault("errors", [])
    live["source"] = "live"
    live["as_of"] = datetime.now(timezone.utc)
    return live


def source_footnote(pack: Dict[str, Any]) -> str:
    src = (pack or {}).get("source") or ""
    as_of = (pack or {}).get("as_of")
    when = ""
    if isinstance(as_of, datetime):
        ts = as_of
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        when = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if src == "db":
        stamp = f" ({when})" if when else ""
        return (
            f"_Kaynak: son VM metrik sync{stamp} — filo taraması vCenter'ı yormaz. "
            "Anlık QueryPerf için soruya **canlı** veya **şimdi** yazın._\n\n"
        )
    if src == "live":
        return "_Kaynak: vCenter anlık (QuickStats / QueryPerf)._\n\n"
    return ""
