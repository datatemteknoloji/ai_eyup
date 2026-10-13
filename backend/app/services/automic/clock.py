"""Sohbet/sorgu katmanı için "şimdi" saati.

Normalde gerçek UTC saatidir. Kalite ölçümü (benchmark) için YALNIZ admin + `debug_trace` isteğinde
`now_override` verilebilir: sabit tarihli DEV-FAKE verisinde "son 24 saat / dün" gibi göreli sorular
zamanla veri kapsamının dışına kayar; ölçümün tekrarlanabilir olması için saat dondurulur.
Yalnız sohbet isteği bağlamını etkiler (ContextVar); toplayıcı/arka plan işleri gerçek saati kullanır.
"""
from __future__ import annotations

import contextvars
from datetime import datetime, timezone
from typing import Optional

_NOW_CV: contextvars.ContextVar[Optional[datetime]] = contextvars.ContextVar("automic_now_override", default=None)


def set_now(dt: Optional[datetime]) -> None:
    _NOW_CV.set(dt)


def parse_override(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_utc() -> datetime:
    return _NOW_CV.get() or datetime.now(timezone.utc)


# ── kodla çözülmüş açık tarih penceresi ───────────────────────────────────────
# Kullanıcı "2025 Aralık / 15 Mart / geçen ayın 3'ü" gibi açık tarih verdiğinde pencereyi KOD hesaplar
# (`llm_chat_policy.resolve_time_window`); araç çağrısında model from/to üretse de bu pencere öncelikli
# uygulanır (model tarih argümanı üretmek zorunda kalmaz; yanlış/bozuk tarih riski kalkar).
_WINDOW_CV: contextvars.ContextVar[Optional[tuple]] = contextvars.ContextVar("automic_forced_window", default=None)


def set_window(window: Optional[tuple]) -> None:
    """window = (from_iso, to_iso) veya None."""
    _WINDOW_CV.set(window)


def forced_window() -> Optional[tuple]:
    return _WINDOW_CV.get()


def apply_window(args: dict) -> dict:
    """Zorunlu pencere varsa from/to'yu ona ayarlar, range'i kaldırır.

    Aynı dict üzerinde günceller (araç izine yazılan args ile execute args aynı
    nesne olduğundan izde `range=24h` kalıp from/to'nun görünmemesi engellenir).
    """
    w = _WINDOW_CV.get()
    if not w:
        return args
    args["from"], args["to"] = w[0], w[1]
    args.pop("range", None)
    return args


# entity_latest: varsayılan 24h yerine geniş aralık (en son ilgili çalışmalar)
_MODE_CV: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("automic_window_mode", default=None)


def set_window_mode(mode: Optional[str]) -> None:
    """mode: None | 'entity_latest' | 'default_fallback'."""
    _MODE_CV.set(mode)


def window_mode() -> Optional[str]:
    return _MODE_CV.get()
