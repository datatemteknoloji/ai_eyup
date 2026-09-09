"""Uzak LLM erişilebilirliği — fail-fast devre kesici.

Ürün kuralı: uzak model (REMOTE_LLM_*) aktifken sohbet/agent istekleri
sessizce yerel Ollama'ya DÜŞMEZ. Uzak sağlayıcı yanıt vermiyorsa istek
hızlıca, kibar bir mesajla başarısız olur; kullanıcıya "yerele geçilsin mi"
sorusu sorulmaz. Yerel modele dönmek yalnızca Ayarlar'daki operatör
kararıdır (REMOTE_LLM_ENABLED).

Devre kesici, uzun timeout'ların AI kuyruğunu doldurup uygulamayı
kilitlemesini engeller: kısa süre içinde birkaç hata olursa devre açılır ve
sonraki istekler ağ beklemeden reddedilir.

Not: RAG embedding bu kuralın dışındadır (bkz. `embedding.py`) — vektör
üretimi sohbet cevabı değildir ve yerel Ollama birincil yoldur.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Pencere içinde bu kadar hata → devre açılır
FAILURE_THRESHOLD = 3
FAILURE_WINDOW_SEC = 60.0
OPEN_SEC = 45.0

# Uzak gateway'e bağlanma (TCP + TLS) için üst sınır — yanıt süresi ayrı
CONNECT_TIMEOUT_SEC = 5.0

_REDIS_OPEN_KEY = "ainew:llm:remote_open"

_lock = threading.Lock()
_failures: list = []
_open_until: float = 0.0
_last_error: Optional[str] = None
_last_success: float = 0.0


def _redis():
    try:
        from app.core.redis_client import get_redis
        return get_redis()
    except Exception:
        return None


def reset() -> None:
    """Test / manuel kurtarma."""
    global _failures, _open_until, _last_error, _last_success
    with _lock:
        _failures = []
        _open_until = 0.0
        _last_error = None
        _last_success = 0.0
    r = _redis()
    if r is not None:
        try:
            r.delete(_REDIS_OPEN_KEY)
        except Exception:
            pass


def record_success() -> None:
    global _failures, _open_until, _last_success
    with _lock:
        was_open = _open_until > time.monotonic()
        _failures = []
        _open_until = 0.0
        _last_success = time.monotonic()
    if was_open:
        logger.info("[LLM] Uzak model yeniden yanıt veriyor — devre kapatıldı")
        r = _redis()
        if r is not None:
            try:
                r.delete(_REDIS_OPEN_KEY)
            except Exception:
                pass


def record_failure(detail: str = "") -> None:
    """Ağ/timeout/5xx hatası. 4xx (istek hatası) için çağrılmaz."""
    global _failures, _open_until, _last_error
    now = time.monotonic()
    opened = False
    with _lock:
        _last_error = (detail or "")[:400]
        _failures = [t for t in _failures if now - t < FAILURE_WINDOW_SEC]
        _failures.append(now)
        if len(_failures) >= FAILURE_THRESHOLD and _open_until <= now:
            _open_until = now + OPEN_SEC
            opened = True
    if opened:
        logger.error(
            "[LLM] Uzak model %s sn devre dışı bırakıldı (%s hata/%.0f sn). Son hata: %s",
            int(OPEN_SEC), FAILURE_THRESHOLD, FAILURE_WINDOW_SEC, (detail or "")[:200],
        )
        r = _redis()
        if r is not None:
            try:
                r.setex(_REDIS_OPEN_KEY, int(OPEN_SEC), (detail or "1")[:200])
            except Exception:
                pass


def is_open() -> bool:
    """Devre açık mı (istek gönderilmeden reddedilmeli mi)?"""
    with _lock:
        if _open_until > time.monotonic():
            return True
    r = _redis()
    if r is not None:
        try:
            return bool(r.exists(_REDIS_OPEN_KEY))
        except Exception:
            return False
    return False


def last_error() -> Optional[str]:
    with _lock:
        return _last_error


def snapshot() -> Dict[str, Any]:
    """UI/durum göstergesi için."""
    with _lock:
        remaining = max(0.0, _open_until - time.monotonic())
        return {
            "circuit_open": remaining > 0,
            "reopen_in_sec": int(remaining),
            "recent_failures": len(_failures),
            "last_error": _last_error,
        }


UNAVAILABLE_MESSAGE = (
    "Uzak dil modeli şu anda yanıt vermiyor, bu nedenle sorunuz yanıtlanamadı. "
    "Yapılandırma gereği istek yerel modele aktarılmaz. Bağlantı yeniden "
    "kurulduğunda aynı soruyu tekrar gönderebilirsiniz."
)


def friendly_error(detail: str = "") -> str:
    """Kullanıcıya gösterilecek kibar hata metni (teknik detay parantez içinde)."""
    detail = (detail or last_error() or "").strip()
    if not detail:
        return UNAVAILABLE_MESSAGE
    return f"{UNAVAILABLE_MESSAGE} (Teknik detay: {detail[:200]})"


def is_retryable_status(status_code: int) -> bool:
    """Devre kesiciyi besleyen HTTP durumları — 4xx istek hatası sayılmaz."""
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return False
    return code == 408 or code == 429 or code >= 500
