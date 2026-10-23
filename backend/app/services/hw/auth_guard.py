"""Kimlik doğrulama koruması (TÜM donanım entegrasyonları): hesap KİLİTLENMESİN.

Kurallar (kullanıcı şartı — docs/plans/hw-providers.md §12):
  1. Kimlik doğrulama 1 kez denenir; 401/oturum reddi → yeniden deneme YOK, durum `auth_failed`, otomatik senkron durur.
  2. 403 de yeniden denenmez (durum `auth_failed`, mesaj "yetki yetersiz").
  3. Yeniden başlatma YALNIZ başarılı "Bağlantıyı test et" ile olur; kimlik bilgisini kaydetmek tek başına başlatmaz.
  4. Paylaşılan hesapla çok sayıda appliance: ilk auth hatasında kalanlara denenmez (çağıran `AuthHalt` fırlatır).
  5. Durum veritabanındadır (meta_json.auth_halted) + deneme anında `attempt_lock` (Redis fleet_lock + süreç-içi kilit):
     UVICORN_WORKERS=2 iken iki worker aynı anda yanlış parolayı denemez.
  6. "Bağlantıyı test et" düğmesinde bekleme süresi (TEST_COOLDOWN_SEC).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional

from app.services.hw.constants import AUTH_FAILED, TEST_COOLDOWN_SEC

logger = logging.getLogger(__name__)

HALT_KEY = "auth_halted"

_PROC_LOCKS: Dict[str, threading.Lock] = {}
_PROC_LOCKS_GUARD = threading.Lock()
_LOCAL_COOLDOWN: Dict[str, float] = {}


class AuthHalt(Exception):
    """Kimlik doğrulama reddedildi → tüm denemeleri durdur (appliance döngüsünü kes)."""

    def __init__(self, kind: str, message: str, where: str = ""):
        super().__init__(message)
        self.kind = kind          # auth | forbidden
        self.message = message
        self.where = where


def _meta(row) -> Dict[str, Any]:
    try:
        return json.loads(row.meta_json) if row.meta_json else {}
    except Exception:  # noqa: BLE001
        return {}


def is_halted(row) -> bool:
    return bool(_meta(row).get(HALT_KEY))


def halt_info(row) -> Optional[Dict[str, Any]]:
    m = _meta(row)
    if not m.get(HALT_KEY):
        return None
    return {"at": m.get("auth_halted_at"), "kind": m.get("auth_halted_kind"), "message": m.get("auth_halted_msg"),
            "where": m.get("auth_halted_where")}


def halt(db, row, *, kind: str, message: str, where: str = "") -> None:
    """Senkronu durdurur (DB). Çağıran commit ETMEZ değil: burada commit edilir."""
    m = _meta(row)
    m[HALT_KEY] = True
    m["auth_halted_at"] = datetime.now(timezone.utc).isoformat()
    m["auth_halted_kind"] = kind
    m["auth_halted_msg"] = message[:500]
    m["auth_halted_where"] = where[:255]
    row.meta_json = json.dumps(m)
    row.last_status = AUTH_FAILED
    row.last_error = message[:2000]
    db.commit()
    try:
        from app.services.capabilities import invalidate_capabilities
        invalidate_capabilities()
    except Exception:  # noqa: BLE001
        pass
    logger.warning("HW entegrasyonu %s kimlik doğrulama hatası nedeniyle DURDURULDU (%s): %s", row.id, kind, where)


def clear(db, row) -> None:
    """Yalnız BAŞARILI bağlantı testinden sonra çağrılır."""
    m = _meta(row)
    for k in (HALT_KEY, "auth_halted_at", "auth_halted_kind", "auth_halted_msg", "auth_halted_where",
              "consecutive_failures", "breaker_until"):
        m.pop(k, None)
    row.meta_json = json.dumps(m)
    if row.last_status == AUTH_FAILED:
        row.last_status = "ok" if row.last_sync_at else "never"
        row.last_error = None
    db.commit()


def _proc_lock(name: str) -> threading.Lock:
    with _PROC_LOCKS_GUARD:
        return _PROC_LOCKS.setdefault(name, threading.Lock())


@contextmanager
def attempt_lock(instance_id: Optional[int]) -> Iterator[bool]:
    """Bir entegrasyona karşı AYNI ANDA tek bağlantı denemesi (worker'lar arası). False → başka deneme sürüyor."""
    name = f"hw_attempt_{instance_id if instance_id is not None else 'tmp'}"
    plock = _proc_lock(name)
    if not plock.acquire(blocking=False):
        yield False
        return
    try:
        from app.services.fleet_mutex import fleet_lock
        with fleet_lock(name, ttl_sec=300) as got:
            yield bool(got)
    finally:
        plock.release()


def acquire_test_slot(key: str, *, cooldown_sec: int = TEST_COOLDOWN_SEC) -> int:
    """Test düğmesi bekleme süresi. 0 → izin verildi; >0 → kalan saniye. Redis (worker'lar arası) + yerel yedek."""
    now = time.monotonic()
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
    except Exception:  # noqa: BLE001
        r = None
    rkey = f"ainew:hw_test_cd:{key}"
    if r is not None:
        try:
            if r.set(rkey, "1", nx=True, ex=cooldown_sec):
                return 0
            ttl = r.ttl(rkey)
            return max(1, int(ttl)) if ttl and ttl > 0 else cooldown_sec
        except Exception:  # noqa: BLE001
            pass
    last = _LOCAL_COOLDOWN.get(key)
    if last is not None and (now - last) < cooldown_sec:
        return max(1, int(cooldown_sec - (now - last)))
    _LOCAL_COOLDOWN[key] = now
    return 0


def reset_test_slot(key: str) -> None:
    _LOCAL_COOLDOWN.pop(key, None)
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        if r is not None:
            r.delete(f"ainew:hw_test_cd:{key}")
    except Exception:  # noqa: BLE001
        pass
