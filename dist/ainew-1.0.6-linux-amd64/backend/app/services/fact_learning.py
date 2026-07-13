"""
"Sordukca arastirdikca ortami ogrenen" yapi — SSH/WinRM ile toplanan bilgilerden
KALICI, sunucuya bagli, YAPISAL gercekleri (learned facts) cikarip saklar.

Tasarim ilkesi: SADECE degismesi beklenmeyen / nadiren degisen bilgiler ogrenilir
(OS/kernel surumu, disk-mount duzeni, guvenlik yapilandirmasi, donanim, kurulu
yazilim surumleri, sysctl parametreleri...). Anlik metrikler (CPU/RAM/disk
kullanim yuzdesi, calisan process'ler, loglar, oturumlar) ASLA burada saklanmaz
ve her zaman canli SSH/WinRM'den okunur — aksi halde AI eski/degismis bir
degeri gercekmis gibi sunabilir.

Akis:
  1. collect_server_info() bir sunucudan veri cektiginde -> extract_and_store_facts()
     whitelist'teki alanlari LearnedFact tablosuna upsert eder (deger aynıysa
     times_confirmed++/last_confirmed_at guncellenir; deger degistiyse
     first_learned_at da sifirlanir — "yeniden ogrenildi" sayilir).
  2. Chat prompt'u olusturulurken get_learned_facts_block() o sunucu icin
     bilinen gercekleri kisa bir blok olarak dondurur; LLM'e bunun ONCEDEN
     OGRENILMIS oldugu ve canli BAGLAM'in her zaman ustun oldugu belirtilir.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Linux: collect_server_info() sonuc anahtarlarindan hangileri "sabit gercek"? ──
# key -> kategori. linux_info_collector.py'deki COMMAND_GROUPS'un bir alt kumesi;
# anlik/degisken olanlar (cpu_usage, disk_usage, top_processes, loglar, oturumlar,
# servis durumu vb.) KASITLI OLARAK burada YOK.
LINUX_STABLE_FACT_FIELDS: Dict[str, str] = {
    # Kernel / OS kimligi
    "kernel_version": "kernel", "kernel_full": "kernel", "kernel_proc_version": "kernel",
    "sysctl_kernel": "kernel", "kernel_modules": "kernel",
    "sysctl_important": "sysctl", "sysctl_requested": "sysctl", "sysctl_limits": "sysctl",
    "os_info": "os", "os_hostnamectl": "os", "locale_info": "os", "timezone": "os",
    "hostname_short": "os", "hostname_fqdn": "os", "runlevel": "os",
    # CPU / Donanim
    "cpu_count": "cpu", "cpu_detail": "cpu", "cpuinfo": "cpu", "cpu_logical_count": "cpu",
    "hw_system": "hardware", "hw_memory_slots": "hardware", "hw_summary": "hardware",
    "hw_model": "hardware", "pci_devices": "hardware", "usb_devices": "hardware",
    # Disk / Mount duzeni (degisen "kullanim %" degil, YAPI)
    "block_devices": "disk", "blkid_info": "disk", "fstab": "disk", "network_mounts": "disk",
    "lvm_info": "disk", "raid_info": "disk", "mounts": "disk", "boot_partition": "disk",
    "swap_devices": "memory", "thp_status": "memory",
    # Ag yapisi (arayuzler/MAC/DNS/gateway — trafik degil)
    "network_interfaces": "network", "mac_addresses": "network", "resolv_conf": "network",
    "nsswitch_conf": "network", "default_route": "network", "network_config": "network",
    # Guvenlik yapilandirmasi
    "selinux_status": "security", "firewall_status": "security", "sudoers": "security",
    "system_users": "security", "system_groups": "security", "ssh_dirs": "security",
    "audit_rules": "security",
    # Paket / yazilim surumleri
    "rpm_count": "packages", "key_packages": "packages",
    "java_version": "apps", "python_version": "apps", "node_version": "apps",
    "php_version": "apps", "ruby_version": "apps", "go_version": "apps",
    # Sistem limitleri
    "ulimits": "limits", "file_limits": "limits", "security_limits": "limits", "pid_limits": "limits",
    # SSL
    "cert_files": "ssl", "openssl_version": "ssl",
}

# ── Windows: collect_server_info() (windows_info_collector.py) sonuc anahtarlari ──
WINDOWS_STABLE_FACT_FIELDS: Dict[str, str] = {
    "os": "os",
    "hardware": "hardware",
    "network": "network",
}

_MAX_VALUE_CHARS = 2000


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def extract_and_store_facts(
    db: Session, server, info: Dict[str, Any], platform: str = "linux"
) -> int:
    """collect_server_info() ciktisindan whitelist'teki sabit gercekleri upsert eder.

    Donen deger: kac fact yeni ogrenildi/guncellendi (best-effort, hata
    durumunda sessizce 0 doner — ogrenme mekanizmasi asla chat cevabini
    bozmamali).
    """
    if not info or info.get("error") or not server or not getattr(server, "id", None):
        return 0

    whitelist = LINUX_STABLE_FACT_FIELDS if platform == "linux" else WINDOWS_STABLE_FACT_FIELDS
    now = datetime.now(timezone.utc)
    touched = 0

    try:
        from app.models.learned_fact import LearnedFact

        for field_key, category in whitelist.items():
            if field_key not in info or not info[field_key]:
                continue
            raw_value = info[field_key]

            # Windows alanlari (os/hardware/network) dict/list oldugu icin bir
            # ust seviye "duzlestirme" yapilir — her alt alan kendi fact'i olur.
            entries: List[tuple]
            if platform != "linux" and isinstance(raw_value, dict):
                entries = [(f"{field_key}.{k}", v) for k, v in raw_value.items() if v not in (None, "")]
            elif platform != "linux" and isinstance(raw_value, list):
                entries = [(field_key, raw_value)]
            else:
                entries = [(field_key, raw_value)]

            for fact_key, fact_value in entries:
                value_str = _stringify(fact_value)[:_MAX_VALUE_CHARS]
                if not value_str:
                    continue

                existing = (
                    db.query(LearnedFact)
                    .filter(
                        LearnedFact.server_id == server.id,
                        LearnedFact.category == category,
                        LearnedFact.key == fact_key,
                    )
                    .first()
                )
                if existing:
                    if existing.value == value_str:
                        existing.last_confirmed_at = now
                        existing.times_confirmed = (existing.times_confirmed or 1) + 1
                    else:
                        # Deger degisti — yeniden ogrenilmis sayilir
                        existing.value = value_str
                        existing.first_learned_at = now
                        existing.last_confirmed_at = now
                        existing.times_confirmed = 1
                    existing.source = "ssh" if platform == "linux" else "winrm"
                else:
                    db.add(LearnedFact(
                        server_id=server.id, category=category, key=fact_key, value=value_str,
                        source="ssh" if platform == "linux" else "winrm",
                        first_learned_at=now, last_confirmed_at=now, times_confirmed=1,
                    ))
                touched += 1

        if touched:
            db.commit()
    except Exception as e:
        logger.debug(f"Fact learning atlandi ({getattr(server, 'name', '?')}): {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return 0

    return touched


def _age_label(dt: Optional[datetime]) -> str:
    if not dt:
        return "bilinmiyor"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    days = delta.days
    if days <= 0:
        hours = max(1, delta.seconds // 3600)
        return f"{hours} saat once"
    if days == 1:
        return "1 gun once"
    if days < 30:
        return f"{days} gun once"
    return f"{days // 30} ay once"


def get_learned_facts_block(db: Session, server, max_items: int = 25) -> str:
    """Bir sunucu icin onceden ogrenilmis gercekleri LLM prompt'una eklenebilecek
    kisa bir metin blogu olarak dondurur (bos ise "")."""
    if not server or not getattr(server, "id", None):
        return ""
    try:
        from app.models.learned_fact import LearnedFact

        rows = (
            db.query(LearnedFact)
            .filter(LearnedFact.server_id == server.id)
            .order_by(LearnedFact.category, LearnedFact.key)
            .limit(max_items)
            .all()
        )
        if not rows:
            return ""
        lines = []
        for r in rows:
            val = (r.value or "").replace("\n", " ").strip()
            if len(val) > 200:
                val = val[:200] + "…"
            lines.append(f"- [{r.category}] {r.key} = {val} (son dogrulama: {_age_label(r.last_confirmed_at)})")
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"Learned facts block olusturulamadi: {e}")
        return ""
