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
        "help": "AI Ready, credential apply, OS yenileme paralel bağlantı sayısı. Centrify için 25; ~7k filoda 16–32 deneyin.",
        "env": "BULK_SSH_WORKERS",
    },
    "log_ssh_workers": {
        "default": 32, "type": "int", "min": 1, "max": 64,
        "group": "workers", "label": "Log tarama SSH worker",
        "help": "Linux journalctl log toplama paralelliği. 15k+ ortamda 24–40 önerilir; çok yüksek LoginGraceTime / MaxStartups baskısı yaratır.",
        "env": "LOG_SSH_WORKERS",
    },
    "bulk_tcp_workers": {
        "default": 100, "type": "int", "min": 1, "max": 256,
        "group": "workers", "label": "Toplu TCP health worker",
        "help": "Health checker paralel TCP probe sayısı. Büyük filoda 64–128 yeterli.",
        "env": "BULK_TCP_WORKERS",
    },
    "vcenter_sync_workers": {
        "default": 10, "type": "int", "min": 1, "max": 64,
        "group": "workers", "label": "vCenter sync worker",
        "help": "VM detay çekme paralelliği. ~7k VM için 8–16 makul; vCenter’ı boğmayın.",
        "env": "VCENTER_SYNC_WORKERS",
    },
    "celery_concurrency": {
        "default": 2, "type": "int", "min": 1, "max": 32,
        "group": "process", "label": "Celery concurrency",
        "help": "Filo arka plan kuyruğu (onboarding, metric, log…) paralelliği. Kaynak artınca 4–8 deneyin. Uygulamak için worker container recreate gerekir.",
        "env": "CELERY_CONCURRENCY",
        "requires_restart": True,
        "restart_target": "worker",
    },
    "uvicorn_workers": {
        "default": 2, "type": "int", "min": 1, "max": 8,
        "group": "process", "label": "Uvicorn workers (API)",
        "help": "HTTP API process sayısı. RAG pgvector ile 2+ worker güvenlidir. Celery paralelliği ayrı ayardır. Uygulamak için backend recreate gerekir.",
        "env": "UVICORN_WORKERS",
        "requires_restart": True,
        "restart_target": "backend",
    },
    "chat_ai_max_concurrent": {
        "default": 3, "type": "int", "min": 1, "max": 8,
        "group": "process", "label": "Eşzamanlı AI üretimi",
        "help": "Aynı anda en fazla kaç LLM çağrısı. Fazlası FIFO kuyruğa alınır; sohbette sıra gösterilir.",
        "env": "CHAT_AI_MAX_CONCURRENT",
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
    "log_ssh_connect_timeout_sec": {
        "default": 12, "type": "float", "min": 3, "max": 60,
        "group": "ssh", "label": "Log tarama SSH connect timeout (sn)",
        "help": "Journalctl toplama için kısa connect; yavaş host'u çabuk atlar (15k ölçek).",
        "env": "LOG_SSH_CONNECT_TIMEOUT_SEC",
    },
    "log_ssh_cmd_timeout_sec": {
        "default": 25, "type": "int", "min": 5, "max": 120,
        "group": "ssh", "label": "Log tarama komut timeout (sn)",
        "help": "journalctl/syslog komutu için timeout.",
        "env": "LOG_SSH_CMD_TIMEOUT_SEC",
    },
    "ssh_connect_retries": {
        "default": 1, "type": "int", "min": 1, "max": 3,
        "group": "ssh", "label": "SSH bağlanma denemesi",
        "help": "Başarısız bağlantıda kaç kez denensin. Log taraması ve toplu işlerde 1 önerilir (tekrar deneme yok).",
        "env": "SSH_CONNECT_RETRIES",
    },
    "ssh_auth_prefer": {
        "default": "auto", "type": "str", "min": 0, "max": 16,
        "group": "ssh", "label": "SSH auth tercihi",
        "help": "auto = Centrify/PAM (KI→password, birden fazla TCP). password = tek TCP (client sshd'de Timeout before authentication gürültüsünü azaltır). Log taraması her zaman password kullanır.",
        "env": "SSH_AUTH_PREFER",
        "choices": ["auto", "password"],
    },
    # ── Log / Events ────────────────────────────────────────────────
    "log_journal_priority": {
        "default": 4, "type": "int", "min": 0, "max": 7,
        "group": "logs", "label": "journalctl öncelik eşiği (-p)",
        "help": "0=emerg … 3=err, 4=warning, 5=notice, 6=info, 7=debug. Seçilen seviye VE daha kritikleri toplanır (örn. 4 → warning+error+crit).",
        "env": "LOG_JOURNAL_PRIORITY",
    },
    "log_scan_ai_ready_only": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "logs", "label": "Log taraması yalnız AI Ready",
        "help": "Şimdi Tara / periyodik Linux log taraması yalnızca AI Ready sunucularda SSH açar.",
        "env": "LOG_SCAN_AI_READY_ONLY",
    },
    "log_source_mode": {
        "default": "auto", "type": "str", "min": 0, "max": 16,
        "group": "logs", "label": "SSH log kaynağı",
        "help": "auto = önce journalctl, boşsa syslog dosyası. journal = yalnız journalctl. syslog = yalnız /var/log/syslog|messages|secure (SSH ile).",
        "env": "LOG_SOURCE_MODE",
        "choices": ["auto", "journal", "syslog"],
    },
    "syslog_receiver_enabled": {
        "default": False, "type": "bool", "min": 0, "max": 1,
        "group": "logs", "label": "Syslog alıcı (UDP)",
        "help": "Açıkken sunucular rsyslog/syslog-ng ile ainew'e UDP syslog gönderebilir (15k+ için SSH çekmeye alternatif). Hostname/IP eşleşen Server'a event yazar.",
        "env": "SYSLOG_RECEIVER_ENABLED",
    },
    "syslog_receiver_port": {
        "default": 5514, "type": "int", "min": 1024, "max": 65535,
        "group": "logs", "label": "Syslog alıcı UDP port",
        "help": "Varsayılan 5514 (root gerektirmez). Docker'da port yayınlanmalı. Klasik 514 için host'ta iptables/redirect veya root container gerekir.",
        "env": "SYSLOG_RECEIVER_PORT",
    },
    "syslog_receiver_min_severity": {
        "default": 4, "type": "int", "min": 0, "max": 7,
        "group": "logs", "label": "Syslog alıcı min öncelik",
        "help": "0=emerg … 4=warning. Bu seviye ve daha kritikleri kaydeder (RFC3164 facility.severity).",
        "env": "SYSLOG_RECEIVER_MIN_SEVERITY",
    },
    "log_collection_batch_size": {
        "default": 500, "type": "int", "min": 50, "max": 5000,
        "group": "logs", "label": "Log tarama batch boyutu",
        "help": "Periyodik turda en fazla N sunucu (round-robin). 15k host'ta 400–800 önerilir; Şimdi Tara tüm AI Ready'i worker ile tarar.",
        "env": "LOG_COLLECTION_BATCH_SIZE",
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
        "default": 300, "type": "int", "min": 60, "max": 7200,
        "group": "background", "label": "Linux log toplama aralığı (sn)",
        "help": "Bir sonraki batch turu. 15k ortamda 300sn + batch 500 ≈ ~2.5 saatte tüm filoyu döner.",
        "env": "LOG_COLLECTION_INTERVAL_SEC",
    },
    "windows_log_interval_sec": {
        "default": 900, "type": "int", "min": 120, "max": 7200,
        "group": "background", "label": "Windows log toplama aralığı (sn)",
        "help": "WinRM ile event log çekme.",
        "env": "WINDOWS_LOG_INTERVAL_SEC",
    },
    "windows_log_workers": {
        "default": 20, "type": "int", "min": 1, "max": 64,
        "group": "workers", "label": "Windows log tarama WinRM worker",
        "help": "Windows Event Log (System/Application) toplama paralelliği. 10k+ ortamda batch boyutuyla birlikte artırın.",
        "env": "WINDOWS_LOG_WORKERS",
    },
    "windows_log_batch_size": {
        "default": 500, "type": "int", "min": 50, "max": 5000,
        "group": "logs", "label": "Windows log tarama batch boyutu",
        "help": "Periyodik turda en fazla N Windows sunucu (round-robin). Linux log batch ile aynı mantık.",
        "env": "WINDOWS_LOG_BATCH_SIZE",
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
        "default": 30, "type": "int", "min": 1, "max": 120,
        "group": "background", "label": "Envanter sync aralığı (dk)",
        "help": "Hypervisor VM envanteri + opsiyonel uCMDB senkron aralığı (full sync).",
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
    "event_cleanup_interval_sec": {
        "default": 21600, "type": "int", "min": 3600, "max": 86400,
        "group": "background", "label": "Eski event temizleme aralığı (sn)",
        "help": "system_events tablosunda otomatik retention (varsayılan 6 saatte bir).",
        "env": "EVENT_CLEANUP_INTERVAL_SEC",
    },
    "event_retention_days": {
        "default": 180, "type": "int", "min": 30, "max": 3650,
        "group": "background", "label": "Event saklama süresi (gün)",
        "help": "Bu süreden eski system_events kayıtları otomatik silinir (tablo sınırsız büyümesin).",
        "env": "EVENT_RETENTION_DAYS",
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
        "help": "Yeni sunucu keşif / onboarding taraması (AI Ready, exporter vb. döngü).",
        "env": "AUTO_ONBOARDING_INTERVAL_SEC",
    },
    # ── AI Ready throttle ───────────────────────────────────────────
    "ai_ready_ready_recheck_sec": {
        "default": 3600, "type": "int", "min": 300, "max": 86400,
        "group": "ai_ready", "label": "AI Ready sunucu yeniden kontrol (sn)",
        "help": "Zaten AI Ready olan sunucular arka planda bu aralıktan daha sık SSH/WinRM ile denenmez. Manuel ‘AI Ready Güncelle’ tümünü test eder.",
        "env": "AI_READY_READY_RECHECK_SEC",
    },
    "ai_ready_not_ready_recheck_sec": {
        "default": 86400, "type": "int", "min": 3600, "max": 604800,
        "group": "ai_ready", "label": "AI Ready olmayan yeniden kontrol (sn)",
        "help": "AI Ready olmayan (SSH/WinRM başarısız) sunucular varsayılan 1 günde bir denenir — sürekli SSH gürültüsünü keser.",
        "env": "AI_READY_NOT_READY_RECHECK_SEC",
    },
    "ai_ready_auth_fail_backoff_sec": {
        "default": 259200, "type": "int", "min": 3600, "max": 604800,
        "group": "ai_ready", "label": "AI Ready auth fail backoff (sn)",
        "help": "SSH/WinRM AI Ready başarısız olunca arka plan (throttle) bu süre boyunca o host'a tekrar denemez. Manuel ‘AI Ready Güncelle’ backoff'u yok sayar. Varsayılan 72 saat — hesap kilitleme riskini azaltır.",
        "env": "AI_READY_AUTH_FAIL_BACKOFF_SEC",
    },
    "app_discovery_rescan_hours": {
        "default": 12, "type": "int", "min": 1, "max": 168,
        "group": "background", "label": "Uygulama keşif yeniden tarama (saat)",
        "help": "Aynı sunucunun uygulama envanteri bu aralıktan daha sık taranmaz.",
        "env": "APP_DISCOVERY_RESCAN_HOURS",
    },
    # ── NLQ / Linux envanter snapshot ───────────────────────────────
    "nlq_collector_interval_sec": {
        "default": 900, "type": "int", "min": 120, "max": 7200,
        "group": "nlq", "label": "NLQ snapshot tur aralığı (sn)",
        "help": "Arka plan Linux NL envanter snapshot collector döngü sıklığı.",
        "env": "NLQ_COLLECTOR_INTERVAL_SEC",
    },
    "nlq_collector_workers": {
        "default": 50, "type": "int", "min": 1, "max": 100,
        "group": "nlq", "label": "NLQ snapshot worker sayısı",
        "help": "Eşzamanlı SSH toplama üst sınırı (max 100).",
        "env": "NLQ_COLLECTOR_WORKERS",
    },
    "nlq_success_recheck_sec": {
        "default": 900, "type": "int", "min": 120, "max": 86400,
        "group": "nlq", "label": "Başarılı snapshot yenileme (sn)",
        "help": "collection_status=success olan sunucu bu süre dolmadan tekrar SSH ile toplanmaz.",
        "env": "NLQ_SUCCESS_RECHECK_SEC",
    },
    "nlq_failed_recheck_sec": {
        "default": 86400, "type": "int", "min": 3600, "max": 604800,
        "group": "nlq", "label": "Başarısız snapshot yeniden deneme (sn)",
        "help": "failed/unreachable snapshot’lar varsayılan 1 günde bir yeniden denenir.",
        "env": "NLQ_FAILED_RECHECK_SEC",
    },
    "nlq_metric_enrich_enabled": {
        "default": True, "type": "bool",
        "group": "nlq", "label": "metric_data ile snapshot zenginleştir",
        "help": "Açıksa collector Prometheus/metric_data değerlerini (CPU detay, swap, disk IO, ağ) envanter satırına yazar.",
        "env": "NLQ_METRIC_ENRICH_ENABLED",
    },
    "nlq_metric_max_age_min": {
        "default": 30, "type": "int", "min": 5, "max": 360,
        "group": "nlq", "label": "metric_data max yaşı (dk)",
        "help": "Bu dakikadan eski metric_data satırları enrich için kullanılmaz.",
        "env": "NLQ_METRIC_MAX_AGE_MIN",
    },
    "nlq_prefer_metric_over_ssh": {
        "default": True, "type": "bool",
        "group": "nlq", "label": "CPU/RAM/disk için metric_data öncelikli",
        "help": "Açıksa Prom/metric_data değerleri SSH df/mem bilgi üzerine yazar. Kapalıysa yalnızca boş alanlar doldurulur.",
        "env": "NLQ_PREFER_METRIC_OVER_SSH",
    },
    # ── Unified Chat (agentic tool-calling) ──────────────────────────
    "unified_chat_agentic_mode": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "unified_chat", "label": "Unified Chat agentic mod",
        "help": "Açıkken varsayılan yol agentic-first'tir (sabit collect ile XOR). "
                "Derin analiz veya chat_force_collect_and_agentic ikisini birlikte açar. "
                "Kapalıysa yalnızca sabit Linux/Windows collect.",
        "env": "UNIFIED_CHAT_AGENTIC_MODE",
    },
    "unified_chat_max_tool_steps": {
        "default": 4, "type": "int", "min": 1, "max": 12,
        "group": "unified_chat", "label": "Unified Chat maks. araç adımı",
        "help": "Agentic modda bir yanıt üretilmeden önce art arda çağrılabilecek en fazla "
                "araç (tool) sayısı. Dalga 2 varsayılanı 4 (TTFT).",
        "env": "UNIFIED_CHAT_MAX_TOOL_STEPS",
    },
    "unified_chat_planning_max_tool_steps": {
        "default": 2, "type": "int", "min": 1, "max": 6,
        "group": "unified_chat", "label": "Migrasyon/planlama maks. araç adımı",
        "help": "vCenter↔OpenShift taşıma / kapasite / kaynak planı sorularında agentic "
                "üst sınırı (daha düşük = daha hızlı TTFT). Başarılı 1–2 tool sonrası "
                "döngü erken biter.",
        "env": "UNIFIED_CHAT_PLANNING_MAX_TOOL_STEPS",
    },
    "chat_model_fast": {
        "default": "", "type": "str", "min": 0, "max": 128,
        "group": "unified_chat", "label": "Hızlı model (knowledge / simple)",
        "help": "Unified'da knowledge veya simple karmaşıklıkta kullanılır. Boşsa "
                "kullanıcı/aktif model (regresyonsuz). Örn. llama3.2:3b, mistral:latest.",
        "env": "CHAT_MODEL_FAST",
    },
    "chat_model_strong": {
        "default": "", "type": "str", "min": 0, "max": 128,
        "group": "unified_chat", "label": "Güçlü model (live / planning)",
        "help": "Unified live/planning yolunda, kullanıcı model seçmediyse kullanılır. "
                "Boşsa request.model veya sistem aktif modeli.",
        "env": "CHAT_MODEL_STRONG",
    },
    # ── Linux Chat (agentic tool-calling) ────────────────────────────
    "linux_chat_agentic_mode": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "linux_chat", "label": "Linux Chat agentic mod",
        "help": "Açıkken varsayılan yol agentic-first'tir (sabit SSH collect ile XOR — "
                "ikisi birden yalnızca derin analiz veya chat_force_collect_and_agentic). "
                "Kapalıysa yalnızca sabit collect kullanılır.",
        "env": "LINUX_CHAT_AGENTIC_MODE",
    },
    "linux_chat_max_tool_steps": {
        "default": 4, "type": "int", "min": 1, "max": 12,
        "group": "linux_chat", "label": "Linux Chat maks. araç adımı",
        "help": "Agentic modda bir yanıt üretilmeden önce art arda çağrılabilecek en fazla "
                "araç (tool) sayısı. Dalga 2 varsayılanı 4 (TTFT).",
        "env": "LINUX_CHAT_MAX_TOOL_STEPS",
    },
    "chat_ssh_fleet_cap": {
        "default": 64, "type": "int", "min": 1, "max": 512,
        "group": "linux_chat", "label": "Chat filo canlı tarama üst sınırı",
        "help": "Linux/Windows/Unified sohbette eşzamanlı SSH/WinRM hedef üst sınırı. "
                "Seçim yokken varsayılan olarak filo taranmaz; 'tüm sunucular / filo / bütün liste' "
                "denirse bu cap kadar örneklem alınır. Cap aşılırsa onay istenir; onayda "
                "yalnızca o soru için chat_fleet_hard_max uygulanır.",
        "env": "CHAT_SSH_FLEET_CAP",
    },
    "chat_fleet_hard_max": {
        "default": 5000, "type": "int", "min": 50, "max": 20000,
        "group": "linux_chat", "label": "Chat onaylı tam filo tavanı",
        "help": "Kullanıcı “tüm filo / tüm sunucular / bütün liste” için onay verdiğinde "
                "yalnızca o soruya uygulanan üst sınır. Cevap bitince varsayılan cap’e dönülür.",
        "env": "CHAT_FLEET_HARD_MAX",
    },
    "chat_force_collect_and_agentic": {
        "default": False, "type": "bool", "min": 0, "max": 1,
        "group": "linux_chat", "label": "Collect + agentic birlikte (ağır yol)",
        "help": "Açıksa Dalga 2 XOR iptal: sabit collect ve agentic aynı turda çalışır. "
                "Derin analiz kelimeleri (vmstat/iostat/derin analiz) zaten ikisini açar.",
        "env": "CHAT_FORCE_COLLECT_AND_AGENTIC",
    },
    # ── Windows Chat (agentic tool-calling) ──────────────────────────
    "windows_chat_agentic_mode": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "windows_chat", "label": "Windows Chat agentic mod",
        "help": "Açıkken varsayılan yol agentic-first (WinRM collect ile XOR). "
                "Kapalıysa yalnızca sabit WinRM collect.",
        "env": "WINDOWS_CHAT_AGENTIC_MODE",
    },
    "windows_chat_max_tool_steps": {
        "default": 4, "type": "int", "min": 1, "max": 12,
        "group": "windows_chat", "label": "Windows Chat maks. araç adımı",
        "help": "Agentic modda bir yanıt üretilmeden önce art arda çağrılabilecek en fazla "
                "araç sayısı. Dalga 2 varsayılanı 4 (TTFT).",
        "env": "WINDOWS_CHAT_MAX_TOOL_STEPS",
    },
    # ── Virt Chat (agentic live tools beside hypervisor_intelligence) ─
    "virt_chat_agentic_mode": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "virt_chat", "label": "Sanallaştırma Chat agentic mod",
        "help": "Açıkken kapasite/storage/HA/alarm vb. sorularda vCenter READ_ONLY araçları "
                "önce çalışır; 'bilinmiyor' yerine canlı veri çekilir.",
        "env": "VIRT_CHAT_AGENTIC_MODE",
    },
    "virt_chat_max_tool_steps": {
        "default": 4, "type": "int", "min": 1, "max": 8,
        "group": "virt_chat", "label": "Sanallaştırma Chat maks. araç adımı",
        "help": "Agentic sanallaştırma sohbetinde bir yanıt üretilmeden önce art arda "
                "çağrılabilecek en fazla vCenter READ_ONLY araç sayısı.",
        "env": "VIRT_CHAT_MAX_TOOL_STEPS",
    },
    "virt_chat_vm_list_limit": {
        "default": 50, "type": "int", "min": 10, "max": 2000,
        "group": "virt_chat", "label": "Virt chat varsayılan VM liste limiti",
        "help": "Sohbet bağlamında ve özet listelerde gösterilecek varsayılan VM sayısı. "
                "“Tüm VM’ler” + onay ile yalnızca o soruda hard max’e çıkılır.",
        "env": "VIRT_CHAT_VM_LIST_LIMIT",
    },
    "virt_chat_vm_list_hard_max": {
        "default": 5000, "type": "int", "min": 50, "max": 20000,
        "group": "virt_chat", "label": "Virt chat onaylı tam liste tavanı",
        "help": "Kullanıcı “tüm VM’ler” için onay verdiğinde tek soruya uygulanacak üst sınır. "
                "Cevap bitince varsayılan limite dönülür.",
        "env": "VIRT_CHAT_VM_LIST_HARD_MAX",
    },
    "llm_context_token_budget": {
        "default": "32768", "type": "str",
        "choices": ["8192", "16384", "32768", "49152", "65536", "128000"],
        "group": "llm_context", "label": "LLM context token bütçesi",
        "help": "Uzak/yerel modele gönderilen toplam context üst sınırı (token). "
                "Model limitinden düşük veya eşit seçin (örn. gpt-oss-120b → 32768). "
                "Aşımda bağlam otomatik kısaltılır.",
        "env": "LLM_CONTEXT_TOKEN_BUDGET",
    },
    # ── RAG Reranker (HuggingFace cross-encoder) ─────────────────────
    "rag_reranker_enabled": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "rag_reranker", "label": "RAG reranker aktif",
        "help": "Açıkken embedding aramasından gelen aday sonuçlar bir HuggingFace "
                "cross-encoder modeliyle yeniden sıralanır (runbook/incident/bilgi "
                "bankası araması daha isabetli olur). Model ilk çağrıda indirilir/yüklenir; "
                "yüklenemezse (offline vb.) otomatik olarak devre dışı kalır, RAG bozulmaz.",
        "env": "RAG_RERANKER_ENABLED",
    },
    "rag_reranker_model": {
        "default": "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", "type": "str",
        "group": "rag_reranker", "label": "Reranker modeli (HuggingFace)",
        "help": "sentence-transformers CrossEncoder ile yüklenecek HuggingFace model adı. "
                "Varsayılan hafif/çok dilli MiniLM modeli — bu sunucuda GPU olmadığı için "
                "CPU'da hızlıdır (~15 aday <1sn). Daha yüksek kaliteli ama ÇOK daha yavaş "
                "(CPU'da 15 aday ~10sn) bir alternatif için 'BAAI/bge-reranker-v2-m3' "
                "girilebilir — yalnızca chat gecikmesi sorun değilse önerilir.",
        "env": "RAG_RERANKER_MODEL",
    },
    "rag_reranker_candidates": {
        "default": 15, "type": "int", "min": 5, "max": 50,
        "group": "rag_reranker", "label": "Reranker aday sayısı",
        "help": "Reranking öncesi embedding aramasından çekilecek aday sayısı — bu "
                "adaylar cross-encoder ile yeniden sıralanıp en iyi top-k seçilir. "
                "Büyütmek isabetliliği artırabilir ama CPU'da yanıt süresini uzatır.",
        "env": "RAG_RERANKER_CANDIDATES",
    },
    # ── Proxy (uygulama notu; nginx restart ile uygulanır) ───────────
    "nginx_proxy_read_timeout_sec": {
        "default": 1800, "type": "int", "min": 60, "max": 7200,
        "group": "proxy", "label": "Nginx API proxy read timeout (sn)",
        "help": "Frontend nginx /api/ proxy_read_timeout. Değişiklik paket rebuild veya nginx conf güncellemesiyle yansır; uzun SSH toplu işler için 1800 önerilir.",
        "env": "NGINX_PROXY_READ_TIMEOUT_SEC",
    },
    # ── Kısa TTL API önbellekleri (Redis) ───────────────────────────
    "ocp_overview_cache_ttl_sec": {
        "default": 30, "type": "int", "min": 5, "max": 300,
        "group": "api_cache", "label": "OpenShift overview cache TTL (sn)",
        "help": "GET /openshift/clusters/{id}/overview Redis TTL. Tekrarlayan dashboard açılışlarını hızlandırır; 0 Redis’i kullanmaz (fail-open zaten var).",
        "env": "OCP_OVERVIEW_CACHE_TTL_SEC",
    },
    "ops_summary_cache_ttl_sec": {
        "default": 45, "type": "int", "min": 5, "max": 300,
        "group": "api_cache", "label": "Ops summary cache TTL (sn)",
        "help": "GET /ops-center/summary Redis TTL — navbar badge çoklu platform çağrıları için.",
        "env": "OPS_SUMMARY_CACHE_TTL_SEC",
    },
    "monitoring_servers_cache_ttl_sec": {
        "default": 20, "type": "int", "min": 5, "max": 120,
        "group": "api_cache", "label": "Monitoring servers cache TTL (sn)",
        "help": "GET /monitoring/metrics/servers Redis TTL. fresh=1 ile bypass.",
        "env": "MONITORING_SERVERS_CACHE_TTL_SEC",
    },
}

GROUP_LABELS = {
    "health": "Health checker",
    "workers": "Paralellik (worker)",
    "process": "Process (Celery / Uvicorn)",
    "ssh": "SSH timeout",
    "winrm": "WinRM",
    "background": "Arka plan görevleri",
    "ai_ready": "AI Ready tarama",
    "nlq": "Linux NL envanter snapshot",
    "logs": "Log toplama (SSH / Syslog)",
    "unified_chat": "Unified Chat (agentic)",
    "linux_chat": "Linux Chat (agentic)",
    "virt_chat": "Sanallaştırma Chat",
    "llm_context": "LLM / Context",
    "rag_reranker": "RAG Reranker (HuggingFace)",
    "proxy": "Proxy / Nginx",
    "api_cache": "API önbellek (Redis)",
}

# UI kaydı → entrypoint’in okuduğu dosya (volume: /app/uploads)
PROCESS_WORKERS_ENV_FILE = os.environ.get(
    "PROCESS_WORKERS_ENV_FILE", "/app/uploads/ainew_process_workers.env"
)
PROCESS_WORKER_KEYS = ("celery_concurrency", "uvicorn_workers")

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
        if t == "str":
            val = str(raw).strip()
            choices = meta.get("choices")
            if choices and val not in choices:
                return default
            max_len = meta.get("max")
            if max_len and len(val) > int(max_len):
                val = val[: int(max_len)]
            return val or default
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


def get_bool(key: str) -> bool:
    return bool(get_setting(key))


def get_str(key: str) -> str:
    v = get_setting(key)
    return "" if v is None else str(v)


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
            "label": meta.get("label", key),
            "help": meta.get("help", ""),
            "env": meta.get("env"),
            "choices": meta.get("choices"),
            "requires_restart": bool(meta.get("requires_restart")),
            "restart_target": meta.get("restart_target") or "",
        })
    return out


def write_process_workers_env_file(*, celery_concurrency: Any = None, uvicorn_workers: Any = None) -> str:
    """Entrypoint’in okuduğu CELERY_CONCURRENCY / UVICORN_WORKERS dosyasını güncelle."""
    path = PROCESS_WORKERS_ENV_FILE
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    except Exception:
        pass

    # Mevcut değerleri koru
    current: Dict[str, str] = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip()
                    if k in ("CELERY_CONCURRENCY", "UVICORN_WORKERS"):
                        current[k] = v
        except Exception:
            pass

    if celery_concurrency is None:
        celery_concurrency = get_setting("celery_concurrency")
    if uvicorn_workers is None:
        uvicorn_workers = get_setting("uvicorn_workers")

    current["CELERY_CONCURRENCY"] = str(int(celery_concurrency))
    current["UVICORN_WORKERS"] = str(max(1, min(8, int(uvicorn_workers))))

    body = (
        "# ainew process workers — docker-entrypoint okur; container recreate gerekir\n"
        f"CELERY_CONCURRENCY={current['CELERY_CONCURRENCY']}\n"
        f"UVICORN_WORKERS={current['UVICORN_WORKERS']}\n"
    )
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.replace(tmp, path)
    logger.info("Process workers env yazıldı: %s", path)
    return path


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

    restart_keys = [k for k in saved if ADVANCED_SCHEMA.get(k, {}).get("requires_restart")]
    if restart_keys:
        try:
            write_process_workers_env_file(
                celery_concurrency=saved.get("celery_concurrency"),
                uvicorn_workers=saved.get("uvicorn_workers"),
            )
        except Exception as exc:
            logger.warning("process workers env yazılamadı: %s", exc)

    logger.info("Gelişmiş ayarlar güncellendi: %s", list(saved.keys()))
    return saved
