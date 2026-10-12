"""Capability registry — aktif entegrasyon instance'larından yetenek kümesi.

UI menü/sekme, findings ``requires_capability``, fleet scheduler ve sohbet tool
filtresi bu servisten beslenir.

Karar (Dilim B): ``integration_instances`` yalnız *yeni* entegrasyonlar içindir
(category örn. backup, ileride bmc). Centrify / Automic / hypervisor kartları
bu tabloya taşınmaz.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, FrozenSet, Optional, Set

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CACHE: Optional[FrozenSet[str]] = None
_CACHE_AT: float = 0.0
_TTL_SEC = 5.0  # kısa TTL; invalidate ile anında da düşer


def invalidate_capabilities() -> None:
    """Entegrasyon enable/disable/silme sonrası çağrılır."""
    global _CACHE, _CACHE_AT
    with _LOCK:
        _CACHE = None
        _CACHE_AT = 0.0


def get_capabilities(*, force_refresh: bool = False) -> FrozenSet[str]:
    """Aktif + sağlıklı instance'lardan capability kümesi."""
    global _CACHE, _CACHE_AT
    now = time.monotonic()
    with _LOCK:
        if not force_refresh and _CACHE is not None and (now - _CACHE_AT) < _TTL_SEC:
            return _CACHE
    caps = frozenset(_collect())
    with _LOCK:
        _CACHE = caps
        _CACHE_AT = time.monotonic()
    return caps


def capabilities_payload() -> Dict[str, Any]:
    caps = sorted(get_capabilities())
    from app.services.backup.demo_gate import BANNER_TR, DEMO_CAPABILITY
    demo = DEMO_CAPABILITY in caps
    return {"ok": True, "capabilities": caps, "has_backup": "backup" in caps,
            "demo_active": demo, "demo_banner": BANNER_TR if demo else None}


def _collect() -> Set[str]:
    out: Set[str] = set()
    try:
        from app.core.database import SessionLocal
        from app.models.integration_instance import IntegrationInstance
        from app.services.backup.registry import capabilities_for_instance

        db = SessionLocal()
        try:
            rows = (
                db.query(IntegrationInstance)
                .filter(IntegrationInstance.enabled.is_(True))
                .all()
            )
            from app.services.backup.demo_gate import (
                DEMO_CAPABILITY, demo_enabled, is_demo_kind,
            )
            has_real = any(not is_demo_kind(r.kind) for r in rows)
            for row in rows:
                if is_demo_kind(row.kind):
                    # F.0: DEMO yalnız açık bayrakla ve gerçek sağlayıcı yokken görünür; "backup"
                    # yeteneğini AÇMAZ (araç/bulgu/koruma kuralları demo'dan etkilenmez).
                    if demo_enabled() and not has_real and (
                            (row.last_status or "") == "ok" or row.last_sync_at is not None):
                        out.add(DEMO_CAPABILITY)
                    continue
                # Hiç başarılı senkron yoksa (yanlış parola vb.) capability açılmaz;
                # daha önce başarılı olmuş instance geçici hatada kaybolmaz — veri bayat
                # işaretlenir (bk.provider.* bulguları görünür kalır).
                if (row.last_status or "") != "ok" and row.last_sync_at is None:
                    continue
                try:
                    out |= set(capabilities_for_instance(row))
                except Exception as e:  # noqa: BLE001
                    logger.debug("capability collect %s: %s", row.kind, e)
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        # Tablo henüz yok / ilk boot — boş küme (Veeam'siz davranış).
        logger.debug("capabilities collect skipped: %s", e)
    return out
