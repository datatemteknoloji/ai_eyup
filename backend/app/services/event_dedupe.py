"""SystemEvent tekilleştirme yardımcısı (external_key araması).

Neden (Adım 11 bulgusu): vCenter/oVirt/OpenShift Virtualization event toplayıcıları her olay için
«son 7 günün TÜM SystemEvent satırlarını» ORM nesnesi olarak yükleyip Python'da dolaşıyordu
(`vcenter_event` kaynağında ~91 bin satır × olay başına). Bu saf-Python iş bir `ssh_worker`
iş parçacığında dakikalarca GIL tutuyor, event döngüsünü 4–16 sn tıkıyor (sohbet SSE gecikmesi).
Burada arama SQL tarafında (`raw_data ->> 'external_key'`) veya sync başına TEK hafif sorguyla
(yalnız id + anahtar sütunu; ORM nesnesi yok) yapılır. Davranış aynı: aynı kaynakta, son 7 günde,
aynı `external_key` varsa mevcut satır döner.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from app.core.timeutil import utc_now
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.event import SystemEvent

WINDOW_DAYS = 7


def _key_expr():
    return SystemEvent.raw_data["external_key"].as_string()


class ExternalKeyIndex:
    """Bir sync turu boyunca kaynak başına `external_key → satır id` önbelleği (tembel yükleme)."""

    def __init__(self, db: Session, window_days: int = WINDOW_DAYS):
        self._db = db
        self._since = utc_now() - timedelta(days=window_days)
        self._maps: Dict[str, Dict[str, Any]] = {}

    def _load(self, source: str) -> Dict[str, Any]:
        m = self._maps.get(source)
        if m is not None:
            return m
        m = {}
        key = _key_expr()
        rows = (
            self._db.query(SystemEvent.id, key)
            .filter(SystemEvent.source == source, SystemEvent.created_at >= self._since, key.isnot(None))
            .order_by(SystemEvent.id)
            .all()
        )
        for rid, ext in rows:
            m.setdefault(ext, rid)  # ilk eşleşme (eski davranış: ilk bulunan)
        self._maps[source] = m
        return m

    def find(self, source: str, ext_key: str) -> Optional[SystemEvent]:
        v = self._load(source).get(ext_key)
        if v is None:
            return None
        if isinstance(v, SystemEvent):
            return v
        return self._db.get(SystemEvent, v)

    def add(self, source: str, ext_key: str, event: SystemEvent) -> None:
        """Bu turda eklenen (henüz flush edilmemiş olabilir) satırı aynı tur içi kopyalar için kaydet."""
        self._load(source).setdefault(ext_key, event)


def find_existing_event(
    db: Session,
    source: str,
    ext_key: str,
    index: Optional[ExternalKeyIndex] = None,
) -> Optional[SystemEvent]:
    """Aynı kaynakta son 7 günde aynı `external_key` ile kayıtlı satırı döndür (yoksa None)."""
    if index is not None:
        return index.find(source, ext_key)
    since = utc_now() - timedelta(days=WINDOW_DAYS)
    return (
        db.query(SystemEvent)
        .filter(SystemEvent.source == source, SystemEvent.created_at >= since, _key_expr() == ext_key)
        .order_by(SystemEvent.id)
        .first()
    )
