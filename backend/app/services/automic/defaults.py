"""Automic modülü varsayılan ayarları ve doğrulama sınırları.

Kaynak: docs/internal/automic/automic-retention-policy.yaml. Kuruma özgü hiçbir
değer burada yoktur; her şey sistem ayarlarıyla (AutomicSystem.settings) ezilebilir.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Tuple

DEFAULT_SETTINGS: Dict[str, Any] = {
    # LLM konumu: internal (varsayılan) | external — external'da kurulum uyarısı + audit
    "llm_deployment": "internal",
    "collection": {
        "interval_min": 10,             # 5–60
        "windows": [],                  # [{"days":[0..6], "from":"00:00", "to":"23:59"}]; boş = 7×24
        "blackout": [],                 # aynı biçim; toplama yapılmaz
        "max_run_minutes": 10,
        "overlap_min": 15,
        "heavy_window": {"from": "02:00", "to": "05:00"},
        "backfill_days": 0,             # 0 = backfill yok; kaynak geçmişi ve saklama ile sınırlı
        "timezone": "Europe/Istanbul",  # pencerelerin yorumlandığı saat dilimi
        "refresh_hours": 24,            # her turda son N saat AH PK yeniden okuma
        "stale_warn_hours": 6,          # last_success bu süreyi aşarsa kritik uyarı
        "zero_ingest_warn_ticks": 6,    # N tur 0 satır + kaynakta yeni veri → kritik uyarı
        "reconcile_days": 2,            # mutabakat penceresi (gün)
        "reconcile_diff_pct": 1.0,      # kaynak↔modül fark eşiği (%)
        # Adım bütçeleri: toplam max_run_minutes içindeki pay (toplam ≤ 1). Aşan adım kesilir, imleçten devam eder.
        "step_budget_pct": {
            "ingest": 0.30, "active": 0.04, "reports": 0.22, "refresh": 0.12, "users": 0.03, "infra": 0.04,
            "gap": 0.02, "jpp": 0.05, "script": 0.05, "reconcile": 0.04, "backfill": 0.05, "resync": 0.04,
        },
        "refresh_ids_per_run": 400,     # durum güncelleme: tur başına en fazla RunID (açık liste, PK sorgusu)
        "refresh_chunk": 50,            # PK sorgu parçası
        "refresh_recent_min": 30,       # son N dk'da biten çalışmalar da yeniden okunur (geç gelen güncellemeler)
    },
    "source_guard": {
        "max_sessions": 2,
        "call_timeout_sec": 30,         # varsayılan sorgu zaman aşımı (sn)
        "collector_timeout_sec": 60,    # toplayıcı (ayrı)
        "chat_timeout_sec": 30,         # sohbet / canlı sorgu
        "slice_minutes": 15,
        "max_rows_per_slice": 500,      # temkinli varsayılan (plan kontrolü öncesi)
        "arraysize": 500,
        "chat_max_rows": 200,
        "circuit_failures": 3,
        "circuit_open_sec": 300,
        "role_check_interval_min": 15,  # V$DATABASE rol kontrolü (bilgilendirme)
        "runid_slack_hours": 24,        # zaman→RunID: alt sınır payı (aktivasyon vs bitiş)
        "cautious_mode": True,          # plan kontrolü yapılana kadar küçük parçalar
        "slow_query_sec": 10,           # aşarsa şablon durdurulur + yönetici uyarısı
        "disabled_templates": [],       # yavaş/ riskli şablonlar (otomatik dolar)
        "default_fetch_limit": 500,     # FETCH FIRST üst sınırı (render)
        "backfill_chunk_rows": 500,     # AH_Idnr parça boyutu (temkinli)
        "backfill_chunk_rows_normal": 5000,
        "backfill_pause_sec": 2,        # parçalar arası bekleme
        "report_head_lines": 50,
        "report_tail_lines": 200,
        "report_max_fetch": 500,        # RT satır üst sınırı
        "jpp_sync_enabled": True,       # JPP → modül DB (ağır pencere)
        "jpp_chunk_rows": 500,          # OH_Idnr parça (temkinli = backfill_chunk ile aynı ölçek)
        "script_sync_enabled": True,    # OT script → modül DB (OH değişenler, ağır pencere)
        "script_chunk_objects": 20,     # tur başına en fazla nesne script'i
        "user_sync_enabled": True,      # OH USER → automic_users (USR okunmaz)
        "user_chunk_rows": 2000,        # OH_Idnr parça boyutu
        "user_id_mismatch_warn_ratio": 0.05,  # AH_USR_Idnr↔OH eşleşmeme uyarı eşiği
        # Canlı okuma (collector dışı) — merkezi politika
        "live_read_mode": "off",        # off | windows_only | always
        "live_budget_per_min": 10,      # tüm kullanıcılar toplamı / dk
        "live_budget_per_user_per_min": 3,
        "infra_sync_enabled": True,     # HOST/MQSRV/OHG küçük tablo senkronu
        "small_table_row_threshold": 10000,
    },
    "infrastructure": {
        "life_sign_stale_sec": 300,      # kaynak saatine göre yaşam sinyali eşiği
        "sync_stale_sec": 900,           # bizim son senkron eşiği (duvar saati)
        "snapshot_interval_min": 5,      # durum snapshot aralığı
        "reverse_dns_enabled": False,   # ters DNS varsayılan kapalı
        "detail_days": 90,
        "daily_summary_days": 730,
    },
    "retention": {
        "executions_days": 90,
        "compress_after_days": 7,
        "failed_report_excerpts_days": 90,
        "report_cache_hours": 24,
        "failed_index_days": 365,
        "daily_aggregates_days": 730,
        "object_script_versions": 10,
        "object_script_version_days": 90,
        "object_headers_deleted_days": 90,
        "conversations_days": 90,
        "audit_days": 90,
    },
    "excerpt": {
        "head_lines": 50,
        "tail_lines": 200,
        "context_lines": 5,
        "max_kb": 64,
        "max_reports_per_execution": 3,
        "patterns": ["ERROR", "ERR", "FATAL", "Exception", "ORA-", "return code",
                     "Permission denied", "No such file", "No space left", "timeout"],
        "report_types": [],             # boş = keşiften
        "max_attempts": 5,              # geçici hata: bu kadar denemeden sonra "rapor alınamadı" (bir daha denenmez)
        "retry_backoff_min": 10,        # deneme n sonrası bekleme = min(360, bu × 2^(n-1)) dk
        "queue_batch": 600,             # tur başına kuyruktan en fazla çalışma
    },
    "storage": {
        "quota_gb": 100,
        "disk_overhead_factor": 1.5,
        "warn_pct": 70,
        "prune_pct": 85,
        "critical_pct": 95,
    },
    "status_classes": {
        "failed": {"ranges": [[1800, 1899]], "exclude": [1850, 1851]},
        "cancelled": {"codes": [1850, 1851]},
        "ok": {"ranges": [[1900, 1999]]},
    },
    "masking": {
        "country_pack": "tr",
        # Varsayılan: IP ve hostname gösterilir; gizli kimlik bilgileri her zaman maskelenir
        "mask_ip": False,
        "mask_hostname": False,
        "custom_patterns": [],          # [{"name": "...", "regex": "..."}]
    },
    "projection": {
        "daily_exec": 0,
        "failure_rate": 0.01,
        "active_objects_daily": 0,
        "compression_ratio": 8,
        "avg_excerpt_kb": 15,
        "index_overhead_factor": 1.4,
    },
    "awi_url": "",
    "ae_version": "24.4",              # elle; otomatik kaynak okuma yok
}

# (yol, min, max) — kurulum sihirbazı ve PUT doğrulaması
LIMITS: List[Tuple[str, float, float]] = [
    ("collection.interval_min", 5, 60),
    ("collection.max_run_minutes", 1, 55),
    ("collection.overlap_min", 0, 120),
    ("collection.backfill_days", 0, 90),
    ("collection.refresh_hours", 1, 168),
    ("collection.stale_warn_hours", 1, 168),
    ("collection.zero_ingest_warn_ticks", 2, 48),
    ("collection.reconcile_days", 1, 14),
    ("collection.reconcile_diff_pct", 0.1, 50),
    ("source_guard.max_sessions", 1, 4),
    ("source_guard.call_timeout_sec", 5, 600),
    ("source_guard.collector_timeout_sec", 5, 600),
    ("source_guard.chat_timeout_sec", 5, 120),
    ("source_guard.role_check_interval_min", 5, 1440),
    ("source_guard.slice_minutes", 1, 240),
    ("source_guard.max_rows_per_slice", 100, 500000),
    ("source_guard.arraysize", 50, 50000),
    ("source_guard.chat_max_rows", 10, 5000),
    ("source_guard.runid_slack_hours", 1, 168),
    ("source_guard.slow_query_sec", 2, 600),
    ("source_guard.default_fetch_limit", 50, 50000),
    ("source_guard.backfill_chunk_rows", 50, 50000),
    ("source_guard.backfill_chunk_rows_normal", 100, 100000),
    ("source_guard.backfill_pause_sec", 0, 120),
    ("source_guard.report_max_fetch", 50, 5000),
    ("source_guard.jpp_chunk_rows", 50, 50000),
    ("source_guard.script_chunk_objects", 1, 200),
    ("source_guard.user_chunk_rows", 50, 50000),
    ("source_guard.user_id_mismatch_warn_ratio", 0.01, 1.0),
    ("source_guard.live_budget_per_min", 1, 120),
    ("source_guard.live_budget_per_user_per_min", 1, 60),
    ("source_guard.small_table_row_threshold", 100, 500000),
    ("infrastructure.life_sign_stale_sec", 60, 86400),
    ("infrastructure.sync_stale_sec", 60, 86400),
    ("infrastructure.snapshot_interval_min", 1, 60),
    ("retention.executions_days", 30, 90),
    ("retention.failed_report_excerpts_days", 14, 90),
    ("retention.report_cache_hours", 0, 72),
    ("retention.failed_index_days", 90, 730),
    ("retention.daily_aggregates_days", 90, 1825),
    ("retention.conversations_days", 7, 90),
    ("retention.audit_days", 30, 365),
    ("storage.quota_gb", 10, 2000),
]


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def effective_settings(stored: Dict[str, Any] | None) -> Dict[str, Any]:
    return _deep_merge(DEFAULT_SETTINGS, stored or {})


def _get(d: Dict[str, Any], path: str):
    cur: Any = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def validate_settings(settings: Dict[str, Any]) -> List[str]:
    """Sınır dışı değerler için Türkçe hata listesi döner (boş = geçerli)."""
    errors: List[str] = []
    merged = effective_settings(settings)
    for path, lo, hi in LIMITS:
        v = _get(merged, path)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            errors.append(f"{path}: sayı olmalı")
            continue
        if fv < lo or fv > hi:
            errors.append(f"{path}: {lo:g}–{hi:g} aralığında olmalı (verilen {v})")
    mode = str((_get(merged, "source_guard.live_read_mode") or "off")).strip().lower()
    if mode not in ("off", "windows_only", "always"):
        errors.append("source_guard.live_read_mode: off | windows_only | always olmalı")
    llm_dep = str((_get(merged, "llm_deployment") or "internal")).strip().lower()
    if llm_dep not in ("internal", "external"):
        errors.append("llm_deployment: internal | external olmalı")
    return errors
