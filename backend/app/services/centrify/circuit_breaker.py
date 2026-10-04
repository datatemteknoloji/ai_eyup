"""Centrify WinRM circuit breaker — lockout koruması.

2 ardışık auth hatası → circuit açılır → tüm okuma/yazma işlemleri reddedilir.
Circuit açıkken admin manuel reset yapmalı (veya TTL sonunda otomatik kapanır).

Redis anahtarları:
  centrify:auth_fail_count  — art arda hata sayacı
  centrify:circuit_open     — "1" ise devre açık
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

CENTRIFY_AUTH_FAIL_KEY = "centrify:auth_fail_count"
CENTRIFY_CIRCUIT_KEY = "centrify:circuit_open"
MAX_AUTH_FAILS = 2
CIRCUIT_RESET_TTL = 3600  # 1 saat sonra otomatik kapanır


def _redis():
    from app.core.redis_client import get_redis
    return get_redis()


def is_circuit_open() -> bool:
    """Circuit breaker açık mı?"""
    r = _redis()
    if r is None:
        return False
    try:
        return r.get(CENTRIFY_CIRCUIT_KEY) == "1"
    except Exception:
        return False


def record_auth_failure() -> bool:
    """Auth hatası kaydet. True dönerse circuit yeni açıldı."""
    r = _redis()
    if r is None:
        logger.warning("Redis yok — circuit breaker çalışamıyor; auth hatası loglandı")
        return False
    try:
        count = r.incr(CENTRIFY_AUTH_FAIL_KEY)
        r.expire(CENTRIFY_AUTH_FAIL_KEY, CIRCUIT_RESET_TTL)
        if count >= MAX_AUTH_FAILS:
            r.set(CENTRIFY_CIRCUIT_KEY, "1", ex=CIRCUIT_RESET_TTL)
            logger.critical(
                "Centrify circuit breaker AÇILDI: %d ardışık auth hatası. "
                "Tüm Centrify işlemleri durduruldu. Admin reset gerekli.",
                count,
            )
            return True
        logger.warning("Centrify auth hatası #%d/%d", count, MAX_AUTH_FAILS)
        return False
    except Exception as exc:
        logger.error("Circuit breaker kayıt hatası: %s", exc)
        return False


def record_auth_success() -> None:
    """Başarılı auth sonrası sayacı sıfırla."""
    r = _redis()
    if r is None:
        return
    try:
        r.delete(CENTRIFY_AUTH_FAIL_KEY)
    except Exception:
        pass


def reset_circuit(*, actor: str = "system") -> bool:
    """Circuit'ı manuel kapat (admin işlemi). True = başarılı."""
    r = _redis()
    if r is None:
        return False
    try:
        r.delete(CENTRIFY_CIRCUIT_KEY)
        r.delete(CENTRIFY_AUTH_FAIL_KEY)
        logger.info("Centrify circuit breaker RESETLENDI — actor: %s", actor)
        return True
    except Exception as exc:
        logger.error("Circuit reset hatası: %s", exc)
        return False


def get_circuit_status() -> dict:
    """Circuit durumu: {open, fail_count, ttl_seconds}."""
    r = _redis()
    if r is None:
        return {"open": False, "fail_count": 0, "ttl_seconds": None, "redis_available": False}
    try:
        is_open = r.get(CENTRIFY_CIRCUIT_KEY) == "1"
        fail_count = int(r.get(CENTRIFY_AUTH_FAIL_KEY) or 0)
        ttl = r.ttl(CENTRIFY_CIRCUIT_KEY) if is_open else None
        return {
            "open": is_open,
            "fail_count": fail_count,
            "ttl_seconds": ttl if ttl and ttl > 0 else None,
            "redis_available": True,
        }
    except Exception:
        return {"open": False, "fail_count": 0, "ttl_seconds": None, "redis_available": False}
