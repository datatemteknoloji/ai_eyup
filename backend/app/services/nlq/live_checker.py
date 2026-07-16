"""
NLQ live checker — only candidate servers, allowlisted probes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.credential import GlobalCredential
from app.models.server import Server
from app.services.nlq.linux_inventory_collector import collect_one_server


def live_check_servers(
    db: Session,
    results: List[dict],
    *,
    fields: Optional[List[str]] = None,
) -> List[dict]:
    """
    Compare inventory snapshot fields with a fresh allowlisted SSH probe.
    Returns list of diff dicts: hostname, field, inventory, live.
    """
    fields = fields or ["uptime_days", "cpu_usage_percent", "memory_usage_percent", "disk_usage_percent"]
    global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()  # noqa: E712
    if not global_cred:
        global_cred = db.query(GlobalCredential).first()

    diffs: List[dict] = []
    for row in results[:50]:  # hard cap live fan-out
        sid = row.get("server_id")
        if not sid:
            continue
        srv = db.query(Server).filter(Server.id == sid).first()
        if not srv:
            continue
        if not bool(getattr(srv, "ai_ready", False)):
            diffs.append({
                "hostname": row.get("hostname"),
                "field": "collection_status",
                "inventory": row.get("collection_status"),
                "live": "skipped_not_ai_ready",
            })
            continue
        live = collect_one_server(srv, global_cred)
        if live.get("collection_status") != "success":
            diffs.append({
                "hostname": row.get("hostname"),
                "field": "collection_status",
                "inventory": row.get("collection_status"),
                "live": live.get("collection_status"),
            })
            continue
        live_uptime_s = live.get("uptime_seconds")
        live_map = {
            "uptime_days": round(live_uptime_s / 86400.0, 1) if live_uptime_s is not None else None,
            "uptime_seconds": live_uptime_s,
            "cpu_usage_percent": live.get("cpu_usage_percent"),
            "memory_usage_percent": live.get("memory_usage_percent"),
            "disk_usage_percent": live.get("disk_usage_percent"),
            "kernel_version": live.get("kernel_version"),
        }
        for f in fields:
            inv_v = row.get(f)
            live_v = live_map.get(f)
            if inv_v is None and live_v is None:
                continue
            # numeric tolerance
            try:
                if inv_v is not None and live_v is not None and abs(float(inv_v) - float(live_v)) < 0.15:
                    continue
            except (TypeError, ValueError):
                if inv_v == live_v:
                    continue
            diffs.append({
                "hostname": row.get("hostname"),
                "field": f,
                "inventory": inv_v,
                "live": live_v,
            })
    return diffs
