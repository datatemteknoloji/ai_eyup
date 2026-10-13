"""Süreç/konteyner genelinde LLM eşzamanlılık semaforu + öncelik (Adım 6c).

Ollama `Parallel:1` ile uyumlu: aynı anda en fazla N (varsayılan 1) LLM çağrısı çalışır, gerisi kuyrukta bekler.

Öncelik sınıfları:
  chat        — kullanıcı sohbeti (aktif `chat_request_metrics` ölçümü olan istek) ve açıkça `priority("chat")`
  background  — diğer her şey (backfill, rapor, dashboard özeti, AIOps/analiz işleri, benchmark işaretli istekler)

Kural: bir sohbet çağrısı kuyrukta bekliyorsa arka plan çağrıları YENİ LLM çağrısı BAŞLATMAZ (çalışan çağrı kesilmez).
Arka plan çağrısı açlıktan korunmak için en fazla `llm_sched_bg_max_wait_sec` bekler, sonra devam eder (loglanır).

Çok worker/konteyner: Redis lease tabanlı sayaç (ZSET: üye=jeton, skor=bitiş zamanı; çökmüş sahipler TTL ile düşer).
Redis yoksa süreç içi (threading) yedek kullanılır. Aynı bağlamdaki iç içe çağrı yeniden-girişli sayılır (kilitlenme yok).
`llm_max_concurrent=0` → kapalı.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import random
import threading
import time
import uuid
from typing import Any, AsyncIterator, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

CHAT = "chat"
BACKGROUND = "background"

_ACTIVE_KEY = "ainew:llm:sem:active"
_WAIT_KEY = "ainew:llm:sem:wait_chat"
_LEASE_TTL_SEC = 900          # çökmüş sahibin kilidi bırakması (en uzun çağrıdan büyük)
_WAIT_REG_TTL_SEC = 20        # kuyrukta bekleyen sohbet kaydı (poll ile tazelenir)

_prio_override: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("llm_prio", default=None)
_held: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("llm_sem_held", default=None)

_ACQUIRE_LUA = """
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local cap = tonumber(ARGV[3])
local token = ARGV[4]
local prio = ARGV[5]
local wttl = tonumber(ARGV[6])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
if prio == 'chat' then
  redis.call('ZADD', KEYS[2], now + wttl, token)
else
  if redis.call('ZCARD', KEYS[2]) > 0 then return 0 end
end
if redis.call('ZCARD', KEYS[1]) < cap then
  redis.call('ZADD', KEYS[1], now + ttl, token)
  redis.call('ZREM', KEYS[2], token)
  return 1
end
return 0
"""


def _setting(key: str, fallback: Any) -> Any:
    try:
        from app.services.runtime_settings import get_setting
        v = get_setting(key)
        return fallback if v is None or v == "" else v
    except Exception:
        return fallback


def max_concurrent() -> int:
    try:
        return max(0, int(_setting("llm_max_concurrent", 1)))
    except Exception:
        return 1


def _bg_max_wait() -> float:
    try:
        return max(1.0, float(_setting("llm_sched_bg_max_wait_sec", 120)))
    except Exception:
        return 120.0


def _hard_max_wait() -> float:
    try:
        return max(5.0, float(_setting("llm_sched_max_wait_sec", 600)))
    except Exception:
        return 600.0


# ── öncelik ───────────────────────────────────────────────────────────────

@contextlib.contextmanager
def priority(level: str) -> Iterator[None]:
    """with llm_scheduler.priority('background'): … — bu bağlamdaki LLM çağrılarının sınıfını belirler."""
    tok = _prio_override.set(level if level in (CHAT, BACKGROUND) else None)
    try:
        yield
    finally:
        _prio_override.reset(tok)


def set_priority(level: Optional[str]) -> None:
    """Bağlam boyunca (reset'siz) sınıf ata — SSE/async üreteçlerinde `with` kullanılamadığında."""
    _prio_override.set(level if level in (CHAT, BACKGROUND) else None)


def current_priority() -> str:
    ov = _prio_override.get()
    if ov:
        return ov
    try:
        from app.services import chat_request_metrics as crm
        if crm.current() is not None:
            return CHAT
    except Exception:
        pass
    return BACKGROUND


# ── yedek: süreç içi semafor ──────────────────────────────────────────────

class _LocalBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: Dict[str, float] = {}
        self._wait_chat: Dict[str, float] = {}

    def try_acquire(self, token: str, prio: str, cap: int, now: float) -> bool:
        with self._lock:
            for d in (self._active, self._wait_chat):
                for k in [k for k, exp in d.items() if exp <= now]:
                    d.pop(k, None)
            if prio == CHAT:
                self._wait_chat[token] = now + _WAIT_REG_TTL_SEC
            elif self._wait_chat:
                return False
            if len(self._active) < cap:
                self._active[token] = now + _LEASE_TTL_SEC
                self._wait_chat.pop(token, None)
                return True
            return False

    def release(self, token: str) -> None:
        with self._lock:
            self._active.pop(token, None)
            self._wait_chat.pop(token, None)

    def state(self) -> Dict[str, int]:
        with self._lock:
            return {"active": len(self._active), "waiting_chat": len(self._wait_chat)}


_local = _LocalBackend()
_redis_script = None


def _redis():
    try:
        from app.core.redis_client import get_redis
        return get_redis()
    except Exception:
        return None


def _try_acquire(token: str, prio: str, cap: int) -> bool:
    now = time.time()
    r = _redis()
    if r is not None:
        try:
            ok = r.eval(_ACQUIRE_LUA, 2, _ACTIVE_KEY, _WAIT_KEY, now, _LEASE_TTL_SEC, cap, token, prio, _WAIT_REG_TTL_SEC)
            return bool(int(ok or 0))
        except Exception as exc:
            logger.debug("llm_scheduler redis: %s → yerel yedek", exc)
    return _local.try_acquire(token, prio, cap, now)


def _release(token: str) -> None:
    _local.release(token)
    r = _redis()
    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.zrem(_ACTIVE_KEY, token)
            pipe.zrem(_WAIT_KEY, token)
            pipe.execute()
        except Exception as exc:
            logger.debug("llm_scheduler release: %s", exc)


def state() -> Dict[str, Any]:
    """Anlık durum (admin/teşhis)."""
    out: Dict[str, Any] = {"max_concurrent": max_concurrent(), "local": _local.state(), "redis": None}
    r = _redis()
    if r is not None:
        try:
            now = time.time()
            out["redis"] = {
                "active": int(r.zcount(_ACTIVE_KEY, now, "+inf")),
                "waiting_chat": int(r.zcount(_WAIT_KEY, now, "+inf")),
            }
        except Exception:
            pass
    return out


class Lease:
    __slots__ = ("token", "priority", "wait_ms", "bypassed", "reason")

    def __init__(self, token: str, prio: str, wait_ms: float = 0.0, bypassed: bool = False, reason: str = ""):
        self.token, self.priority, self.wait_ms = token, prio, wait_ms
        self.bypassed, self.reason = bypassed, reason

    def as_dict(self) -> Dict[str, Any]:
        return {"priority": self.priority, "sched_wait_ms": round(self.wait_ms, 1),
                "sched_bypassed": self.bypassed or None}


def _deadline_for(prio: str) -> float:
    return _hard_max_wait() if prio == CHAT else min(_bg_max_wait(), _hard_max_wait())


def _poll_sleep(attempt: int) -> float:
    return min(0.25, 0.03 + attempt * 0.01) + random.random() * 0.02


def _note_wait(lease: Lease) -> None:
    try:
        from app.services import chat_request_metrics as crm
        crm.note_sched_wait(lease.wait_ms, lease.priority)
    except Exception:
        pass


@contextlib.contextmanager
def slot(kind: str = "") -> Iterator[Lease]:
    """Senkron: LLM çağrısı boyunca bir semafor yuvası tutar."""
    cap = max_concurrent()
    if cap <= 0 or _held.get():
        yield Lease("", current_priority(), 0.0, bypassed=True, reason="disabled" if cap <= 0 else "reentrant")
        return
    prio = current_priority()
    token = f"{uuid.uuid4().hex[:12]}"
    t0 = time.perf_counter()
    deadline = t0 + _deadline_for(prio)
    attempt = 0
    bypass = ""
    while not _try_acquire(token, prio, cap):
        if time.perf_counter() >= deadline:
            bypass = f"bekleme sınırı aşıldı ({prio})"
            break
        time.sleep(_poll_sleep(attempt))
        attempt += 1
    wait_ms = (time.perf_counter() - t0) * 1000
    lease = Lease(token, prio, wait_ms, bypassed=bool(bypass), reason=bypass)
    if bypass:
        _release(token)  # bekleme kaydını temizle
        logger.warning("[LLMSched] %s: slot alınmadan devam (%s, %.0f ms bekledi)", kind, bypass, wait_ms)
    elif wait_ms > 50:
        logger.info("[LLMSched] %s (%s) kuyrukta %.0f ms bekledi", kind, prio, wait_ms)
    _note_wait(lease)
    held_tok = _held.set(token if not bypass else None)
    try:
        yield lease
    finally:
        _held.set(None)
        if not bypass:
            _release(token)


@contextlib.asynccontextmanager
async def aslot(kind: str = "") -> AsyncIterator[Lease]:
    """Asenkron: olay döngüsünü bloklamadan bekler."""
    cap = max_concurrent()
    if cap <= 0 or _held.get():
        yield Lease("", current_priority(), 0.0, bypassed=True, reason="disabled" if cap <= 0 else "reentrant")
        return
    prio = current_priority()
    token = f"{uuid.uuid4().hex[:12]}"
    t0 = time.perf_counter()
    deadline = t0 + _deadline_for(prio)
    attempt = 0
    bypass = ""
    loop = asyncio.get_running_loop()
    while not await loop.run_in_executor(None, _try_acquire, token, prio, cap):
        if time.perf_counter() >= deadline:
            bypass = f"bekleme sınırı aşıldı ({prio})"
            break
        await asyncio.sleep(_poll_sleep(attempt))
        attempt += 1
    wait_ms = (time.perf_counter() - t0) * 1000
    lease = Lease(token, prio, wait_ms, bypassed=bool(bypass), reason=bypass)
    if bypass:
        await loop.run_in_executor(None, _release, token)
        logger.warning("[LLMSched] %s: slot alınmadan devam (%s, %.0f ms bekledi)", kind, bypass, wait_ms)
    elif wait_ms > 50:
        logger.info("[LLMSched] %s (%s) kuyrukta %.0f ms bekledi", kind, prio, wait_ms)
    _note_wait(lease)
    _held.set(token if not bypass else None)
    try:
        yield lease
    finally:
        _held.set(None)
        if not bypass:
            await loop.run_in_executor(None, _release, token)
