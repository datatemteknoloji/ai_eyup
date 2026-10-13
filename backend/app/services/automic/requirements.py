"""UC4 Automic kurulum / entegrasyon gereksinimleri — (i) paneli ve teşhis için."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


def module_db_endpoint() -> Dict[str, str]:
    return {
        "host": os.environ.get("AUTOMIC_DB_HOST", "localhost"),
        "port": os.environ.get("AUTOMIC_DB_PORT", "5435"),
        "name": os.environ.get("AUTOMIC_DB_NAME", "automic"),
        "user": os.environ.get("AUTOMIC_DB_USER", "automic"),
    }


def build_requirements(*, connection: Optional[Dict[str, Any]] = None,
                       source_type: Optional[str] = None,
                       quota_gb: Optional[float] = None,
                       disk_overhead: Optional[float] = None) -> List[Dict[str, Any]]:
    """Kurulumda 'şu olmalı' listesi — gruplanmış maddeler."""
    conn = connection or {}
    host = (conn.get("host") or "").strip() or "AE_Oracle_host"
    port = conn.get("port") or 1521
    service = (conn.get("service_name") or conn.get("service") or "").strip() or "SERVICE_NAME"
    use_tcps = bool(conn.get("tcps") or conn.get("protocol") == "tcps")
    is_fake = (source_type or "").lower() == "fake"
    mdb = module_db_endpoint()
    qgb = float(quota_gb or 100)
    oh = float(disk_overhead or 1.5)
    min_disk = int(round(qgb * oh))

    groups: List[Dict[str, Any]] = [
        {
            "title": "Ainew platformu",
            "items": [
                {"must": True, "text": "UI erişimi (varsayılan HTTPS/HTTP :3000) ve API (:8000) çalışır durumda olmalı."},
                {"must": True, "text": "UC4 Automic sayfaları (`/automation/*`) ve özel Automic asistanı için kullanıcıya `automation` modül yetkisi verilmeli."},
                {"must": True, "text": "Sistem ekleme/düzenleme için `integrations` modülü + en az operator rolü gerekir."},
                {"must": False, "text": "Unified Yönetici sohbeti (`admin` / `ai_automation` / `executive`): Automic soruları için ayrıca `automation` yetkisi gerekmez — diğer platformlar gibi `automic_*` araçları açılır."},
            ],
        },
        {
            "title": "Modül veritabanı (ainew tarafı)",
            "items": [
                {"must": True, "text": f"`automic_db` (TimescaleDB/Postgres) ayakta olmalı — varsayılan `127.0.0.1:{mdb['port']}` (ainew :5432, dropt :5433, centrify :5434 ile çakışmaz)."},
                {"must": True, "text": f"Ortam: `AUTOMIC_DB_HOST={mdb['host']}`, `AUTOMIC_DB_PORT={mdb['port']}`, `AUTOMIC_DB_NAME={mdb['name']}`, `AUTOMIC_DB_USER={mdb['user']}`, `AUTOMIC_DB_PASSWORD` (veya `AUTOMIC_DATABASE_URL`)."},
                {"must": True, "text": f"Disk: kota {qgb:g} GB × overhead {oh:g} ≈ en az ~{min_disk} GB boş alan (WAL/sıkıştırma payı)."},
                {"must": True, "text": "Compose: `docker-compose.automic.yml` include edilmiş olmalı (`docker compose up -d automic-db`)."},
            ],
        },
        {
            "title": "Automic kaynak DB (automic_source, salt okunur)",
            "items": [
                {"must": True, "text": "Kaynak, kurulumda verilen bağlantıdır; uygulama primary/standby/kopya varsaymaz. Rol yalnızca bilgilendirme için V$DATABASE'den okunur."},
                {"must": True, "text": f"Firewall / ağ: ainew sunucusu → Oracle host TCP{(('/TCPS') if use_tcps else '')} erişimi. Hedef örnek: `{host}:{port}` (servis `{service}`). SCAN/VIP IP'leri de açılmalı."},
                {"must": True, "text": "DNS: AE host adı ainew sunucusundan çözülmeli (veya bağlantıda IP kullanın)."},
                {"must": True, "text": "Servis kullanıcısı yalnız SELECT; şema sahibi / `master` / `uc4` / `system` / `sys` reddedilir. Gerekli tablolarda doğrudan SELECT (view şart değil)."},
                {"must": True, "text": "Yetki listesi: `docs/guides/tr/modules/automic-source-dba-grants.md` (ae-24.4-columns.yaml + V_$DATABASE)."},
                {"must": True, "text": "Resmi AE tabloları (keşifle doğrulanır): AH, EH, RH/RT, OH, OT, OFS, JPP — yalnız SELECT; USR tablosu okunmaz."},
                {"must": False, "text": "`V_$DATAGUARD_STATS` SELECT yetkisi varsa apply lag okunur; yoksa veya kaynak standby değilse sessizce atlanır."},
                {"must": False, "text": "Oracle 12.1+; NNE/TCPS zorunluysa Instant Client + `ORACLE_CLIENT_LIB_DIR` (thick mod) gerekir. Backend imajında `python-oracledb` kurulu olmalı."},
                {"must": False, "text": "AE zaman damgalarını UTC tutar (resmi dokümantasyon); ainew UTC varsayar, farklı görünürse keşifte işaretler."},
            ],
        },
        {
            "title": "REST API (bu sürümde zorunlu değil)",
            "items": [
                {"must": False, "text": "AE'nin DB'deki ERT alanları (AH_ERT / EH_Ert / EH_ERTEnd / OH_Ert) DB kaynağıyla zaten okunur. Forecast ve AE process (sunucu) sağlığı REST adaptörüyle sonraki sürümde gelecek; şu an yalnız DB kaynağı kullanılır."},
                {"must": False, "text": "Kurumda REST varsa not alın: tipik portlar 8088/8089/8090; TLS politikası ve istek aralığı (ör. ≥10 sn) kurum kuralına bağlıdır. DB ile aynı AE sistemine ait olmadıkça birlikte kullanılmaz."},
            ],
        },
        {
            "title": "Güvenlik ve operasyon",
            "items": [
                {"must": True, "text": "Her oturumda SET TRANSACTION READ ONLY; tüm SQL merkezi sql_guard'dan geçer (yalnız SELECT/WITH)."},
                {"must": True, "text": "Kaynak kimlik bilgileri AutomicSystem.connection + secret_enc'de; ainew modül DB (AUTOMIC_DB_*) ile paylaşılmaz."},
                {"must": True, "text": "DATABASE_ROLE=PRIMARY ise kurulumda açık onay + audit gerekir; çalışma sırasında rol değişirse erişim kesilmez, uyarı üretilir."},
                {"must": True, "text": "Rapor/script içeriği saklanmadan önce maskelenir (parola/token/key her zaman; IP/hostname ayarlanabilir; Automic kullanıcı adları korunur)."},
                {"must": False, "text": "Teşhis: `scripts/automic-diagnose.sh` (sır yazdırmaz). Sahte veri için `AUTOMIC_FAKE=1` veya kaynak tipi `fake`."},
            ],
        },
    ]
    if is_fake:
        groups.insert(0, {
            "title": "Geliştirme (fake kaynak)",
            "items": [
                {"must": False, "text": "Bu sistem `fake` kaynak kullanıyor — gerçek AE Oracle portu/firewall şart değil; modül DB ve `automation` yetkisi yine gerekir."},
            ],
        })
    return groups
