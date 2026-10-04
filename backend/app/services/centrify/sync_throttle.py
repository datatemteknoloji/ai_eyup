"""WinRM istek hızı / bağlantı düzenleyici — hedef Access Manager'ı yormamak için.

Varsayılanlar ortam değişkenleriyle override edilebilir:
  CENTRIFY_SYNC_MIN_INTERVAL_MS   — ardışık WinRM çağrıları arası min ms (default 800)
  CENTRIFY_SYNC_ZONE_DELAY_SEC    — zone'lar arası ek bekleme sn (default 2.0)
  CENTRIFY_SYNC_MAX_RETRIES       — geçici hata retry (default 2)
  CENTRIFY_SYNC_RETRY_BACKOFF_SEC — retry bekleme sn (default 3.0)
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_lock = threading.Lock()
_last_request_monotonic = 0.0


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def min_interval_sec() -> float:
    return max(0.0, _env_float("CENTRIFY_SYNC_MIN_INTERVAL_MS", 800) / 1000.0)


def zone_delay_sec() -> float:
    return max(0.0, _env_float("CENTRIFY_SYNC_ZONE_DELAY_SEC", 2.0))


def max_retries() -> int:
    return max(0, _env_int("CENTRIFY_SYNC_MAX_RETRIES", 2))


def retry_backoff_sec() -> float:
    return max(0.5, _env_float("CENTRIFY_SYNC_RETRY_BACKOFF_SEC", 3.0))


def wait_for_slot() -> None:
    """Global tek-slot: aynı anda bir WinRM çağrısı; min aralık uygula."""
    global _last_request_monotonic
    with _lock:
        now = time.monotonic()
        gap = min_interval_sec()
        wait = (_last_request_monotonic + gap) - now
        if wait > 0:
            time.sleep(wait)
        _last_request_monotonic = time.monotonic()


def mark_request_done() -> None:
    global _last_request_monotonic
    with _lock:
        _last_request_monotonic = time.monotonic()


def pause_between_zones() -> None:
    d = zone_delay_sec()
    if d > 0:
        logger.debug("Centrify sync zone delay: %.1fs", d)
        time.sleep(d)


def call_with_throttle(fn: Callable[[], T], *, label: str = "winrm") -> T:
    """Throttle + sınırlı transient retry."""
    from app.services.centrify.exceptions import (
        CentrifyAuthError,
        CentrifyCircuitOpenError,
        CentrifyConnectionError,
        CentrifyErrorClass,
        CentrifyScriptError,
    )

    attempts = 1 + max_retries()
    last_exc: Exception | None = None
    for i in range(attempts):
        wait_for_slot()
        try:
            result = fn()
            mark_request_done()
            return result
        except CentrifyCircuitOpenError:
            raise
        except CentrifyAuthError:
            raise
        except (CentrifyConnectionError, CentrifyScriptError, TimeoutError, OSError) as exc:
            last_exc = exc
            mark_request_done()
            # ScriptError kalıcı olabilir; yalnızca bağlantı/timeout'ta retry
            transient = isinstance(exc, (CentrifyConnectionError, TimeoutError, OSError))
            if isinstance(exc, CentrifyScriptError):
                # stderr'de timeout/busy varsa transient say
                msg = (getattr(exc, "stderr", None) or str(exc)).lower()
                transient = any(x in msg for x in ("timeout", "timed out", "busy", "unavailable", "connection"))
            if not transient or i >= attempts - 1:
                raise
            backoff = retry_backoff_sec() * (i + 1)
            logger.warning(
                "Centrify %s geçici hata (deneme %s/%s), %.1fs bekleniyor: %s",
                label, i + 1, attempts, backoff, exc,
            )
            time.sleep(backoff)
    assert last_exc is not None
    raise last_exc
