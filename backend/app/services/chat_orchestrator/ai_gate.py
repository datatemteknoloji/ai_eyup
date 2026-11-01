"""Global AI kapısı v2 (Adım 13) — aynı anda en fazla N sohbet turu LLM hattına girer (Redis, çok process).

Neden yeniden yazıldı (Adım 13 bulguları):
  * Eski bekleyen LİSTESİ yalnız zaman aşımında/alınınca temizleniyordu → süreç ölürse baştaki ölü jeton kuyruğu SONSUZA
    kadar tıkıyordu. Şimdi bekleyen kaydı **canlılık işareti** (`HB_TTL_SEC`) taşır; işaretsiz baş kayıt atılır.
  * Eski slot SAYAÇ'ı (`incr/decr`) `finally`'ye girmeden ölen süreçte yüksek kalıyordu (TTL kayıyordu). Şimdi slot bir
    **lease**'tir (ZSET: jeton → bitiş); `renew` ile yenilenir, süre dolunca kendiliğinden düşer. Jeton = `turn_id`.
  * Bekleme `time.sleep` döngüsüyle `chat_io` iş parçacığı tutuyordu → artık `asyncio.sleep`; her yoklama tek kısa Lua.
  * Kullanıcı başına eşzamanlı tur sınırı (`chat_user_max_active_turns`), kuyruk üst sınırı (`chat_gate_max_queue`),
    oturum başına seri (`chat_session_serial_enabled`), «hızlı şerit» (kavramsal/selamlaşma soruları `chat_gate_fast_bonus_sec`
    kadar öne geçer; aşan normal bekleyen geçilmez → açlık yok), tahmini bekleme (EWMA tur süresi) ve Prometheus metni.

Redis yoksa süreç içi yedek (tek worker; öncelik/lease yok).
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

_LEASE = "ainew:ai:lease"          # ZSET jeton → lease bitişi (epoch sn)
_WAITQ = "ainew:ai:waitq"          # ZSET jeton → öncelik skoru (küçük = önce)
_HB = "ainew:ai:hb:"               # bekleyen canlılık işareti (EX HB_TTL_SEC)
_STATS = "ainew:ai:stats"          # HASH sayaçlar
_AVG = "ainew:ai:avg_turn_ms"      # EWMA tur süresi (ms)
_UACT = "ainew:chat:uact:{uid}"    # ZSET kullanıcının aktif turları (jeton → bitiş)
_UTURN = "ainew:chat:uturn:{turn}"  # tur → kullanıcı eşlemesi
_SESS = "ainew:chat:sess:{sid}"    # oturum kilidi (değer = turn_id)

_DEFAULT_LIMIT = 3
LEASE_TTL_SEC = 240                # çökmüş sahibin slotu bırakması (renew ile yenilenir)
HB_TTL_SEC = 15                    # bekleyen canlılık işareti
USER_ACTIVE_TTL_SEC = 900          # kullanıcı aktif-tur kaydı güvenlik süresi
SESSION_LOCK_TTL_SEC = 420         # oturum kilidi güvenlik süresi (renew ile yenilenir)
RENEW_EVERY_SEC = 20.0             # çağıranın renew sıklığı (service.run_turn)
_AVG_DEFAULT_MS = 15000.0
WAIT_BUCKETS = (1, 5, 15, 30, 60, 120, 300)

FAST = "fast"
NORMAL = "normal"

MSG_QUEUE_FULL = "Sistem şu an çok yoğun (sırada {n} soru var). Lütfen birkaç dakika sonra tekrar deneyin."
MSG_USER_LIMIT = ("Önceki sorularınız hâlâ işleniyor. Yanıtın bitmesini bekleyin (veya «Durdur» deyin), "
                  "ardından yeni soru sorun.")
MSG_TIMEOUT = ("Sistem yoğun: sıranız gelmeden bekleme süresi ({s} sn) doldu. "
               "Lütfen birkaç dakika sonra tekrar deneyin.")
MSG_SESSION_TIMEOUT = ("Bu sohbetteki önceki soru hâlâ yanıtlanıyor; bekleme süresi ({s} sn) doldu. "
                       "Lütfen önceki yanıtın bitmesini bekleyin.")


class AdmissionError(Exception):
    """Tur oluşturulmadan reddedildi (HTTP 429)."""

    def __init__(self, reason: str, detail: str, status: int = 429):
        super().__init__(detail)
        self.reason, self.detail, self.status = reason, detail, status


@dataclass
class GateResult:
    ok: bool
    reason: str = "ok"            # ok | timeout | queue_full | cancelled
    wait_ms: float = 0.0
    lane: str = NORMAL
    first_position: int = 0       # kuyruğa girerken önünde bekleyen sayısı (0 = hemen/ilk)
    message: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


# ── ayarlar (runtime_settings önbellekli; çağıran iş parçacığında okur) ──────────────────────────────────────────

def _int_setting(key: str, default: int, lo: int, hi: int) -> int:
    try:
        from app.services import runtime_settings
        v = runtime_settings.get_setting(key)
        return max(lo, min(hi, int(default if v is None or v == "" else v)))
    except Exception:
        return default


def _limit() -> int:
    return _int_setting("chat_ai_max_concurrent", _DEFAULT_LIMIT, 1, 8)


def max_wait_sec() -> int:
    return _int_setting("chat_gate_max_wait_sec", 180, 10, 900)


def max_queue() -> int:
    return _int_setting("chat_gate_max_queue", 20, 0, 500)


def user_limit() -> int:
    return _int_setting("chat_user_max_active_turns", 2, 0, 10)


def fast_bonus_sec() -> int:
    return _int_setting("chat_gate_fast_bonus_sec", 45, 0, 600)


def session_serial_enabled() -> bool:
    return bool(_int_setting("chat_session_serial_enabled", 1, 0, 1))


def classify_lane(message: Optional[str]) -> str:
    """Hızlı şerit: selamlaşma/kavramsal (cache adayı) soru. Hata → normal. Saf regex; LLM/DB yok."""
    try:
        from app.services.chat_cache_service import classify_question
        from app.services.chat_chitchat_policy import is_chitchat
        if message and (is_chitchat(message) or classify_question(message)[0]):
            return FAST
    except Exception:
        pass
    return NORMAL


# ── Lua ──────────────────────────────────────────────────────────────────────────────────────────────────────────

# KEYS: 1=lease 2=waitq   ARGV: now limit token score lease_ttl hb_prefix hb_ttl max_queue enqueue(0|1)
# Dönüş: {durum, sıra}  durum: 1=alındı 0=beklemede -1=kuyruk dolu -2=kuyrukta değil (canlılık işareti kaçırıldı → yeniden gir)
_ACQUIRE_LUA = """
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local token = ARGV[3]
local score = tonumber(ARGV[4])
local lease_ttl = tonumber(ARGV[5])
local hbp = ARGV[6]
local hb_ttl = tonumber(ARGV[7])
local max_q = tonumber(ARGV[8])
local enq = ARGV[9]
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if enq == '1' then
  -- kuyruğa girerken ölü kayıtları süpür (sınırlı)
  local all = redis.call('ZRANGE', KEYS[2], 0, 199)
  for i = 1, #all do
    if all[i] ~= token and redis.call('EXISTS', hbp .. all[i]) == 0 then
      redis.call('ZREM', KEYS[2], all[i])
    end
  end
  if max_q > 0 and redis.call('ZCARD', KEYS[2]) >= max_q then return {-1, 0} end
  redis.call('ZADD', KEYS[2], 'NX', score, token)
end
redis.call('SET', hbp .. token, '1', 'EX', hb_ttl)
local guard = 0
while guard < 64 do
  local head = redis.call('ZRANGE', KEYS[2], 0, 0)[1]
  if not head then break end
  if head == token or redis.call('EXISTS', hbp .. head) == 1 then break end
  redis.call('ZREM', KEYS[2], head)
  guard = guard + 1
end
local rank = redis.call('ZRANK', KEYS[2], token)
if rank == false then return {-2, 0} end
if rank == 0 and redis.call('ZCARD', KEYS[1]) < limit then
  redis.call('ZREM', KEYS[2], token)
  redis.call('ZADD', KEYS[1], now + lease_ttl, token)
  redis.call('DEL', hbp .. token)
  return {1, 0}
end
return {0, rank}
"""

# KEYS: 1=kullanıcı ZSET   ARGV: now limit turn ttl   Dönüş: 1=eklendi, 0=limit dolu
_USER_ADMIT_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', tonumber(ARGV[1]))
if tonumber(ARGV[2]) > 0 and redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
redis.call('ZADD', KEYS[1], tonumber(ARGV[1]) + tonumber(ARGV[4]), ARGV[3])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
return 1
"""

# KEYS: 1=oturum kilidi  ARGV: turn_id ttl   Dönüş: 1=bizde
_SESS_ACQUIRE_LUA = """
local ok = redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', tonumber(ARGV[2]))
if ok then return 1 end
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
  return 1
end
return 0
"""

_SESS_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


# ── süreç içi yedek (Redis yok) ───────────────────────────────────────────────────────────────────────────────────

class _Local:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.held: Dict[str, float] = {}
        self.queue: List[str] = []

    def poll(self, token: str, limit: int, max_q: int, enqueue: bool) -> Tuple[int, int]:
        with self.lock:
            now = time.time()
            for k in [k for k, exp in self.held.items() if exp <= now]:
                self.held.pop(k, None)
            if enqueue and token not in self.queue:
                if max_q > 0 and len(self.queue) >= max_q:
                    return -1, 0
                self.queue.append(token)
            if token not in self.queue:
                return -2, 0
            rank = self.queue.index(token)
            if rank == 0 and len(self.held) < limit:
                self.queue.pop(0)
                self.held[token] = now + LEASE_TTL_SEC
                return 1, 0
            return 0, rank

    def drop(self, token: str) -> None:
        with self.lock:
            if token in self.queue:
                self.queue.remove(token)

    def release(self, token: str) -> None:
        with self.lock:
            self.held.pop(token, None)

    def renew(self, token: str) -> None:
        with self.lock:
            self.held[token] = time.time() + LEASE_TTL_SEC


_local = _Local()
_local_t0: Dict[str, float] = {}      # jeton → alınış anı (monotonic) — EWMA için


def _redis():
    try:
        return get_redis()
    except Exception:
        return None


# ── sayaç / EWMA ────────────────────────────────────────────────────────────────────────────────────────────────

def _stat(field_name: str, n: int = 1) -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.hincrby(_STATS, field_name, int(n))
    except Exception:
        pass


def _observe_wait(wait_sec: float) -> None:
    r = _redis()
    if r is None:
        return
    try:
        pipe = r.pipeline()
        pipe.hincrby(_STATS, "wait_count", 1)
        pipe.hincrby(_STATS, "wait_ms_sum", int(wait_sec * 1000))
        placed = False
        for b in WAIT_BUCKETS:
            if wait_sec <= b:
                pipe.hincrby(_STATS, f"wait_le_{b}", 1)
                placed = True
                break
        if not placed:
            pipe.hincrby(_STATS, "wait_le_inf", 1)
        pipe.execute()
    except Exception:
        pass


def _update_avg(hold_ms: float) -> None:
    r = _redis()
    if r is None or hold_ms <= 0:
        return
    try:
        prev = float(r.get(_AVG) or _AVG_DEFAULT_MS)
        r.set(_AVG, f"{0.8 * prev + 0.2 * hold_ms:.0f}", ex=7 * 86400)
    except Exception:
        pass


def avg_turn_sec() -> float:
    r = _redis()
    if r is None:
        return _AVG_DEFAULT_MS / 1000.0
    try:
        return float(r.get(_AVG) or _AVG_DEFAULT_MS) / 1000.0
    except Exception:
        return _AVG_DEFAULT_MS / 1000.0


def held_count() -> int:
    r = _redis()
    if r is None:
        return len(_local.held)
    try:
        return int(r.zcount(_LEASE, time.time(), "+inf") or 0)
    except Exception:
        return 0


def queue_len() -> int:
    r = _redis()
    if r is None:
        return len(_local.queue)
    try:
        return int(r.zcard(_WAITQ) or 0)
    except Exception:
        return 0


def queue_position(token: Optional[str] = None) -> int:
    """Jeton verilirse 1 tabanlı kendi sırası (kuyrukta değilse 0); verilmezse kuyruk uzunluğu."""
    r = _redis()
    if token is None:
        return queue_len()
    if r is None:
        with _local.lock:
            return (_local.queue.index(token) + 1) if token in _local.queue else 0
    try:
        rank = r.zrank(_WAITQ, token)
        return 0 if rank is None else int(rank) + 1
    except Exception:
        return 0


def expected_position() -> int:
    """Şimdi kuyruğa girecek turun 1 tabanlı sırası; beklemesi yoksa 0 (slot boş ve kuyruk boş)."""
    try:
        q = queue_len()
        if q > 0 or held_count() >= _limit():
            return q + 1
    except Exception:
        pass
    return 0


def eta_seconds(position: int) -> int:
    """Tahmini bekleme (sn): kapı doluysa (position + 1) tur / paralellik × EWMA tur süresi."""
    try:
        limit = _limit()
        if position <= 0 and held_count() < limit:
            return 0
        return int(round((max(position, 1)) * avg_turn_sec() / max(1, limit)))
    except Exception:
        return 0


# ── kabul (kuyruğa girmeden önce; HTTP 429) ────────────────────────────────────────────────────────────────────────

def admit(turn_id: str, user_id: Optional[int]) -> None:
    """Tur oluşturulmadan ÖNCE (chat_io iş parçacığında). Kuyruk dolu / kullanıcı limiti aşıldı → `AdmissionError`.
    Başarıda kullanıcı aktif-tur kaydı yazılır; `turn_finished` siler. Redis yoksa kabul (fail-open)."""
    r = _redis()
    if r is None:
        return
    mq, ul = max_queue(), user_limit()
    try:
        if mq > 0:
            n = int(r.zcard(_WAITQ) or 0)
            if n >= mq:
                _stat("rej_queue_full")
                raise AdmissionError("queue_full", MSG_QUEUE_FULL.format(n=n))
        if user_id is not None and ul > 0:
            ok = r.eval(_USER_ADMIT_LUA, 1, _UACT.format(uid=int(user_id)), time.time(), ul, turn_id, USER_ACTIVE_TTL_SEC)
            if not int(ok or 0):
                _stat("rej_user_limit")
                raise AdmissionError("user_limit", MSG_USER_LIMIT)
            r.set(_UTURN.format(turn=turn_id), str(int(user_id)), ex=USER_ACTIVE_TTL_SEC)
    except AdmissionError:
        raise
    except Exception as e:
        logger.warning("ai_gate.admit hata (kabul edildi): %s", e)


def turn_finished(turn_id: str) -> None:
    """Tur bitti/iptal/hata: kullanıcı aktif-tur kaydını düşür (idempotent)."""
    r = _redis()
    if r is None:
        return
    try:
        uid = r.get(_UTURN.format(turn=turn_id))
        if uid:
            r.zrem(_UACT.format(uid=int(uid)), turn_id)
            r.delete(_UTURN.format(turn=turn_id))
    except Exception:
        pass


# ── slot (lease) ─────────────────────────────────────────────────────────────────────────────────────────────────

def _poll(token: str, score: float, enqueue: bool, limit: int, mq: int, turn_id: str) -> Tuple[int, int, bool]:
    """Tek yoklama (chat_io iş parçacığı, ms). Dönüş: (durum, sıra, iptal_mi). Durum: 1/0/-1/-2 (bkz. Lua)."""
    try:
        from app.services.chat_orchestrator import events
        if events.is_cancel_requested(turn_id):
            drop(token)
            return 0, 0, True
    except Exception:
        pass
    r = _redis()
    if r is None:
        st, rank = _local.poll(token, limit, mq, enqueue)
        return st, rank, False
    try:
        res = r.eval(_ACQUIRE_LUA, 2, _LEASE, _WAITQ, time.time(), limit, token, score,
                     LEASE_TTL_SEC, _HB, HB_TTL_SEC, mq, "1" if enqueue else "0")
        return int(res[0]), int(res[1]), False
    except Exception as e:
        logger.warning("AI gate yoklama hatası: %s", e)
        st, rank = _local.poll(token, limit, mq, enqueue)      # Redis hatasında süreç içi yedek
        return st, rank, False


def drop(token: str) -> None:
    """Kuyruktan çık (zaman aşımı/iptal/hata)."""
    _local.drop(token)
    r = _redis()
    if r is None:
        return
    try:
        pipe = r.pipeline()
        pipe.zrem(_WAITQ, token)
        pipe.delete(_HB + token)
        pipe.execute()
    except Exception:
        pass


def _prepare(message: Optional[str]) -> Dict[str, Any]:
    return {"limit": _limit(), "max_wait": max_wait_sec(), "mq": max_queue(),
            "bonus": fast_bonus_sec(), "lane": classify_lane(message)}


def _poll_sleep(rank: int) -> float:
    return min(1.0, 0.15 + 0.05 * max(rank, 0)) + random.random() * 0.05


async def acquire(turn_id: str, *, message: Optional[str] = None, timeout: Optional[float] = None,
                  lane: Optional[str] = None) -> GateResult:
    """Slot al (async). Bekleme `asyncio.sleep`; her yoklama kısa (`run_chat_io`). Jeton = `turn_id`."""
    from app.core.chat_executor import run_chat_io

    cfg = await run_chat_io(_prepare, message)
    if lane in (FAST, NORMAL):
        cfg["lane"] = lane
    wait_budget = float(timeout) if timeout else float(cfg["max_wait"])
    score = time.time() - (cfg["bonus"] if cfg["lane"] == FAST else 0)
    t0 = time.monotonic()
    enqueue = True
    first_pos: Optional[int] = None
    acquired = False
    try:
        while True:
            st, rank, cancelled = await run_chat_io(_poll, turn_id, score, enqueue, cfg["limit"], cfg["mq"], turn_id)
            if cancelled:
                _stat("cancelled_waiting")
                return GateResult(False, "cancelled", (time.monotonic() - t0) * 1000, cfg["lane"], first_pos or 0)
            if st == -1:
                _stat("rej_queue_full")
                n = await run_chat_io(queue_len)
                return GateResult(False, "queue_full", 0.0, cfg["lane"], 0, MSG_QUEUE_FULL.format(n=n))
            if st == -2:
                enqueue = True            # canlılık işareti kaçırıldı (ör. döngü tıkanması) → aynı skorla yeniden gir
                continue
            enqueue = False
            if first_pos is None:
                first_pos = rank
            if st == 1:
                acquired = True
                wait_s = time.monotonic() - t0
                if not _redis():
                    _local_t0[turn_id] = time.monotonic()
                _stat("acquired")
                _observe_wait(wait_s)
                return GateResult(True, "ok", wait_s * 1000, cfg["lane"], first_pos or 0)
            if time.monotonic() - t0 >= wait_budget:
                _stat("timeouts")
                return GateResult(False, "timeout", (time.monotonic() - t0) * 1000, cfg["lane"], first_pos or 0,
                                  MSG_TIMEOUT.format(s=int(wait_budget)))
            await asyncio.sleep(_poll_sleep(rank))
    finally:
        if not acquired:
            await run_chat_io(drop, turn_id)


def release(token: str, held_since: Optional[float] = None) -> None:
    """Slotu bırak (idempotent). `held_since` (monotonic) verilirse EWMA tur süresi güncellenir."""
    _local.release(token)
    r = _redis()
    if r is not None:
        try:
            r.zrem(_LEASE, token)
        except Exception:
            pass
    t0 = held_since if held_since is not None else _local_t0.pop(token, None)
    if t0 is not None:
        _update_avg((time.monotonic() - t0) * 1000.0)


def renew(token: str, session_id: Optional[int] = None) -> None:
    """Uzun turlarda lease'i (ve varsa oturum kilidini) uzat. Çağıran ~RENEW_EVERY_SEC'te bir çağırır."""
    _local.renew(token)
    r = _redis()
    if r is None:
        return
    try:
        r.zadd(_LEASE, {token: time.time() + LEASE_TTL_SEC})
        if session_id:
            r.expire(_SESS.format(sid=int(session_id)), SESSION_LOCK_TTL_SEC)
        r.expire(_UTURN.format(turn=token), USER_ACTIVE_TTL_SEC)
    except Exception:
        pass


# ── oturum başına seri ──────────────────────────────────────────────────────────────────────────────────────────

def _sess_try(session_id: int, turn_id: str, turn_for_cancel: str) -> Tuple[bool, bool]:
    """(alındı, iptal_edildi). Redis yoksa serileştirme yok (alındı)."""
    try:
        from app.services.chat_orchestrator import events
        if events.is_cancel_requested(turn_for_cancel):
            return False, True
    except Exception:
        pass
    r = _redis()
    if r is None:
        return True, False
    try:
        ok = r.eval(_SESS_ACQUIRE_LUA, 1, _SESS.format(sid=int(session_id)), turn_id, SESSION_LOCK_TTL_SEC)
        return bool(int(ok or 0)), False
    except Exception as e:
        logger.warning("oturum kilidi hatası (serileştirme atlandı): %s", e)
        return True, False


async def session_acquire(session_id: Optional[int], turn_id: str, timeout: Optional[float] = None,
                          on_wait: Optional[Callable[[], Any]] = None) -> GateResult:
    """Aynı oturumda bir önceki tur bitene kadar bekle. `session_id` yok / ayar kapalı → hemen ok.
    `on_wait` (async çağrılabilir) ilk başarısız yoklamada BİR kez çağrılır (kullanıcıya «sıra bekleniyor» olayı için)."""
    if not session_id:
        return GateResult(True)
    from app.core.chat_executor import run_chat_io

    enabled = await run_chat_io(session_serial_enabled)
    if not enabled:
        return GateResult(True)
    budget = float(timeout) if timeout else float(await run_chat_io(max_wait_sec))
    t0 = time.monotonic()
    waited = False
    while True:
        ok, cancelled = await run_chat_io(_sess_try, int(session_id), turn_id, turn_id)
        if cancelled:
            return GateResult(False, "cancelled", (time.monotonic() - t0) * 1000)
        if ok:
            if waited:
                _stat("session_waited")
            return GateResult(True, "ok", (time.monotonic() - t0) * 1000)
        if not waited and on_wait is not None:
            try:
                await on_wait()
            except Exception:
                logger.debug("session on_wait hata", exc_info=True)
        waited = True
        if time.monotonic() - t0 >= budget:
            _stat("session_timeouts")
            return GateResult(False, "timeout", (time.monotonic() - t0) * 1000, NORMAL, 0,
                              MSG_SESSION_TIMEOUT.format(s=int(budget)))
        await asyncio.sleep(0.4 + random.random() * 0.1)


def session_release(session_id: Optional[int], turn_id: str) -> None:
    if not session_id:
        return
    r = _redis()
    if r is None:
        return
    try:
        r.eval(_SESS_RELEASE_LUA, 1, _SESS.format(sid=int(session_id)), turn_id)
    except Exception:
        pass


# ── gözlem: snapshot + Prometheus metni ────────────────────────────────────────────────────────────────────────────

def _llm_cap() -> int:
    try:
        from app.services import llm_scheduler
        return int(llm_scheduler.max_concurrent())
    except Exception:
        return 0


def snapshot() -> Dict[str, Any]:
    """Anlık durum + sayaçlar (Redis; çok worker doğru). Ölü bekleyenleri süpürmez (yalnız okur)."""
    limit, cap = _limit(), _llm_cap()
    out: Dict[str, Any] = {
        "held": held_count(), "limit": limit, "queue_len": queue_len(), "queue_limit": max_queue(),
        "avg_turn_sec": round(avg_turn_sec(), 2), "llm_cap": cap,
        "max_wait_sec": max_wait_sec(), "user_limit": user_limit(), "fast_bonus_sec": fast_bonus_sec(),
        "stats": {},
    }
    if cap and limit > cap:
        out["note"] = (f"chat_ai_max_concurrent ({limit}) > llm_max_concurrent ({cap}): kapı {limit} turu içeri alır "
                       f"ama LLM çağrıları {cap} paralel yürür — fazlası LLM semaforunda bekler.")
    r = _redis()
    if r is not None:
        try:
            out["stats"] = {k: int(v) for k, v in (r.hgetall(_STATS) or {}).items()}
        except Exception:
            pass
    return out


def render_prometheus() -> str:
    s = snapshot()
    st = s["stats"]
    lines: List[str] = []

    def g(name: str, help_: str, value: Any, typ: str = "gauge") -> None:
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} {typ}")
        lines.append(f"{name} {value}")

    g("ainew_chat_gate_held", "Şu an kapıda tutulan (çalışan) tur sayısı", s["held"])
    g("ainew_chat_gate_limit", "chat_ai_max_concurrent", s["limit"])
    g("ainew_chat_gate_queue_len", "Kapıda bekleyen tur sayısı", s["queue_len"])
    g("ainew_chat_gate_queue_limit", "chat_gate_max_queue (0=kapalı)", s["queue_limit"])
    g("ainew_chat_gate_llm_cap", "llm_max_concurrent (0=kapalı)", s["llm_cap"])
    g("ainew_chat_gate_avg_turn_seconds", "EWMA tur süresi", s["avg_turn_sec"])
    g("ainew_chat_gate_acquired_total", "Slot alan tur sayısı", st.get("acquired", 0), "counter")
    g("ainew_chat_gate_timeouts_total", "Kapı bekleme zaman aşımı", st.get("timeouts", 0), "counter")
    g("ainew_chat_gate_cancelled_waiting_total", "Kuyrukta beklerken iptal", st.get("cancelled_waiting", 0), "counter")
    g("ainew_chat_gate_session_waited_total", "Oturum sırası beklemesi olan tur", st.get("session_waited", 0), "counter")
    g("ainew_chat_gate_session_timeouts_total", "Oturum sırası zaman aşımı", st.get("session_timeouts", 0), "counter")
    lines.append("# HELP ainew_chat_gate_rejected_total Tur oluşturulmadan reddedilenler")
    lines.append("# TYPE ainew_chat_gate_rejected_total counter")
    lines.append(f'ainew_chat_gate_rejected_total{{reason="queue_full"}} {st.get("rej_queue_full", 0)}')
    lines.append(f'ainew_chat_gate_rejected_total{{reason="user_limit"}} {st.get("rej_user_limit", 0)}')
    lines.append("# HELP ainew_chat_gate_wait_seconds Kapı bekleme süresi")
    lines.append("# TYPE ainew_chat_gate_wait_seconds histogram")
    cum = 0
    for b in WAIT_BUCKETS:
        cum += st.get(f"wait_le_{b}", 0)
        lines.append(f'ainew_chat_gate_wait_seconds_bucket{{le="{b}"}} {cum}')
    cum += st.get("wait_le_inf", 0)
    lines.append(f'ainew_chat_gate_wait_seconds_bucket{{le="+Inf"}} {cum}')
    lines.append(f"ainew_chat_gate_wait_seconds_sum {st.get('wait_ms_sum', 0) / 1000.0}")
    lines.append(f"ainew_chat_gate_wait_seconds_count {st.get('wait_count', 0)}")
    return "\n".join(lines) + "\n"
