"""Kaynak koruması: devre kesici + eşzamanlı oturum sınırı + probe rate limit.

Redis anahtarları: automic:{system_id}:fail / :open / :slots
Redis yoksa süreç-içi yedek kullanılır (fail-open değil: sınır yine uygulanır).
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import Deque, Dict, Iterator, Tuple

from app.core.redis_client import get_redis

from .source.base import SourceError

_local_lock = threading.Lock()
_local_fail: Dict[int, Tuple[int, float]] = {}
_local_open_until: Dict[int, float] = {}
_local_slots: Dict[int, int] = {}
_probe_hits: Dict[str, Deque[float]] = defaultdict(deque)

# Bağlantı testi / keşif — kullanıcı başına pencere
_PROBE_LIMIT = 10
_PROBE_WINDOW_SEC = 60


def _k(system_id: int, suffix: str) -> str:
    return f"automic:{system_id}:{suffix}"


def check_source_probe_rate(user_id: int, *, ip: str = "",
                            limit: int = _PROBE_LIMIT,
                            window_sec: int = _PROBE_WINDOW_SEC) -> None:
    """test/discover uçları için basit kayan pencere. Aşımda SourceError(rate_limited)."""
    key = f"probe:{user_id}:{ip or '-'}"
    now = time.time()
    r = get_redis()
    if r is not None:
        try:
            rk = f"automic:probe:{user_id}:{ip or '-'}"
            pipe = r.pipeline()
            pipe.zremrangebyscore(rk, 0, now - window_sec)
            pipe.zadd(rk, {f"{now}:{uuid.uuid4().hex}": now})
            pipe.zcard(rk)
            pipe.expire(rk, window_sec + 5)
            _, _, n, _ = pipe.execute()
            if int(n) > limit:
                raise SourceError(
                    f"Çok fazla bağlantı testi/keşif isteği. {window_sec} sn içinde en fazla {limit} deneme.",
                    code="rate_limited", retryable=True,
                )
            return
        except SourceError:
            raise
        except Exception as _e:
            note_error("guard.check_source_probe_rate", _e)
    with _local_lock:
        q = _probe_hits[key]
        while q and q[0] < now - window_sec:
            q.popleft()
        if len(q) >= limit:
            raise SourceError(
                f"Çok fazla bağlantı testi/keşif isteği. {window_sec} sn içinde en fazla {limit} deneme.",
                code="rate_limited", retryable=True,
            )
        q.append(now)


def circuit_open_remaining(system_id: int) -> int:
    r = get_redis()
    if r is not None:
        try:
            ttl = r.ttl(_k(system_id, "open"))
            return max(0, int(ttl or 0))
        except Exception as _e:
            note_error("guard.circuit_open_remaining", _e)
    with _local_lock:
        return max(0, int(_local_open_until.get(system_id, 0) - time.time()))


def record_success(system_id: int) -> None:
    r = get_redis()
    if r is not None:
        try:
            r.delete(_k(system_id, "fail"))
            return
        except Exception as _e:
            note_error("guard.record_success", _e)
    with _local_lock:
        _local_fail.pop(system_id, None)


def record_failure(system_id: int, *, threshold: int, open_sec: int) -> bool:
    """Hata sayar; eşik aşılırsa devreyi açar. Devre açıldıysa True."""
    r = get_redis()
    if r is not None:
        try:
            n = r.incr(_k(system_id, "fail"))
            r.expire(_k(system_id, "fail"), max(open_sec * 2, 600))
            if n >= threshold:
                r.set(_k(system_id, "open"), "1", ex=open_sec)
                r.delete(_k(system_id, "fail"))
                return True
            return False
        except Exception as _e:
            note_error("guard.record_failure", _e)
    with _local_lock:
        n, _ = _local_fail.get(system_id, (0, 0.0))
        n += 1
        if n >= threshold:
            _local_open_until[system_id] = time.time() + open_sec
            _local_fail.pop(system_id, None)
            return True
        _local_fail[system_id] = (n, time.time())
        return False


def reset_circuit(system_id: int) -> None:
    r = get_redis()
    if r is not None:
        try:
            r.delete(_k(system_id, "fail"), _k(system_id, "open"))
        except Exception as _e:
            note_error("guard.reset_circuit", _e)
    with _local_lock:
        _local_fail.pop(system_id, None)
        _local_open_until.pop(system_id, None)


@contextmanager
def source_slot(system_id: int, *, max_sessions: int, wait_sec: float = 10.0,
                hold_sec: int = 900) -> Iterator[None]:
    """Kaynakta en fazla max_sessions eşzamanlı oturum. Dolu ise bekler, süre aşımında hata."""
    remaining = circuit_open_remaining(system_id)
    if remaining > 0:
        raise SourceError(
            f"Kaynak geçici olarak devre dışı (art arda hata). {remaining} sn sonra yeniden denenecek.",
            code="circuit_open",
        )
    r = get_redis()
    token = uuid.uuid4().hex
    deadline = time.time() + wait_sec
    acquired = False
    if r is not None:
        key = _k(system_id, "slots")
        try:
            while True:
                now = time.time()
                r.zremrangebyscore(key, 0, now - hold_sec)
                if r.zcard(key) < max_sessions:
                    r.zadd(key, {token: now})
                    if r.zrank(key, token) is not None and r.zrank(key, token) < max_sessions:
                        acquired = True
                        break
                    r.zrem(key, token)
                if time.time() >= deadline:
                    break
                time.sleep(0.25)
        except Exception:
            r = None
    if r is None:
        while True:
            with _local_lock:
                if _local_slots.get(system_id, 0) < max_sessions:
                    _local_slots[system_id] = _local_slots.get(system_id, 0) + 1
                    acquired = True
            if acquired or time.time() >= deadline:
                break
            time.sleep(0.25)
    if not acquired:
        raise SourceError("Kaynak oturum sınırı dolu; kısa süre sonra tekrar deneyin.", code="busy")
    try:
        yield
    finally:
        if r is not None:
            try:
                r.zrem(_k(system_id, "slots"), token)
            except Exception as _e:
                note_error("guard.source_slot", _e)
        else:
            with _local_lock:
                _local_slots[system_id] = max(0, _local_slots.get(system_id, 1) - 1)
