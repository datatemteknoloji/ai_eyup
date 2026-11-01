"""Çağrı sınıfına göre dinamik LLM okuma zaman aşımı.

Sınıflar (llm_activity.classify ile aynı adlar):
  route_hint    — isteğe bağlı yönlendirme ipucu (UZAMAZ: üst sınır ≤ 10 sn)
  tool_turn     — araç seçimi / araç turu (`chat_sync`); alt sınır 90 sn
  final_answer  — cevap üreten akışlar; alt sınır = mevcut 120/180 sn varsayılanı
  background    — diğer (rapor, özet, analiz)

Kural: ``timeout = clamp(p95 × k, min, max)``. ``p95`` = sınıfın son N (50) çağrısı ve son 30 dk
(Redis `llm_activity`, tüm worker'lar; scheduler KUYRUK beklemesi HARİÇ — `duration_ms` slot alındıktan
sonra ölçülür). Örnek sayısı yetersizse (< `llm_timeout_min_samples`) alt sınır (= mevcut davranış).
Dinamik değer yalnız alt sınırın ÜSTÜNE çıkabilir; üst sınırı ayarlar belirler (uç değer koruması).
Sağlayıcıdan bağımsızdır (Ollama native / OpenAI-uyumlu / harici): yalnız ölçülen süreye bakar.

Açıkça `timeout=` verilen çağrılar bu yardımcıyı kullanmaz (override önceliklidir); `timeout=None`
varsayılanı ve çağrı noktaları (`route_llm_hint`, araç döngüsü) buradan beslenir.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

CLASSES = ("route_hint", "tool_turn", "final_answer", "background")

# sınıf → (k, min_sn, max_sn). runtime_settings varsayılanlarıyla aynı (fallback).
DEFAULTS: Dict[str, Tuple[float, float, float]] = {
    "route_hint": (1.5, 8.0, 10.0),
    "tool_turn": (2.0, 90.0, 180.0),
    "final_answer": (2.0, 120.0, 240.0),
    "background": (2.0, 120.0, 300.0),
}
ROUTE_HINT_HARD_MAX_SEC = 10.0      # route_hint dinamik olarak bunun üstüne ÇIKAMAZ (ayar da buna sınırlı)
DEFAULT_MIN_SAMPLES = 10
_CACHE_TTL_SEC = 10.0

_lock = threading.Lock()
_cache: Dict[str, Tuple[float, Optional[float], int]] = {}   # sınıf → (zaman, p95_sn, örnek)


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _setting(key: str, fallback: Any) -> Any:
    try:
        from app.services.runtime_settings import get_setting
        v = get_setting(key)
        return fallback if v is None or v == "" else v
    except Exception:
        return fallback


def _f(key: str, fallback: float) -> float:
    try:
        return float(_setting(key, fallback))
    except (TypeError, ValueError):
        return float(fallback)


def params(cls: str) -> Tuple[float, float, float]:
    """(k, min_sn, max_sn) — ayarlardan; tutarsızsa (max < min) max = min."""
    k0, lo0, hi0 = DEFAULTS.get(cls, DEFAULTS["background"])
    k = max(0.5, _f(f"llm_timeout_{cls}_k", k0))
    lo = max(1.0, _f(f"llm_timeout_{cls}_min_sec", lo0))
    hi = max(lo, _f(f"llm_timeout_{cls}_max_sec", hi0))
    if cls == "route_hint":
        hi = min(hi, ROUTE_HINT_HARD_MAX_SEC)
        lo = min(lo, hi)
    return k, lo, hi


def _dynamic_enabled() -> bool:
    v = _setting("llm_timeout_dynamic", True)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def _p95(cls: str) -> Tuple[Optional[float], int]:
    """(p95 sn, örnek sayısı) — 10 sn önbellekli (her LLM çağrısında Redis okunmasın)."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(cls)
        if hit and (now - hit[0]) < _CACHE_TTL_SEC:
            return hit[1], hit[2]
    p95: Optional[float] = None
    n = 0
    try:
        from app.services import llm_activity
        samples = llm_activity.class_samples(cls, window_sec=1800.0, last_n=50)
        n = len(samples)
        if samples:
            p95 = llm_activity._percentile(samples, 0.95)
    except Exception as exc:
        logger.debug("llm_timeouts örnek okunamadı: %s", exc)
    with _lock:
        _cache[cls] = (now, p95, n)
    return p95, n


def timeout_for(cls: str, *, floor: Optional[float] = None) -> float:
    """Sınıf için okuma zaman aşımı (sn).

    ``floor``: çağrı noktasının mevcut sabit varsayılanı (ör. 120 / 180) — sınıf alt sınırının yerine geçer
    (tool_turn: 90). Dinamik değer yalnız bunun üstüne çıkar.
    """
    cls = cls if cls in CLASSES else "background"
    k, lo, hi = params(cls)
    if floor is not None and cls != "route_hint":
        lo = max(1.0, float(floor))
        hi = max(hi, lo)
    if not _dynamic_enabled():
        return lo
    p95, n = _p95(cls)
    try:
        min_samples = max(1, int(float(_setting("llm_timeout_min_samples", DEFAULT_MIN_SAMPLES))))
    except (TypeError, ValueError):
        min_samples = DEFAULT_MIN_SAMPLES
    if p95 is None or n < min_samples:
        return lo
    return max(lo, min(hi, p95 * k))


def snapshot() -> Dict[str, Dict[str, Any]]:
    """Teşhis: sınıf başına etkin zaman aşımı, p95, örnek sayısı (admin/health)."""
    out: Dict[str, Dict[str, Any]] = {}
    for cls in CLASSES:
        k, lo, hi = params(cls)
        p95, n = _p95(cls)
        out[cls] = {
            "timeout_sec": round(timeout_for(cls), 1), "p95_sec": round(p95, 1) if p95 is not None else None,
            "samples": n, "k": k, "min_sec": lo, "max_sec": hi,
        }
    return out
