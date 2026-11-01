"""Uzak LLM erişilebilirliği — fail-fast devre kesici.

Ürün kuralı: uzak model (REMOTE_LLM_*) aktifken sohbet/agent istekleri
sessizce yerel Ollama'ya DÜŞMEZ. Uzak sağlayıcı yanıt vermiyorsa istek
hızlıca, kibar bir mesajla başarısız olur; kullanıcıya "yerele geçilsin mi"
sorusu sorulmaz. Yerel modele dönmek yalnızca Ayarlar'daki operatör
kararıdır (REMOTE_LLM_ENABLED).

Devre kesici, uzun timeout'ların AI kuyruğunu doldurup uygulamayı
kilitlemesini engeller: kısa süre içinde birkaç hata olursa devre açılır ve
sonraki istekler ağ beklemeden reddedilir.

Yoklamalı devre kesici (Adım 3): eşik dolunca devre hemen AÇILMAZ; önce hafif bir sağlık yoklaması
(Ollama `/api/version`, OpenAI-uyumlu `/v1/models`) yapılır. Sunucu yoklamaya yanıt veriyorsa
("yavaş ama ayakta") devre açılmaz; ulaşılamıyorsa veya bağlantı reddi/DNS/TLS hatasıysa açılır.
Açık kalma süresi dolunca ilk istekte tek yoklamalı yarı açık deneme yapılır. İsteğe bağlı yan
çağrılar (`generate_*(best_effort=True)`) bu sayaca hiç girmez. Eşikler `runtime_settings`
(`llm_circuit_*`); aşağıdaki sabitler yalnız fallback.

Not: RAG embedding bu kuralın dışındadır (bkz. `embedding.py`) — vektör
üretimi sohbet cevabı değildir ve yerel Ollama birincil yoldur.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Fallback sabitleri — asıl değerler runtime_settings `llm_circuit_*` (varsayılanlar aynı)
FAILURE_THRESHOLD = 3
FAILURE_WINDOW_SEC = 60.0
OPEN_SEC = 45.0
PROBE_TIMEOUT_SEC = 3.0
# Yoklama sonucu bu süre önbelleklenir (hata başına yoklama yağmuru olmasın)
PROBE_CACHE_SEC = 5.0
_CFG_CACHE_SEC = 5.0

# Uzak gateway'e bağlanma (TCP + TLS) için üst sınır — yanıt süresi ayrı
CONNECT_TIMEOUT_SEC = 5.0

_REDIS_OPEN_KEY = "ainew:llm:remote_open"

_lock = threading.Lock()
_failures: list = []
_open_until: float = 0.0
_last_error: Optional[str] = None
_last_success: float = 0.0
_half_open_pending = False      # devre açıldı; süre dolunca ilk istekte tek yoklama yapılacak
_probing = False                # eşik yoklaması sürüyor (aynı anda tek yoklama)
_probe_cache: Tuple[float, Optional[bool]] = (0.0, None)   # (wall zamanı, sonuç)
_cfg_cache: Tuple[float, Tuple[int, float, float, float]] = (0.0, (0, 0.0, 0.0, 0.0))

# Bağlantı kurulamadı sınıfı (reddedildi / DNS / TLS) — yoklamasız hemen açılır
_HARD_CONNECT_RE = re.compile(
    r"ConnectTimeout|ConnectError|NewConnectionError|NameResolutionError|gaierror|SSLError|"
    r"CERTIFICATE_VERIFY|Connection refused|Name or service not known|getaddrinfo|"
    r"Temporary failure in name resolution|No route to host|Network is unreachable"
)


def _cfg() -> Tuple[int, float, float, float]:
    """(eşik, pencere sn, açık kalma sn, yoklama zaman aşımı sn) — runtime_settings, 5 sn önbellek."""
    global _cfg_cache
    now = time.time()
    at, val = _cfg_cache
    if val[0] and (now - at) < _CFG_CACHE_SEC:
        return val
    thr, win, opn, prb = FAILURE_THRESHOLD, FAILURE_WINDOW_SEC, OPEN_SEC, PROBE_TIMEOUT_SEC
    try:
        from app.services import runtime_settings as rts
        thr = max(1, int(rts.get_int("llm_circuit_failure_threshold")))
        win = max(1.0, float(rts.get_int("llm_circuit_failure_window_sec")))
        opn = max(1.0, float(rts.get_int("llm_circuit_open_sec")))
        prb = max(0.5, float(rts.get_int("llm_circuit_probe_timeout_sec")))
    except Exception:
        pass
    _cfg_cache = (now, (thr, win, opn, prb))
    return _cfg_cache[1]


def _in_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def _redis():
    try:
        from app.core.redis_client import get_redis
        return get_redis()
    except Exception:
        return None


def reset() -> None:
    """Test / manuel kurtarma."""
    global _failures, _open_until, _last_error, _last_success, _half_open_pending, _probing, _probe_cache, _cfg_cache
    with _lock:
        _failures = []
        _open_until = 0.0
        _last_error = None
        _last_success = 0.0
        _half_open_pending = False
        _probing = False
        _probe_cache = (0.0, None)
        _cfg_cache = (0.0, (0, 0.0, 0.0, 0.0))
    r = _redis()
    if r is not None:
        try:
            r.delete(_REDIS_OPEN_KEY)
        except Exception:
            pass


def record_success() -> None:
    global _failures, _open_until, _last_success, _half_open_pending
    with _lock:
        was_open = _open_until > time.monotonic()
        _failures = []
        _open_until = 0.0
        _half_open_pending = False
        _last_success = time.monotonic()
    if was_open:
        logger.info("[LLM] Uzak model yeniden yanıt veriyor — devre kapatıldı")
        r = _redis()
        if r is not None:
            try:
                r.delete(_REDIS_OPEN_KEY)
            except Exception:
                pass


def _probe_health() -> Optional[bool]:
    """Sağlık yoklaması (sonuç ~5 sn önbellekli). True=ayakta, False=ulaşılamıyor, None=yoklanamaz."""
    global _probe_cache
    now = time.time()
    with _lock:
        at, val = _probe_cache
        if val is not None and (now - at) < PROBE_CACHE_SEC:
            return val
    timeout = _cfg()[3]
    try:
        from app.services import llm_transport
        res = llm_transport.probe_remote_health(timeout=timeout)
    except Exception as exc:
        logger.info("[LLM] yoklama çalıştırılamadı: %s", exc)
        res = None
    if res is not None:
        with _lock:
            _probe_cache = (time.time(), res)
    return res


def _open_circuit(detail: str) -> None:
    """Devreyi aç (yerel + Redis paylaşımlı)."""
    global _open_until, _half_open_pending, _failures
    opn = _cfg()[2]
    with _lock:
        _open_until = time.monotonic() + opn
        _half_open_pending = True
    logger.error(
        "[LLM] Uzak model %s sn devre dışı bırakıldı (%s hata/%.0f sn). Son hata: %s",
        int(opn), _cfg()[0], _cfg()[1], (detail or "")[:200],
    )
    r = _redis()
    if r is not None:
        try:
            r.setex(_REDIS_OPEN_KEY, int(opn), (detail or "1")[:200])
        except Exception:
            pass


def _decide_after_threshold(detail: str) -> None:
    """Eşik doldu: bağlantı reddi/DNS/TLS → aç; aksi halde yoklama (ayakta → açma)."""
    global _probing, _failures
    try:
        if _HARD_CONNECT_RE.search(detail or ""):
            _open_circuit(detail)
            return
        ok = _probe_health()
        if ok is True:
            with _lock:
                _failures = []      # sunucu ayakta: hata yavaşlıktan; sayaç sıfırlanır
            logger.info(
                "[LLM] Uzak model yoklaması başarılı — devre açılmadı (yavaş ama ayakta). Son hata: %s",
                (detail or "")[:200],
            )
            return
        _open_circuit(detail)
    finally:
        with _lock:
            _probing = False


def record_failure(detail: str = "") -> None:
    """Ağ/timeout/5xx hatası. 4xx (istek hatası) için çağrılmaz.

    İsteğe bağlı yan çağrılar bunu çağırmaz (`best_effort`). Eşik dolunca devre, sağlık yoklaması
    başarısızsa (veya bağlantı reddi/DNS/TLS ise) açılır; olay döngüsünde yoklama arka planda koşar.
    """
    global _failures, _last_error, _probing
    thr, win, _opn, _prb = _cfg()
    now = time.monotonic()
    reached = False
    with _lock:
        _last_error = (detail or "")[:400]
        _failures = [t for t in _failures if now - t < win]
        _failures.append(now)
        if len(_failures) >= thr and _open_until <= now and not _probing:
            _probing = True
            reached = True
    if not reached:
        return
    if _in_event_loop() and not _HARD_CONNECT_RE.search(detail or ""):
        threading.Thread(
            target=_decide_after_threshold, args=(detail,), name="llm-circuit-probe", daemon=True,
        ).start()
    else:
        _decide_after_threshold(detail)


def _half_open_probe() -> None:
    """OPEN_SEC doldu: tek yoklama. Başarılı → devre kapanır; başarısız → yeniden açılır."""
    global _failures, _open_until
    ok = _probe_health()
    if ok is True:
        with _lock:
            _failures = []
            _open_until = 0.0
        logger.info("[LLM] Yarı açık yoklama başarılı — devre kapatıldı")
        r = _redis()
        if r is not None:
            try:
                r.delete(_REDIS_OPEN_KEY)
            except Exception:
                pass
    else:
        _open_circuit(_last_error or "yarı açık yoklama başarısız")


def is_open() -> bool:
    """Devre açık mı (istek gönderilmeden reddedilmeli mi)?"""
    global _half_open_pending
    now = time.monotonic()
    claim = False
    with _lock:
        if _open_until > now:
            return True
        if _half_open_pending:
            _half_open_pending = False
            claim = True
    if claim:
        if _in_event_loop():
            # Olay döngüsünü bloklama: yoklama arka planda; bu istek deneme isteği olarak geçer
            threading.Thread(target=_half_open_probe, name="llm-halfopen-probe", daemon=True).start()
        else:
            _half_open_probe()
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
