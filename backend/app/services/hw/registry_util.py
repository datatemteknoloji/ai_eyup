"""Küçük yardımcılar: etkin donanım entegrasyonu var mı (zamanlayıcı + onboarding kapısı)."""
from __future__ import annotations

from app.services.hw.constants import CATEGORY


def has_enabled_hw_instance() -> bool:
    """Senkron DB sorgusu (async yoldan `asyncio.to_thread` ile çağrılmalı). Demo yalnız bayrak açıkken sayılır."""
    from app.core.database import SessionLocal
    from app.models.integration_instance import IntegrationInstance
    from app.services.hw.demo_gate import demo_enabled, is_demo_kind
    db = SessionLocal()
    try:
        rows = (db.query(IntegrationInstance.kind)
                .filter(IntegrationInstance.category == CATEGORY, IntegrationInstance.enabled.is_(True)).all())
        return any((not is_demo_kind(k)) or demo_enabled() for (k,) in rows)
    except Exception:  # noqa: BLE001
        return False
    finally:
        db.close()
