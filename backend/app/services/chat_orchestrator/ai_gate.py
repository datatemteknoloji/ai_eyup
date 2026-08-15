"""Global AI FIFO — aynı anda en fazla N LLM üretimi (Redis, çok process)."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

_SEM = "ainew:ai:sem"
_WAIT = "ainew:ai:wait"
_DEFAULT_LIMIT = 3

_local_held = 0
_local_limit = _DEFAULT_LIMIT


def _limit() -> int:
    try:
        from app.services import runtime_settings
        return max(1, min(8, int(runtime_settings.get_int("chat_ai_max_concurrent") or _DEFAULT_LIMIT)))
    except Exception:
        return _DEFAULT_LIMIT


def queue_position() -> int:
    r = get_redis()
    if r is None:
        return max(0, _local_held)
    try:
        return int(r.llen(_WAIT) or 0)
    except Exception:
        return 0


def try_acquire(timeout_sec: float = 180.0) -> tuple[bool, int]:
    """
    Slot al. Dönüş: (ok, position_when_waiting).
    Redis yoksa process-içi sayaç (tek worker fallback).
    """
    global _local_held, _local_limit
    limit = _limit()
    r = get_redis()
    token = str(uuid.uuid4())
    if r is None:
        started = time.monotonic()
        while time.monotonic() - started < timeout_sec:
            if _local_held < limit:
                _local_held += 1
                _local_limit = limit
                return True, 0
            time.sleep(0.15)
        return False, _local_held
    started = time.monotonic()
    r.rpush(_WAIT, token)
    try:
        while time.monotonic() - started < timeout_sec:
            try:
                pos = 0
                waiting = r.lrange(_WAIT, 0, -1) or []
                try:
                    pos = waiting.index(token)
                except ValueError:
                    pos = 0
                held = int(r.get(_SEM) or 0)
                if pos == 0 and held < limit:
                    pipe = r.pipeline()
                    pipe.lpop(_WAIT)
                    pipe.incr(_SEM)
                    pipe.expire(_SEM, 600)
                    pipe.execute()
                    return True, 0
                time.sleep(0.2)
            except Exception:
                time.sleep(0.3)
        try:
            r.lrem(_WAIT, 1, token)
        except Exception:
            pass
        return False, queue_position()
    except Exception as e:
        logger.warning("AI gate acquire failed: %s", e)
        return False, 0


def release() -> None:
    global _local_held
    r = get_redis()
    if r is None:
        _local_held = max(0, _local_held - 1)
        return
    try:
        n = int(r.decr(_SEM) or 0)
        if n < 0:
            r.set(_SEM, 0)
    except Exception:
        pass
