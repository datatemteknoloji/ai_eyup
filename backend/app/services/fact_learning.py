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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

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
    "ip_brief": "network",  # identity grubu — canlı IP özeti
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
    "selinux_status": "security", "getenforce": "security", "firewall_status": "security",
    "sudoers": "security",
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
    # Admin lite / config (yapısal — anlık doluluk değil)
    "lite_selinux": "security", "lite_sshd": "security", "lite_fstab": "disk",
    "lite_sysctl": "sysctl", "lite_net_dns": "network",
    "cfg_fstab": "disk", "cfg_dns_nss": "network", "cfg_hosts": "network",
    "cfg_sysctl": "sysctl", "cfg_limits": "limits", "cfg_sshd": "security",
    "cfg_selinux": "security", "cfg_time": "os", "cfg_firewall": "security",
    "cfg_network": "network", "cfg_ip_route": "network", "cfg_cron": "cron",
    "cfg_tuned": "os", "cfg_hostname_target": "os", "cfg_logrotate": "os",
    "cfg_sudoers_summary": "security",
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
            try:
                from app.services.chat_cache_service import invalidate_context
                invalidate_context(
                    db,
                    platform=platform if platform in ("linux", "windows") else "linux",
                    server_ids=[server.id],
                )
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"Fact learning atlandi ({getattr(server, 'name', '?')}): {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return 0

    return touched


# ── Sohbet icinde ad-hoc calistirilan READ_ONLY tool'lardan hangileri "yapisal/
# durabilir" bilgi tasir. Anlik metrik/log/process/olay iceren tool'lar (ör.
# get_processes, read_service_logs, get_kernel_errors, get_security_events)
# KASITLI OLARAK burada YOK — bu modulun tasarim ilkesine (sadece degismesi
# beklenmeyen bilgi ogrenilir) uymak icin.
TOOL_OUTPUT_STABLE_TOOLS = {
    "get_system_summary", "lvm_info", "list_free_disks", "get_mount_health",
    "get_network_status", "get_package_status", "get_security_patch_status",
    "execute_approved_command", "get_disk_usage",
}

_TOOL_FACT_CATEGORY = "chat_discovery"


def extract_facts_from_tool_output(
    db: Session, server, tool_name: str, output: Dict[str, Any],
) -> int:
    """Unified Chat'in agentic modunda serbestce cagrilan bir READ_ONLY tool'un
    ciktisindan (yalnizca TOOL_OUTPUT_STABLE_TOOLS'taki 'yapisal' araclar icin)
    kalici bir "chat_discovery" fact'i olusturur/gunceller.

    extract_and_store_facts()'ten farki: sabit bir alan whitelist'ine degil,
    dogrudan tool'un (kisaltilmis) tum ciktisina dayanir — cunku sohbet
    icinde serbestce cagrilan araclarin cikti sekli onceden bilinmez/sabit
    degildir. Boylece ad-hoc bir soruyla kesfedilen yapisal bilgi de (ör.
    "df -h ile kesfedilen mount duzeni") kalici hafizaya girer.
    """
    if tool_name not in TOOL_OUTPUT_STABLE_TOOLS or not output:
        return 0
    if not server or not getattr(server, "id", None):
        return 0
    if isinstance(output, dict) and (output.get("ok") is False or output.get("error")):
        return 0

    value_str = _stringify(output)[:_MAX_VALUE_CHARS]
    if not value_str:
        return 0

    now = datetime.now(timezone.utc)
    try:
        from app.models.learned_fact import LearnedFact

        existing = (
            db.query(LearnedFact)
            .filter(
                LearnedFact.server_id == server.id,
                LearnedFact.category == _TOOL_FACT_CATEGORY,
                LearnedFact.key == tool_name,
            )
            .first()
        )
        if existing:
            if existing.value == value_str:
                existing.last_confirmed_at = now
                existing.times_confirmed = (existing.times_confirmed or 1) + 1
            else:
                existing.value = value_str
                existing.first_learned_at = now
                existing.last_confirmed_at = now
                existing.times_confirmed = 1
            existing.source = "chat_tool"
        else:
            db.add(LearnedFact(
                server_id=server.id, category=_TOOL_FACT_CATEGORY, key=tool_name, value=value_str,
                source="chat_tool", first_learned_at=now, last_confirmed_at=now, times_confirmed=1,
            ))
        db.commit()
        return 1
    except Exception as e:
        logger.debug(f"Chat discovery fact learning atlandi ({getattr(server, 'name', '?')}/{tool_name}): {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return 0


def _age_label(dt: Optional[datetime]) -> str:
    if not dt:
        return "tarih yok"
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
            src = (r.source or "ssh").strip().lower()
            age = _age_label(r.last_confirmed_at)
            if src == "manual":
                lines.append(
                    f"- [{r.category}] {r.key} = {val} "
                    f"(MANUEL SABITLEME — canli SSH/WinRM ile celisirse CANLI veriyi esas al; "
                    f"son dogrulama: {age})"
                )
            else:
                lines.append(
                    f"- [{r.category}] {r.key} = {val} (kaynak={src}, son dogrulama: {age})"
                )
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"Learned facts block olusturulamadi: {e}")
        return ""


# ── Virt / VM envanterinden yapısal öğrenme ──────────────────────────────────
# LearnedFact.server_id → servers satırı (VM kaydı). Hypervisor sync sonrası
# VM'nin nadiren değişen alanları kalıcı hafızaya yazılır.

VIRT_STABLE_SERVER_FIELDS: Dict[str, str] = {
    "os_type": "virt_os",
    "vm_power_state": "virt_power",
    "vm_tools_status": "virt_tools",
    "vm_datastore": "virt_storage",
    "vm_cluster": "virt_cluster",
    "vm_guest_hostname": "virt_os",
    "vm_guest_ip": "virt_network",
    "vm_hardware_version": "virt_os",
    "cpu_cores": "virt_cpu",
    "memory_gb": "virt_memory",
    "vm_disk_gb": "virt_storage",
    "ip_address": "virt_network",
    "hostname": "virt_os",
}


# Değişmeyen bir fact'in "son onay" damgası bu süreden sık güncellenmez (sync her turda ~12 satırı
# boşuna UPDATE ediyordu: 1000 VM'de ~12.000 UPDATE, kayıt fazının ~%45'i). Değer değişirse hemen yazılır.
FACT_CONFIRM_MIN_INTERVAL = timedelta(hours=1)


def _confirm_or_update_fact(existing, value_str: str, now: datetime, source: str) -> bool:
    """Var olan fact'i onayla/güncelle. Satıra yazıldıysa True; sıklık sınırı yüzünden atlandıysa False."""
    if existing.value == value_str:
        last = existing.last_confirmed_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if existing.source == source and last is not None and (now - last) < FACT_CONFIRM_MIN_INTERVAL:
            return False
        existing.last_confirmed_at = now
        existing.times_confirmed = (existing.times_confirmed or 1) + 1
    else:
        existing.value = value_str
        existing.first_learned_at = now
        existing.last_confirmed_at = now
        existing.times_confirmed = 1
    existing.source = source
    return True


def extract_and_store_virt_facts(db: Session, server, *, commit: bool = True) -> int:
    """Inventory sync sonrası VM Server satırından yapısal virt fact'leri upsert eder.

    `commit=False`: çağıran toplu commit yapar (sync döngüsü 10 VM'de bir); fact yazımı SAVEPOINT içindedir,
    hata yalnız fact'leri geri alır, çağıranın bekleyen işini bozmaz.
    """
    if not server or not getattr(server, "id", None):
        return 0
    if not getattr(server, "hypervisor_id", None) and (getattr(server, "server_type", "") or "").upper() != "VIRTUAL":
        return 0

    now = datetime.now(timezone.utc)
    touched = 0
    try:
        from app.models.learned_fact import LearnedFact

        # (category, key, value) — önce hepsi toplanır, mevcut satırlar TEK sorguda okunur
        # (eskiden fact başına bir SELECT: VM başına ~14 sorgu).
        wanted: List[Tuple[str, str, str]] = []
        for attr, category in VIRT_STABLE_SERVER_FIELDS.items():
            raw = getattr(server, attr, None)
            if raw is None or raw == "":
                continue
            value_str = _stringify(raw)[:_MAX_VALUE_CHARS]
            if not value_str:
                continue
            wanted.append((category, f"virt.{attr}", value_str))

        if getattr(server, "hypervisor_id", None):
            hv_name = None
            try:
                hv = getattr(server, "hypervisor", None)
                if hv is not None:
                    hv_name = getattr(hv, "name", None)
            except Exception:
                hv_name = None
            if not hv_name:
                try:
                    from app.models.hypervisor import Hypervisor
                    hv = db.query(Hypervisor).filter(Hypervisor.id == server.hypervisor_id).first()
                    hv_name = hv.name if hv else None
                except Exception:
                    pass
            if hv_name:
                wanted.append(("virt_cluster", "virt.hypervisor_name", str(hv_name)[:200]))

        def _apply() -> int:
            n = 0
            if wanted:
                rows = (
                    db.query(LearnedFact)
                    .filter(
                        LearnedFact.server_id == server.id,
                        LearnedFact.key.in_([k for _, k, _ in wanted]),
                    )
                    .all()
                )
                existing_by = {(r.category, r.key): r for r in rows}
                for category, key, value_str in wanted:
                    existing = existing_by.get((category, key))
                    if existing:
                        if _confirm_or_update_fact(existing, value_str, now, "virt_sync"):
                            n += 1
                    else:
                        db.add(LearnedFact(
                            server_id=server.id, category=category, key=key, value=value_str,
                            source="virt_sync", first_learned_at=now, last_confirmed_at=now, times_confirmed=1,
                        ))
                        n += 1

            return n

        if commit:
            touched = _apply()
        else:
            with db.begin_nested():
                touched = _apply()

        if touched and commit:
            db.commit()
    except Exception as e:
        logger.debug("Virt fact learning atlandi (%s): %s", getattr(server, "name", "?"), e)
        if commit:
            try:
                db.rollback()
            except Exception:
                pass
        return 0
    return touched


def store_live_datastore_facts(db: Session, datastores: List[Dict[str, Any]]) -> int:
    """Canlı vCenter datastore kapasitesini ilgili VM'lerin learned fact'ine yazar.

    Öncelik zinciri (cevap tarafında): canlı SSH/vCenter → learned → DB.
    """
    if not datastores:
        return 0
    now = datetime.now(timezone.utc)
    touched = 0
    try:
        from app.models.learned_fact import LearnedFact
        from app.models.server import Server

        by_name = {str(d.get("name") or "").strip().lower(): d for d in datastores if d.get("name")}
        if not by_name:
            return 0
        servers = (
            db.query(Server)
            .filter(Server.vm_datastore.isnot(None), Server.vm_datastore != "")
            .all()
        )
        # (server, [(key, category, value)]) — mevcut fact'ler sunucu başına değil, parça başına TEK sorguda
        # okunur (eskiden fact başına SELECT: 1000 VM'de ~5000 sorgu + ~5000 UPDATE, sohbet isteğinde 7-9 sn).
        work = []
        for s in servers:
            ds_name = (s.vm_datastore or "").strip()
            d = by_name.get(ds_name.lower())
            if not d:
                continue
            pairs = []
            for key, raw in (
                ("virt.datastore_name", ds_name),
                ("virt.datastore_usage_pct", d.get("usage_pct")),
                ("virt.datastore_free_gb", d.get("free_gb")),
                ("virt.datastore_capacity_gb", d.get("capacity_gb")),
                ("virt.datastore_accessible", d.get("accessible")),
            ):
                if raw is None or raw == "":
                    continue
                pairs.append((key, "virt_storage", _stringify(raw)[:_MAX_VALUE_CHARS]))
            if pairs:
                work.append((s, pairs))

        chunk = 500
        for off in range(0, len(work), chunk):
            part = work[off:off + chunk]
            rows = (
                db.query(LearnedFact)
                .filter(
                    LearnedFact.server_id.in_([s.id for s, _ in part]),
                    LearnedFact.key.in_(sorted({k for _, ps in part for k, _, _ in ps})),
                )
                .all()
            )
            existing_by = {(r.server_id, r.category, r.key): r for r in rows}
            for s, pairs in part:
                for key, category, value_str in pairs:
                    existing = existing_by.get((s.id, category, key))
                    if existing:
                        if _confirm_or_update_fact(existing, value_str, now, "vcenter_live"):
                            touched += 1
                    else:
                        db.add(LearnedFact(
                            server_id=s.id, category=category, key=key, value=value_str,
                            source="vcenter_live",
                            first_learned_at=now, last_confirmed_at=now, times_confirmed=1,
                        ))
                        touched += 1
        if touched:
            db.commit()
    except Exception as e:
        logger.debug("store_live_datastore_facts: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return 0
    return touched


def upsert_manual_fact_correction(
    db: Session,
    server_id: int,
    key: str,
    value: str,
    category: str = "correction",
) -> Optional[Dict[str, Any]]:
    """Admin/feedback ile yanlış öğrenilmiş bilgiyi düzeltilmiş değerle kaydet."""
    if not server_id or not key or value is None:
        return None
    now = datetime.now(timezone.utc)
    value_str = _stringify(value)[:_MAX_VALUE_CHARS]
    try:
        from app.models.learned_fact import LearnedFact

        existing = (
            db.query(LearnedFact)
            .filter(
                LearnedFact.server_id == server_id,
                LearnedFact.key == key,
            )
            .first()
        )
        if existing:
            existing.value = value_str
            existing.category = category or existing.category
            existing.source = "manual"
            existing.last_confirmed_at = now
            existing.confidence = 1.0
            existing.times_confirmed = (existing.times_confirmed or 1) + 1
        else:
            existing = LearnedFact(
                server_id=server_id,
                category=category or "correction",
                key=key,
                value=value_str,
                source="manual",
                first_learned_at=now,
                last_confirmed_at=now,
                times_confirmed=1,
                confidence=1.0,
            )
            db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing.to_dict()
    except Exception as e:
        logger.warning("Manual fact correction failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return None
