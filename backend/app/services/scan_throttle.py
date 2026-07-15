"""AI Ready / NLQ snapshot tarama throttle yardımcıları."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def should_recheck_ai_ready(
    *,
    ai_ready: bool,
    last_check: Optional[datetime],
    ready_recheck_sec: int,
    not_ready_recheck_sec: int,
    now: Optional[datetime] = None,
) -> bool:
    """True → bu sunucu SSH/WinRM AI Ready testine alınmalı."""
    now = now or _utc_now()
    last = _as_aware(last_check)
    if last is None:
        return True
    age = now - last
    if ai_ready:
        return age >= timedelta(seconds=max(60, int(ready_recheck_sec)))
    return age >= timedelta(seconds=max(60, int(not_ready_recheck_sec)))


def should_recheck_nlq_snapshot(
    *,
    collection_status: Optional[str],
    collection_time: Optional[datetime],
    success_recheck_sec: int,
    failed_recheck_sec: int,
    now: Optional[datetime] = None,
) -> bool:
    """True → NLQ inventory snapshot SSH ile yeniden toplanmalı."""
    now = now or _utc_now()
    last = _as_aware(collection_time)
    if last is None or not collection_status:
        return True
    st = (collection_status or "").lower()
    age = now - last
    if st == "success":
        return age >= timedelta(seconds=max(60, int(success_recheck_sec)))
    # failed / unreachable / partial / missing
    return age >= timedelta(seconds=max(60, int(failed_recheck_sec)))
