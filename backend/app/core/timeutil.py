"""UTC-aware zaman yardımcıları — metrik / JSON serileştirme.

Postgres oturum TZ'si (ör. Europe/Istanbul) iken naive `utcnow()` / `utcfromtimestamp`
yazmak timestamptz'yi ~offset kadar geri kaydırır. Tüm metrik yazıları ve API
zaman alanları bu modülden geçmeli.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Union

UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Naive datetime'ı UTC varsay; aware olanı UTC'ye çevir."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def from_unix(ts: Union[int, float]) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=UTC)


def to_iso(dt: Optional[datetime]) -> Optional[str]:
    """ISO-8601 UTC (`...Z`). Frontend parseApiTime bunu güvenle okur."""
    if dt is None:
        return None
    d = ensure_utc(dt)
    if d is None:
        return None
    return d.isoformat().replace("+00:00", "Z")
