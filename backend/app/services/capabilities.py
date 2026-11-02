"""Capability registry — aktif entegrasyon instance'larından yetenek kümesi.

UI menü/sekme, findings ``requires_capability``, fleet scheduler ve sohbet tool
filtresi bu servisten beslenir.

Karar (Dilim B): ``integration_instances`` yalnız *yeni* entegrasyonlar içindir
(category: backup, hardware). Centrify / Automic / hypervisor kartları
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
    from app.services.hw.demo_gate import BANNER_TR as HW_BANNER_TR, DEMO_CAPABILITY as HW_DEMO_CAPABILITY
    demo = DEMO_CAPABILITY in caps
    hw_demo = HW_DEMO_CAPABILITY in caps
    # Faz 3c: portal (OME/OneView) olmadan da log odaklı Donanım sayfası — bayrak açık veya log kaydı var.
    try:
        from app.services.hw.host_logs import logs_available
        has_hw_logs = bool(logs_available())
    except Exception:  # noqa: BLE001
        has_hw_logs = False
    return {"ok": True, "capabilities": caps, "has_backup": "backup" in caps,
            "demo_active": demo, "demo_banner": BANNER_TR if demo else None,
            "has_hw": "hw" in caps, "hw_demo_active": hw_demo, "has_hw_logs": has_hw_logs,
            "hw_demo_banner": HW_BANNER_TR if hw_demo else None,
            "has_automic": "automic" in caps, "has_centrify": "centrify" in caps}


def _demo_gates() -> Dict[str, Any]:
    """kategori → (is_demo_kind, demo_enabled, demo_capability). Kategori başına bağımsız (karışmaz)."""
    from app.services.backup import demo_gate as bk
    from app.services.hw import demo_gate as hw
    return {
        "backup": (bk.is_demo_kind, bk.demo_enabled, bk.DEMO_CAPABILITY),
        "hardware": (hw.is_demo_kind, hw.demo_enabled, hw.DEMO_CAPABILITY),
    }


def _collect() -> Set[str]:
    out: Set[str] = set()
    try:
        from app.core.database import SessionLocal
        from app.models.integration_instance import IntegrationInstance
        from app.services.integrations.registry import capabilities_for_instance

        db = SessionLocal()
        try:
            rows = (
                db.query(IntegrationInstance)
                .filter(IntegrationInstance.enabled.is_(True))
                .all()
            )
            gates = _demo_gates()

            def _gate(cat: str):
                return gates.get(cat) or (lambda k: str(k or "").endswith("_demo"), lambda: False, f"{cat}_demo")

            # DÜZELTME: "gerçek sağlayıcı var mı" KATEGORİ bazlıdır; Veeam gerçek instance'ı HW demosunu
            # (ve tersi) bastırmaz.
            has_real: Dict[str, bool] = {}
            for r in rows:
                is_demo = _gate(r.category)[0]
                if not is_demo(r.kind):
                    has_real[r.category] = True
            for row in rows:
                is_demo, demo_on, demo_cap = _gate(row.category)
                if is_demo(row.kind):
                    # F.0: DEMO yalnız açık bayrakla ve (aynı kategoride) gerçek sağlayıcı yokken görünür;
                    # gerçek yeteneği ("backup"/"hw") AÇMAZ.
                    if demo_on() and not has_real.get(row.category) and (
                            (row.last_status or "") == "ok" or row.last_sync_at is not None):
                        out.add(demo_cap)
                    continue
                # Hiç başarılı senkron yoksa (yanlış parola vb.) capability açılmaz;
                # daha önce başarılı olmuş instance geçici hatada kaybolmaz — veri bayat işaretlenir.
                if (row.last_status or "") != "ok" and row.last_sync_at is None:
                    continue
                try:
                    out |= set(capabilities_for_instance(row))
                except Exception as e:  # noqa: BLE001
                    logger.debug("capability collect %s: %s", row.kind, e)
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        # Tablo henüz yok / ilk boot — boş küme (entegrasyonsuz davranış).
        logger.debug("capabilities collect skipped: %s", e)
    out |= _menu_integrations()
    return out


def _menu_integrations() -> Set[str]:
    """UC4 / Centrify menüsü yalnız tanımlı bağlantı varken açılır.

    Kayıt yoksa veya modül veritabanına ulaşılamazsa menü gizlenir.
    Entegrasyon kurulum sayfaları (Entegrasyonlar) bu bayrağa bakmaz.
    """
    found: Set[str] = set()
    if _automic_system_defined():
        found.add("automic")
    if _centrify_configured():
        found.add("centrify")
    return found


def _automic_system_defined() -> bool:
    try:
        from sqlalchemy import text
        from app.services.automic.database import get_engine
        with get_engine().connect() as conn:
            return conn.execute(text("SELECT 1 FROM automic_systems LIMIT 1")).first() is not None
    except Exception as exc:  # noqa: BLE001
        logger.debug("automic menü kapalı: %s", exc)
        return False


def _centrify_configured() -> bool:
    try:
        from sqlalchemy import text
        from app.services.centrify.database import get_centrify_thread_session
        db = get_centrify_thread_session()
        if db is None:
            return False
        try:
            row = db.execute(text(
                "SELECT 1 FROM centrify_integration_config WHERE enabled IS TRUE LIMIT 1"
            )).first()
            return row is not None
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("centrify menü kapalı: %s", exc)
        return False
