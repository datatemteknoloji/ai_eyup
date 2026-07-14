"""
Gelişmiş runtime ayarları — timeout / interval / worker.

Öncelik: AppSettings (DB) → ortam değişkeni → varsayılan.
30 sn önbellek; Ayarlar → Gelişmiş üzerinden güncellenir (restart gerekmez).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# key: (default, type, min, max, group, label_tr, help_tr, env_fallback)
# type: "int" | "float" | "bool"
ADVANCED_SCHEMA: Dict[str, dict] = {
    # ── Health checker ──────────────────────────────────────────────
    "health_check_interval_sec": {
        "default": 600, "type": "int", "min": 120, "max": 3600,
        "group": "health", "label": "Health check aralığı (sn)",
        "help": "Tüm sunucuların TCP durum kontrolü sıklığı. WinRM credential yoksa Windows atlanır.",
        "env": "HEALTH_CHECK_INTERVAL_SEC",
    },
    "health_tcp_timeout_sec": {
        "default": 2, "type": "float", "min": 0.5, "max": 15,
        "group": "health", "label": "Health TCP timeout (sn)",
        "help": "Port açık mı kontrolünde socket timeout.",
        "env": "HEALTH_TCP_TIMEOUT_SEC",
    },
    # ── Workers ─────────────────────────────────────────────────────
    "bulk_ssh_workers": {
        "default": 25, "type": "int", "min": 1, "max": 128,
        "group": "workers", "label": "Toplu SSH/WinRM worker",
        "help": "AI Ready, credential apply, OS yenileme paralel bağlantı sayısı. Centrify için 25 önerilir.",
        "env": "BULK_SSH_WORKERS",
    },
    "bulk_tcp_workers": {
        "default": 100, "type": "int", "min": 1, "max": 256,
        "group": "workers", "label": "Toplu TCP health worker",
        "help": "Health checker paralel TCP probe sayısı.",
        "env": "BULK_TCP_WORKERS",
    },
    "vcenter_sync_workers": {
        "default": 10, "type": "int", "min": 1, "max": 64,
        "group": "workers", "label": "vCenter sync worker",
        "help": "VM detay çekme paralelliği.",
        "env": "VCENTER_SYNC_WORKERS",
    },
    # ── SSH ─────────────────────────────────────────────────────────
    "ssh_connect_timeout_sec": {
        "default": 20, "type": "float", "min": 5, "max": 120,
        "group": "ssh", "label": "SSH connect timeout (sn)",
        "help": "TCP + kimlik doğrulama için ana timeout.",
        "env": "SSH_CONNECT_TIMEOUT_SEC",
    },
    "ssh_banner_timeout_sec": {
        "default": 30, "type": "float", "min": 5, "max": 120,
        "group": "ssh", "label": "SSH banner timeout (sn)",
        "help": "sshd/Centrify banner beklerken. /etc/issue yavaş ortamda artırın.",
        "env": "SSH_BANNER_TIMEOUT_SEC",
    },
    "ssh_auth_timeout_sec": {
        "default": 30, "type": "float", "min": 5, "max": 120,
        "group": "ssh", "label": "SSH auth timeout (sn)",
        "help": "keyboard-interactive / password auth için.",
        "env": "SSH_AUTH_TIMEOUT_SEC",
    },
    "ssh_default_cmd_timeout_sec": {
        "default": 15, "type": "int", "min": 5, "max": 600,
        "group": "ssh", "label": "SSH komut timeout (sn)",
        "help": "execute_command varsayılan timeout (info collect, kısa komutlar).",
        "env": "SSH_DEFAULT_CMD_TIMEOUT_SEC",
    },
    # ── WinRM ───────────────────────────────────────────────────────
    "winrm_timeout_sec": {
        "default": 30, "type": "int", "min": 5, "max": 300,
        "group": "winrm", "label": "WinRM işlem timeout (sn)",
        "help": "WinRM komut/oturum timeout.",
        "env": "WINRM_TIMEOUT_SEC",
    },
    # ── Background intervals ────────────────────────────────────────
    "log_collection_interval_sec": {
        "default": 900, "type": "int", "min": 120, "max": 7200,
        "group": "background", "label": "Linux log toplama aralığı (sn)",
        "help": "ONLINE Linux sunuculardan log çekme.",
        "env": "LOG_COLLECTION_INTERVAL_SEC",
    },
    "windows_log_interval_sec": {
        "default": 900, "type": "int", "min": 120, "max": 7200,
        "group": "background", "label": "Windows log toplama aralığı (sn)",
        "help": "WinRM ile event log çekme.",
        "env": "WINDOWS_LOG_INTERVAL_SEC",
    },
    "virt_log_interval_sec": {
        "default": 900, "type": "int", "min": 120, "max": 7200,
        "group": "background", "label": "Sanallaştırma log aralığı (sn)",
        "help": "vCenter/ESX olay senkronu.",
        "env": "VIRT_LOG_INTERVAL_SEC",
    },
    "anomaly_scan_interval_sec": {
        "default": 300, "type": "int", "min": 60, "max": 3600,
        "group": "background", "label": "Anomali tarama aralığı (sn)",
        "help": "Metrik/event anomali analizi.",
        "env": "ANOMALY_SCAN_INTERVAL_SEC",
    },
    "metric_sync_interval_sec": {
        "default": 600, "type": "int", "min": 60, "max": 3600,
        "group": "background", "label": "Metrik sync aralığı (sn)",
        "help": "Prometheus’tan sunucu metriklerini çekme.",
        "env": "METRIC_SYNC_INTERVAL_SEC",
    },
    "inventory_sync_interval_minutes": {
        "default": 5, "type": "int", "min": 1, "max": 120,
        "group": "background", "label": "Envanter sync aralığı (dk)",
        "help": "Harici/UCMDB envanter senkronu (mevcut ayar anahtarı).",
        "env": "INVENTORY_SYNC_INTERVAL_MINUTES",
    },
    "esx_metric_interval_sec": {
        "default": 900, "type": "int", "min": 120, "max": 7200,
        "group": "background", "label": "ESX metrik aralığı (sn)",
        "help": "ESXi host metrik toplama.",
        "env": "ESX_METRIC_INTERVAL_SEC",
    },
    "rag_reindex_interval_sec": {
        "default": 1800, "type": "int", "min": 300, "max": 86400,
        "group": "background", "label": "RAG reindex aralığı (sn)",
        "help": "Bilgi tabanı yeniden indeksleme.",
        "env": "RAG_REINDEX_INTERVAL_SEC",
    },
    "snapshot_cleanup_interval_sec": {
        "default": 3600, "type": "int", "min": 600, "max": 86400,
        "group": "background", "label": "Snapshot temizleme aralığı (sn)",
        "help": "Eski uygulama snapshot kayıtlarını temizleme.",
        "env": "SNAPSHOT_CLEANUP_INTERVAL_SEC",
    },
    "sysupdate_recovery_interval_sec": {
        "default": 300, "type": "int", "min": 60, "max": 3600,
        "group": "background", "label": "Sistem güncelleme recovery (sn)",
        "help": "Takılı/yarıda kalan update job kurtarma.",
        "env": "SYSUPDATE_RECOVERY_INTERVAL_SEC",
    },
    "node_exporter_sync_interval_sec": {
        "default": 600, "type": "int", "min": 60, "max": 3600,
        "group": "background", "label": "Node exporter sync (sn)",
        "help": "Prometheus node-exporter hedef listesi güncelleme.",
        "env": "NODE_EXPORTER_SYNC_INTERVAL_SEC",
    },
    "windows_exporter_sync_interval_sec": {
        "default": 600, "type": "int", "min": 60, "max": 3600,
        "group": "background", "label": "Windows exporter sync (sn)",
        "help": "Prometheus windows-exporter hedef listesi güncelleme.",
        "env": "WINDOWS_EXPORTER_SYNC_INTERVAL_SEC",
    },
    "vm_auto_sync_interval_sec": {
        "default": 7200, "type": "int", "min": 600, "max": 86400,
        "group": "background", "label": "VM auto-sync aralığı (sn)",
        "help": "Hypervisor’dan VM envanter otomatik senkronu.",
        "env": "VM_AUTO_SYNC_INTERVAL_SEC",
    },
    "auto_onboarding_interval_sec": {
        "default": 600, "type": "int", "min": 120, "max": 7200,
        "group": "background", "label": "Auto-onboarding aralığı (sn)",
        "help": "Yeni sunucu keşif / onboarding taraması.",
        "env": "AUTO_ONBOARDING_INTERVAL_SEC",
    },
    "app_discovery_rescan_hours": {
        "default": 12, "type": "int", "min": 1, "max": 168,
        "group": "background", "label": "Uygulama keşif yeniden tarama (saat)",
        "help": "Aynı sunucunun uygulama envanteri bu aralıktan daha sık taranmaz.",
        "env": "APP_DISCOVERY_RESCAN_HOURS",
    },
    # ── Proxy (uygulama notu; nginx restart ile uygulanır) ───────────
    "nginx_proxy_read_timeout_sec": {
        "default": 1800, "type": "int", "min": 60, "max": 7200,
        "group": "proxy", "label": "Nginx API proxy read timeout (sn)",
        "help": "Frontend nginx /api/ proxy_read_timeout. Değişiklik paket rebuild veya nginx conf güncellemesiyle yansır; uzun SSH toplu işler için 1800 önerilir.",
        "env": "NGINX_PROXY_READ_TIMEOUT_SEC",
    },
}

GROUP_LABELS = {
    "health": "Health checker",
    "workers": "Paralellik (worker)",
    "ssh": "SSH timeout",
    "winrm": "WinRM",
    "background": "Arka plan görevleri",
    "proxy": "Proxy / Nginx",
}

_cache: Dict[str, Any] = {}
_cache_ts: float = 0.0
_CACHE_TTL = 15.0
_lock = threading.Lock()


def invalidate_cache() -> None:
    global _cache_ts
    with _lock:
        _cache_ts = 0.0


def _coerce(raw: Any, meta: dict) -> Any:
    t = meta["type"]
    default = meta["default"]
    if raw is None or raw == "":
        return default
    try:
        if t == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "yes", "on")
        if t == "float":
            val = float(raw)
        else:
            val = int(float(raw))
        lo, hi = meta.get("min"), meta.get("max")
        if lo is not None:
            val = max(lo, val)
        if hi is not None:
            val = min(hi, val)
        return val
    except (TypeError, ValueError):
        return default


def _load_db_map() -> Dict[str, str]:
    try:
        from app.core.database import ThreadSessionLocal
        from app.models.app_settings import AppSettings
        db = ThreadSessionLocal()
        try:
            rows = db.query(AppSettings).filter(
                AppSettings.key.in_(list(ADVANCED_SCHEMA.keys()))
            ).all()
            return {r.key: r.value for r in rows if r.value is not None}
        finally:
            db.close()
    except Exception as e:
        logger.debug("runtime_settings DB okunamadı: %s", e)
        return {}


def _refresh_cache() -> None:
    global _cache, _cache_ts
    db_map = _load_db_map()
    fresh: Dict[str, Any] = {}
    for key, meta in ADVANCED_SCHEMA.items():
        if key in db_map:
            fresh[key] = _coerce(db_map[key], meta)
        else:
            env_name = meta.get("env") or ""
            env_val = os.environ.get(env_name, "") if env_name else ""
            if env_val.strip():
                fresh[key] = _coerce(env_val, meta)
            else:
                fresh[key] = meta["default"]
    with _lock:
        _cache = fresh
        _cache_ts = time.monotonic()


def get_setting(key: str) -> Any:
    meta = ADVANCED_SCHEMA.get(key)
    if not meta:
        return None
    with _lock:
        stale = (time.monotonic() - _cache_ts) > _CACHE_TTL
    if stale or not _cache:
        _refresh_cache()
    with _lock:
        return _cache.get(key, meta["default"])


def get_int(key: str) -> int:
    return int(get_setting(key))


def get_float(key: str) -> float:
    return float(get_setting(key))


def list_advanced_settings() -> List[dict]:
    _refresh_cache()
    out = []
    for key, meta in ADVANCED_SCHEMA.items():
        out.append({
            "key": key,
            "value": get_setting(key),
            "default": meta["default"],
            "type": meta["type"],
            "min": meta.get("min"),
            "max": meta.get("max"),
            "group": meta["group"],
            "group_label": GROUP_LABELS.get(meta["group"], meta["group"]),
            "label": meta["label"],
            "help": meta["help"],
            "env": meta.get("env"),
        })
    return out


def save_advanced_settings(updates: Dict[str, Any], db) -> Dict[str, Any]:
    """updates: {key: value}. Geçersiz key atlanır. db = SQLAlchemy Session."""
    from app.models.app_settings import AppSettings

    saved = {}
    for key, raw in (updates or {}).items():
        meta = ADVANCED_SCHEMA.get(key)
        if not meta:
            continue
        val = _coerce(raw, meta)
        stored = str(val).lower() if meta["type"] == "bool" else str(val)
        row = db.query(AppSettings).filter(AppSettings.key == key).first()
        if row:
            row.value = stored
        else:
            db.add(AppSettings(key=key, value=stored))
        saved[key] = val
    db.commit()
    invalidate_cache()
    logger.info("Gelişmiş ayarlar güncellendi: %s", list(saved.keys()))
    return saved
