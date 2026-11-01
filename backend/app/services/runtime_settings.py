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
        "help": "Aynı anda en fazla kaç sohbet turu LLM hattına girer. Fazlası kuyruğa alınır; sohbette sıra ve tahmini süre gösterilir. "
                "Etkin LLM paralelliği ayrıca «Eşzamanlı LLM çağrısı sınırı» (llm_max_concurrent) ile sınırlıdır; bu değer onu "
                "aşarsa fazla turlar LLM semaforunda bekler.",
        "env": "CHAT_AI_MAX_CONCURRENT",
    },
    "chat_gate_max_wait_sec": {
        "default": 180, "type": "int", "min": 10, "max": 900,
        "group": "process", "label": "Sohbet kuyruğu en uzun bekleme (sn)",
        "help": "Adım 13: bir tur kapıda en fazla bu kadar bekler; dolunca kullanıcıya «sistem yoğun» mesajı gösterilir.",
        "env": "CHAT_GATE_MAX_WAIT_SEC",
    },
    "chat_gate_max_queue": {
        "default": 20, "type": "int", "min": 0, "max": 500,
        "group": "process", "label": "Sohbet kuyruğu üst sınırı",
        "help": "Adım 13: kuyrukta bu kadar tur bekliyorsa yeni soru beklemeden HTTP 429 «Sistem yoğun» ile reddedilir (tur oluşmaz). 0 = sınırsız.",
        "env": "CHAT_GATE_MAX_QUEUE",
    },
    "chat_user_max_active_turns": {
        "default": 2, "type": "int", "min": 0, "max": 10,
        "group": "process", "label": "Kullanıcı başına eşzamanlı aktif sohbet turu",
        "help": "Adım 13: bir kullanıcının aynı anda bekleyen+çalışan tur sayısı bu değeri aşarsa yeni soru HTTP 429 ile reddedilir "
                "(çok sekme/çift gönderim bir kullanıcının tüm slotları almasını engeller). 0 = sınırsız.",
        "env": "CHAT_USER_MAX_ACTIVE_TURNS",
    },
    "chat_gate_fast_bonus_sec": {
        "default": 45, "type": "int", "min": 0, "max": 600,
        "group": "process", "label": "Hızlı şerit avantajı (sn)",
        "help": "Adım 13: selamlaşma ve kavramsal (önbellek adayı) sorular kuyrukta bu kadar saniye öne geçer; bu süreden uzun bekleyen "
                "normal tur geçilmez (açlık yok). 0 = saf FIFO.",
        "env": "CHAT_GATE_FAST_BONUS_SEC",
    },
    "chat_session_serial_enabled": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "process", "label": "Aynı oturumda turlar sırayla",
        "help": "Adım 13: aynı sohbet oturumuna art arda gelen ikinci soru, ilkinin yanıtı bitene kadar bekler (geçmiş tutarlı kalır). "
                "Farklı oturumlar etkilenmez.",
        "env": "CHAT_SESSION_SERIAL_ENABLED",
    },
    "chat_unified_stream_final": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "llm_chat", "label": "Sohbet: cevap canlı akar (tüm AI sohbet ekranları)",
        "help": "Adım 14/17: Yönetici, Windows, Linux/OpenShift sohbetinde araçlar çalıştıktan sonra modelin son turu "
                "doğrudan kullanıcıya canlı akıtılır; ikinci bir üretim çağrısı yapılmaz (ilk karakter ve toplam süre kısalır). "
                "Sanallaştırma sohbetinde cevap token token akar. Kapalıysa eski davranış: cevap bloklayan çağrıdan sonra "
                "topluca gelir. Kısalma/uzun/hatalı turlarda otomatik ikinci üretime düşer.",
        "env": "CHAT_UNIFIED_STREAM_FINAL",
    },
    "chat_final_think": {
        "default": "low", "type": "str", "choices": ["", "low", "medium", "high"],
        "group": "llm_chat", "label": "Sohbet: ikinci üretimde düşünme seviyesi",
        "help": "Adım 14: araç turunun cevabı kullanılamayınca (sızıntı/kesik/nudge) yapılan ikinci üretimin gpt-oss think "
                "seviyesi. Araç verisini özetlemek için uzun düşünme gerekmez; sınırsız düşünme bu çağrıyı 30–200 sn "
                "sessiz bırakabiliyordu. Boş = model varsayılanı (eski davranış).",
        "env": "CHAT_FINAL_THINK",
    },
    "chat_stream_thinking": {
        "default": "admin", "type": "str", "choices": ["off", "admin", "all"],
        "group": "llm_chat", "label": "Sohbet: «Düşünme süreci» akışı",
        "help": "Adım 14: modelin akıl yürütmesi (cevap değil) araç aşamasında canlı gösterilir, kullanıcı ilk karakteri "
                "beklerken boş kalmaz. off = kapalı; admin = yalnız yönetici; all = herkes. Cevap metnine / kayda / "
                "önbelleğe karışmaz.",
        "env": "CHAT_STREAM_THINKING",
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
    "openshift_sync_prune_enabled": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "background", "label": "OpenShift senkronu: bayat pod temizliği",
        "help": "OpenShift senkronu TAM ve BAŞARILI bir pod listelemesi aldığında, o cluster'da bu senkronda görülmeyen "
                "(silinmiş/bitmiş) pod satırlarını envanterden temizler. Liste hata/zaman aşımı/kısmi ise, sahte cluster'da "
                "ve aşırı büyük silmede (yarıdan fazlası) HİÇBİR ŞEY silinmez. Kapatılırsa pod satırları yalnız eklenir/güncellenir (eski davranış).",
        "env": "OPENSHIFT_SYNC_PRUNE_ENABLED",
    },
    "esx_metric_interval_sec": {
        "default": 900, "type": "int", "min": 120, "max": 7200,
        "group": "background", "label": "ESX metrik aralığı (sn)",
        "help": "ESXi host metrik toplama.",
        "env": "ESX_METRIC_INTERVAL_SEC",
    },
    "hw_host_logs_enabled": {
        "default": False, "type": "bool", "min": 0, "max": 1,
        "group": "background", "label": "Host donanım logları (ESXi SEL/vmkernel, Linux/Windows)",
        "help": "VARSAYILAN KAPALI. Açıkken ESXi host'lardan vCenter üzerinden IPMI SEL ve vmkernel/vmkwarning donanım "
                "kayıtları okunur (vCenter rolünde Global.Diagnostics gerekir) ve mevcut Linux/Windows log "
                "toplayıcılarının donanım kayıtları (MCE, EDAC/ECC, WHEA, PSU, ısı) ayrıştırılır. iLO/iDRAC'e bağlanılmaz, "
                "yeni port/firewall gerekmez, donanıma yazılmaz. Kapalıyken hiçbir ek çağrı yapılmaz.",
        "env": "HW_HOST_LOGS_ENABLED",
    },
    "hw_ipmi_inband_enabled": {
        "default": False, "type": "bool", "min": 0, "max": 1,
        "group": "background", "label": "Linux fiziksel: in-band ipmitool SEL (donanım logu + BMC IP keşfi)",
        "help": "VARSAYILAN KAPALI. Açıkken SSH ile bağlı FİZİKSEL Linux sunucularda yalnız okuma yapan `ipmitool sel elist` / "
                "`mc info` / `lan print` çalıştırılır (BMC hesabı ve BMC ağına erişim gerekmez). Root değilse `sudo -n` "
                "(parola sorulmaz); ipmitool/IPMI cihazı/sudo yoksa host durumu işaretlenir, hata sayılmaz. Hiçbir şey "
                "kurulmaz, donanıma yazılmaz. Windows ve sanal sunucular atlanır.",
        "env": "HW_IPMI_INBAND_ENABLED",
    },
    "hw_bmc_logs_enabled": {
        "default": False, "type": "bool", "min": 0, "max": 1,
        "group": "background", "label": "BMC (iLO/iDRAC) Redfish donanım logları",
        "help": "VARSAYILAN KAPALI. Açıkken ainew her BMC'ye HTTPS (443) ile doğrudan bağlanır (BMC ağına erişim + salt-okunur "
                "BMC hesabı gerekir; Ayarlar → BMC). Yalnız GET; kimlik reddedilirse o BMC durur (hesap kilitlenmesin). "
                "Kapalıyken BMC'ye hiç bağlanılmaz.",
        "env": "HW_BMC_LOGS_ENABLED",
    },
    "hw_host_logs_interval_sec": {
        "default": 3600, "type": "int", "min": 900, "max": 86400,
        "group": "background", "label": "Host donanım logu aralığı (sn)",
        "help": "Host donanım log toplama sıklığı (varsayılan 1 saat). Kayıtlar 30 gün saklanır.",
        "env": "HW_HOST_LOGS_INTERVAL_SEC",
    },
    "virt_insights_interval_sec": {
        "default": 3600, "type": "int", "min": 600, "max": 86400,
        "group": "background", "label": "Sanallaştırma karar katmanı aralığı (sn)",
        "help": "Kapasite / sağlık / geri kazanım / sapma kontrolleri (vCenter, OLVM Manager, kube API — salt-okunur).",
        "env": "VIRT_INSIGHTS_INTERVAL_SEC",
    },
    "virt_insights_file_scan_hours": {
        "default": 24, "type": "int", "min": 1, "max": 168,
        "group": "background", "label": "Datastore dosya taraması aralığı (saat)",
        "help": "Sahipsiz VMDK / ISO / OLVM disk / OCP DataVolume taraması. Büyük datastore'larda ağırdır.",
        "env": "VIRT_INSIGHTS_FILE_SCAN_HOURS",
    },
    "ocp_monitoring_interval_sec": {
        "default": 60, "type": "int", "min": 30, "max": 900,
        "group": "background", "label": "OpenShift monitoring örnek aralığı (sn)",
        "help": "metrics.k8s.io → Timescale ocp_resource_metrics. Geçmiş bu aralıkla birikir; API geriye doldurulamaz.",
        "env": "OCP_MONITORING_INTERVAL_SEC",
    },
    "rag_reindex_interval_sec": {
        "default": 1800, "type": "int", "min": 300, "max": 86400,
        "group": "background", "label": "RAG reindex aralığı (sn)",
        "help": "Bilgi tabanı yeniden indeksleme.",
        "env": "RAG_REINDEX_INTERVAL_SEC",
    },
    "rag_maintenance_interval_sec": {
        "default": 86400, "type": "int", "min": 3600, "max": 604800,
        "group": "background", "label": "RAG bakım aralığı (sn)",
        "help": "Kaynağı silinmiş (event retention sonrası) RAG chunk'larının "
                "temizlenmesi. Embedding yapmaz, yalnızca DB temizliği.",
        "env": "RAG_MAINTENANCE_INTERVAL_SEC",
    },
    "rag_maintenance_max_delete": {
        "default": 50000, "type": "int", "min": 1000, "max": 1000000,
        "group": "background", "label": "RAG bakım tur başına silme sınırı",
        "help": "Tek bakım turunda silinecek en fazla öksüz chunk sayısı — "
                "büyük birikmelerde DB'yi tek seferde yormamak için.",
        "env": "RAG_MAINTENANCE_MAX_DELETE",
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
    "unified_route_llm_hint": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "unified_chat", "label": "Düşük güven routing LLM",
        "help": "Keyword skor belirsizken (eşik/tie) ucuz bir LLM ikinci fikir sorar. "
                "auto_explore (disk→virt+linux) daraltılamaz. Devre açıksa atlanır.",
        "env": "UNIFIED_ROUTE_LLM_HINT",
    },
    "chat_entity_gate_enabled": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "unified_chat", "label": "Varlık çözümleyici kapısı",
        "help": "Sohbette envanterde olmayan bir ad (VM/sunucu/host/cluster/namespace/node…) sorulursa LLM'e gitmeden "
                "'bulunamadı' der; aynı adla birden fazla VM kaydı varsa kayıtları listeleyip hangisini kastettiğinizi sorar. "
                "Kapatılırsa sorular eskisi gibi doğrudan LLM/araç yoluna gider.",
        "env": "CHAT_ENTITY_GATE_ENABLED",
    },
    "chat_count_rules_enabled": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "unified_chat", "label": "Sayım kuralları (kaç VM/host/datastore/cluster/node/proje)",
        "help": "Sohbette net sayım soruları (ör. 'kaç tane kapalı VM var?', 'OpenShift'te kaç node var?') LLM'e ve araca "
                "gitmeden SQL sayımıyla, kapsam etiketi ve kırılımla cevaplanır; yetkisiz platform görünmez. "
                "Kapatılırsa sayım soruları eskisi gibi QA kuralları / LLM-araç yoluna gider.",
        "env": "CHAT_COUNT_RULES_ENABLED",
    },
    "chat_grounding_mode": {
        "default": "enforce", "type": "str", "min": 0, "max": 16,
        "group": "unified_chat", "label": "Veriye dayalılık doğrulayıcısı modu (off|shadow|enforce)",
        "help": "Cevap bittikten sonra sayı/ad/komut/iç terim/kaynak etiketi/kabul edilen yanlış öncül araç verisine göre denetlenir. "
                "shadow: yalnız iz ve log (cevap değişmez); enforce (varsayılan): «Doğrulama sınıfları» listesindeki sınıflar için "
                "cevabın sonuna uyarı eklenir (cevap yeniden yazılmaz); off: kapalı. Akışı geciktirmez; Automic sohbeti kapsam dışıdır.",
        "env": "CHAT_GROUNDING_MODE",
    },
    "chat_grounding_enforce_classes": {
        "default": "internal_term,source_label,ungrounded_entity,ungrounded_command", "type": "str", "min": 0, "max": 200,
        "group": "unified_chat", "label": "Doğrulama sınıfları (enforce)",
        "help": "Virgülle ayrılmış sınıf adları: ungrounded_number, ungrounded_entity, ungrounded_command, internal_term, "
                "source_label, premise_accepted. Yalnız mod 'enforce' iken uyarı eklenir; boşsa hiçbir sınıf engellenmez. "
                "Varsayılan: ölçümde yanlış alarm <%2 ve yakalama ≥%80 olan sınıflar (ungrounded_number ve premise_accepted gölgede).",
        "env": "CHAT_GROUNDING_ENFORCE_CLASSES",
    },
    "chat_timezone": {
        "default": "Europe/Istanbul", "type": "str", "min": 0, "max": 64,
        "group": "unified_chat", "label": "Sohbet zaman dilimi",
        "help": "'dün', 'geçen hafta', 'bu ay' gibi zaman ifadeleri bu dilimin takvimine göre çözülür "
                "(hafta Pazartesi başlar). Cevapta çözülen pencere yazılır.",
        "env": "CHAT_TIMEZONE",
    },
    "virt_live_event_retention_days": {
        "default": 30, "type": "int", "min": 1, "max": 3650,
        "group": "unified_chat", "label": "vCenter canlı olay saklama süresi (gün)",
        "help": "vCenter'ın olay geçmişini tuttuğu süre (varsayılan 30). Zaman penceresi bunun dışındaysa sohbet "
                "'veri yok + kapsam' der; ortamınızda farklıysa buradan güncelleyin.",
        "env": "VIRT_LIVE_EVENT_RETENTION_DAYS",
    },
    "route_hint_num_predict": {
        "default": 128, "type": "int", "min": 32, "max": 1024,
        "group": "unified_chat", "label": "Routing ipucu — üretim sınırı (num_predict)",
        "help": (
            "Düşük güvenli routing ipucu çağrısının en fazla üreteceği token (gpt-oss'ta düşünme "
            "tokenları dahil). Çıktı yalnız kısa bir modül listesidir; sınırsız düşünme 8 sn zaman "
            "aşımını aşıp ana cevabın LLM'ini boş yere meşgul ediyordu."
        ),
        "env": "ROUTE_HINT_NUM_PREDICT",
    },
    "route_hint_think": {
        "default": "low", "type": "str", "choices": ["low", "medium", "high"],
        "group": "unified_chat", "label": "Routing ipucu — düşünme seviyesi",
        "help": "gpt-oss (Ollama native) için routing ipucu çağrısında gönderilen think seviyesi; diğer modellerde yok sayılır.",
        "env": "ROUTE_HINT_THINK",
    },
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
        "choices": ["4096", "8192", "16384", "32768", "49152", "65536", "98304", "128000", "131072"],
        "min": 4096, "max": 131072,
        "group": "llm_context", "label": "LLM context token bütçesi",
        "help": "Uzak/yerel modele gönderilen toplam context üst sınırı (token). "
                "Model limitinden düşük veya eşit seçin (örn. gpt-oss-120b → 32768). "
                "Aşımda bağlam otomatik kısaltılır. Aralık: 4096–131072. "
                "Yeniden başlatma gerekmez — bir sonraki istekten itibaren geçerli.",
        "notes": [
            "Değişiklik sonrası ilk istekte model yeniden yüklenir.",
            "Büyük değerler daha fazla GPU belleği gerektirir; bellek yetmezse model CPU'ya taşar.",
            "Küçük değerlerde konuşma geçmişi ve araç sonuçları daha fazla kırpılır.",
        ],
        "env": "LLM_CONTEXT_TOKEN_BUDGET",
    },
    "llm_context_hard_cap_tokens": {
        "default": "32768", "type": "str",
        "choices": ["4096", "8192", "16384", "32768", "49152", "65536", "98304", "128000", "131072"],
        "min": 4096, "max": 131072,
        "group": "llm_context", "label": "Gateway/model gerçek context tavanı (güvenlik sınırı)",
        "help": "Uzak gateway'in (Bifrost/LiteLLM) arkasındaki modelin GERÇEK maksimum "
                "context penceresi (ör. gpt-oss-120b → 32768). 'LLM context token bütçesi' "
                "bu değeri aşarsa otomatik olarak buna kırpılır — böylece bütçe ayarı ne "
                "kadar büyük seçilirse seçilsin gateway'e asla model limitini aşan bir "
                "istek gönderilmez (HTTP 400 'exceeds model's maximum context length' "
                "hatasına karşı sabit koruma). Model/gateway değişip pencere büyürse "
                "(ör. 64K/128K) yalnızca bu ayarı güncellemeniz yeterlidir. "
                "Aralık: 4096–131072. Yeniden başlatma gerekmez.",
        "notes": [
            "Değişiklik sonrası ilk istekte model yeniden yüklenir.",
            "Büyük değerler daha fazla GPU belleği gerektirir; bellek yetmezse model CPU'ya taşar.",
            "Küçük değerlerde konuşma geçmişi ve araç sonuçları daha fazla kırpılır.",
        ],
        "env": "LLM_CONTEXT_HARD_CAP_TOKENS",
    },
    "ollama_keep_alive": {
        "default": "-1", "type": "str",
        "choices": ["-1", "0", "60", "300", "600", "1800", "10m", "1h", "24h"],
        "group": "llm_context", "label": "Ollama keep_alive",
        "help": "Chat ve embedding dahil tüm Ollama isteklerinde gönderilir. "
                "Müşteri Ollama sunucu varsayılanına güvenilmez. "
                "-1: süresiz (önerilen), 0: hemen boşalt, sayı: saniye "
                "veya '10m', '24h' gibi süre. Yeniden başlatma gerekmez — "
                "bir sonraki istekten itibaren geçerli.",
        "notes": [
            "Değişiklik sonrası ilk istekte model yeniden yüklenir.",
        ],
        "env": "OLLAMA_KEEP_ALIVE",
    },
    # ── LLM sohbet performansı (Adım 6b) ─────────────────────────────
    "llm_think_tool_selection": {
        "default": "low", "type": "str", "choices": ["low", "medium", "high"],
        "group": "llm_chat", "label": "Düşünme seviyesi — araç seçimi turu",
        "help": "gpt-oss (Ollama native) için araç seçimi turlarında (ilk tur) gönderilen think seviyesi.",
        "env": "LLM_THINK_TOOL_SELECTION",
    },
    "llm_think_simple": {
        "default": "low", "type": "str", "choices": ["low", "medium", "high"],
        "group": "llm_chat", "label": "Düşünme seviyesi — basit veri sorusu",
        "help": "Niyet=data ve basit soru (kaç / ne zaman / listele / hangi …) için cevap turu.",
        "env": "LLM_THINK_SIMPLE",
    },
    "llm_think_analysis": {
        "default": "medium", "type": "str", "choices": ["low", "medium", "high"],
        "group": "llm_chat", "label": "Düşünme seviyesi — analiz sorusu",
        "help": "Neden / karşılaştırma / ortak nokta / trend / değişim soruları için cevap turu.",
        "env": "LLM_THINK_ANALYSIS",
    },
    "llm_think_default": {
        "default": "medium", "type": "str", "choices": ["low", "medium", "high"],
        "group": "llm_chat", "label": "Düşünme seviyesi — sınıflandırılamayan soru",
        "help": "Basit/analiz ayrımı yapılamadığında kullanılır (emin değilse medium).",
        "env": "LLM_THINK_DEFAULT",
    },
    "llm_temperature_tools": {
        "default": 0.1, "type": "float", "min": 0.0, "max": 1.5,
        "group": "llm_chat", "label": "Sıcaklık — araç seçim turu",
        "help": "Araç çağrısı seçilen LLM turlarının temperature değeri (Automic sohbeti). Düşük = daha tutarlı araç argümanı.",
        "env": "LLM_TEMPERATURE_TOOLS",
    },
    "llm_temperature_answer": {
        "default": 0.2, "type": "float", "min": 0.0, "max": 1.5,
        "group": "llm_chat", "label": "Sıcaklık — cevap turu",
        "help": ("Araçlar çalıştıktan sonraki cevap turlarının (canlı akış ve ayrı final turu) temperature değeri. "
                 "Model varsayılanı (gpt-oss) 1.0'dır. Adım 7 A/B (core 10 soru × N=5): 0.0 → 40/50, 0.1 → 40/50, 0.2 → 43/50, 1.0 → 42/50 (fark gürültü içinde; 0.2 en yüksek geçme + ortalama süre 15.6 sn)."),
        "env": "LLM_TEMPERATURE_ANSWER",
    },
    "llm_think_sticky": {
        "default": False, "type": "bool", "min": 0, "max": 1,
        "group": "llm_chat", "label": "Düşünme seviyesi istek boyunca sabit (prefix cache)",
        "help": (
            "gpt-oss şablonunda 'Reasoning: <seviye>' prompt'un başındadır; turlar arasında "
            "seviye değişirse KV/prefix cache baştan geçersiz olur. Açıkken tüm turlar soru "
            "derinliğine göre cevap seviyesini kullanır; kapalıyken araç seçim turu "
            "llm_think_tool_selection seviyesinde çalışır."
        ),
        "env": "LLM_THINK_STICKY",
    },
    "llm_max_concurrent": {
        "default": 1, "type": "int", "min": 0, "max": 16,
        "group": "llm_chat", "label": "Eşzamanlı LLM çağrısı sınırı (semafor)",
        "help": (
            "LLM sunucusunun GERÇEK paralelliğiyle eşleşmelidir (Ollama için sunucudaki OLLAMA_NUM_PARALLEL; "
            "vLLM/Bifrost için sunucunun eşzamanlı istek sınırı). Varsayılan 1. Bu değer sunucudan BÜYÜKSE "
            "istekler sunucuda sıraya girer ve okuma zaman aşımına uğrayabilir; KÜÇÜKSE sunucu kapasitesi boşa gider. "
            "Sınır dolunca çağrılar kuyrukta bekler; kullanıcı sohbeti arka plan işlerinden (rapor, özet, backfill, "
            "analiz) önceliklidir. 0 = kapalı. Kuyruk beklemesi yüksekse LLM sağlık kartında uyarı çıkar."
        ),
        "env": "LLM_MAX_CONCURRENT",
    },
    "llm_sched_bg_max_wait_sec": {
        "default": 120, "type": "int", "min": 1, "max": 3600,
        "group": "llm_chat", "label": "Arka plan çağrısı en uzun kuyruk beklemesi (sn)",
        "help": "Sohbet beklerken arka plan çağrısı en fazla bu kadar bekler (açlık koruması), sonra devam eder.",
        "env": "LLM_SCHED_BG_MAX_WAIT_SEC",
    },
    "llm_sched_max_wait_sec": {
        "default": 600, "type": "int", "min": 5, "max": 7200,
        "group": "llm_chat", "label": "Sohbet çağrısı en uzun kuyruk beklemesi (sn)",
        "help": "Güvenlik sınırı: slot bu sürede alınamazsa çağrı slotsuz devam eder (kilitlenme önleme).",
        "env": "LLM_SCHED_MAX_WAIT_SEC",
    },
    "llm_circuit_failure_threshold": {
        "default": 3, "type": "int", "min": 1, "max": 20,
        "group": "llm_chat", "label": "Uzak LLM devre kesici — hata eşiği",
        "help": (
            "Pencere içinde bu kadar hata birikince devre açılmadan ÖNCE sağlık yoklaması yapılır; "
            "uzak model yoklamaya yanıt veriyorsa (yavaş ama ayakta) devre açılmaz. İsteğe bağlı yan "
            "çağrılar (yönlendirme ipucu vb.) bu sayaca hiç girmez."
        ),
        "env": "LLM_CIRCUIT_FAILURE_THRESHOLD",
    },
    "llm_circuit_failure_window_sec": {
        "default": 60, "type": "int", "min": 5, "max": 3600,
        "group": "llm_chat", "label": "Uzak LLM devre kesici — hata penceresi (sn)",
        "help": "Hataların sayıldığı kayan pencere süresi.",
        "env": "LLM_CIRCUIT_FAILURE_WINDOW_SEC",
    },
    "llm_circuit_open_sec": {
        "default": 45, "type": "int", "min": 5, "max": 3600,
        "group": "llm_chat", "label": "Uzak LLM devre kesici — açık kalma süresi (sn)",
        "help": (
            "Devre açılınca istekler ağ beklemeden reddedilir. Süre dolunca ilk istekte tek yoklamalı "
            "yarı açık deneme yapılır: başarılıysa devre kapanır, değilse yeniden açılır."
        ),
        "env": "LLM_CIRCUIT_OPEN_SEC",
    },
    "llm_circuit_probe_timeout_sec": {
        "default": 3, "type": "int", "min": 1, "max": 15,
        "group": "llm_chat", "label": "Uzak LLM devre kesici — sağlık yoklaması zaman aşımı (sn)",
        "help": "Ollama için /api/version, OpenAI-uyumlu gateway için /v1/models yoklamasının üst süresi.",
        "env": "LLM_CIRCUIT_PROBE_TIMEOUT_SEC",
    },
    "llm_num_predict_low": {
        "default": 1536, "type": "int", "min": 256, "max": 32768,
        "group": "llm_chat", "label": "num_predict — think=low",
        "help": "Üretim üst sınırı (gpt-oss'ta düşünme tokenlarını da kapsar).",
        "env": "LLM_NUM_PREDICT_LOW",
    },
    "llm_num_predict_medium": {
        "default": 3072, "type": "int", "min": 256, "max": 32768,
        "group": "llm_chat", "label": "num_predict — think=medium",
        "help": "Üretim üst sınırı (düşünme dahil).",
        "env": "LLM_NUM_PREDICT_MEDIUM",
    },
    "llm_num_predict_high": {
        "default": 6144, "type": "int", "min": 256, "max": 32768,
        "group": "llm_chat", "label": "num_predict — think=high",
        "help": "Üretim üst sınırı (düşünme dahil).",
        "env": "LLM_NUM_PREDICT_HIGH",
    },
    "unified_tool_think": {
        "default": "medium", "type": "str", "choices": ["low", "medium", "high"],
        "group": "llm_chat", "label": "Araç turu düşünme seviyesi (politikasız sohbetler)",
        "help": ("Unified / Linux / Windows / Sanallaştırma sohbetlerinin araç döngüsü (llm_policy vermeyen yollar) "
                 "için gpt-oss (Ollama native) think seviyesi. Varsayılan medium = gpt-oss'un zaten kullandığı seviye "
                 "(davranış değişmez). Diğer modellerde yok sayılır. Automic kendi politikasını kullanır."),
        "env": "UNIFIED_TOOL_THINK",
    },
    "unified_tool_num_predict": {
        "default": 6144, "type": "int", "min": 0, "max": 32768,
        "group": "llm_chat", "label": "Araç turu üretim tavanı (num_predict)",
        "help": ("Politikasız sohbetlerin araç turunda tek LLM çağrısının üretebileceği en çok token "
                 "(gpt-oss'ta düşünme tokenlarını da kapsar). Sınırsız düşünme, araç turunu zaman aşımına (90 sn) "
                 "taşıyabiliyordu. Konservatif varsayılan 6144; boş çıktı + done_reason=length olursa bir kez "
                 "2 kat tavanla yeniden denenir. 0 = sınırsız (eski davranış). Yalnız Ollama native taşımada "
                 "uygulanır (OpenAI-uyumlu gateway'de yok sayılır)."),
        "env": "UNIFIED_TOOL_NUM_PREDICT",
    },
    "llm_warn_window_sec": {
        "default": 1800, "type": "int", "min": 60, "max": 86400,
        "group": "llm_chat", "label": "LLM sağlık uyarıları — ölçüm penceresi (sn)",
        "help": "Kuyruk bekleme / zaman aşımı / atlanan ipucu uyarıları son bu kadar saniyeyi inceler.",
        "env": "LLM_WARN_WINDOW_SEC",
    },
    "llm_warn_queue_wait_ms": {
        "default": 5000, "type": "int", "min": 100, "max": 600000,
        "group": "llm_chat", "label": "LLM sağlık uyarısı — kuyruk bekleme eşiği (ms, p95)",
        "help": "Penceredeki çağrıların scheduler kuyruk beklemesi p95'i bu değeri aşarsa bilgi uyarısı çıkar (erişimi engellemez).",
        "env": "LLM_WARN_QUEUE_WAIT_MS",
    },
    "llm_warn_best_effort_timeouts": {
        "default": 3, "type": "int", "min": 1, "max": 1000,
        "group": "llm_chat", "label": "LLM sağlık uyarısı — isteğe bağlı çağrı zaman aşımı eşiği",
        "help": "Penceredeki isteğe bağlı (ör. yönlendirme ipucu) çağrılardan en az bu kadarı zaman aşımına dayanırsa uyarı çıkar.",
        "env": "LLM_WARN_BEST_EFFORT_TIMEOUTS",
    },
    "llm_warn_hint_skips": {
        "default": 5, "type": "int", "min": 1, "max": 10000,
        "group": "llm_chat", "label": "LLM sağlık uyarısı — atlanan ipucu eşiği",
        "help": "Penceredeki atlanan (slot meşgul) yönlendirme ipucu sayısı bu değeri aşarsa uyarı çıkar.",
        "env": "LLM_WARN_HINT_SKIPS",
    },
    "llm_warn_tool_turn_limit": {
        "default": 2, "type": "int", "min": 1, "max": 1000,
        "group": "llm_chat", "label": "LLM sağlık uyarısı — araç turu zaman aşımı sınırına dayanma eşiği",
        "help": "Penceredeki araç turu çağrılarından en az bu kadarı zaman aşımı sınırına dayanırsa uyarı çıkar.",
        "env": "LLM_WARN_TOOL_TURN_LIMIT",
    },
    "llm_timeout_dynamic": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "llm_chat", "label": "Dinamik LLM zaman aşımı",
        "help": ("Açıkken okuma zaman aşımı çağrı sınıfına göre ölçülen p95 × k ile uzar (alt sınırın altına inmez, "
                 "üst sınırı aşmaz). Kapalıyken sınıf alt sınırı (sabit eski değerler) kullanılır."),
        "env": "LLM_TIMEOUT_DYNAMIC",
    },
    "llm_timeout_min_samples": {
        "default": 10, "type": "int", "min": 3, "max": 200,
        "group": "llm_chat", "label": "Dinamik zaman aşımı — en az örnek sayısı",
        "help": "Sınıfın penceresinde bu kadar çağrı yoksa dinamik hesap yapılmaz, alt sınır kullanılır.",
        "env": "LLM_TIMEOUT_MIN_SAMPLES",
    },
    "llm_chat_stream_final": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "llm_chat", "label": "Araç döngüsünün son turunu doğrudan stream et",
        "help": "Açıkken araç çağırmayan son tur cevabı kullanıcıya akıtılır; ayrı bir final turu çalışmaz.",
        "env": "LLM_CHAT_STREAM_FINAL",
    },
    "llm_tool_result_max_rows": {
        "default": 20, "type": "int", "min": 3, "max": 500,
        "group": "llm_chat", "label": "LLM'e giden araç sonucu satır sınırı",
        "help": "Liste alanları bu kadar satıra kısaltılır (toplam kayıt notu eklenir). UI bileşenleri tam veriyle üretilir.",
        "env": "LLM_TOOL_RESULT_MAX_ROWS",
    },
    "llm_tool_result_max_tokens": {
        "default": 3000, "type": "int", "min": 300, "max": 30000,
        "group": "llm_chat", "label": "Tek araç sonucu token sınırı (LLM)",
        "help": "Tek bir araç sonucunun modele gidecek tahmini token üst sınırı.",
        "env": "LLM_TOOL_RESULT_MAX_TOKENS",
    },
    "llm_tool_results_total_max_tokens": {
        "default": 7000, "type": "int", "min": 500, "max": 60000,
        "group": "llm_chat", "label": "Tüm araç sonuçları toplam token sınırı (LLM)",
        "help": "Bir isteğin tüm araç sonuçları için toplam tahmini token sınırı.",
        "env": "LLM_TOOL_RESULTS_TOTAL_MAX_TOKENS",
    },
    "llm_ctx_warn_ratio_pct": {
        "default": 70, "type": "int", "min": 30, "max": 95,
        "group": "llm_chat", "label": "Prompt / num_ctx uyarı eşiği (%)",
        "help": "Bir turun promptu num_ctx'in bu yüzdesini aşarsa loglanır ve araç sonuçları daha da küçültülür.",
        "env": "LLM_CTX_WARN_RATIO_PCT",
    },
    "llm_transport_mode": {
        "default": "auto", "type": "str",
        "choices": ["auto", "ollama", "openai"],
        "group": "llm_context", "label": "REMOTE_LLM taşıma modu",
        "help": "REMOTE_LLM etkinken isteklerin nasıl gönderileceği. "
                "auto: adres Ollama ise (GET /api/version) native /api/chat|/api/generate "
                "(keep_alive + num_ctx); aksi halde OpenAI /v1/chat/completions. "
                "ollama / openai: algılamayı ezer. Yeniden başlatma gerekmez.",
        "notes": [
            "Ollama OpenAI-uyumlu /v1 arkasında bile native taşıma keep_alive/num_ctx sağlar.",
        ],
        "env": "LLM_TRANSPORT_MODE",
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
    "rag_embed_concurrency": {
        "default": 4, "type": "int", "min": 1, "max": 32,
        "group": "rag_reranker", "label": "Embedding eşzamanlılığı",
        "help": "RAG embedding sırasında Ollama'ya aynı anda gönderilecek istek sayısı "
                "(varsayılan 4). Embedding CPU'da çalışıyorsa 1–2'ye düşürün; 8+ thrashing "
                "ve model unload (Stopping…) üretebilir. GPU'da 4–8 genelde güvenli.",
        "env": "OLLAMA_EMBED_CONCURRENCY",
    },    "rag_reranker_candidates": {
        "default": 15, "type": "int", "min": 5, "max": 50,
        "group": "rag_reranker", "label": "Reranker aday sayısı",
        "help": "Reranking öncesi embedding aramasından çekilecek aday sayısı — bu "
                "adaylar cross-encoder ile yeniden sıralanıp en iyi top-k seçilir. "
                "Büyütmek isabetliliği artırabilir ama CPU'da yanıt süresini uzatır.",
        "env": "RAG_RERANKER_CANDIDATES",
    },
    "rag_min_relevance_enabled": {
        "default": False, "type": "bool", "min": 0, "max": 1,
        "group": "rag_reranker", "label": "RAG alaka eşiği (açık/kapalı)",
        "help": "Açıkken reranker skoru «Alaka eşiği» değerinin altındaki bilgi parçaları sohbet bağlamına girmez; "
                "hepsi altındaysa bağlam boş kalır (bilgi bankasında yok yolu). Varsayılan KAPALI; değer ölçümle seçilir. "
                "Reranker kapalıysa/yüklenmediyse eşik uygulanmaz.",
        "env": "RAG_MIN_RELEVANCE_ENABLED",
    },
    "rag_min_relevance": {
        "default": 0.0, "type": "float", "min": -30, "max": 30,
        "group": "rag_reranker", "label": "RAG alaka eşiği (reranker skoru)",
        "help": "Cross-encoder ham skoru; ölçek modele bağlıdır (ölçüm: docs/chat-quality/plan.md Adım 8R). Yalnız eşik açıkken geçerli.",
        "env": "RAG_MIN_RELEVANCE",
    },
    "rag_lexical_timeout_ms": {
        "default": 1500, "type": "int", "min": 0, "max": 60000,
        "group": "rag_reranker", "label": "RAG lexical (FTS) zaman sınırı (ms)",
        "help": "Tam metin (FTS) kolunun toplam süre sınırı. Aşılırsa lexical sonuç boş döner ve hibrit aramada yalnız vektör sonucu kullanılır "
                "(incidents ~1,2 M satırda yaygın sözcükler saniyeler/dakikalar sürebiliyordu). 0 = sınır yok.",
        "env": "RAG_LEXICAL_TIMEOUT_MS",
    },
    "rag_lexical_max_candidates": {
        "default": 2000, "type": "int", "min": 0, "max": 100000,
        "group": "rag_reranker", "label": "RAG lexical aday sınırı",
        "help": "Yalnız büyük koleksiyonlarda (≥ 50 bin satır; incidents): FTS ile eşleşen satırlardan en çok bu kadarı sıralanır "
                "(aday seçimi fiziksel sırayla, yani en eski kayıtlar öncelikli — vektör kolu bunu dengeler). 0 = sınır yok.",
        "env": "RAG_LEXICAL_MAX_CANDIDATES",
    },
    "rag_incidents_retention_enabled": {
        "default": False, "type": "bool", "min": 0, "max": 1,
        "group": "rag_reranker", "label": "RAG incidents yaş bazlı budama (açık/kapalı)",
        "help": "VARSAYILAN KAPALI. Açıkken RAG bakım turu, saklama süresinden eski event/log gömme satırlarını (vcenter_event, openshift_event, "
                "openshift_virt_event, log_entry, virt_log) önce yedekleyip tek işlemde siler; `incident` kayıtları kalıcıdır. "
                "Açmadan önce dry-run raporu incelenmeli (docs/chat-quality/plan.md Adım 8R). VACUUM/REINDEX ayrı bakım işidir.",
        "env": "RAG_INCIDENTS_RETENTION_ENABLED",
    },
    "rag_incidents_retention_days": {
        "default": 60, "type": "int", "min": 7, "max": 3650,
        "group": "rag_reranker", "label": "RAG incidents saklama süresi (gün)",
        "help": "Yalnız budama açıkken geçerli; bu günden eski event/log satırları silinir (tur başına `rag_maintenance_max_delete` üst sınırı).",
        "env": "RAG_INCIDENTS_RETENTION_DAYS",
    },
    "chat_cache_enabled": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "llm_chat", "label": "Sohbet cevap önbelleği (açık/kapalı)",
        "help": "Adım 9: yalnız KAVRAMSAL sorular (nedir / ne demek / nasıl çalışır …) için TAM eşleşmeli önbellek; veri, sayım, durum, zaman-göreli, "
                "varlık adı içeren, araç/canlı veri kullanan, ret/hata/«veri yok» cevapları önbelleğe girmez. Anahtar platform + kullanıcının izinli modül imzasıdır. "
                "Kapalıyken ne okuma ne yazma yapılır (anında etkili).",
        "env": "CHAT_CACHE_ENABLED",
    },
    "chat_cache_ttl_sec": {
        "default": 86400, "type": "int", "min": 60, "max": 604800,
        "group": "llm_chat", "label": "Sohbet cevap önbelleği TTL (sn)",
        "help": "Sabit süre (varsayılan 24 saat); önbellek isabeti süreyi UZATMAZ.",
        "env": "CHAT_CACHE_TTL_SEC",
    },
    "chat_progress_enabled": {
        "default": True, "type": "bool", "min": 0, "max": 1,
        "group": "llm_chat", "label": "Sohbet ilerleme olayları (ilk token öncesi)",
        "help": "Adım 10: ilk token gelmeden önce aşama metni + geçen süre (`type: progress`) gönderilir; LLM/araç çağırmaz, yalnız olay üretir. "
                "Kapalıyken hiç progress olayı yoktur (anında).",
        "env": "CHAT_PROGRESS_ENABLED",
    },
    "chat_progress_heartbeat_sec": {
        "default": 5, "type": "int", "min": 2, "max": 30,
        "group": "llm_chat", "label": "İlerleme kalp atışı aralığı (sn)",
        "help": "Son olaydan bu kadar sn sonra «hâlâ çalışıyor» ilerlemesi gönderilir (yalnız ilk token öncesi).",
        "env": "CHAT_PROGRESS_HEARTBEAT_SEC",
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

# Çağrı sınıfı başına dinamik zaman aşımı parametreleri (llm_timeouts): k, alt sınır, üst sınır.
_TIMEOUT_CLASS_META = {
    "route_hint": ("Yönlendirme ipucu", 1.5, 8, 10, 3, 10,
                   "İsteğe bağlı çağrı; üst sınır 10 sn'yi AŞAMAZ (gerçek sohbeti geciktirmesin)."),
    "tool_turn": ("Araç turu", 2.0, 90, 180, 30, 900,
                  "Araç seçimi / araç turu (chat_sync). Alt sınır mevcut 90 sn davranışıdır."),
    "final_answer": ("Cevap üretimi", 2.0, 120, 240, 30, 1800,
                     "Cevap akışları. Alt sınır mevcut 120/180 sn varsayılanıdır."),
    "background": ("Arka plan", 2.0, 120, 300, 30, 1800,
                   "Rapor, özet, analiz gibi diğer çağrılar."),
}
for _cls, (_ad, _k, _lo, _hi, _rlo, _rhi, _note) in _TIMEOUT_CLASS_META.items():
    ADVANCED_SCHEMA[f"llm_timeout_{_cls}_k"] = {
        "default": _k, "type": "float", "min": 0.5, "max": 10.0,
        "group": "llm_chat", "label": f"Dinamik zaman aşımı — {_ad}: çarpan (p95 × k)",
        "help": f"Zaman aşımı = clamp(p95 × k, alt, üst). {_note}",
        "env": f"LLM_TIMEOUT_{_cls.upper()}_K",
    }
    ADVANCED_SCHEMA[f"llm_timeout_{_cls}_min_sec"] = {
        "default": _lo, "type": "int", "min": _rlo, "max": _rhi,
        "group": "llm_chat", "label": f"Dinamik zaman aşımı — {_ad}: alt sınır (sn)",
        "help": f"Ölçüm yetersizken/düşükken kullanılan değer. {_note}",
        "env": f"LLM_TIMEOUT_{_cls.upper()}_MIN_SEC",
    }
    ADVANCED_SCHEMA[f"llm_timeout_{_cls}_max_sec"] = {
        "default": _hi, "type": "int", "min": _rlo, "max": _rhi,
        "group": "llm_chat", "label": f"Dinamik zaman aşımı — {_ad}: üst sınır (sn)",
        "help": f"Dinamik değerin çıkabileceği en yüksek değer. {_note}",
        "env": f"LLM_TIMEOUT_{_cls.upper()}_MAX_SEC",
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
    "llm_chat": "LLM sohbet performansı (think / num_predict / araç sonucu)",
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
            if choices and val not in [str(c) for c in choices]:
                return default
            lo, hi = meta.get("min"), meta.get("max")
            # Sayısal aralık (context token): min/max token sınırı
            if lo is not None and hi is not None and val.lstrip("-").isdigit():
                try:
                    n = int(val)
                    if n < int(lo) or n > int(hi):
                        return default
                except ValueError:
                    return default
            max_len = meta.get("max_len")
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


def validate_advanced_value(key: str, raw: Any) -> Any:
    """Değeri doğrula; geçersizse ValueError (API 400 için).

    ``_coerce`` sessizce default'a düşer; kayıt öncesi açık hata için bunu kullanın.
    """
    meta = ADVANCED_SCHEMA.get(key)
    if not meta:
        raise ValueError(f"Bilinmeyen ayar: {key}")
    if raw is None or raw == "":
        raise ValueError(f"{key}: boş değer")
    t = meta["type"]
    if t == "str":
        val = str(raw).strip()
        choices = meta.get("choices")
        if choices and val not in [str(c) for c in choices]:
            raise ValueError(
                f"{meta.get('label') or key}: geçersiz değer '{val}'. "
                f"Seçenekler: {', '.join(str(c) for c in choices)}"
            )
        lo, hi = meta.get("min"), meta.get("max")
        if lo is not None and hi is not None and val.lstrip("-").isdigit():
            n = int(val)
            if n < int(lo) or n > int(hi):
                raise ValueError(
                    f"{meta.get('label') or key}: {n} aralık dışında "
                    f"({lo}–{hi})"
                )
        return _coerce(val, meta)
    coerced = _coerce(raw, meta)
    if t in ("int", "float"):
        lo, hi = meta.get("min"), meta.get("max")
        try:
            n = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{meta.get('label') or key}: sayı bekleniyor") from exc
        if lo is not None and n < lo:
            raise ValueError(f"{meta.get('label') or key}: en az {lo}")
        if hi is not None and n > hi:
            raise ValueError(f"{meta.get('label') or key}: en fazla {hi}")
    return coerced


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
            "notes": list(meta.get("notes") or []),
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
