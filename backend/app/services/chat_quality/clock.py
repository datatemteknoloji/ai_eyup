"""Sohbet kalite katmanı saati.

`now()` yalnız admin/bench `now_override` bayrağı açıkken (tur izi üzerinden) sabit
saat döner; aksi halde gerçek saat. Zaman çözümleyici (sonraki adım) bu fonksiyonu kullanır.
"""
from __future__ import annotations

from datetime import datetime

from app.services.chat_quality import trace


def now() -> datetime:
    t = trace.current()
    if t is not None and t.now_override is not None:
        return t.now_override
    return datetime.now()


def now_aware(tz: str | None = None) -> datetime:
    """tz-aware «şimdi» (kullanıcı/uygulama saat dilimi; ayar `chat_timezone`, varsayılan Europe/Istanbul).

    `now_override` varsa onu (naif = sistem yerel saati) aynı dilime çevirir. Zaman penceresi verilmeyen
    (varsayılan) handler yolunda `datetime.utcnow()` yerine KULLANILIR: naif UTC değeri timestamptz
    sütunlarına bağlanınca oturum saat diliminde (Europe/Istanbul) yerel sayılıp pencereyi 3 saat
    genişletiyordu.
    """
    from app.services.chat_quality import time_window as _tw

    zone, _ = _tw._tz(tz or _tw.configured_tz())
    return _tw._aware(now(), zone)


def default_since(days: float, tz: str | None = None) -> datetime:
    """Varsayılan (pencere verilmeyen) yol: tz-aware `now - days`. Sorgu parametresi olarak güvenle bağlanır."""
    from datetime import timedelta

    return now_aware(tz) - timedelta(days=days)
