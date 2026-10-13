"""Toplama pencereleri / kara liste (kullanıcının sihirbazda girdiği aralıklar)."""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo


def _parse_hm(s: str, default: time) -> time:
    try:
        h, m = str(s).split(":", 1)
        return time(int(h), int(m))
    except Exception:
        return default


def _in_ranges(now_local: datetime, ranges: List[Dict[str, Any]]) -> bool:
    wd = now_local.weekday()
    t = now_local.time()
    for r in ranges or []:
        days = r.get("days")
        if days and wd not in [int(d) for d in days]:
            continue
        a = _parse_hm(r.get("from", "00:00"), time(0, 0))
        b = _parse_hm(r.get("to", "23:59"), time(23, 59))
        if a <= b:
            if a <= t <= b:
                return True
        elif t >= a or t <= b:  # gece yarısını aşan aralık
            return True
    return False


def _tz(collection: Dict[str, Any]):
    try:
        return ZoneInfo(collection.get("timezone") or "UTC")
    except Exception:
        return timezone.utc


def collection_allowed(collection: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(_tz(collection))
    if _in_ranges(local, collection.get("blackout") or []):
        return False
    windows = collection.get("windows") or []
    return True if not windows else _in_ranges(local, windows)


def in_heavy_window(collection: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    hw = collection.get("heavy_window") or {}
    if not hw:
        return True
    now = now or datetime.now(timezone.utc)
    return _in_ranges(now.astimezone(_tz(collection)), [hw])
