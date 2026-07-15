"""
NLQ executor — run validated query, build summary stats.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.linux_inventory import LinuxInventory
from app.models.server import Server
from app.services.nlq.builder import build_query
from app.services.nlq.schema import STALE_DATA_MINUTES


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _row_dict(server: Server, inv: Optional[LinuxInventory], columns: List[str]) -> Dict[str, Any]:
    uptime_s = inv.uptime_seconds if inv else None
    uptime_days = round(uptime_s / 86400.0, 1) if uptime_s is not None else None
    mapping = {
        "server_id": server.id,
        "hostname": server.hostname or server.name,
        "ip_address": server.ip_address,
        "environment": server.tier,
        "operating_system": server.os_type,
        "os_version": server.os_version,
        "kernel_version": server.kernel_version,
        "status": server.status,
        "datacenter": inv.datacenter if inv else None,
        "application": inv.application if inv else None,
        "application_owner": inv.application_owner if inv else None,
        "uptime_seconds": uptime_s,
        "uptime_days": uptime_days,
        "boot_time": inv.boot_time.isoformat() if inv and inv.boot_time else None,
        "cpu_usage_percent": float(inv.cpu_usage_percent) if inv and inv.cpu_usage_percent is not None else None,
        "memory_usage_percent": float(inv.memory_usage_percent) if inv and inv.memory_usage_percent is not None else None,
        "disk_usage_percent": float(inv.disk_usage_percent) if inv and inv.disk_usage_percent is not None else None,
        "last_patch_date": inv.last_patch_date.isoformat() if inv and inv.last_patch_date else None,
        "last_reboot_date": inv.last_reboot_date.isoformat() if inv and inv.last_reboot_date else None,
        "collection_time": inv.collection_time.isoformat() if inv and inv.collection_time else None,
        "collection_status": inv.collection_status if inv else "missing",
    }
    if columns:
        out = {c: mapping.get(c) for c in columns if c in mapping}
        out["server_id"] = server.id
        return out
    return mapping


def execute_query(db: Session, validated: dict) -> Dict[str, Any]:
    q, sql_template = build_query(db, validated)
    rows = q.all()
    columns = validated.get("requested_columns") or []

    results = []
    unreachable = 0
    stale = 0
    failed = 0
    latest_ct: Optional[datetime] = None
    stale_before = _utc_now() - timedelta(minutes=STALE_DATA_MINUTES)

    for server, inv in rows:
        results.append(_row_dict(server, inv, columns))
        if inv is None:
            failed += 1
            unreachable += 1
            continue
        st = (inv.collection_status or "").lower()
        if st in ("failed", "unreachable"):
            unreachable += 1
            failed += 1
        elif st == "partial":
            failed += 1
        if inv.collection_time:
            ct = inv.collection_time
            if ct.tzinfo is None:
                ct = ct.replace(tzinfo=timezone.utc)
            if latest_ct is None or ct > latest_ct:
                latest_ct = ct
            if ct < stale_before:
                stale += 1

    return {
        "results": results,
        "sql_template": sql_template,
        "summary": {
            "total_found": len(results),
            "unreachable_count": unreachable,
            "failed_collection_count": failed,
            "stale_data_count": stale,
            "latest_collection_time": latest_ct.isoformat() if latest_ct else None,
            "stale_threshold_minutes": STALE_DATA_MINUTES,
        },
    }
