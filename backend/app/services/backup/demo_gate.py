"""DEMO (fixture) yedek sağlayıcısı için tek kapı — F.0.

Kurallar (hepsi bu modülden geçer; dağınık ``kind.endswith("_demo")`` kontrolü yok):

1. DEMO varsayılan KAPALI. Yalnız ``BACKUP_DEMO_ENABLED=true`` ortam değişkeni (dev) açar.
   Kapalıyken veritabanındaki demo instance satırı durur ama **etkisizdir**: capability
   üretmez, senkronlanmaz, bulgu/kanıt/rapor/skor üretmez, yeniden etkinleştirilemez.
2. DEMO ve gerçek sağlayıcı **asla karışmaz**: etkin gerçek (demo olmayan) instance varsa demo
   yok sayılır. Böylece demo VM'leri gerçek koruma/RPO hesabına sızamaz.
3. DEMO etkinken veri yalnız Yedekleme ekranında (üstte "DEMO VERİ" bandıyla) görünür; bulguları
   ``platform="backup_demo"`` altında saklanır ve varsayılan bulgu sorguları/özetleri bunu dışlar →
   ISO A.8.13 kanıtı, denetim dışa aktarımları, raporlar ve panel skorlarına girmez.
"""
from __future__ import annotations

import os
from typing import List, Optional

ENV_FLAG = "BACKUP_DEMO_ENABLED"
DEMO_KIND_SUFFIX = "_demo"
from app.services.findings.registry import PLATFORM_BACKUP_DEMO as DEMO_PLATFORM  # noqa: E402  (varsayılan bulgu sorgularından dışlanır)
DEMO_CAPABILITY = "backup_demo"    # "backup" yeteneğini AÇMAZ; yalnız Yedekleme ekranını görünür kılar

BANNER_TR = "DEMO VERİ — gerçek Veeam değil"
DISABLED_MSG_TR = ("DEMO yedek sağlayıcısı kapalı. Yalnızca geliştirme ortamında "
                   f"{ENV_FLAG}=true ortam değişkeniyle açılır.")


def demo_enabled() -> bool:
    """Ortam bayrağı (her çağrıda okunur; test ve yeniden başlatma için)."""
    return os.getenv(ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def is_demo_kind(kind: Optional[str]) -> bool:
    return str(kind or "").endswith(DEMO_KIND_SUFFIX)


def _enabled_backup_rows(db) -> list:
    from app.models.integration_instance import IntegrationInstance
    return (db.query(IntegrationInstance)
            .filter(IntegrationInstance.category == "backup", IntegrationInstance.enabled.is_(True)).all())


def backup_mode(db) -> str:
    """'real' | 'demo' | 'none' — karışım yok."""
    rows = _enabled_backup_rows(db)
    if any(not is_demo_kind(r.kind) for r in rows):
        return "real"
    if demo_enabled() and any(is_demo_kind(r.kind) for r in rows):
        return "demo"
    return "none"


def active_instances(db, *, include_demo: bool = False) -> List:
    """Etkin yedek instance'ları. Varsayılan: yalnız gerçek sağlayıcılar.

    ``include_demo=True`` yalnız Yedekleme ekranı / bulgu üreticisi içindir; demo satırları bayrak
    açık ve gerçek sağlayıcı yokken döner.
    """
    rows = _enabled_backup_rows(db)
    real = [r for r in rows if not is_demo_kind(r.kind)]
    if real:
        return real
    if include_demo and demo_enabled():
        return [r for r in rows if is_demo_kind(r.kind)]
    return []


# F.0 kararı: demo modunda bu iki sohbet aracı AÇIK; çıktıları ve kaynak satırı "DEMO veri" etiketi taşır.
DEMO_VISIBLE_TOOLS = frozenset({"virt_backup_status", "virt_rpo_compliance"})
DEMO_LABEL_TR = "DEMO veri"
DEMO_TOOL_NOTE_TR = ("DEMO VERİ — gerçek Veeam değil (fixture). Yanıtında bunu açıkça 'DEMO veri' olarak belirt; "
                     "gerçek durummuş gibi sunma.")


def demo_tools_active() -> bool:
    """Yalnız bayrak açık + demo görünür + gerçek sağlayıcı yok iken True (capability registry'den)."""
    try:
        from app.services.capabilities import get_capabilities
        caps = get_capabilities()
    except Exception:  # noqa: BLE001
        return False
    return DEMO_CAPABILITY in caps and "backup" not in caps and demo_enabled()


def tool_is_demo(name: str) -> bool:
    return name in DEMO_VISIBLE_TOOLS and demo_tools_active()


def demo_active(db) -> bool:
    return backup_mode(db) == "demo"
