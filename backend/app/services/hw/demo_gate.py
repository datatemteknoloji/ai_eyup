"""Donanım DEMO (fixture) sağlayıcısı için tek kapı — backup/demo_gate ile aynı kurallar.

* Varsayılan KAPALI; yalnız ``HW_DEMO_ENABLED=true`` (dev) açar. Kapalıyken demo satırı etkisizdir.
* DEMO ve gerçek sağlayıcı karışmaz: etkin gerçek donanım sağlayıcısı varsa demo yok sayılır.
* DEMO veri yalnız Donanım ekranında "DEMO VERİ" bandıyla görünür; bulgu/kanıt/rapor/skor üretmez.
"""
from __future__ import annotations

import os
from typing import List, Optional

from app.services.hw.constants import CAP_DEMO, CATEGORY, KIND_DEMO

ENV_FLAG = "HW_DEMO_ENABLED"
DEMO_CAPABILITY = CAP_DEMO
BANNER_TR = "DEMO VERİ — gerçek donanım sağlayıcısı değil"
DISABLED_MSG_TR = ("DEMO donanım sağlayıcısı kapalı. Yalnızca geliştirme ortamında "
                   f"{ENV_FLAG}=true ortam değişkeniyle açılır.")


def demo_enabled() -> bool:
    return os.getenv(ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def is_demo_kind(kind: Optional[str]) -> bool:
    return str(kind or "") == KIND_DEMO


def _enabled_rows(db) -> list:
    from app.models.integration_instance import IntegrationInstance
    return (db.query(IntegrationInstance)
            .filter(IntegrationInstance.category == CATEGORY, IntegrationInstance.enabled.is_(True)).all())


def hw_mode(db) -> str:
    """'real' | 'demo' | 'none' — karışım yok."""
    rows = _enabled_rows(db)
    if any(not is_demo_kind(r.kind) for r in rows):
        return "real"
    if demo_enabled() and any(is_demo_kind(r.kind) for r in rows):
        return "demo"
    return "none"


def active_instances(db, *, include_demo: bool = False) -> List:
    rows = _enabled_rows(db)
    real = [r for r in rows if not is_demo_kind(r.kind)]
    if real:
        return real
    if include_demo and demo_enabled():
        return [r for r in rows if is_demo_kind(r.kind)]
    return []


def demo_active(db) -> bool:
    return hw_mode(db) == "demo"
