"""Üç değerli altyapı durumu: bağlı / kopuk / bilinmiyor.

Tazelik: kaynak DB zamanı (MQSRV max LastUpdate) referans alınır.
Uygulama sunucusu saati yalnızca «bizim senkron eski mi?» için kullanılır.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

STATUS_CONNECTED = "connected"
STATUS_DISCONNECTED = "disconnected"
STATUS_UNKNOWN = "unknown"
STATUS_MISSING = "missing"

MQSRV_TYPE_LABELS = {
    1: "CP",
    2: "WP",
    4: "PWP",
    8: "Agent",
    16: "JWP",
    32: "REST",
    64: "JCP",
}


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def thresholds(settings: Optional[Dict[str, Any]]) -> Dict[str, int]:
    infra = (settings or {}).get("infrastructure") or {}
    return {
        "life_sign_stale_sec": int(infra.get("life_sign_stale_sec") or 300),
        "sync_stale_sec": int(infra.get("sync_stale_sec") or 900),
        "snapshot_interval_min": int(infra.get("snapshot_interval_min") or 5),
    }


def _age_sec(newer: Optional[datetime], older: Optional[datetime]) -> Optional[float]:
    a, b = _aware(newer), _aware(older)
    if a is None or b is None:
        return None
    return (a - b).total_seconds()


def compute_agent_status(
    *,
    host_active: Optional[int],
    last_life_sign: Optional[datetime],
    source_now: Optional[datetime],
    synced_at: Optional[datetime],
    wall_now: Optional[datetime] = None,
    settings: Optional[Dict[str, Any]] = None,
    missing: bool = False,
) -> Tuple[str, str]:
    """(status, rule_code)."""
    if missing:
        return STATUS_MISSING, "missing_from_source"
    thr = thresholds(settings)
    wall = _aware(wall_now) or datetime.now(timezone.utc)
    sync_age = _age_sec(wall, synced_at)
    if sync_age is None or sync_age > thr["sync_stale_sec"]:
        return STATUS_UNKNOWN, "sync_stale"
    if source_now is None:
        return STATUS_UNKNOWN, "no_source_clock"
    life_age = _age_sec(source_now, last_life_sign)
    active = int(host_active) if host_active is not None else None
    if active == 0:
        return STATUS_DISCONNECTED, "host_active_0"
    if life_age is None:
        return STATUS_UNKNOWN, "no_life_sign"
    if life_age > thr["life_sign_stale_sec"]:
        return STATUS_DISCONNECTED, "life_sign_stale_vs_source"
    if active == 1 or active is None:
        return STATUS_CONNECTED, "host_active_and_life_sign_fresh"
    return STATUS_UNKNOWN, "ambiguous"


def compute_engine_status(
    *,
    last_life_sign: Optional[datetime],
    source_now: Optional[datetime],
    synced_at: Optional[datetime],
    wall_now: Optional[datetime] = None,
    settings: Optional[Dict[str, Any]] = None,
    missing: bool = False,
) -> Tuple[str, str]:
    if missing:
        return STATUS_MISSING, "missing_from_source"
    thr = thresholds(settings)
    wall = _aware(wall_now) or datetime.now(timezone.utc)
    sync_age = _age_sec(wall, synced_at)
    if sync_age is None or sync_age > thr["sync_stale_sec"]:
        return STATUS_UNKNOWN, "sync_stale"
    if source_now is None:
        return STATUS_UNKNOWN, "no_source_clock"
    life_age = _age_sec(source_now, last_life_sign)
    if life_age is None:
        return STATUS_UNKNOWN, "no_life_sign"
    if life_age > thr["life_sign_stale_sec"]:
        return STATUS_DISCONNECTED, "life_sign_stale_vs_source"
    return STATUS_CONNECTED, "life_sign_fresh_vs_source"


def status_label_tr(status: str) -> str:
    return {
        STATUS_CONNECTED: "bağlı",
        STATUS_DISCONNECTED: "kopuk",
        STATUS_UNKNOWN: "bilinmiyor",
        STATUS_MISSING: "durdu (kayıt kayboldu)",
    }.get(status, status)


def rule_label_tr(rule: str) -> str:
    return {
        "missing_from_source": "Önceki senkronizde vardı, kaynakta artık yok",
        "sync_stale": "Son başarılı toplamamız eşiği aştı — kesin durum söylenemez",
        "no_source_clock": "Kaynak zaman referansı yok",
        "host_active_0": "HOST_Active = 0",
        "no_life_sign": "MQSRV (Type=8) LastUpdate yok",
        "life_sign_stale_vs_source": "Yaşam sinyali kaynak saatine göre eski",
        "host_active_and_life_sign_fresh": "HOST_Active=1 ve yaşam sinyali taze",
        "life_sign_fresh_vs_source": "Yaşam sinyali kaynak saatine göre taze",
        "ambiguous": "Belirsiz",
    }.get(rule or "", rule or "")


def mqsrv_type_label(type_code: Optional[int]) -> str:
    try:
        return MQSRV_TYPE_LABELS.get(int(type_code), f"TYPE_{type_code}")
    except (TypeError, ValueError):
        return "UNKNOWN"


# Sohbet ve altyapı ekranı AYNI filtre sözlüğünü kullanır: "kopuk" = disconnected (≠ missing/"durdu").
_STATUS_ALIASES = {
    "kopuk": STATUS_DISCONNECTED, "disconnected": STATUS_DISCONNECTED, "down": STATUS_DISCONNECTED,
    "bağlı": STATUS_CONNECTED, "bagli": STATUS_CONNECTED, "connected": STATUS_CONNECTED, "up": STATUS_CONNECTED,
    "bilinmiyor": STATUS_UNKNOWN, "unknown": STATUS_UNKNOWN,
    "durdu": STATUS_MISSING, "kayıp": STATUS_MISSING, "kayip": STATUS_MISSING, "missing": STATUS_MISSING,
}


def normalize_status(value: Optional[str]) -> Optional[str]:
    """Kullanıcı/model değerini kanonik duruma çevirir; boş → None; tanınmayan → olduğu gibi (sonuç boş döner)."""
    v = (value or "").strip().lower()
    if not v:
        return None
    return _STATUS_ALIASES.get(v, v)
