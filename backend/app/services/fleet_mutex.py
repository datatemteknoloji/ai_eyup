"""
Fleet arka plan görevleri için overlap koruması.

Redis SET NX (multi-process / Celery güvenli). Redis yoksa process-içi
threading.Lock fallback (tek API process).
"""
from __future__ import annotations

import logging
import threading
import uuid
from contextlib import contextmanager
from typing import Dict, Iterator, Optional

logger = logging.getLogger(__name__)

_LOCKS: Dict[str, threading.Lock] = {
    "health": threading.Lock(),
    "logs": threading.Lock(),
    "onboarding": threading.Lock(),
    "metric_sync": threading.Lock(),
    "inventory": threading.Lock(),
    "nlq": threading.Lock(),
    "anomaly": threading.Lock(),
    "esx_metric": threading.Lock(),
    "node_exporter": threading.Lock(),
    "windows_exporter": threading.Lock(),
    "windows_logs": threading.Lock(),
    "windows_live": threading.Lock(),
}

_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


@contextmanager
def fleet_lock(name: str, *, ttl_sec: int = 3600) -> Iterator[bool]:
    """True = kilit alındı (çalıştır); False = önceki tur hâlâ aktif (atla)."""
    from app.core.redis_client import get_redis

    key = f"ainew:fleet_lock:{name}"
    token = uuid.uuid4().hex
    r = get_redis()
    if r is not None:
        try:
            acquired = bool(r.set(key, token, nx=True, ex=max(60, int(ttl_sec))))
        except Exception as exc:
            logger.warning("Redis fleet_lock(%s) başarısız, local fallback: %s", name, exc)
            acquired = None  # type: ignore
        if acquired is True:
            try:
                yield True
            finally:
                try:
                    r.eval(_RELEASE_LUA, 1, key, token)
                except Exception:
                    try:
                        r.delete(key)
                    except Exception:
                        pass
            return
        if acquired is False:
            logger.info("Fleet '%s' atlandı: önceki tur hâlâ çalışıyor (redis)", name)
            yield False
            return
        # fall through to local

    lock = _LOCKS.get(name)
    if lock is None:
        yield True
        return
    got = lock.acquire(blocking=False)
    if not got:
        logger.info("Fleet '%s' atlandı: önceki tur hâlâ çalışıyor (local)", name)
    try:
        yield got
    finally:
        if got:
            lock.release()
