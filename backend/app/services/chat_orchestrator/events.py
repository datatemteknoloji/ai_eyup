"""
Chat event log — Redis Streams (XADD/XREAD). Replay + canlı SSE.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

_STREAM = "ainew:chat:evt:{turn_id}"
_QUEUE = "ainew:chat:queue"
_LOCK = "ainew:chat:lock:{turn_id}"
_MAXLEN = 4000
_TTL_SEC = 6 * 3600


def _stream_key(turn_id: str) -> str:
    return _STREAM.format(turn_id=turn_id)


def _lock_key(turn_id: str) -> str:
    return _LOCK.format(turn_id=turn_id)


def enqueue_job(turn_id: str) -> bool:
    r = get_redis()
    if r is None:
        return False
    try:
        r.lpush(_QUEUE, turn_id)
        return True
    except Exception as e:
        logger.warning("chat queue enqueue failed: %s", e)
        return False


def dequeue_job(timeout_sec: int = 2) -> Optional[str]:
    r = get_redis()
    if r is None:
        return None
    try:
        item = r.brpop(_QUEUE, timeout=max(1, int(timeout_sec)))
        if not item:
            return None
        return str(item[1])
    except Exception:
        return None


def acquire_turn_lock(turn_id: str, ttl_sec: int = 300) -> bool:
    r = get_redis()
    if r is None:
        return False
    try:
        return bool(r.set(_lock_key(turn_id), str(time.time()), nx=True, ex=int(ttl_sec)))
    except Exception:
        return False


def refresh_turn_lock(turn_id: str, ttl_sec: int = 300) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        r.expire(_lock_key(turn_id), int(ttl_sec))
    except Exception:
        pass


def release_turn_lock(turn_id: str) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        r.delete(_lock_key(turn_id))
    except Exception:
        pass


def publish_event(turn_id: str, event: Dict[str, Any]) -> int:
    """Event yaz; monotonik seq döner (0 = yazılamadı)."""
    r = get_redis()
    payload = json.dumps(event, ensure_ascii=False, default=str)
    if r is None:
        return 0
    try:
        xid = r.xadd(
            _stream_key(turn_id),
            {"d": payload},
            maxlen=_MAXLEN,
            approximate=True,
        )
        r.expire(_stream_key(turn_id), _TTL_SEC)
        # Redis stream id "ms-seq" — seq olarak ms kullan
        try:
            return int(str(xid).split("-")[0])
        except Exception:
            return 1
    except Exception as e:
        logger.warning("chat event publish failed: %s", e)
        return 0


def read_new_events(turn_id: str, after_id: str = "0-0", block_ms: int = 1500, count: int = 50) -> list[tuple[str, dict]]:
    """Tek XREAD. Boş liste = timeout/idle."""
    r = get_redis()
    if r is None:
        return []
    last = after_id if after_id and after_id not in ("0",) else "0-0"
    try:
        resp = r.xread({_stream_key(turn_id): last}, count=int(count), block=int(block_ms))
    except Exception as e:
        logger.debug("xread failed: %s", e)
        return []
    out: list[tuple[str, dict]] = []
    if not resp:
        return out
    for _name, entries in resp:
        for eid, fields in entries:
            raw = fields.get("d") if isinstance(fields, dict) else None
            try:
                data = json.loads(raw) if raw else {}
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {"data": data}
            data["_id"] = eid
            out.append((eid, data))
    return out


def snapshot_events(turn_id: str, after_id: str = "0-0", count: int = 500) -> list[dict]:
    r = get_redis()
    if r is None:
        return []
    last = after_id if after_id and after_id != "0" else "0-0"
    try:
        entries = r.xrange(_stream_key(turn_id), min=f"({last}" if last not in ("0-0", "0") else "-", max="+", count=count)
    except Exception:
        try:
            entries = r.xrange(_stream_key(turn_id), count=count)
        except Exception:
            return []
    out = []
    for eid, fields in entries or []:
        raw = fields.get("d") if isinstance(fields, dict) else None
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        if isinstance(data, dict):
            data["_id"] = eid
            out.append(data)
    return out
