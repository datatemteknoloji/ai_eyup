"""
Hypervisor Intelligence — Doğal dil ile altyapı sorgulama motoru.

Desteklenen soru tipleri:
  1. Envanter    → "kaç esx host var", "hangi vm hangi host'ta"
  2. Kapasite    → "doluluk durumu", "en yoğun host"
  3. Karşılaştır → "bu vm ile bunu karşılaştır"
  4. Tools       → "vmware tools olanlar / olmayanlar"
  5. OS          → "rhel vm'ler", "windows olanlar"
  6. Değerlendirme → "ortam değerlendirmesi"
  7. Özel soru   → genel LLM bağlamıyla yanıtla

Mimari:
  - build_full_context()  → Tüm hypervisor + VM + ESX metrik verisini toplar
  - detect_intent()       → Sorudan hangi veri odağının gerektiğini bulur
  - answer_question()     → Context + soru → Ollama → cevap
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings, get_active_model
from app.models.event import SystemEvent
from app.models.hypervisor import Hypervisor
from app.models.infrastructure_report import BusinessServiceMap
from app.models.server import Server
from app.services import llm_gateway

logger = logging.getLogger(__name__)

# ── Sanallaştırma AI kimliği ────────────────────────────────────────────────
# Linux (chat.py) ve Windows (windows_chat.py) sohbetlerindeki kıdemli admin
# personasıyla aynı derinlikte — bu modül de kendi alanının (sanallaştırma)
# uzmanı gibi düşünmeli/cevap vermeli, jenerik/kısa bir "VMware/KVM uzmanı"
# tanımından ibaret kalmamalı.
_VIRTUALIZATION_PERSONA = (
    "Sen 15+ yıllık deneyime sahip kıdemli bir "
    "Sanallaştırma Yöneticisisin (Senior Virtualization Administrator).\n\n"
    "UZMANLIK ALANLARIN:\n"
    "- VMware vSphere/ESXi (vCenter, DRS, HA, vMotion, Storage vMotion, vSAN)\n"
    "- KVM/oVirt/oLVM (cluster, storage domain, live migration, snapshot yönetimi)\n"
    "- Proxmox VE (cluster, ZFS/Ceph storage, LXC/QEMU)\n"
    "- Microsoft Hyper-V (Failover Cluster, Live Migration, VHDX yönetimi)\n"
    "- Kapasite planlama: CPU/RAM overcommit oranları, datastore/storage doluluk analizi, "
    "kaynak darboğazı tespiti\n"
    "- VM yaşam döngüsü: provisioning, template/klonlama, kaynak resize, snapshot/backup stratejisi\n"
    "- Ağ sanallaştırma: vSwitch/vDS, VLAN, port group tasarımı\n"
    "- Lisanslama ve sürüm uyumluluğu, guest OS/Tools durumu, HA/DRS risk değerlendirmesi\n\n"
    "VERİ DİSİPLİNİ — KRİTİK:\n"
    "- Ortamda vCenter/hypervisor bağlantısı vardır; cevapları SAĞLANAN CANLI VERİYE dayandır.\n"
    "- 'Bilinmiyor', 'bu veriye erişimim yok', 'collector yok', 'senkronize edilmiyor' deme — "
    "veri blokunda yoksa yalnızca bağlantı/sorgu hatasını veya 'canlı sorguda kayıt dönmedi'yi söyle.\n"
    "- Tahmin etme, uydurma; eksik alan için boş bırak veya 'sorguda gelmedi' yaz.\n\n"
    "YANIT UZUNLUĞU — VARSAYILAN KISA: Varsayılan olarak KISA, SADE ve NET cevap ver — "
    "basit/doğrudan bir soruya ('kaç VM var?', 'hangi ESX'te?' gibi) 1-3 cümlelik doğrudan "
    "cevap ya da küçük bir tablo yeterlidir; gereksiz giriş cümlesi veya istenmeyen ek yorum "
    "ekleme. SADECE kullanıcı açıkça 'detaylı anlat', 'derinlemesine incele', 'risk "
    "değerlendirmesi yap' derse ya da soru gerçekten kapasite/sağlık değerlendirmesi "
    "gerektiriyorsa kapasite riskini, olası kök nedeni ve somut aksiyon önerisini de ekle."
)

# ── Intent keywords ───────────────────────────────────────────────────────────
INTENT_PATTERNS = {
    "count_hosts":     r"kaç\s+(esx|host|sunucu)|how many.*(esx|host)",
    "vm_per_host":     r"hangi\s+esx.*kaç|hangi\s+host.*vm|vm.*dağılım|esx.*vm\s+sayı",
    "capacity":        r"doluluk|kapasite|boş.*yer|boş\s*kayna|ne kadar (dolu|boş)|cpu.*memory.*dolu|yoğun|kapasit|free\s*capacity",
    "compare_vms":     r"karşılaştır|compare|fark.*nedir|farkı|vs\b|versus",
    "tools_status":    r"vmware\s+tools|vm.*tools|tools\s+(olan|olmayan|yüklü|kurulu)",
    "os_filter":       r"\b(rhel|oel|oracle|windows|win\s*sunucu|ubuntu|centos|rocky|linux)\b",
    "powered_off":     r"kapalı|powered.off|shut.*down|çalışmayan",
    "assessment":      r"değerlendirme|assessment|genel\s+durum|rapor|özet|nasıl.*ortam|sağlık",
    "network":         r"network|\bağ\b|10g|1g|bant\s*genişliği|interface|\bvlan\b|port\s*group|portgroup|vswitch|vds",
    "snapshot":        r"snapshot|anlık\s+görüntü",
    "report":          r"rapor|report|üret|oluştur|göster.*rapor",
}

# ── Rapor intent eşleşme tablosu ─────────────────────────────────────────────
REPORT_KEYWORD_MAP = {
    "executive_summary":      [r"executive|yönetici\s+özet|genel\s+(sağlık|özet|durum)|üst\s+yönetim|tek\s+sayfalık"],
    "capacity":               [r"kapasite\s+rapor|capacity\s+report|doluluk\s+rapor|ne\s+zaman\s+dol|kullanım\s+trend"],
    "risk":                   [r"risk\s+(dashboard|rapor)|kritik\s+risk|risk\s+özet|kritik\s+alarmlar.n.\s+rapor"],
    "vm_health":              [r"vm\s+sağlık|sağlık\s+skor|health\s+scor"],
    "resource_usage":         [r"kaynak\s+kullanım|en\s+çok\s+(cpu|ram|disk)\s+tüketen|en\s+fazla\s+kaynak\s+tüketen|resource\s+usage"],
    "security_compliance":    [r"güvenlik.*uyum|compliance|security.*rapor"],
    "consolidation":          [r"konsolidasyon|boşta.*vm|kapalı.*vm.*rapor|israf|kullanılmayan.*düşük\s+kullanılan|düşük\s+kullanılan\s+vm|kaynak\s+optimizasyon|fazla\s+cpu.ram\s+atanmış"],
    "lifecycle":              [r"yaşam\s+döngüsü|lifecycle|eski.*sürüm|upgrade.*gerek|vm\s+büyüme\s+trend|vm\s+artış.azalış"],
    "anomaly":                [r"anomali.*rapor|anormal.*rapor|tespit.*rapor"],
    "forecast":               [r"tahmin|forecast|3\s*ay|6\s*ay|12\s*ay|büyüme\s+tahmin|kapasite\s+tükenme|kapasite\s+projeksiyon"],
    "finance":                [r"maliyet|finans|finance|cost\s+report|para"],
    "riskiest_assets":        [r"en\s+riskli|riskiest|yüksek\s+risk.*varlık"],
    "operations":             [r"operasyon\s+rapor|ops.*report|aktivite\s+rapor"],
    "performance_bottleneck": [r"darboğaz|bottleneck|performans.*sorun|cpu\s+ready|latency"],
    "sla":                    [r"sla|erişilebilirlik|uptime|kesinti.*rapor"],
    "business_impact":        [r"iş\s+servisi|business\s+impact|servis\s+etki|kritik\s+vm.lerin\s+ha\s+uygunluk"],
}


def _tr_lower(s: str) -> str:
    """Türkçe büyük 'İ' → 'i' dönüşümü. Python'un str.lower()'ı 'İ'yi 'i̇' (iki
    karakter: i + combining dot) yapar; bu da regex eşleşmelerini kırar."""
    return s.replace("İ", "i").replace("I", "ı").lower()


# Yazı ile sayılar ("bir ay", "iki hafta") — sık kullanılan ilk 12 sayı yeterli.
_TR_NUMBER_WORDS = {
    "bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7,
    "sekiz": 8, "dokuz": 9, "on": 10, "onbir": 11, "oniki": 12, "yarım": 0.5,
}
_TR_UNIT_TO_DAYS = {
    "saat": 1 / 24, "gün": 1, "gunun": 1, "hafta": 7, "ay": 30, "yıl": 365, "sene": 365,
}
_PERIOD_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(saat|gün|hafta|ay|yıl|sene)\w*"
)
_BARE_UNIT_RE = re.compile(r"\b(bugün|dün|geçen\s+hafta|bu\s+hafta|geçen\s+ay|bu\s+ay|geçen\s+yıl|bu\s+yıl|saat|gün|hafta|ay|yıl|sene)\b")


def _normalize_numbers(s: str) -> str:
    """Yazı ile sayıları rakama çevirir — yalnızca zaman birimi önünde.

    Örn. "bir ay" -> "1 ay", "on gün" -> "10 gün".
    İngilizce "powered on" içindeki "on" ASLA 10 olmamalı.
    """
    for word, num in _TR_NUMBER_WORDS.items():
        s = re.sub(
            rf"\b{word}\b(?=\s*(?:saat|gün|hafta|ay|yıl|sene)\w*)",
            str(num),
            s,
        )
    return s


def _parse_days_from_question(question: str, default: int = 7) -> int:
    """
    Soru metninden zaman penceresini (gün cinsinden) çıkarır: "son 15 gün",
    "2 ay", "1 yıl", "3 hafta", "geçen ay", "dün", "bugün" vb. — süre gerçekten
    önemsiz olmalı: kullanıcı ne yazarsa yazsın aynı handler doğru pencereyi
    kullanabilsin diye TÜM zaman-pencereli handler'lar bu fonksiyonu çağırır.
    Eşleşme yoksa `default` (handler'ın orijinal varsayılanı) döner.
    """
    q = _normalize_numbers(_tr_lower(question))

    m = _PERIOD_RE.search(q)
    if m:
        n = float(m.group(1).replace(",", "."))
        unit = m.group(2)
        days = n * _TR_UNIT_TO_DAYS.get(unit, 1)
        return max(1, round(days))

    if re.search(r"\bbugün\b", q):
        return 1
    if re.search(r"\bdün\b", q):
        return 2
    if re.search(r"geçen\s+hafta|bu\s+hafta", q):
        return 7
    if re.search(r"geçen\s+ay|bu\s+ay", q):
        return 30
    if re.search(r"geçen\s+yıl|bu\s+yıl", q):
        return 365

    m2 = _BARE_UNIT_RE.search(q)
    if m2 and m2.group(1) in _TR_UNIT_TO_DAYS:
        return max(1, round(_TR_UNIT_TO_DAYS[m2.group(1)]))

    return default


def detect_intent(question: str) -> List[str]:
    """Sorudan intent listesi çıkar (birden fazla olabilir)."""
    q = _tr_lower(question)
    intents = []
    for intent, pattern in INTENT_PATTERNS.items():
        if re.search(pattern, q, re.IGNORECASE):
            intents.append(intent)
    if not intents:
        intents = ["general"]
    return intents


def detect_report_type(question: str) -> Optional[str]:
    """Soru bir rapor isteği mi? Hangi rapor tipine karşılık geliyor?"""
    q = _tr_lower(question)
    # Önce "rapor" kelimesi var mı?
    if not re.search(r"rapor|report|üret|oluştur|göster|ver|forecast|tahmin|chargeback|showback|sla|dr\s+hazırlık", q):
        return None
    for rtype, patterns in REPORT_KEYWORD_MAP.items():
        for pat in patterns:
            if re.search(pat, q, re.IGNORECASE):
                return rtype
    # Genel rapor isteği ama tip belirtilmemiş → executive summary
    if re.search(r"genel\s+rapor|ortam\s+rapor|durum\s+rapor|executive", q):
        return "executive_summary"
    return None


def _extract_vm_names(question: str, vm_names: List[str]) -> List[str]:
    """Soru metninde geçen VM adlarını bul."""
    q_lower = question.lower()
    found = []
    for name in vm_names:
        if name.lower() in q_lower:
            found.append(name)
    return found[:4]  # max 4 VM


# ── Veri toplama fonksiyonları ────────────────────────────────────────────────

def _get_hypervisors(db: Session) -> List[Dict[str, Any]]:
    hvs = db.query(Hypervisor).all()
    result = []
    for hv in hvs:
        result.append({
            "id": hv.id,
            "name": hv.name,
            "type": hv.hypervisor_type.value if hasattr(hv.hypervisor_type, 'value') else str(hv.hypervisor_type),
            "ip": hv.ip_address,
            "status": hv.status,
            "last_sync": hv.last_sync.strftime("%Y-%m-%d %H:%M") if hv.last_sync else None,
        })
    return result


def _get_esx_hosts(db: Session) -> List[Dict[str, Any]]:
    """En güncel ESX host metriklerini getir."""
    try:
        rows = db.execute(text("""
            SELECT DISTINCT ON (host_name)
                host_name, hypervisor_id,
                cpu_usage_pct, cpu_usage_mhz, cpu_total_mhz, cpu_cores,
                mem_used_mb, mem_total_mb, mem_usage_pct,
                ds_used_gb, ds_total_gb, ds_usage_pct,
                net_rx_kbps, net_tx_kbps,
                vms_running, vms_total,
                connection_state, power_state, maintenance_mode,
                timestamp
            FROM hypervisor_host_metrics
            ORDER BY host_name, timestamp DESC
        """)).all()
    except Exception:
        return []

    result = []
    for r in rows:
        mem_free_gb = round((r.mem_total_mb - r.mem_used_mb) / 1024, 1) if r.mem_total_mb and r.mem_used_mb else None
        cpu_free_pct = round(100 - r.cpu_usage_pct, 1) if r.cpu_usage_pct is not None else None
        result.append({
            "host": r.host_name,
            "hypervisor_id": r.hypervisor_id,
            "cpu_pct": round(r.cpu_usage_pct, 1) if r.cpu_usage_pct else 0,
            "cpu_free_pct": cpu_free_pct,
            "cpu_cores": r.cpu_cores,
            "cpu_mhz_used": r.cpu_usage_mhz,
            "cpu_mhz_total": r.cpu_total_mhz,
            "mem_pct": round(r.mem_usage_pct, 1) if r.mem_usage_pct else 0,
            "mem_free_gb": mem_free_gb,
            "mem_total_gb": round(r.mem_total_mb / 1024, 1) if r.mem_total_mb else None,
            "ds_pct": round(r.ds_usage_pct, 1) if r.ds_usage_pct else 0,
            "ds_free_gb": round(r.ds_total_gb - r.ds_used_gb, 1) if r.ds_total_gb and r.ds_used_gb else None,
            "ds_total_gb": r.ds_total_gb,
            "vms_running": r.vms_running,
            "vms_total": r.vms_total,
            "state": r.connection_state,
            "maintenance": bool(r.maintenance_mode),
            "last_update": r.timestamp.strftime("%Y-%m-%d %H:%M") if r.timestamp else None,
        })
    return result


def _get_host_inventory(db: Session) -> Dict[str, Dict[str, Any]]:
    """
    ESX host donanım kimliği (vendor/model) ve ağ envanterini (pnic/vswitch/
    portgroup/VLAN/vnic/DNS) host_name → {...} sözlüğü olarak getirir.
    """
    try:
        rows = db.execute(text("""
            SELECT DISTINCT ON (hypervisor_id, host_ref)
                host_name, vendor, model, uuid, cpu_model,
                pnics, vswitches, portgroups, vnics, dns
            FROM hypervisor_host_inventory
            ORDER BY hypervisor_id, host_ref, last_synced_at DESC
        """)).all()
    except Exception:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        out[r.host_name] = {
            "vendor":     r.vendor,
            "model":      r.model,
            "uuid":       r.uuid,
            "cpu_model":  r.cpu_model,
            "pnics":      r.pnics or [],
            "vswitches":  r.vswitches or [],
            "portgroups": r.portgroups or [],
            "vnics":      r.vnics or [],
            "dns":        r.dns or {},
        }
    return out


def _get_vms(db: Session, hypervisor_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """VM envanterini çek.

    Sanallaştırma modülü "bütün VM'leri" göstermeli: hem hypervisor sync ile
    gelen VM'ler (`hypervisor_id` dolu) hem de başka kaynaklardan (ör. UCMDB)
    `server_type=VIRTUAL` olarak işaretlenmiş sunucular dahil edilir —
    `report_engine._get_vms` ile tutarlı olacak şekilde.
    """
    from app.services.platform_scope import vm_filter_condition
    q = db.query(Server).filter(vm_filter_condition())
    if hypervisor_id:
        q = q.filter(Server.hypervisor_id == hypervisor_id)
    vms = q.all()

    result = []
    for vm in vms:
        # Network bilgisi — adaptör adı ve IP
        nets = vm.vm_network_info or []
        net_summary = []
        for n in nets:
            ips = [ip.get("address", "") for ip in n.get("ips", []) if ip.get("address")]
            net_summary.append({
                "adapter": n.get("name", ""),
                "mac": n.get("mac", ""),
                "ips": ips,
            })

        result.append({
            "id": vm.id,
            "name": vm.name,
            "hostname": vm.hostname or vm.vm_guest_hostname or "",
            "ip": vm.ip_address or vm.vm_guest_ip or "",
            "hypervisor_id": vm.hypervisor_id,
            "vm_id": vm.hypervisor_vm_id,
            "os_type": vm.os_type or "",
            "os_version": vm.os_version or "",
            "os_release": vm.os_release_id or "",
            "cpu_count": vm.vm_cpu_count or vm.cpu_cores,
            "memory_gb": round((vm.vm_memory_mb or 0) / 1024, 1) if vm.vm_memory_mb else vm.memory_gb,
            "disk_gb": vm.vm_disk_gb,
            "power_state": vm.vm_power_state or "unknown",
            "tools_status": vm.vm_tools_status or "unknown",
            "cluster": vm.vm_cluster or "",
            "datastore": vm.vm_datastore or "",
            "hw_version": vm.vm_hardware_version or "",
            "network": net_summary,
            "tier": getattr(vm, "tier", "unknown") or "unknown",
            "last_sync": vm.vm_last_sync.strftime("%Y-%m-%d %H:%M") if vm.vm_last_sync else None,
        })
    return result


# ── Context builder ───────────────────────────────────────────────────────────

def build_context(
    db: Session,
    question: str,
    vm_names_to_compare: Optional[List[str]] = None,
) -> str:
    """
    Soruya göre optimize edilmiş bağlam metni oluşturur.
    LLM token limitini aşmamak için gereksiz veriyi kırpar.
    """
    intents = detect_intent(question)
    hypervisors = _get_hypervisors(db)
    esx_hosts = _get_esx_hosts(db)
    host_inventory = _get_host_inventory(db)
    vms = _get_vms(db)

    # Hypervisor → host mapping
    hv_map = {hv["id"]: hv for hv in hypervisors}
    host_hv_map: Dict[str, str] = {}
    for host in esx_hosts:
        hv = hv_map.get(host["hypervisor_id"], {})
        host_hv_map[host["host"]] = hv.get("name", "")

    # VM → host mapping (vm'in hypervisor_id üzerinden)
    vm_host_map: Dict[int, str] = defaultdict(str)
    for vm in vms:
        hv = hv_map.get(vm["hypervisor_id"], {})
        vm_host_map[vm["id"]] = hv.get("name", "")

    parts: List[str] = []

    # ── Bölüm 1: Hypervisor özeti ────────────────────────────────────────────
    hv_lines = []
    for hv in hypervisors:
        hv_lines.append(f"  - {hv['name']} ({hv['type']}) @ {hv['ip']} | Durum: {hv['status']} | Son sync: {hv['last_sync']}")
    parts.append(f"## HYPERVISOR'LAR ({len(hypervisors)} adet)\n" + "\n".join(hv_lines))

    # ── Bölüm 2: ESX host durumu ────────────────────────────────────────────
    host_lines = []
    for h in sorted(esx_hosts, key=lambda x: -x["cpu_pct"]):
        hv_name = hv_map.get(h["hypervisor_id"], {}).get("name", "?")
        maint = " [BAKIM MODU]" if h["maintenance"] else ""
        inv = host_inventory.get(h["host"], {})
        hw_line = ""
        if inv.get("vendor") or inv.get("model"):
            hw_line = f"\n    Donanım: {inv.get('vendor') or 'Bilinmiyor'} {inv.get('model') or ''}".rstrip()
            if inv.get("cpu_model"):
                hw_line += f" | CPU: {inv['cpu_model']}"
        host_lines.append(
            f"  - {h['host']} [{hv_name}]{maint}\n"
            f"    CPU: %{h['cpu_pct']} kullanımda (%{h['cpu_free_pct']} boş, {h['cpu_cores']} core)\n"
            f"    RAM: %{h['mem_pct']} kullanımda ({h['mem_free_gb']} GB boş / {h['mem_total_gb']} GB toplam)\n"
            f"    Disk: %{h['ds_pct']} kullanımda ({h['ds_free_gb']} GB boş / {h['ds_total_gb']} GB toplam)\n"
            f"    VM: {h['vms_running']} çalışan / {h['vms_total']} toplam"
            f"{hw_line}"
        )
    parts.append(f"## ESX / KVM HOST'LARI ({len(esx_hosts)} adet)\n" + "\n".join(host_lines))

    # ── Bölüm 2b: Ağ envanteri (NIC/vSwitch/port group/VLAN/VMkernel) ────────
    # Network / capacity / genel envanter sorularında detay ekle.
    if any(i in intents for i in ("network", "assessment", "capacity", "general")):
        net_lines = []
        for h in esx_hosts:
            inv = host_inventory.get(h["host"])
            if not inv:
                continue
            lines = [f"  - {h['host']}:"]
            if inv.get("vendor") or inv.get("model"):
                lines.append(f"    Donanım: {inv.get('vendor') or '?'} {inv.get('model') or ''} (UUID: {inv.get('uuid') or '?'})")

            pnics = inv.get("pnics") or []
            if pnics:
                pnic_txt = ", ".join(
                    f"{p.get('device','?')} ({p.get('link_speed_mb','?')}Mb, MTU {p.get('mtu','?')}, MAC {p.get('mac','?')})"
                    for p in pnics
                )
                lines.append(f"    Fiziksel NIC: {pnic_txt}")
            else:
                lines.append("    Fiziksel NIC: Veri yok")

            vswitches = inv.get("vswitches") or []
            if vswitches:
                vs_txt = ", ".join(
                    f"{vs.get('name','?')} ({len(vs.get('pnics') or [])} pnic, {len(vs.get('portgroups') or [])} port group)"
                    for vs in vswitches
                )
                lines.append(f"    vSwitch: {vs_txt}")
            else:
                lines.append("    vSwitch: Veri yok")

            portgroups = inv.get("portgroups") or []
            if portgroups:
                pg_txt = ", ".join(
                    f"{pg.get('name','?')} (VLAN {pg.get('vlan_id') if pg.get('vlan_id') is not None else '0'}, {pg.get('vswitch_name','?')})"
                    for pg in portgroups
                )
                lines.append(f"    Port Group / VLAN: {pg_txt}")
            else:
                lines.append("    Port Group / VLAN: Veri yok")

            vnics = inv.get("vnics") or []
            if vnics:
                vn_txt = ", ".join(
                    f"{vn.get('device','?')}={vn.get('ip_address') or '?'}/{vn.get('subnet_mask') or '?'} "
                    f"({'DHCP' if vn.get('dhcp') else 'Statik'}, MTU {vn.get('mtu','?')}, {vn.get('portgroup','?')})"
                    for vn in vnics
                )
                lines.append(f"    VMkernel NIC: {vn_txt}")
            else:
                lines.append("    VMkernel NIC: Veri yok")

            dns = inv.get("dns") or {}
            if dns.get("servers"):
                dhcp_txt = "DHCP" if dns.get("dhcp") else "Statik"
                lines.append(f"    DNS: {', '.join(dns['servers'])} ({dhcp_txt}, domain: {dns.get('domain_name') or '?'})")

            net_lines.append("\n".join(lines))

        if net_lines:
            parts.append(f"## ESX HOST AĞ & DONANIM ENVANTERİ\n" + "\n".join(net_lines))
        else:
            parts.append(
                "## ESX HOST AĞ & DONANIM ENVANTERİ\n"
                "  Henüz host ağ envanteri canlı çekilmedi — vCenter sync bekleniyor "
                "(arka planda periyodik çalışır veya Entegrasyonlar'dan manuel sync)."
            )

    # ── Bölüm 3: VM envanteri ────────────────────────────────────────────────
    if "compare_vms" in intents and vm_names_to_compare:
        target_vms = [vm for vm in vms if vm["name"].lower() in [n.lower() for n in vm_names_to_compare]]
        if len(target_vms) >= 2:
            vm_lines = [_vm_detail_block(vm, hv_map) for vm in target_vms]
            parts.append(f"## KARŞILAŞTIRILAN VM'LER\n" + "\n".join(vm_lines))
        else:
            parts.append(_vm_list_block(vms, hv_map, intents))
    else:
        parts.append(_vm_list_block(vms, hv_map, intents))

    # ── Bölüm 3b: Cluster özeti (vm_cluster alanına göre) ─────────────────────
    cluster_parts = _cluster_summary_block(vms, esx_hosts)
    if cluster_parts:
        parts.append(cluster_parts)

    # ── Bölüm 4: Datastore kapasite (vCenter canlı) + VM disk tahsisi ────────
    for vm in vms:
        vm["hypervisor"] = hv_map.get(vm["hypervisor_id"], {}).get("name", "Bilinmiyor")

    live_ds = _get_live_datastores(db)
    ds_summary = _datastore_vm_disk_summary(vms, esx_hosts, live_datastores=live_ds)
    if ds_summary:
        parts.append(ds_summary)

    # ── Bölüm 5: Ortam özeti (her soruda) ────────────────────────────────────
    parts.append(_environment_totals_block(hypervisors, esx_hosts, vms))

    return "\n\n".join(parts)


def _cluster_summary_block(vms: List[Dict], esx_hosts: List[Dict]) -> str:
    from collections import defaultdict
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for vm in vms:
        groups[(vm.get("cluster") or "").strip() or "Atanmamış"].append(vm)
    if not groups:
        return ""
    lines = [
        "## CLUSTER / KAYNAK HAVUZU ÖZETİ",
        "_Not: vCenter Cluster objesi ayrı sync edilmiyor; VM `vm_cluster` alanına göre gruplanır._",
    ]
    for name, group in sorted(groups.items(), key=lambda x: -len(x[1])):
        on = sum(1 for v in group if str(v.get("power_state") or "").lower() in ("powered_on", "poweredon", "up", "running"))
        cpu = sum(int(v.get("cpu_count") or 0) for v in group)
        ram = sum(float(v.get("memory_gb") or 0) for v in group)
        lines.append(
            f"  - {name}: {len(group)} VM ({on} açık) · vCPU={cpu} · RAM≈{round(ram, 1)} GB"
        )
    if esx_hosts:
        lines.append("")
        lines.append("## HOST METRİK ÖZETİ (CPU/RAM/DISK)")
        for h in sorted(esx_hosts, key=lambda x: -(x.get("cpu_pct") or 0))[:40]:
            lines.append(
                f"  - {h['host']}: CPU %{h.get('cpu_pct')} · RAM %{h.get('mem_pct')} "
                f"({h.get('mem_free_gb')} GB boş) · Disk %{h.get('ds_pct')} · "
                f"VM {h.get('vms_running')}/{h.get('vms_total')}"
            )
    return "\n".join(lines)


def _environment_totals_block(
    hypervisors: List[Dict],
    esx_hosts: List[Dict],
    vms: List[Dict],
) -> str:
    on = sum(
        1
        for v in vms
        if str(v.get("power_state") or "").lower() in ("powered_on", "poweredon", "up", "running")
    )
    return (
        "## ORTAM TOPLAMLARI\n"
        f"  Hypervisor: {len(hypervisors)}\n"
        f"  Host: {len(esx_hosts)}\n"
        f"  VM: {len(vms)} ({on} açık / {len(vms) - on} kapalı veya bilinmeyen)\n"
        "  Bu bağlam host metrikleri, VM envanteri, cluster/datastore grupları ve "
        "(uygun sorularda) ağ/donanım envanterini içerir. Sync sonrası günceldir; "
        "canlı anlık performans için Sync VMs / host metrik sync çalıştırın."
    )


def _vm_detail_block(vm: Dict[str, Any], hv_map: Dict) -> str:
    hv_name = hv_map.get(vm["hypervisor_id"], {}).get("name", "?")
    nets = "\n    ".join(
        f"  {n['adapter']}: {', '.join(n['ips']) or 'IP yok'} (MAC: {n['mac']})"
        for n in vm["network"]
    ) or "  Bilgi yok"
    return (
        f"### VM: {vm['name']}\n"
        f"  Hypervisor   : {hv_name}\n"
        f"  IP           : {vm['ip']}\n"
        f"  OS           : {vm['os_version'] or vm['os_type'] or 'Bilinmiyor'} ({vm['os_release']})\n"
        f"  vCPU         : {vm['cpu_count']} çekirdek\n"
        f"  RAM          : {vm['memory_gb']} GB\n"
        f"  Disk         : {vm['disk_gb']} GB\n"
        f"  Güç Durumu   : {vm['power_state']}\n"
        f"  VMware Tools : {vm['tools_status']}\n"
        f"  Cluster      : {vm['cluster'] or '-'}\n"
        f"  Datastore    : {vm['datastore'] or '-'}\n"
        f"  HW Versiyonu : {vm['hw_version'] or '-'}\n"
        f"  Ortam Tieri  : {vm['tier']}\n"
        f"  Ağ Adaptörleri:\n    {nets}\n"
        f"  Son Sync     : {vm['last_sync'] or '-'}"
    )


def _datastore_vm_disk_summary(
    vms: List[Dict],
    esx_hosts: List[Dict],
    live_datastores: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Datastore bazında: vCenter kapasite (toplam/boş) + VM disk tahsisi.
    live_datastores verilmezse yalnızca tahsis özeti üretilir.
    """
    from collections import defaultdict

    groups: Dict[str, List[Dict]] = defaultdict(list)
    for vm in vms:
        ds = (vm.get("datastore") or "").strip()
        key = ds if ds else f"Hypervisor: {vm.get('hypervisor', 'Bilinmiyor')}"
        groups[key].append(vm)

    live_idx = _datastore_capacity_index(live_datastores or [])

    # Canlı DS'leri de ekle (üzerinde VM olmasa bile)
    for d in live_datastores or []:
        name = (d.get("name") or "").strip()
        if name and name not in groups:
            groups[name] = []

    if not groups and not live_datastores:
        return ""

    all_hv_based = bool(groups) and all(k.startswith("Hypervisor:") for k in groups)
    header_label = (
        "HYPERVİSOR BAZINDA VM DİSK TAHSİSATI"
        if all_hv_based
        else "DATASTORE KAPASİTE + VM DİSK TAHSİSATI"
    )

    lines = [f"## {header_label}"]
    if live_datastores:
        lines.append(
            "  Kaynak: vCenter Datastore summary.capacity/freeSpace (canlı) + VM vm_disk_gb tahsisi."
        )
    elif all_hv_based:
        lines.append("  NOT: vm_datastore alanı henüz dolu değil; veriler hypervisor bazında gösteriliyor.")
    else:
        lines.append(
            "  NOT: Datastore nesne kapasitesi bu yanıtta yok (vCenter canlı sorgu yok/başarısız); "
            "yalnızca VM disk tahsisi gösteriliyor — boş GB hesaplanamaz."
        )

    for group_name, group_vms in sorted(
        groups.items(),
        key=lambda x: -(
            (live_idx.get(x[0].lower()) or {}).get("capacity_gb")
            or sum(v.get("disk_gb") or 0 for v in x[1])
            or 0
        ),
    ):
        allocated_gb = sum((v.get("disk_gb") or 0) for v in group_vms)
        powered_on = sum(
            1 for v in group_vms
            if v.get("power_state") in ("POWERED_ON", "up", "running", "poweredOn")
        )
        cap = live_idx.get(group_name.lower()) if not group_name.startswith("Hypervisor:") else None

        lines.append(f"\n### {group_name}")
        if cap and cap.get("capacity_gb") is not None:
            lines.append(
                f"  Kapasite (vCenter): toplam {cap.get('capacity_gb')} GB · "
                f"kullanılan {cap.get('used_gb')} GB · boş {cap.get('free_gb')} GB · "
                f"doluluk %{cap.get('usage_pct')}"
                + (f" · tip {cap.get('type')}" if cap.get("type") else "")
                + ("" if cap.get("accessible", True) else " · ERİŞİLEMEZ")
            )
        elif not group_name.startswith("Hypervisor:"):
            lines.append("  Kapasite (vCenter): canlı sorguda bu datastore için dönmedi")

        lines.append(f"  VM Sayısı         : {len(group_vms)} ({powered_on} çalışan)")
        lines.append(f"  Toplam Tahsis Disk: {round(allocated_gb, 1)} GB (vm_disk_gb toplamı)")
        if group_vms:
            lines.append("  VM Disk Detayı   :")
            for v in sorted(group_vms, key=lambda x: -(x.get("disk_gb") or 0))[:20]:
                lines.append(
                    f"    - {v['name']} | Disk:{v.get('disk_gb') or 0} GB | "
                    f"vCPU:{v.get('cpu_count') or 0} RAM:{v.get('memory_gb') or 0}GB | "
                    f"Güç:{v['power_state']}"
                )
            if len(group_vms) > 20:
                lines.append(f"    ... ve {len(group_vms) - 20} VM daha")

    return "\n".join(lines)


def _vm_list_block(vms: List[Dict], hv_map: Dict, intents: List[str]) -> str:
    lines = []

    # Filtreler
    filtered = vms
    if "powered_off" in intents:
        filtered = [v for v in vms if v["power_state"] not in ("POWERED_ON", "up", "running")]
    elif "tools_status" in intents:
        q_lower = " ".join(intents)
        if "olmayan" in q_lower or "yüklü değil" in q_lower:
            filtered = [v for v in vms if not v["tools_status"] or "running" not in v["tools_status"].lower()]
        else:
            filtered = [v for v in vms if v["tools_status"] and "running" in v["tools_status"].lower()]

    # OS filtresi — os_release, os_version VE os_type alanlarının hepsine bakar
    os_map = {
        "rhel": "rhel", "oel": "ol", "oracle": "ol",
        "windows": "windows", "ubuntu": "ubuntu",
        "centos": "centos", "rocky": "rocky",
        "linux": ("linux", "rhel", "centos", "ubuntu", "ol", "rocky", "sles"),
    }
    intent_str = " ".join(intents)
    for kw, release in os_map.items():
        if kw in intent_str:
            releases = (release,) if isinstance(release, str) else release
            def _matches(v, releases=releases):
                haystack = " ".join([
                    (v["os_release"] or "").lower(),
                    (v["os_version"] or "").lower(),
                    (v["os_type"]    or "").lower(),
                ])
                return any(r in haystack for r in releases)
            filtered = [v for v in filtered if _matches(v)]
            break

    for vm in filtered[:50]:  # token limiti için max 50 VM
        hv_name = hv_map.get(vm["hypervisor_id"], {}).get("name", "?")
        net_ips = ", ".join(
            ip for n in vm["network"] for ip in n["ips"]
        ) or vm["ip"]
        disk_info = f" Disk:{vm['disk_gb']}GB" if vm.get("disk_gb") else ""
        ds_info   = f" Datastore:{vm['datastore']}" if vm.get("datastore") else ""
        lines.append(
            f"  - {vm['name']} | {hv_name} | OS: {vm['os_release'] or vm['os_type'] or '?'} | "
            f"vCPU:{vm['cpu_count']} RAM:{vm['memory_gb']}GB{disk_info} | "
            f"Güç:{vm['power_state']} | Tools:{vm['tools_status'] or '?'} | "
            f"IP:{net_ips}{ds_info}"
        )

    total = len(filtered)
    shown = min(50, total)
    header = f"## VM ENVANTERİ ({total} toplam"
    if shown < total:
        header += f", ilk {shown} gösteriliyor"
    header += ")"
    return header + "\n" + "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# DETERMİNİSTİK SORU-CEVAP KATMANI ("100+ soru" kataloğu)
# ═══════════════════════════════════════════════════════════════════════════
# Bu kurallar DB/canlı vCenter sorgusu ile KESİN cevaplanabilen sorularda
# LLM'e hiç gitmeden hızlı ve %100 veri-doğru yanıt üretir. Veri toplanmayan
# konularda (CPU Ready, tag, gerçek cluster/HA/DRS nesnesi, snapshot boyutu,
# per-VM network trafiği, backup, maliyet vb.) dürüstçe "veri yok" cevabı
# döner — LLM'in uydurmasını engeller. Eşleşme yoksa akış LLM+context yoluna
# düşer (mevcut davranış korunur).

def _pstate(v: Dict[str, Any]) -> str:
    return (v.get("power_state") or "").lower()


def _is_on(v: Dict[str, Any]) -> bool:
    return _pstate(v) in ("powered_on", "up", "running", "poweredon")


def _is_off(v: Dict[str, Any]) -> bool:
    return _pstate(v) in ("powered_off", "down", "poweredoff", "off")


def _is_suspended(v: Dict[str, Any]) -> bool:
    return "suspend" in _pstate(v)


def _md_table(headers: List[str], rows: List[List[Any]], empty_msg: str = "_Kayıt bulunamadı._") -> str:
    if not rows:
        return empty_msg
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join("-" if c is None else str(c) for c in row) + " |")
    return "\n".join(lines)


def _fmt_ts(ts: Optional[str]) -> str:
    if not ts:
        return "-"
    return str(ts).replace("T", " ").replace("Z", "")[:19]


def _na(detail: str) -> str:
    """Canlı sorgu sonucu boş/hatalı olduğunda kullanıcıya net teknik mesaj."""
    return (
        f"**Canlı sorgu sonucu:** {detail}\n\n"
        "_Not: Ortam bağlantısı varsa veri çekilir; 'bilinmiyor' demek yerine "
        "yukarıdaki sorgu/bağlantı sonucuna bakın._"
    )


# ── VM Durumu ────────────────────────────────────────────────────────────────

def h_restart_week(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_lifecycle as lc
    days = _parse_days_from_question(question, default=7)
    r = lc.restart_report(db, days=days)
    if r["errors"] and not r["restarts"] and not r["raw_event_count"]:
        return _na(f"vCenter event sorgusu başarısız oldu: {'; '.join(r['errors'][:2])}")
    rows = [[x["vm_name"], x["restart_count"], _fmt_ts(x["last_event_at"]), x["hypervisor"]] for x in r["restarts"][:30]]
    return (
        f"### Son {days} Günde Restart Edilen VM'ler\n\n"
        f"**Toplam restart olayı:** {r['total_restart_events']} | **Etkilenen VM sayısı:** {r['vm_count']}\n\n"
        + _md_table(["VM", "Restart Sayısı", "Son Olay", "Hypervisor"], rows, f"Son {days} günde restart tespit edilmedi.")
    )


def h_toggle_24h(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_lifecycle as lc
    days = _parse_days_from_question(question, default=1)
    r = lc.power_toggle_last_24h(db, days=days)
    rows = [[x["vm_name"], x["event_count"]] for x in r["toggled"]]
    return (
        f"### Son {days} Günde Kapatılıp Açılan VM'ler\n\n"
        + _md_table(["VM", "Olay Sayısı"], rows, f"Son {days} günde kapanıp açılan VM tespit edilmedi.")
    )


def h_longest_uptime(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    vms = [v for v in r["vms"] if v.get("uptime_days") is not None and v["power_state"] == "poweredOn"]
    if not vms:
        return _na("Canlı vCenter uptime sorgusu sonuç döndürmedi (VM'ler kapalı olabilir veya sorgu başarısız oldu).")
    vms.sort(key=lambda v: -v["uptime_days"])
    rows = [[v["name"], f"{v['uptime_days']} gün", _fmt_ts(v["boot_time"]), v["hypervisor"]] for v in vms[:20]]
    return "### En Uzun Süredir Çalışan VM'ler (ilk 20)\n\n" + _md_table(["VM", "Uptime", "Boot Zamanı", "Hypervisor"], rows)


def h_created_30d(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_lifecycle as lc
    days = _parse_days_from_question(question, default=30)
    r = lc.creation_events(db, days=days)
    rows = [[e["vm_name"], _fmt_ts(e.get("timestamp")), e.get("hypervisor")] for e in r["created"][:50]]
    return (
        f"### Son {days} Günde Oluşturulan VM'ler\n\n"
        f"**Toplam:** {len(r['created'])}\n\n"
        + _md_table(["VM", "Oluşturma Zamanı", "Hypervisor"], rows, f"Son {days} günde yeni VM oluşturulmamış.")
    )


def h_removed_30d(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_lifecycle as lc
    days = _parse_days_from_question(question, default=30)
    r = lc.removal_events(db, days=days)
    rows = [[e["vm_name"], _fmt_ts(e.get("timestamp")), e.get("hypervisor")] for e in r["removed"][:50]]
    return (
        f"### Son {days} Günde Silinen / Envanterden Çıkarılan VM'ler\n\n"
        f"**Toplam:** {len(r['removed'])}\n\n"
        + _md_table(["VM", "Silinme Zamanı", "Hypervisor"], rows, f"Son {days} günde silinen VM tespit edilmedi.")
    )


def h_powered_off_count(db: Session, question: str = "") -> str:
    vms = _get_vms(db)
    off = [v for v in vms if _is_off(v)]
    return f"### Powered Off Durumda Bekleyen VM Sayısı\n\n**{len(off)}** VM kapalı durumda (toplam {len(vms)} VM içinde).\n\n" + _md_table(
        ["VM", "Datastore", "RAM (GB)"], [[v["name"], v["datastore"] or "-", v["memory_gb"]] for v in off[:30]]
    )


def h_count_hosts(db: Session, question: str = "") -> str:
    hosts = _get_esx_hosts(db)
    rows = [[
        h.get("host"),
        h.get("state") or "-",
        h.get("vms_running"),
        h.get("vms_total"),
        f"%{h.get('cpu_pct')}" if h.get("cpu_pct") is not None else "-",
        f"%{h.get('mem_pct')}" if h.get("mem_pct") is not None else "-",
    ] for h in hosts]
    return (
        f"### ESX / Hypervisor Host Sayısı\n\n"
        f"**Toplam host:** {len(hosts)}\n\n"
        + _md_table(["Host", "Durum", "Çalışan VM", "Toplam VM", "CPU %", "RAM %"], rows, "Host metriği bulunamadı.")
    )


def h_count_vms(db: Session, question: str = "") -> str:
    vms = _get_vms(db)
    on = sum(1 for v in vms if _is_on(v))
    off = sum(1 for v in vms if _is_off(v))
    sus = sum(1 for v in vms if _is_suspended(v))
    other = len(vms) - on - off - sus
    return (
        "### VM Envanter Özeti\n\n"
        f"**Toplam VM:** {len(vms)}\n"
        f"- Çalışan (powered on): **{on}**\n"
        f"- Kapalı (powered off): **{off}**\n"
        f"- Suspended: **{sus}**\n"
        + (f"- Diğer/bilinmeyen power state: **{other}**\n" if other else "")
    )


def h_count_powered_on(db: Session, question: str = "") -> str:
    vms = _get_vms(db)
    on = [v for v in vms if _is_on(v)]
    return (
        f"### Çalışan (Powered On) VM Sayısı\n\n"
        f"**{len(on)}** VM çalışıyor (toplam {len(vms)} VM içinde).\n\n"
        + _md_table(
            ["VM", "Host/Cluster", "vCPU", "RAM (GB)"],
            [[v["name"], v.get("cluster") or "-", v.get("cpu_count"), v.get("memory_gb")] for v in on[:40]],
            "Çalışan VM yok.",
        )
    )


def h_vm_per_host(db: Session, question: str = "") -> str:
    hosts = _get_esx_hosts(db)
    if hosts:
        rows = [[h.get("host"), h.get("vms_running"), h.get("vms_total"), f"%{h.get('cpu_pct')}", f"%{h.get('mem_pct')}"]
                for h in sorted(hosts, key=lambda x: -(x.get("vms_total") or 0))]
        return "### Host Bazında VM Dağılımı\n\n" + _md_table(
            ["Host", "Çalışan", "Toplam", "CPU %", "RAM %"], rows, "Host metriği yok."
        )
    # Fallback: VM kayıtlarındaki cluster alanı
    groups: Dict[str, Dict[str, int]] = defaultdict(lambda: {"on": 0, "total": 0})
    for v in _get_vms(db):
        key = v.get("cluster") or "(cluster alanı boş)"
        groups[key]["total"] += 1
        if _is_on(v):
            groups[key]["on"] += 1
    rows = [[k, g["on"], g["total"]] for k, g in sorted(groups.items(), key=lambda x: -x[1]["total"])]
    return "### Host/Grup Bazında VM Dağılımı\n\n" + _md_table(["Host/Grup", "Çalışan", "Toplam"], rows)


def h_inventory_flash(db: Session, question: str = "") -> str:
    """Yönetici için tek bakışta envanter + doluluk."""
    hosts = _get_esx_hosts(db)
    vms = _get_vms(db)
    on = sum(1 for v in vms if _is_on(v))
    off = sum(1 for v in vms if _is_off(v))
    avg_cpu = round(sum(h.get("cpu_pct") or 0 for h in hosts) / len(hosts), 1) if hosts else 0
    avg_mem = round(sum(h.get("mem_pct") or 0 for h in hosts) / len(hosts), 1) if hosts else 0
    return (
        "### Ortam Envanter / Anlık Durum\n\n"
        f"| Metrik | Değer |\n|---|---|\n"
        f"| Host | {len(hosts)} |\n"
        f"| Toplam VM | {len(vms)} |\n"
        f"| Çalışan VM | {on} |\n"
        f"| Kapalı VM | {off} |\n"
        f"| Ort. Host CPU | %{avg_cpu} |\n"
        f"| Ort. Host RAM | %{avg_mem} |\n"
    )


def h_suspended_vms(db: Session, question: str = "") -> str:
    vms = _get_vms(db)
    sus = [v for v in vms if _is_suspended(v)]
    return "### Suspended Durumda Kalan VM'ler\n\n" + _md_table(
        ["VM", "Hypervisor ID", "Son Sync"], [[v["name"], v["hypervisor_id"], v["last_sync"] or "-"] for v in sus],
        "Suspended durumda VM bulunmuyor."
    )


def h_power_state_changes_7d(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_lifecycle as lc
    days = _parse_days_from_question(question, default=7)
    r = lc.power_state_changes(db, days=days)
    rows = [[name, cnt] for name, cnt in r["changed"][:30]]
    return f"### Son {days} Günde Power State Değiştiren VM'ler\n\n" + _md_table(["VM", "Olay Sayısı"], rows, f"Son {days} günde power state değişikliği tespit edilmedi.")


def h_last_reboot_top20(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_lifecycle as lc
    days = _parse_days_from_question(question, default=90)
    r = lc.last_reboot_times(db, days=days)
    items = sorted(r["last_reboot"].items(), key=lambda x: x[1], reverse=True)
    rows = [[name, _fmt_ts(ts)] for name, ts in items[:20]]
    return (
        f"### Son Reboot Tarihine Göre İlk 20 VM (son {days} gün penceresi)\n\n"
        + _md_table(["VM", "Son Reboot"], rows, f"Son {days} günde reboot kaydı bulunamadı.")
    )


def h_never_rebooted(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_lifecycle as lc
    days = _parse_days_from_question(question, default=90)
    vms = [v for v in _get_vms(db) if _is_on(v)]
    r = lc.last_reboot_times(db, days=days)
    rebooted_names = {n.lower() for n in r["last_reboot"].keys()}
    never = [v for v in vms if v["name"].lower() not in rebooted_names]
    return (
        f"### Hiç Reboot Edilmemiş VM'ler (son {days} günlük event penceresinde reboot kaydı yok)\n\n"
        f"_Not: Bu, {days} günden daha önce en son yeniden başlatılmış olabileceği veya event geçmişinin "
        "o kadar geriye gitmediği anlamına da gelebilir — kesin 'hiç' garantisi değildir._\n\n"
        + _md_table(["VM"], [[v["name"]] for v in never[:40]], f"Tüm çalışan VM'ler son {days} günde en az bir kez yeniden başlatılmış.")
    )


# ── CPU ──────────────────────────────────────────────────────────────────────

def h_cpu_usage_over_90(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    high = [v for v in r["vms"] if v.get("cpu_usage_pct") is not None and v["cpu_usage_pct"] >= 90]
    high.sort(key=lambda v: -v["cpu_usage_pct"])
    note = ""
    if not r["vms"]:
        return _na("Canlı VM CPU sorgusu sonuç döndürmedi.")
    return (
        "### CPU Kullanımı %90 Üzerinde Olan VM'ler (anlık)\n\n"
        + _md_table(["VM", "CPU %", "vCPU", "Hypervisor"], [[v["name"], v["cpu_usage_pct"], v["num_cpu"], v["hypervisor"]] for v in high],
                    "Şu anda CPU kullanımı %90'ın üzerinde VM yok.")
    )


def h_cpu_top20_now(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    vms = [v for v in r["vms"] if v.get("cpu_usage_mhz")]
    vms.sort(key=lambda v: -v["cpu_usage_mhz"])
    return (
        "### En Çok CPU Tüketen 20 VM (anlık ölçüm)\n\n"
        "_Not: Sorulan '24 saat' penceresi için tarihsel VM performans serisi tutulmuyor; "
        "aşağıdaki değerler şu anki canlı ölçümdür._\n\n"
        + _md_table(["VM", "CPU (MHz)", "CPU %", "Hypervisor"], [[v["name"], round(v["cpu_usage_mhz"]), v.get("cpu_usage_pct"), v["hypervisor"]] for v in vms[:20]])
    )


def h_highest_vcpu(db: Session, question: str = "") -> str:
    vms = sorted(_get_vms(db), key=lambda v: -(v.get("cpu_count") or 0))
    if not vms:
        return "VM envanteri boş."
    top = vms[:10]
    return "### En Yüksek vCPU Sayısına Sahip VM'ler\n\n" + _md_table(["VM", "vCPU"], [[v["name"], v["cpu_count"]] for v in top])


def h_overcommit_ratio(db: Session, question: str = "") -> str:
    vms = _get_vms(db)
    hosts = _get_esx_hosts(db)
    total_vcpu = sum(v.get("cpu_count") or 0 for v in vms if _is_on(v))
    total_pcpu = sum(h.get("cpu_cores") or 0 for h in hosts)
    if not total_pcpu:
        return _na("Host CPU çekirdek verisi canlı sorguda yok — ESX host metrik sync / vCenter bağlantısını kontrol edin.")
    ratio = round(total_vcpu / total_pcpu, 2)
    return (
        f"### CPU Overcommit Oranı\n\n"
        f"- Çalışan VM'lerin toplam vCPU'su: **{total_vcpu}**\n"
        f"- Host'ların toplam fiziksel çekirdek sayısı: **{total_pcpu}**\n"
        f"- **Overcommit oranı: {ratio}:1**\n\n"
        + ("Bu oran genelde 4:1'in üzerine çıktığında CPU contention riski artar." if ratio else "")
    )


def h_busiest_host_cpu(db: Session, question: str = "") -> str:
    hosts = sorted(_get_esx_hosts(db), key=lambda h: -(h.get("cpu_pct") or 0))
    if not hosts:
        return _na("ESX host metrikleri canlı sorguda dönmedi — vCenter bağlantısı / host metrik sync kontrol edin.")
    rows = [[h["host"], f"%{h['cpu_pct']}", h["cpu_cores"]] for h in hosts[:10]]
    return "### CPU Açısından En Yoğun Host'lar\n\n" + _md_table(["Host", "CPU %", "Çekirdek"], rows)


def h_cpu_not_available(db: Session, topic: str) -> str:
    """Eski stub — mümkünse canlı CPU Ready / performans sorgusuna yönlendir."""
    if "ready" in (topic or "").lower():
        return h_cpu_ready(db, topic)
    return h_cpu_top20_now(db, topic)


def h_cpu_ready(db: Session, question: str = "") -> str:
    """vCenter PerformanceManager cpu.ready (anlık % ve ms)."""
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    if r.get("errors") and not r["vms"]:
        return _na(f"vCenter CPU Ready sorgusu başarısız: {'; '.join(r['errors'][:2])}")
    with_data = [v for v in r["vms"] if v.get("cpu_ready_pct") is not None or v.get("cpu_ready_ms") is not None]
    if not with_data:
        if not r["vms"]:
            return _na("Canlı VM listesi boş — vCenter bağlantısını kontrol edin.")
        return _na(
            "PerformanceManager'da cpu.ready sayacı bu vCenter'da dönmedi "
            f"({len(r['vms'])} VM canlı okundu; ready sayacı boş)."
        )
    with_data.sort(key=lambda v: -(v.get("cpu_ready_pct") or 0))
    rows = [[
        v["name"],
        f"%{v.get('cpu_ready_pct')}" if v.get("cpu_ready_pct") is not None else "—",
        v.get("cpu_ready_ms"),
        v.get("num_cpu"),
        v.get("hypervisor"),
    ] for v in with_data[:25]]
    return (
        "### VM CPU Ready (vCenter PerformanceManager, anlık 20s)\n\n"
        "_Ready % = ready_ms / (20000 × vCPU) × 100. %5 üzeri contention belirtisi olabilir._\n\n"
        + _md_table(["VM", "Ready %", "Ready ms", "vCPU", "Hypervisor"], rows)
    )


def h_cpu_hot_add(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    if not r["vms"]:
        return _na("Canlı VM CPU Hot Add sorgusu sonuç döndürmedi.")
    rows = [[v["name"], "Açık" if str(v.get("cpu_hot_add")).lower() == "true" else "Kapalı", v["hypervisor"]] for v in r["vms"]]
    return "### VM Bazında CPU Hot Add Durumu\n\n" + _md_table(["VM", "CPU Hot Add", "Hypervisor"], rows)


def h_memory_hot_add(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    if not r["vms"]:
        return _na("Canlı VM Memory Hot Add sorgusu sonuç döndürmedi.")
    rows = [[v["name"], "Açık" if str(v.get("memory_hot_add")).lower() == "true" else "Kapalı", v["hypervisor"]] for v in r["vms"]]
    return "### VM Bazında Memory Hot Add Durumu\n\n" + _md_table(["VM", "Memory Hot Add", "Hypervisor"], rows)


def h_cpu_reservation(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    if not r["vms"]:
        return _na("Canlı VM CPU rezervasyon sorgusu sonuç döndürmedi.")
    reserved = [v for v in r["vms"] if (v.get("cpu_reservation_mhz") or 0) > 0]
    reserved.sort(key=lambda v: -(v.get("cpu_reservation_mhz") or 0))
    return (
        "### CPU Rezervasyonu Olan VM'ler\n\n"
        + _md_table(["VM", "Rezervasyon (MHz)", "vCPU", "Hypervisor"],
                    [[v["name"], v["cpu_reservation_mhz"], v["num_cpu"], v["hypervisor"]] for v in reserved],
                    "Hiçbir VM'de CPU rezervasyonu tanımlı değil.")
    )


def h_cpu_limit(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    if not r["vms"]:
        return _na("Canlı VM CPU limit sorgusu sonuç döndürmedi.")
    limited = [v for v in r["vms"] if (v.get("cpu_limit_mhz") or -1) not in (-1, None)]
    limited.sort(key=lambda v: (v.get("cpu_limit_mhz") or 0))
    return (
        "### CPU Limiti Uygulanmış VM'ler\n\n"
        "_Not: vCenter'da limit tanımsızsa değer -1 (sınırsız) döner, bu VM'ler listeye dahil edilmez._\n\n"
        + _md_table(["VM", "Limit (MHz)", "vCPU", "Hypervisor"],
                    [[v["name"], v["cpu_limit_mhz"], v["num_cpu"], v["hypervisor"]] for v in limited],
                    "Hiçbir VM'de CPU limiti tanımlı değil.")
    )


def h_memory_reservation(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    if not r["vms"]:
        return _na("Canlı VM memory rezervasyon sorgusu sonuç döndürmedi.")
    reserved = [v for v in r["vms"] if (v.get("memory_reservation_mb") or 0) > 0]
    reserved.sort(key=lambda v: -(v.get("memory_reservation_mb") or 0))
    return (
        "### Memory Rezervasyonu Olan VM'ler\n\n"
        + _md_table(["VM", "Rezervasyon (MB)", "RAM (GB)", "Hypervisor"],
                    [[v["name"], v["memory_reservation_mb"], v["mem_total_mb"] and round(v["mem_total_mb"] / 1024, 1), v["hypervisor"]] for v in reserved],
                    "Hiçbir VM'de memory rezervasyonu tanımlı değil.")
    )


# ── RAM ──────────────────────────────────────────────────────────────────────

def h_ram_usage_over_90(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    high = [v for v in r["vms"] if v.get("mem_usage_pct") is not None and v["mem_usage_pct"] >= 90]
    high.sort(key=lambda v: -v["mem_usage_pct"])
    if not r["vms"]:
        return _na("Canlı VM RAM sorgusu sonuç döndürmedi.")
    return (
        "### Bellek Kullanımı %90 Üzerinde Olan VM'ler (anlık)\n\n"
        + _md_table(["VM", "RAM %", "Kullanılan (MB)", "Tahsis (MB)"], [[v["name"], v["mem_usage_pct"], round(v["mem_used_mb"] or 0), v["mem_total_mb"]] for v in high],
                    "Şu anda RAM kullanımı %90'ın üzerinde VM yok.")
    )


def h_ballooning(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    ballooned = [v for v in r["vms"] if (v.get("ballooned_mb") or 0) > 0]
    ballooned.sort(key=lambda v: -v["ballooned_mb"])
    if not r["vms"]:
        return _na("Canlı VM bellek sorgusu sonuç döndürmedi.")
    return (
        "### Memory Ballooning Oluşan VM'ler\n\n"
        + _md_table(["VM", "Ballooned (MB)"], [[v["name"], round(v["ballooned_mb"])] for v in ballooned],
                    "Şu anda hiçbir VM'de memory ballooning tespit edilmedi (host RAM baskısı yok).")
    )


def h_swap(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    swapped = [v for v in r["vms"] if (v.get("swapped_mb") or 0) > 0]
    swapped.sort(key=lambda v: -v["swapped_mb"])
    if not r["vms"]:
        return _na("Canlı VM bellek sorgusu sonuç döndürmedi.")
    return (
        "### Swap Kullanan VM'ler\n\n"
        + _md_table(["VM", "Swapped (MB)"], [[v["name"], round(v["swapped_mb"])] for v in swapped],
                    "Şu anda swap kullanan VM tespit edilmedi.")
    )


def h_highest_ram(db: Session, question: str = "") -> str:
    vms = sorted(_get_vms(db), key=lambda v: -(v.get("memory_gb") or 0))
    return "### En Fazla RAM'e Sahip VM'ler\n\n" + _md_table(["VM", "RAM (GB)"], [[v["name"], v["memory_gb"]] for v in vms[:10]])


def h_avg_ram_top20(db: Session, question: str = "") -> str:
    vms = sorted(_get_vms(db), key=lambda v: -(v.get("memory_gb") or 0))[:20]
    return (
        "### Tahsis Edilen RAM'e Göre İlk 20 VM\n\n"
        "_Not: 'Ortalama RAM kullanımı' için tarihsel VM performans serisi tutulmuyor; sıralama tahsis edilen (allocated) RAM'e göredir._\n\n"
        + _md_table(["VM", "RAM (GB)"], [[v["name"], v["memory_gb"]] for v in vms])
    )


def h_host_ram_fill(db: Session, question: str = "") -> str:
    hosts = sorted(_get_esx_hosts(db), key=lambda h: -(h.get("mem_pct") or 0))
    if not hosts:
        return _na("ESX host metrikleri canlı sorguda dönmedi — vCenter bağlantısı / host metrik sync kontrol edin.")
    return "### Host Bazında RAM Doluluk Oranı\n\n" + _md_table(
        ["Host", "RAM %", "Boş (GB)", "Toplam (GB)"], [[h["host"], f"%{h['mem_pct']}", h["mem_free_gb"], h["mem_total_gb"]] for h in hosts]
    )


def h_host_ram_insufficient(db: Session, question: str = "") -> str:
    hosts = [h for h in _get_esx_hosts(db) if (h.get("mem_pct") or 0) >= 90]
    return "### Bellek Yetersizliği Yaşayan Host'lar (RAM ≥ %90)\n\n" + _md_table(
        ["Host", "RAM %", "Boş (GB)"], [[h["host"], f"%{h['mem_pct']}", h["mem_free_gb"]] for h in hosts],
        "RAM kullanımı %90'ın üzerinde host yok."
    )


# ── Disk / Snapshot ───────────────────────────────────────────────────────────

def h_snapshot_vms(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    with_snap = [v for v in r["vms"] if (v.get("snapshot_count") or 0) > 0]
    with_snap.sort(key=lambda v: -v["snapshot_count"])
    if not r["vms"]:
        return _na("Canlı snapshot sorgusu sonuç döndürmedi.")
    return (
        "### Snapshot Bulunan VM'ler\n\n"
        + _md_table(["VM", "Snapshot Sayısı", "En Eski Snapshot"], [[v["name"], v["snapshot_count"], _fmt_ts(v.get("snapshot_oldest"))] for v in with_snap],
                    "Hiçbir VM'de snapshot bulunmuyor.")
    )


def h_old_snapshots(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    days = _parse_days_from_question(question, default=30)
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    r = perf.fetch_live_vm_stats(db)
    old = [v for v in r["vms"] if v.get("snapshot_oldest") and str(v["snapshot_oldest"]) < cutoff]
    old.sort(key=lambda v: v["snapshot_oldest"])
    if not r["vms"]:
        return _na("Canlı snapshot sorgusu sonuç döndürmedi.")
    return (
        f"### {days} Günden Eski Snapshot'lar\n\n"
        + _md_table(["VM", "En Eski Snapshot", "Snapshot Sayısı"], [[v["name"], _fmt_ts(v["snapshot_oldest"]), v["snapshot_count"]] for v in old],
                    f"{days} günden eski snapshot bulunmuyor.")
    )


def h_disk_not_available(db: Session, topic: str) -> str:
    """Eski stub — latency / snapshot boyutu / idle disk canlı sorgularına yönlendir."""
    t = (topic or "").lower()
    if "latency" in t:
        return h_disk_latency(db, topic)
    if "snapshot" in t:
        return h_largest_snapshot(db, topic)
    if "idle" in t or "kullanılmayan" in t or "boşta" in t:
        return h_idle_disks(db, topic)
    return h_disk_iops_top(db, topic)


def h_disk_latency(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    if r.get("errors") and not r["vms"]:
        return _na(f"vCenter disk latency sorgusu başarısız: {'; '.join(r['errors'][:2])}")
    with_data = [
        v for v in r["vms"]
        if any(v.get(k) is not None for k in (
            "disk_latency_ms", "disk_read_latency_ms", "disk_write_latency_ms",
            "ds_read_latency_ms", "ds_write_latency_ms",
        ))
    ]
    if not with_data:
        if not r["vms"]:
            return _na("Canlı VM listesi boş — vCenter bağlantısını kontrol edin.")
        return _na(
            f"PerformanceManager disk/datastore latency sayaçları boş döndü "
            f"({len(r['vms'])} VM canlı okundu)."
        )

    def _lat(v):
        vals = [v.get(k) for k in (
            "disk_latency_ms", "disk_read_latency_ms", "disk_write_latency_ms",
            "ds_read_latency_ms", "ds_write_latency_ms",
        ) if v.get(k) is not None]
        return max(vals) if vals else 0

    with_data.sort(key=_lat, reverse=True)
    rows = [[
        v["name"],
        v.get("disk_latency_ms"),
        v.get("disk_read_latency_ms"),
        v.get("disk_write_latency_ms"),
        v.get("ds_read_latency_ms"),
        v.get("ds_write_latency_ms"),
        v.get("hypervisor"),
    ] for v in with_data[:25]]
    return (
        "### Disk / Datastore Latency (vCenter PerformanceManager, anlık ms)\n\n"
        + _md_table(
            ["VM", "Disk total", "vDisk read", "vDisk write", "DS read", "DS write", "Hypervisor"],
            rows,
        )
    )


def h_largest_snapshot(db: Session, question: str = "") -> str:
    """Snapshot alanı: summary.storage.uncommitted (yaklaşık) + snapshot sayısı."""
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    if not r["vms"]:
        return _na("Canlı snapshot sorgusu sonuç döndürmedi — vCenter bağlantısını kontrol edin.")
    with_snap = [v for v in r["vms"] if (v.get("snapshot_count") or 0) > 0]
    with_snap.sort(
        key=lambda v: (-(v.get("snapshot_space_gb") or 0), -(v.get("snapshot_count") or 0)),
    )
    rows = [[
        v["name"],
        v.get("snapshot_count"),
        v.get("snapshot_space_gb") if v.get("snapshot_space_gb") is not None else "—",
        _fmt_ts(v.get("snapshot_oldest")),
        v.get("hypervisor"),
    ] for v in with_snap[:25]]
    return (
        "### En Büyük / En Çok Snapshot (vCenter canlı)\n\n"
        "_Sıralama: snapshot adedi (desc), sonra en eski tarih. "
        "Byte cinsinden zincir boyutu bu API sürümünde `summary.storage` ile gelmiyor; "
        "adet + yaş üzerinden canlı listelenir._\n\n"
        + _md_table(
            ["VM", "Snapshot adedi", "Alan (GB ≈)", "En eski", "Hypervisor"],
            rows,
            "Hiçbir VM'de snapshot yok.",
        )
    )


def h_idle_disks(db: Session, question: str = "") -> str:
    """Çalışan VM'lerde anlık IOPS≈0 olanlar (boşta disk IO)."""
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    if not r["vms"]:
        return _na("Canlı disk IOPS sorgusu sonuç döndürmedi — vCenter bağlantısını kontrol edin.")
    powered = [
        v for v in r["vms"]
        if str(v.get("power_state") or "").lower() in ("poweredon", "powered_on", "on")
    ]
    idle = [
        v for v in powered
        if v.get("disk_read_iops") is not None or v.get("disk_write_iops") is not None
    ]
    idle = [
        v for v in idle
        if (v.get("disk_read_iops") or 0) + (v.get("disk_write_iops") or 0) < 0.5
    ]
    idle.sort(key=lambda v: v["name"])
    rows = [[v["name"], v.get("disk_read_iops"), v.get("disk_write_iops"), v.get("hypervisor")] for v in idle[:40]]
    return (
        "### Anlık Disk IO≈0 Olan Çalışan VM'ler (PerformanceManager)\n\n"
        "_Not: Bu anlık örneklemedir; guest içinde mount edilmemiş VMDK tespiti guest OS "
        "komutu gerektirir. IOPS sayacı boş VM'ler listelenmez._\n\n"
        + _md_table(["VM", "Read IOPS", "Write IOPS", "Hypervisor"], rows, "IOPS≈0 çalışan VM yok (veya sayaç boş).")
    )


def h_guest_disk_usage_over_90(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    with_data = [v for v in r["vms"] if v.get("guest_disk_pct") is not None]
    if not with_data:
        return _na(
            "Guest içi disk doluluk verisi hiçbir VM için gelmedi — bu bilgi VMware Tools'un "
            "çalışıyor olmasını gerektirir; Tools kapalı/kurulu değilse vCenter bu veriyi vermez."
        )
    high = sorted([v for v in with_data if v["guest_disk_pct"] >= 90], key=lambda v: -v["guest_disk_pct"])
    return (
        f"### Guest İçi Disk Doluluğu %90 Üzerinde Olan VM'ler (anlık, VMware Tools üzerinden)\n\n"
        f"_Not: {len(with_data)}/{len(r['vms'])} VM'de Tools çalışıyor ve veri döndü; diğerlerinde Tools kapalı/kurulu değil._\n\n"
        + _md_table(["VM", "Disk %", "Toplam (GB)", "Boş (GB)", "Hypervisor"],
                    [[v["name"], v["guest_disk_pct"], v["guest_disk_total_gb"], v["guest_disk_avail_gb"], v["hypervisor"]] for v in high],
                    "Guest içi disk doluluğu %90'ın üzerinde VM yok.")
    )


def h_disk_provisioning(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    with_data = [v for v in r["vms"] if v.get("disk_provisioning")]
    if not with_data:
        return _na("VM disk provisioning (thin/thick) bilgisi hiçbir VM için gelmedi.")
    rows = [[v["name"], v["disk_provisioning"], v["hypervisor"]] for v in sorted(with_data, key=lambda v: v["disk_provisioning"])]
    return (
        "### VM Disk Provisioning Tipi (thin/thick)\n\n"
        "_Not: 'mixed' — VM'in birden fazla diski var ve tipleri farklı._\n\n"
        + _md_table(["VM", "Provisioning", "Hypervisor"], rows)
    )


def h_disk_iops_top(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    with_data = [v for v in r["vms"] if v.get("disk_read_iops") is not None or v.get("disk_write_iops") is not None]
    if not with_data:
        return _na("Canlı disk IOPS sorgusu sonuç döndürmedi (PerformanceManager sayaçları bu vCenter'da bulunamadı olabilir).")
    with_data.sort(key=lambda v: -((v.get("disk_read_iops") or 0) + (v.get("disk_write_iops") or 0)))
    rows = [[v["name"], v.get("disk_read_iops"), v.get("disk_write_iops"), v["hypervisor"]] for v in with_data[:20]]
    return (
        "### En Fazla Disk IO/IOPS Kullanan VM'ler (anlık, PerformanceManager)\n\n"
        + _md_table(["VM", "Read IOPS", "Write IOPS", "Hypervisor"], rows)
    )


# ── Network ──────────────────────────────────────────────────────────────────

def h_duplicate_ip(db: Session, question: str = "") -> str:
    vms = _get_vms(db)
    by_ip: Dict[str, List[str]] = defaultdict(list)
    for v in vms:
        ip = (v.get("ip") or "").strip()
        if ip:
            by_ip[ip].append(v["name"])
    dupes = {ip: names for ip, names in by_ip.items() if len(names) > 1}
    rows = [[ip, ", ".join(names)] for ip, names in dupes.items()]
    return "### Aynı IP'yi Kullanan VM'ler\n\n" + _md_table(["IP", "VM'ler"], rows, "Çakışan IP tespit edilmedi.")


def h_no_ip_running(db: Session, question: str = "") -> str:
    vms = [v for v in _get_vms(db) if _is_on(v) and not (v.get("ip") or "").strip()]
    return "### IP Adresi Olmayan Çalışan VM'ler\n\n" + _md_table(["VM", "Hypervisor ID"], [[v["name"], v["hypervisor_id"]] for v in vms], "Tüm çalışan VM'lerde IP bilgisi mevcut.")


def h_guest_agent_down(db: Session, question: str = "") -> str:
    vms = [v for v in _get_vms(db) if _is_on(v) and (not v.get("tools_status") or "running" not in (v["tools_status"] or "").lower())]
    return "### Guest Agent / VMware Tools Çalışmayan VM'ler\n\n" + _md_table(
        ["VM", "Tools Durumu"], [[v["name"], v["tools_status"] or "sorguda gelmedi"] for v in vms], "Tüm çalışan VM'lerde Guest Agent aktif."
    )


def h_network_not_available(db: Session, topic: str) -> str:
    """Eski stub — canlı network event / trafik sorgusuna yönlendir."""
    return h_network_errors(db, topic)


def h_network_errors(db: Session, question: str = "") -> str:
    """system_events + adapter disconnected + düşük trafik özeti."""
    days = _parse_days_from_question(question, default=7)
    since = datetime.utcnow() - timedelta(days=days)
    rows_q = db.execute(text("""
        SELECT title, severity, source, created_at FROM system_events
        WHERE created_at >= :since
          AND (
            lower(title) LIKE '%network%' OR lower(title) LIKE '%nic%'
            OR lower(title) LIKE '%vlan%' OR lower(title) LIKE '%link%'
            OR lower(title) LIKE '%disconnect%' OR lower(title) LIKE '%ağ%'
          )
        ORDER BY created_at DESC LIMIT 40
    """), {"since": since}).all()
    rows = [
        [r.title[:80], r.severity, r.source, r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "-"]
        for r in rows_q
    ]
    disc = h_adapter_disconnected(db, question)
    return (
        f"### Son {days} Günde Ağ ile İlgili Olaylar\n\n"
        + _md_table(["Olay", "Önem", "Kaynak", "Zaman"], rows, f"Son {days} günde ağ olayı yok.")
        + "\n\n"
        + disc
    )


def h_network_traffic_top(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    with_data = [v for v in r["vms"] if v.get("net_rx_kbps") is not None or v.get("net_tx_kbps") is not None]
    if not with_data:
        return _na("Canlı network trafiği sorgusu sonuç döndürmedi (PerformanceManager sayaçları bu vCenter'da bulunamadı olabilir).")
    with_data.sort(key=lambda v: -((v.get("net_rx_kbps") or 0) + (v.get("net_tx_kbps") or 0)))
    rows = [[v["name"], v.get("net_rx_kbps"), v.get("net_tx_kbps"), v["hypervisor"]] for v in with_data[:20]]
    return (
        "### En Fazla Network Trafiğine Sahip VM'ler (anlık, KB/s)\n\n"
        + _md_table(["VM", "Inbound (KB/s)", "Outbound (KB/s)", "Hypervisor"], rows)
    )


def h_adapter_disconnected(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    if not r["vms"]:
        return _na("Canlı VM ağ adaptörü sorgusu sonuç döndürmedi.")
    disc = [v for v in r["vms"] if (v.get("nic_disconnected") or 0) > 0]
    rows = [[v["name"], v["nic_disconnected"], v["nic_total"], v["hypervisor"]] for v in disc]
    return (
        "### Ağ Adaptörü (NIC) Bağlantısı Kesik VM'ler\n\n"
        + _md_table(["VM", "Disconnected NIC", "Toplam NIC", "Hypervisor"], rows,
                    "Tüm VM'lerde tüm ağ adaptörleri bağlı (connected) durumda.")
    )


def h_vm_vlans(db: Session, question: str = "") -> str:
    """vCenter'dan canlı: VM → NIC → port-group → VLAN (standart + vDS)."""
    from app.services import vcenter_vm_network as vnet

    r = vnet.fetch_live_vm_vlans(db)
    rows_raw = r.get("rows") or []
    if not rows_raw:
        err = "; ".join((r.get("errors") or [])[:3])
        if err:
            return _na(f"vCenter VLAN sorgusu sonuç döndürmedi: {err}")
        return _na("vCenter'da VM ağ adaptörü / port-group bilgisi bulunamadı.")

    q = _tr_lower(question or "")
    # İsteğe bağlı: soruda geçen VM adına kaba filtre
    name_hint = None
    m = re.search(r"(?:vm|sanal\s*makine)\s*[:\-]?\s*[\"']?([a-z0-9][\w.\-]{2,})", q, re.I)
    if m:
        name_hint = m.group(1).lower()
    if name_hint:
        filtered = [x for x in rows_raw if name_hint in (x.get("vm_name") or "").lower()]
        if filtered:
            rows_raw = filtered

    table_rows = []
    for x in rows_raw[:200]:
        vlan = x.get("vlan_label")
        if vlan in (None, ""):
            vlan = x.get("vlan_id")
            vlan = "—" if vlan is None else str(vlan)
        bt = x.get("backing_type") or ""
        bt_tr = {"standard": "vSwitch", "distributed": "vDS", "opaque": "opaque"}.get(bt, bt)
        table_rows.append([
            x.get("vm_name") or "-",
            x.get("nic") or "-",
            x.get("portgroup") or "-",
            vlan,
            bt_tr,
            x.get("hypervisor") or "-",
        ])

    extra = ""
    if len(rows_raw) > 200:
        extra = f"\n\n_Not: {len(rows_raw)} satırdan ilk 200 gösterildi._"
    err_note = ""
    if r.get("errors"):
        err_note = f"\n\n_Uyarı: {'; '.join(r['errors'][:2])}_"

    return (
        "### VM Port-Group / VLAN ID'leri (vCenter canlı)\n\n"
        f"**Satır:** {len(rows_raw)} | **Hypervisor:** {r.get('hypervisors', 0)}\n\n"
        + _md_table(
            ["VM", "NIC", "Port-Group", "VLAN", "Tip", "Hypervisor"],
            table_rows,
            "Kayıt yok.",
        )
        + extra
        + err_note
    )


# ── Host Sağlığı ──────────────────────────────────────────────────────────────

def h_busiest_host_ram(db: Session, question: str = "") -> str:
    hosts = sorted(_get_esx_hosts(db), key=lambda h: -(h.get("mem_pct") or 0))
    return "### RAM Kullanımı En Yüksek Host'lar\n\n" + _md_table(["Host", "RAM %"], [[h["host"], f"%{h['mem_pct']}"] for h in hosts[:10]],
                                                                    "Host metrik verisi yok.")


def h_busiest_host_storage(db: Session, question: str = "") -> str:
    hosts = sorted(_get_esx_hosts(db), key=lambda h: -(h.get("ds_pct") or 0))
    return "### Storage Kullanımı En Yüksek Host'lar\n\n" + _md_table(["Host", "Disk %"], [[h["host"], f"%{h['ds_pct']}"] for h in hosts[:10]],
                                                                        "Host metrik verisi yok.")


def h_maintenance_hosts(db: Session, question: str = "") -> str:
    hosts = [h for h in _get_esx_hosts(db) if h.get("maintenance")]
    return "### Maintenance Modunda Olan Host'lar\n\n" + _md_table(["Host"], [[h["host"]] for h in hosts], "Maintenance modunda host yok.")


def h_host_disconnected(db: Session, question: str = "") -> str:
    hosts = [h for h in _get_esx_hosts(db) if (h.get("state") or "").lower() not in ("connected", "")]
    return "### Bağlantı Sorunu Yaşayan / Disconnected Host'lar\n\n" + _md_table(
        ["Host", "Durum"], [[h["host"], h["state"]] for h in hosts], "Tüm host'lar bağlı durumda."
    )


def h_host_most_vms(db: Session, question: str = "") -> str:
    hosts = sorted(_get_esx_hosts(db), key=lambda h: -(h.get("vms_total") or 0))
    return "### En Fazla VM Barındıran Host'lar\n\n" + _md_table(["Host", "VM Sayısı", "Çalışan"], [[h["host"], h["vms_total"], h["vms_running"]] for h in hosts[:10]])


def h_host_events_30d(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_lifecycle as lc
    days = _parse_days_from_question(question, default=30)
    r = lc.host_lifecycle_events(db, days=days)
    if r["errors"] and not r["events"]:
        return _na(f"vCenter host event sorgusu başarısız: {'; '.join(r['errors'][:2])}")
    rows = [[e.get("host_ref") or "-", e.get("event_type_id"), _fmt_ts(e.get("timestamp"))] for e in r["events"][:40]]
    return f"### Son {days} Günde Host Olayları (bağlantı/reboot/maintenance/HA)\n\n" + _md_table(["Host", "Olay Tipi", "Zaman"], rows, f"Son {days} günde host olayı tespit edilmedi.")


def h_cluster_imbalance(db: Session, question: str = "") -> str:
    hosts = _get_esx_hosts(db)
    if len(hosts) < 2:
        rows = [[h["host"], f"%{h.get('cpu_pct')}", f"%{h.get('mem_pct')}", h.get("vms_running"), h.get("vms_total")]
                for h in hosts]
        return (
            "### Host'lar Arası Yük Dengesi\n\n"
            f"**Tek host / karşılaştırılacak ikinci host yok** ({len(hosts)} host metriği). "
            "Dengesizlik analizi en az 2 host gerektirir; mevcut host özeti aşağıda.\n\n"
            + _md_table(["Host", "CPU %", "RAM %", "Çalışan VM", "Toplam VM"], rows, "Host metriği yok.")
        )
    cpu_vals = [h["cpu_pct"] for h in hosts if h.get("cpu_pct") is not None]
    if not cpu_vals:
        return _na("Host CPU metrikleri yok.")
    spread = max(cpu_vals) - min(cpu_vals)
    rows = [[h["host"], f"%{h['cpu_pct']}", f"%{h['mem_pct']}"] for h in sorted(hosts, key=lambda h: -h["cpu_pct"])]
    verdict = "**Dengesiz yük dağılımı tespit edildi** (host'lar arası CPU farkı %30+)." if spread >= 30 else "Yük dağılımı makul seviyede."
    return f"### Host'lar Arası Yük Dengesi\n\nCPU kullanım farkı: **%{round(spread,1)}**. {verdict}\n\n" + _md_table(["Host", "CPU %", "RAM %"], rows)


# ── Cluster (canlı HA/DRS + vm_cluster gruplaması) ────────────────────────────

_CLUSTER_CAVEAT = (
    "_Not: Aşağıdaki gruplama VM `vm_cluster` alanına göredir. "
    "Gerçek Cluster HA/DRS için 'HA DRS durumu' diye sorun (vCenter canlı)._ \n\n"
)


def h_cluster_vm_counts(db: Session, question: str = "") -> str:
    vms = _get_vms(db)
    groups: Dict[str, int] = defaultdict(int)
    for v in vms:
        groups[v.get("cluster") or "(cluster alanı boş)"] += 1
    rows = sorted(groups.items(), key=lambda x: -x[1])
    return "### Cluster/Grup Bazında VM Sayıları\n\n" + _CLUSTER_CAVEAT + _md_table(["Grup", "VM Sayısı"], [[k, v] for k, v in rows])


def h_cluster_cpu_ram(db: Session, question: str = "") -> str:
    vms = _get_vms(db)
    groups: Dict[str, Dict[str, float]] = defaultdict(lambda: {"cpu": 0, "ram": 0, "count": 0})
    for v in vms:
        g = groups[v.get("cluster") or "(cluster alanı boş)"]
        g["cpu"] += v.get("cpu_count") or 0
        g["ram"] += v.get("memory_gb") or 0
        g["count"] += 1
    rows = [[k, g["count"], round(g["cpu"]), round(g["ram"], 1)] for k, g in sorted(groups.items(), key=lambda x: -x[1]["ram"])]
    return "### Grup Bazında Tahsis Edilen CPU/RAM\n\n" + _CLUSTER_CAVEAT + _md_table(["Grup", "VM Sayısı", "Toplam vCPU", "Toplam RAM (GB)"], rows)


def h_cluster_not_available(db: Session, topic: str) -> str:
    """Eski stub — canlı cluster sorgusuna yönlendir."""
    return h_cluster_ha_drs(db, topic)


def h_cluster_ha_drs(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_cluster_status(db)
    if r["errors"] and not r["clusters"]:
        return _na(
            f"vCenter cluster sorgusu başarısız: {'; '.join(r['errors'][:2])}. "
            "Bağlantı/credential kontrol edin."
        )
    if not r["clusters"]:
        hosts = _get_esx_hosts(db)
        host_rows = [[
            h.get("host"),
            h.get("cpu_cores"),
            h.get("mem_total_gb"),
            f"%{h.get('cpu_pct')}",
            f"%{h.get('mem_pct')}",
            "BAKIM" if h.get("maintenance") else "OK",
        ] for h in hosts]
        return (
            "### Cluster HA/DRS (vCenter canlı)\n\n"
            "vCenter'da **ClusterComputeResource** dönmedi — ortam tek host / cluster'sız "
            "ESXi olabilir. Bu durumda HA/DRS cluster özelliği uygulanmaz.\n\n"
            "#### Host özeti (canlı metrik)\n"
            + _md_table(
                ["Host", "CPU core", "RAM (GB)", "CPU %", "RAM %", "Durum"],
                host_rows,
                "Host metrik bulunamadı.",
            )
        )
    rows = []
    for c in r["clusters"]:
        ha = "Açık" if c.get("ha_enabled") else ("Kapalı" if c.get("ha_enabled") is False else "—")
        drs = "Açık" if c.get("drs_enabled") else ("Kapalı" if c.get("drs_enabled") is False else "—")
        rows.append([
            c.get("name"),
            ha,
            drs,
            c.get("drs_behavior") or "—",
            c.get("hosts"),
            c.get("cpu_cores"),
            c.get("memory_gb"),
            c.get("overall_status") or "—",
            c.get("hypervisor"),
        ])
    return "### Cluster HA/DRS Durumu (vCenter canlı)\n\n" + _md_table(
        ["Cluster", "HA", "DRS", "DRS davranışı", "Host", "CPU core", "RAM (GB)", "Status", "Hypervisor"],
        rows,
    )


def h_unused_datastore(db: Session, question: str = "") -> str:
    """Üzerinde VM olmayan veya tahsis=0 datastore'lar — canlı kapasite ile."""
    live = _get_live_datastores(db)
    vms = _get_vms(db)
    used_names = {(v.get("datastore") or "").strip().lower() for v in vms if (v.get("datastore") or "").strip()}
    unused = []
    for d in live:
        name = (d.get("name") or "").strip()
        if not name:
            continue
        if name.lower() not in used_names:
            unused.append(d)
    if not live and not unused:
        return _na("vCenter datastore canlı sorgusu sonuç vermedi — bağlantıyı kontrol edin.")
    if not unused:
        return (
            "### Kullanılmayan Datastore\n\n"
            "_Canlı listede tüm datastore'larda en az bir VM `vm_datastore` kaydı var "
            f"({len(live)} DS tarandı)._\n\n"
            + h_datastore_by_disk(db, question)
        )
    rows = [[
        d.get("name"),
        d.get("capacity_gb"),
        d.get("free_gb"),
        f"%{d.get('usage_pct')}" if d.get("usage_pct") is not None else "—",
        d.get("hypervisor"),
    ] for d in unused]
    return (
        f"### Kullanılmayan Datastore'lar (üzerinde VM kaydı yok) — {len(unused)} adet\n\n"
        + _md_table(["Datastore", "Toplam (GB)", "Boş (GB)", "Doluluk", "Hypervisor"], rows)
    )


# ── Storage ───────────────────────────────────────────────────────────────────

def _get_live_datastores(db: Session) -> List[Dict[str, Any]]:
    """
    vCenter'dan datastore nesnesi bazında capacity/free/used çeker.
    Host metriklerindeki ds_* alanları aggregate'tir; isim bazlı boş kapasite
    yalnızca bu canlı sorgudan gelir.
    """
    try:
        from app.services import vcenter_vm_performance as perf
        r = perf.fetch_datastore_status(db)
        return list(r.get("datastores") or [])
    except Exception as e:
        logger.warning(f"[HVIntelligence] live datastore fetch failed: {e}")
        return []


def _datastore_capacity_index(datastores: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """İsim → kapasite kaydı (case-insensitive)."""
    idx: Dict[str, Dict[str, Any]] = {}
    for d in datastores:
        name = (d.get("name") or "").strip()
        if not name:
            continue
        idx[name.lower()] = d
    return idx


def h_datastore_by_disk(db: Session, question: str = "") -> str:
    vms = _get_vms(db)
    groups: Dict[str, Dict[str, float]] = defaultdict(lambda: {"disk": 0, "count": 0})
    for v in vms:
        ds = (v.get("datastore") or "").strip()
        if not ds:
            continue
        g = groups[ds]
        g["disk"] += v.get("disk_gb") or 0
        g["count"] += 1

    live = _get_live_datastores(db)
    live_idx = _datastore_capacity_index(live)

    # Canlı DS listesini birleştir (VM tahsisi olmayan DS'ler de görünsün)
    names = set(groups.keys()) | {d.get("name") for d in live if d.get("name")}
    if not names:
        return _na("Datastore bilgisi yok (`vm_datastore` boş ve vCenter sorgusu sonuç vermedi).")

    rows = []
    for name in sorted(names, key=lambda n: -(groups.get(n, {}).get("disk") or 0)):
        g = groups.get(name) or {"disk": 0, "count": 0}
        cap = live_idx.get(name.lower()) or {}
        rows.append([
            name,
            int(g["count"]),
            round(g["disk"], 1),
            cap.get("capacity_gb") if cap.get("capacity_gb") is not None else "—",
            cap.get("used_gb") if cap.get("used_gb") is not None else "—",
            cap.get("free_gb") if cap.get("free_gb") is not None else "—",
            f"%{cap['usage_pct']}" if cap.get("usage_pct") is not None else "—",
        ])

    note = (
        "_Not: **Tahsis** = VM `vm_disk_gb` toplamı (provisioned). "
        "**Toplam/Kullanılan/Boş** = vCenter datastore `summary.capacity/freeSpace` (canlı)._\n\n"
    )
    return (
        "### Datastore Kapasite + VM Disk Tahsisatı\n\n" + note
        + _md_table(
            ["Datastore", "VM", "Tahsis (GB)", "Toplam (GB)", "Kullanılan (GB)", "Boş (GB)", "Doluluk"],
            rows,
        )
    )


def h_datastore_over_85(db: Session, question: str = "") -> str:
    live = [d for d in _get_live_datastores(db) if (d.get("usage_pct") or 0) >= 85]
    if live:
        rows = [[
            d.get("name"),
            f"%{d.get('usage_pct')}",
            d.get("free_gb"),
            d.get("capacity_gb"),
            d.get("hypervisor"),
        ] for d in sorted(live, key=lambda x: -(x.get("usage_pct") or 0))]
        return "### %85 Üzeri Dolu Datastore'lar (vCenter canlı)\n\n" + _md_table(
            ["Datastore", "Doluluk", "Boş (GB)", "Toplam (GB)", "Hypervisor"], rows
        )
    # Fallback: eski host aggregate
    hosts = [h for h in _get_esx_hosts(db) if (h.get("ds_pct") or 0) >= 85]
    return (
        "### %85 Üzeri Dolu Host-Datastore Toplamları\n\n"
        "_Canlı datastore sorgusu %85 üzeri DS bulamadı; host aggregate metrikleri:_\n\n"
        + _md_table(
            ["Host", "Disk %", "Boş (GB)"],
            [[h["host"], f"%{h['ds_pct']}", h["ds_free_gb"]] for h in hosts],
            "%85 üzeri dolu datastore/host yok.",
        )
    )


def h_largest_datastore(db: Session, question: str = "") -> str:
    live = sorted(
        [d for d in _get_live_datastores(db) if d.get("capacity_gb")],
        key=lambda d: -(d.get("capacity_gb") or 0),
    )
    if live:
        rows = [[
            d.get("name"),
            d.get("capacity_gb"),
            d.get("free_gb"),
            f"%{d.get('usage_pct')}" if d.get("usage_pct") is not None else "—",
            d.get("hypervisor"),
        ] for d in live[:15]]
        return "### Datastore Kapasiteleri (büyükten küçüğe, vCenter canlı)\n\n" + _md_table(
            ["Datastore", "Toplam (GB)", "Boş (GB)", "Doluluk", "Hypervisor"], rows
        )
    hosts = sorted(_get_esx_hosts(db), key=lambda h: -(h.get("ds_total_gb") or 0))
    return "### En Büyük Depolama Kapasitesine Sahip Host'lar\n\n" + _md_table(
        ["Host", "Toplam (GB)"], [[h["host"], h["ds_total_gb"]] for h in hosts[:10]]
    )


def h_free_resources(db: Session, question: str = "") -> str:
    """Host CPU/RAM + datastore nesne bazlı boş kapasite (canlı)."""
    hosts = _get_esx_hosts(db)
    host_rows = []
    for h in hosts:
        host_rows.append([
            h.get("host"),
            f"%{h.get('cpu_pct')} (boş %{h.get('cpu_free_pct')}, {h.get('cpu_cores')} core)",
            f"%{h.get('mem_pct')} (boş {h.get('mem_free_gb')} GB / {h.get('mem_total_gb')} GB)",
            f"%{h.get('ds_pct')} (boş {h.get('ds_free_gb')} GB / {h.get('ds_total_gb')} GB — tüm DS toplamı)",
        ])

    parts = [
        "### Boş Kaynak Özeti\n",
        "_Host Disk satırı tüm datastore'ların toplamıdır. Ayrı datastore boşlukları aşağıdaki canlı tablodadır._\n",
        "#### Host\n",
        _md_table(["Host", "CPU", "RAM", "Disk (aggregate)"], host_rows, "Host metrik bulunamadı."),
        "\n#### Datastore (vCenter canlı)\n",
    ]
    # Reuse capacity table body from h_datastore_by_disk (strip heading)
    ds_block = h_datastore_by_disk(db, question)
    # drop first markdown heading line
    ds_lines = ds_block.split("\n")
    if ds_lines and ds_lines[0].startswith("###"):
        ds_lines = ds_lines[1:]
    parts.append("\n".join(ds_lines).lstrip())
    return "\n".join(parts)


def h_storage_alarms_30d(db: Session, question: str = "") -> str:
    days = _parse_days_from_question(question, default=30)
    since = datetime.utcnow() - timedelta(days=days)
    rows_q = db.execute(text("""
        SELECT title, severity, created_at FROM system_events
        WHERE source IN ('vcenter_alarm','vcenter_event') AND created_at >= :since
          AND (lower(title) LIKE '%datastore%' OR lower(title) LIKE '%storage%' OR lower(title) LIKE '%disk%')
        ORDER BY created_at DESC LIMIT 40
    """), {"since": since}).all()
    rows = [[r.title[:80], r.severity, r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "-"] for r in rows_q]
    return f"### Son {days} Günde Storage Alarmları\n\n" + _md_table(["Olay", "Önem", "Zaman"], rows, f"Son {days} günde storage ile ilgili alarm bulunmuyor.")


def h_storage_not_available(db: Session, topic: str) -> str:
    """Eski stub — canlı latency / datastore durumuna yönlendir."""
    t = (topic or "").lower()
    if "latency" in t or "performans" in t:
        return h_disk_latency(db, topic)
    return h_datastore_accessibility(db, topic)


def h_datastore_accessibility(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_datastore_status(db)
    if r["errors"] and not r["datastores"]:
        return _na(f"vCenter datastore sorgusu başarısız oldu: {'; '.join(r['errors'][:2])}")
    if not r["datastores"]:
        return _na("vCenter'da datastore bulunamadı.")
    inaccessible = [d for d in r["datastores"] if not d.get("accessible")]
    rows = [[d["name"], d.get("type") or "-", f"%{d.get('usage_pct')}" if d.get("usage_pct") is not None else "-",
             d.get("host_count"), d["hypervisor"]] for d in inaccessible]
    header = f"### Erişilemeyen (Inaccessible) Datastore'lar\n\n**Toplam datastore:** {len(r['datastores'])} | **Erişilemeyen:** {len(inaccessible)}\n\n"
    return header + _md_table(["Datastore", "Tip", "Doluluk", "Bağlı Host Sayısı", "Hypervisor"], rows, "Tüm datastore'lar erişilebilir durumda.")


# ── Olaylar ve Alarm ──────────────────────────────────────────────────────────

def h_critical_alarms_24h(db: Session, question: str = "") -> str:
    days = _parse_days_from_question(question, default=1)
    since = datetime.utcnow() - timedelta(days=days)
    rows_q = db.execute(text("""
        SELECT id, title, severity, source, created_at, server_id FROM system_events
        WHERE severity IN ('critical','emergency') AND created_at >= :since
        ORDER BY created_at DESC LIMIT 40
    """), {"since": since}).all()
    rows = [[r.title[:80], r.source, r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "-"] for r in rows_q]
    label = "24 Saatte" if days <= 1 else f"{days} Günde"
    return f"### Son {label} Oluşan Kritik Alarmlar\n\n" + _md_table(["Olay", "Kaynak", "Zaman"], rows, f"Belirtilen sürede kritik alarm bulunmuyor.")


def h_vm_most_alarms_7d(db: Session, question: str = "") -> str:
    days = _parse_days_from_question(question, default=7)
    since = datetime.utcnow() - timedelta(days=days)
    rows_q = db.execute(text("""
        SELECT s.name, COUNT(*) AS cnt FROM system_events e
        JOIN servers s ON e.server_id = s.id
        WHERE e.created_at >= :since AND e.source IN ('vcenter_alarm','vcenter_event')
        GROUP BY s.name ORDER BY cnt DESC LIMIT 15
    """), {"since": since}).all()
    rows = [[r.name, r.cnt] for r in rows_q]
    return f"### Son {days} Günde En Fazla Alarm/Olay Üreten VM'ler\n\n" + _md_table(["VM", "Olay Sayısı"], rows, "VM'e bağlı alarm/olay bulunmuyor (event'ler henüz VM ile eşleşmemiş olabilir).")


def h_unresolved_alarm_vms(db: Session, question: str = "") -> str:
    rows_q = db.execute(text("""
        SELECT DISTINCT s.name, e.title, e.severity FROM system_events e
        JOIN servers s ON e.server_id = s.id
        WHERE e.resolved = false AND e.source IN ('vcenter_alarm','vcenter_event')
        ORDER BY e.severity LIMIT 40
    """)).all()
    rows = [[r.name, r.title[:60], r.severity] for r in rows_q]
    return "### Çözülmemiş Alarmı Olan VM'ler\n\n" + _md_table(["VM", "Olay", "Önem"], rows, "Çözülmemiş VM alarmı bulunmuyor.")


def h_migration_events(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_lifecycle as lc
    days = _parse_days_from_question(question, default=30)
    r = lc.migration_events(db, days=days)
    if r["errors"] and not r["migrations"] and not r["failed"]:
        return _na(f"vCenter migration event sorgusu başarısız: {'; '.join(r['errors'][:2])}")
    fail_rows = [[e["vm_name"], _fmt_ts(e.get("timestamp")), e.get("hypervisor")] for e in r["failed"][:20]]
    return f"### Son {days} Günde Başarısız Migration'lar\n\n" + _md_table(["VM", "Zaman", "Hypervisor"], fail_rows, f"Son {days} günde başarısız migration tespit edilmedi.")


def h_host_disconnect_events(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_lifecycle as lc
    days = _parse_days_from_question(question, default=30)
    r = lc.host_lifecycle_events(db, days=days)
    disc = [e for e in r["events"] if "disconnect" in (e.get("event_type_id") or "").lower()]
    rows = [[e.get("host_ref") or "-", _fmt_ts(e.get("timestamp")), e.get("hypervisor")] for e in disc[:30]]
    return f"### Son {days} Günde Host Disconnect Olayları\n\n" + _md_table(["Host", "Zaman", "Hypervisor"], rows, f"Son {days} günde host disconnect olayı tespit edilmedi.")


def h_events_not_available(db: Session, topic: str) -> str:
    """Eski stub — vCenter/system_events canlı aramasına yönlendir."""
    return h_events_keyword_search(db, topic)


def h_events_keyword_search(db: Session, question: str = "") -> str:
    """Backup / crash / snapshot silme vb. için system_events + vCenter event taraması."""
    q = (question or "").lower()
    days = _parse_days_from_question(question, default=30)
    since = datetime.utcnow() - timedelta(days=days)

    from app.services import vcenter_vm_lifecycle as lc

    keywords = []
    title = "Olay araması"
    event_types = list(lc.RESTART_TYPES)
    if "backup" in q or "yedek" in q:
        keywords = ["backup", "veeam", "vdp", "replication", "yedek"]
        title = "Backup / yedek ile ilgili olaylar"
        event_types = list(lc.RESTART_TYPES)  # vCenter'da native backup event az; DB + restart proxy
    elif "crash" in q or "çök" in q:
        keywords = ["crash", "blue screen", "bsod", "panic", "halted", "reset", "ha restarted", "failed"]
        title = "VM crash / reset ile ilgili olaylar"
        event_types = list(lc.RESTART_TYPES) + list(lc.HA_TYPES)
    elif "snapshot" in q and ("sil" in q or "delete" in q or "hata" in q):
        keywords = ["snapshot", "remove", "delete", "consolidate"]
        title = "Snapshot silme / consolidate olayları"
        event_types = [
            "VmSnapshotRemovedEvent", "TaskEvent", "VmRemovedSnapshotEvent",
            "SnapshotRemovedEvent", "VmSnapshotCreatedEvent", "VmSnapshotRevertedEvent",
        ]
    else:
        keywords = [w for w in re.findall(r"[a-zçğıöşü0-9]{4,}", q) if w not in (
            "sonra", "olan", "için", "nedir", "hangi", "kadar", "olay", "alarm",
        )][:5]
        title = f"Anahtar kelime araması: {', '.join(keywords) or '—'}"

    like_clauses = " OR ".join(f"lower(title) LIKE :k{i}" for i in range(len(keywords))) or "1=0"
    params: Dict[str, Any] = {"since": since}
    for i, kw in enumerate(keywords):
        params[f"k{i}"] = f"%{kw}%"

    rows_q = []
    if keywords:
        rows_q = db.execute(text(f"""
            SELECT title, severity, source, created_at FROM system_events
            WHERE created_at >= :since AND ({like_clauses})
            ORDER BY created_at DESC LIMIT 40
        """), params).all()

    vc_rows = []
    vc_err = ""
    try:
        ev = lc.fetch_events(db, event_types, days=days, max_events=800)
        for e in (ev.get("events") or []):
            msg = " ".join(str(x or "") for x in (
                e.get("event_type_id"), e.get("message"), e.get("full_message"),
                e.get("fullFormattedMessage"), e.get("vm_name"),
            )).lower()
            if keywords and not any(k.lower() in msg for k in keywords):
                # crash/restart: restart tipleri zaten filtrelenmiş — hepsini göster
                if "crash" not in q and "backup" not in q and "snapshot" not in q:
                    continue
                if "backup" in q:
                    continue
            vc_rows.append([
                (e.get("vm_name") or e.get("entity_name") or "-")[:40],
                (e.get("event_type_id") or "-")[:50],
                _fmt_ts(e.get("timestamp")),
                e.get("hypervisor") or "-",
            ])
            if len(vc_rows) >= 25:
                break
        vc_err = "; ".join((ev.get("errors") or [])[:2])
    except Exception as exc:
        vc_err = str(exc)

    db_rows = [
        [r.title[:80], r.severity, r.source, r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "-"]
        for r in rows_q
    ]
    out = [f"### {title} (son {days} gün)\n"]
    out.append("#### system_events\n")
    out.append(_md_table(["Olay", "Önem", "Kaynak", "Zaman"], db_rows, "Eşleşen kayıt yok."))
    out.append("\n#### vCenter event stream (canlı)\n")
    if vc_err and not vc_rows:
        out.append(f"_vCenter event sorgusu: {vc_err}_\n")
    out.append(_md_table(["VM/Entity", "Event", "Zaman", "Hypervisor"], vc_rows, "Eşleşen vCenter event yok."))
    if not db_rows and not vc_rows:
        out.append(
            "\n_Canlı sorgu çalıştı; eşleşme yok. Harici backup ürünü (Veeam vb.) entegre "
            "değilse backup başarı/hata olayları yalnızca o ürünün logunda olur._"
        )
    return "\n".join(out)


# ── Envanter ──────────────────────────────────────────────────────────────────

def h_unknown_os(db: Session, question: str = "") -> str:
    vms = [v for v in _get_vms(db) if not (v.get("os_type") or v.get("os_release") or v.get("os_version"))]
    return "### İşletim Sistemi Bilgisi Bilinmeyen VM'ler\n\n" + _md_table(["VM", "Hypervisor ID"], [[v["name"], v["hypervisor_id"]] for v in vms], "Tüm VM'lerde OS bilgisi mevcut.")


def h_no_tools(db: Session, question: str = "") -> str:
    vms = [v for v in _get_vms(db) if not v.get("tools_status") or "notinstalled" in (v["tools_status"] or "").lower().replace("_", "")]
    return "### Guest Tools Kurulu Olmayan VM'ler\n\n" + _md_table(["VM", "Tools Durumu"], [[v["name"], v["tools_status"] or "sorguda gelmedi"] for v in vms], "Tüm VM'lerde Guest Tools kurulu görünüyor.")


_TOOLS_VERSION_TR = {
    "guestToolsCurrent": "Güncel",
    "guestToolsNeedUpgrade": "Güncelleme gerekiyor",
    "guestToolsNotInstalled": "Kurulu değil",
    "guestToolsSupportedOld": "Eski ama destekleniyor",
    "guestToolsSupportedNew": "Yeni ama destekleniyor",
    "guestToolsTooOld": "Çok eski (desteklenmiyor)",
    "guestToolsBlacklisted": "Kara listede (uyumsuz)",
    "guestToolsUnmanaged": "Yönetilmiyor (OVT/açık kaynak Tools)",
}


def h_tools_version_outdated(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    with_data = [v for v in r["vms"] if v.get("tools_version_status")]
    if not with_data:
        return _na("Canlı VMware Tools versiyon durumu sorgusu sonuç döndürmedi.")
    outdated = [v for v in with_data if v["tools_version_status"] not in ("guestToolsCurrent", "guestToolsSupportedNew")]
    rows = [[v["name"], _TOOLS_VERSION_TR.get(v["tools_version_status"], v["tools_version_status"]), v["hypervisor"]] for v in outdated]
    return (
        f"### VMware Tools Versiyonu Güncel Olmayan VM'ler\n\n"
        f"_{len(with_data)}/{len(r['vms'])} VM'de Tools durumu okunabildi (Tools kapalıysa veri gelmez)._\n\n"
        + _md_table(["VM", "Tools Durumu", "Hypervisor"], rows, "Tüm VM'lerde Tools versiyonu güncel.")
    )


def h_no_owner(db: Session, question: str = "") -> str:
    mapped_ids = {r[0] for r in db.query(BusinessServiceMap.server_id).all()}
    vms = [v for v in _get_vms(db) if v["id"] not in mapped_ids]
    return (
        "### Owner (Sahip) Bilgisi Olmayan VM'ler\n\n"
        f"**{len(vms)}** / {len(_get_vms(db))} VM için `Business Service Map` (owner/departman) ataması yapılmamış.\n\n"
        + _md_table(["VM"], [[v["name"]] for v in vms[:40]], "Tüm VM'lerin owner ataması mevcut.")
    )


def h_no_tag(db: Session, question: str = "") -> str:
    """vCenter customValue (Custom Attributes) canlı — etiketsiz VM listesi."""
    from app.services import vcenter_vm_performance as perf
    r = perf.fetch_live_vm_stats(db)
    if not r["vms"]:
        return _na(
            "Canlı custom attribute sorgusu sonuç döndürmedi — vCenter bağlantısını kontrol edin."
        )
    no_tag = [v for v in r["vms"] if not (v.get("custom_attrs") or [])]
    with_tag = [v for v in r["vms"] if v.get("custom_attrs")]
    rows = [[v["name"], v.get("hypervisor")] for v in no_tag[:50]]
    sample = []
    for v in with_tag[:5]:
        attrs = ", ".join(
            f"{a.get('key')}={a.get('value')}" for a in (v.get("custom_attrs") or [])[:3]
        )
        sample.append([v["name"], attrs, v.get("hypervisor")])
    return (
        "### Custom Attribute / Etiket Olmayan VM'ler (vCenter customValue, canlı)\n\n"
        f"**Etiketsiz:** {len(no_tag)} / {len(r['vms'])} · **Attribute olan:** {len(with_tag)}\n\n"
        "_Not: Bu sorgu vSphere Tags (CIS tagging) değil; Custom Attributes (`customValue`) "
        "alanıdır. CIS Tags için ayrı Tagging API gerekir._\n\n"
        + _md_table(["VM", "Hypervisor"], rows, "Tüm VM'lerde en az bir custom attribute var.")
        + ("\n\n#### Örnek attribute'lu VM'ler\n" + _md_table(["VM", "Attrs", "Hypervisor"], sample) if sample else "")
    )


def h_duplicate_names(db: Session, question: str = "") -> str:
    vms = _get_vms(db)
    by_name: Dict[str, int] = defaultdict(int)
    for v in vms:
        by_name[v["name"]] += 1
    dupes = [[name, cnt] for name, cnt in by_name.items() if cnt > 1]
    return "### Aynı İsimde Birden Fazla VM\n\n" + _md_table(["VM Adı", "Adet"], dupes, "Aynı isimde birden fazla VM tespit edilmedi.")


def h_prod_marked_test(db: Session, question: str = "") -> str:
    vms = _get_vms(db)
    suspicious = [
        v for v in vms
        if v.get("tier") == "production" and any(k in v["name"].lower() for k in ("test", "dev", "staging", "demo", "temp"))
    ]
    return (
        "### Üretim Ortamında Ama Test/Dev Gibi İsimlendirilmiş VM'ler\n\n"
        "_Heuristik: `tier=production` fakat VM adında test/dev/staging/demo/temp geçiyor._\n\n"
        + _md_table(["VM", "Tier"], [[v["name"], v["tier"]] for v in suspicious], "Şüpheli prod/test çelişkisi tespit edilmedi.")
    )


def h_unbooted_1y(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_lifecycle as lc
    days = _parse_days_from_question(question, default=365)
    off_vms = [v for v in _get_vms(db) if _is_off(v)]
    r = lc.last_reboot_times(db, days=days)
    booted_recently = set(r["last_reboot"].keys())
    candidates = [v for v in off_vms if v["name"] not in booted_recently]
    return (
        f"### Son {days} Gündür Açılmamış Olabilecek VM'ler (kapalı + belirtilen pencerede PoweredOn kaydı yok)\n\n"
        f"_Not: Event geçmişi {days} günden az kapsıyorsa bu liste eksik/aşırı geniş olabilir — kesinlik garantisi yoktur._\n\n"
        + _md_table(["VM"], [[v["name"]] for v in candidates[:40]], "Bu kritere uyan VM tespit edilmedi.")
    )


def h_health_summary_md(db: Session, question: str = "") -> str:
    from app.services.report_engine import generate_report, format_report_as_markdown
    data = generate_report(db, "executive_summary", save=False)
    return format_report_as_markdown("executive_summary", data)


def h_resource_optimization(db: Session, question: str = "") -> str:
    from app.services.report_engine import generate_report, format_report_as_markdown
    data = generate_report(db, "consolidation", save=False)
    return format_report_as_markdown("consolidation", data)


# ── Raporlama kısayolları (50 soruluk ek liste) ──────────────────────────────

def h_restart_report_30d(db: Session, question: str = "") -> str:
    from app.services import vcenter_vm_lifecycle as lc
    days = _parse_days_from_question(question, default=30)
    r = lc.restart_report(db, days=days)
    if r["errors"] and not r["restarts"] and not r["raw_event_count"]:
        return _na(f"vCenter event sorgusu başarısız oldu: {'; '.join(r['errors'][:2])}")
    rows = [[x["vm_name"], x["restart_count"], _fmt_ts(x["last_event_at"]), x["hypervisor"]] for x in r["restarts"][:40]]
    return (
        f"### Son {days} Gün VM Restart Raporu\n\n"
        f"**Toplam restart olayı:** {r['total_restart_events']} | **Etkilenen VM sayısı:** {r['vm_count']}\n\n"
        + _md_table(["VM", "Restart Sayısı", "Son Olay", "Hypervisor"], rows, f"Son {days} günde restart tespit edilmedi.")
    )


def h_alarm_trend(db: Session, question: str = "") -> str:
    days = _parse_days_from_question(question, default=30)
    since = datetime.utcnow() - timedelta(days=days)
    rows_q = db.execute(text("""
        SELECT COALESCE(event_type, source) AS etype, COUNT(*) AS cnt
        FROM system_events
        WHERE created_at >= :since AND source IN ('vcenter_alarm','vcenter_event')
        GROUP BY etype ORDER BY cnt DESC LIMIT 15
    """), {"since": since}).all()
    rows = [[r.etype, r.cnt] for r in rows_q]
    return f"### Son {days} Günde En Çok Tekrar Eden Alarm/Olay Tipleri\n\n" + _md_table(["Olay Tipi", "Adet"], rows, f"Son {days} günde alarm/olay bulunmuyor.")


# ═══════════════════════════════════════════════════════════════════════════
# KURAL TABLOSU — (regex, handler). İlk eşleşen kural çalışır.
# handler(db) -> str  veya  handler(db) -> Dict (rapor tipi kısayolları için)
# ═══════════════════════════════════════════════════════════════════════════
QA_RULES: List[Tuple[str, Any]] = [
    # ── Envanter / sayım (önce — LLM'e düşmesin; spesifik kurallar genelden önce) ──
    (r"restart\s*edilen\s*vm\s*say|kaç.*vm.*restart|son.*hafta.*restart\s*edil", h_restart_week),
    (r"kaç\s*(adet\s*)?(esx|esxi|hypervisor)?\s*host|host\s*sayıs|esx\s*sayıs|how\s*many\s*(esx|host)|toplam\s*host|host\s*adedi|kaç\s*esx", h_count_hosts),
    (r"kaç\s*(adet\s*)?(çalışan|açık|aktif)\s*vm|powered\s*on\s*(vm\s*)?say|çalışan\s*\(?powered\s*on\)?\s*vm|powered\s*on.*kaç|kaç.*powered\s*on", h_count_powered_on),
    (r"kaç\s*(adet\s*)?(kapalı|powered\s*off)\s*vm|kapalı\s*vm\s*say|powered\s*off.*kaç", h_powered_off_count),
    (r"kaç\s*(adet\s*)?vm(?!\s*restart)|vm\s*sayıs|toplam\s*vm(?!\s*restart)|how\s*many\s*vms?|vm\s*adedi|envanterde\s*kaç|kaç\s*sanal\s*makine", h_count_vms),
    (r"hangi\s*host.?ta\s*kaç\s*vm|host.?ta\s*kaç\s*vm|host\s*bazında\s*vm|vm\s*dağılımı|esx.*kaç\s*vm|hangi\s*esx.*vm", h_vm_per_host),
    (r"envanter\s*(özet|flash|özeti)|anlık\s*durum|tek\s*bakışta|ortam\s*özeti|kaç\s*host.*kaç\s*vm|genel\s*envanter", h_inventory_flash),
    (r"en\s*fazla\s*boş\s*(belle[gğk]\w*|ram|hafıza)|boş\s*(belle[gğk]\w*|ram).*(host|en\s*fazla)|ram.?i\s*en\s*boş\s*host|en\s*boş\s*(ram|bellek).*host", h_free_resources),
    (r"disconnect\s*(olan|olmuş)?\s*host|host\s*disconnect|bağlantısı\s*kop(an|muş)\s*host|bağlantı\s*kesilen\s*host", h_host_disconnected),
    (r"vmware\s*tools\s*(kurulu|yüklü)\s*olmayan|tools\s*(kurulu|yüklü)\s*olmayan|guest\s*tools\s*(kurulu|yüklü)\s*olmayan", h_no_tools),
    (r"ortam\s*genel\s*sağlık|genel\s*sağlık\s*değerlendir|sağlık\s*değerlendirmesi|executive\s*summary|yönetici\s*özet", h_health_summary_md),

    # VM Durumu
    (r"son\s*24\s*saat.*kapat.*aç|kapan.p\s*açılan\s*vm", h_toggle_24h),
    (r"en\s*uzun\s*süredir\s*çalışan\s*vm|longest.*uptime|en\s*eski\s*uptime", h_longest_uptime),
    (r"(son|geçen|bu)\s*\d*\s*(saat|gün|hafta|ay|yıl|sene)\w*.*(kurulan|oluşturulan|yeni|eklenen|yüklenen)\s*vm", h_created_30d),
    (r"(son|geçen|bu)\s*\d*\s*(saat|gün|hafta|ay|yıl|sene)\w*.*(silinen|kaldırılan)\s*vm", h_removed_30d),
    (r"powered\s*off\s*durumda\s*bekleyen|kapalı\s*durumda\s*bekleyen\s*vm\s*say|kapalı\s*vm.?ler(\s*hangileri)?|hangi\s*vm.?ler\s*kapalı", h_powered_off_count),
    (r"suspended\s*durumda|suspend(ed)?\s*(kalan|olan|durum)|suspended\s*vm|suspend\s*edilmiş", h_suspended_vms),
    (r"power\s*state\s*değiş", h_power_state_changes_7d),
    (r"son\s*reboot\s*tarihine\s*göre|ilk\s*20\s*vm.*reboot", h_last_reboot_top20),
    (r"hiç\s*reboot\s*edilmemiş", h_never_rebooted),

    # CPU
    (r"cpu\s*kullanımı\s*%?\s*90|cpu.*90.*üzer|cpu.?su\s*%?\s*90", h_cpu_usage_over_90),
    (r"en\s*çok\s*cpu\s*tüketen|cpu.*tüketen\s*20\s*vm|ortalama\s*cpu\s*kullanımına\s*göre|cpu\s*top\s*20|en\s*yoğun\s*cpu\s*vm", h_cpu_top20_now),
    (r"cpu\s*ready|ready\s*time|cpu\s*bekleme", h_cpu_ready),
    (r"cpu\s*hot\s*add|hot.?add.*cpu", h_cpu_hot_add),
    (r"vcpu\s*say.s.\s*en\s*yüksek|en\s*yüksek\s*vcpu|en\s*fazla\s*vcpu", h_highest_vcpu),
    (r"overcommit\s*oran|cpu\s*overcommit|aşırı\s*tahsis", h_overcommit_ratio),
    (r"hangi\s*host\s*cpu\s*açısından\s*en\s*yoğun|cpu.*en\s*yoğun\s*host|cpu\s*kullanımı\s*en\s*yüksek\s*host|en\s*yoğun\s*esx", h_busiest_host_cpu),
    (r"cpu\s*rezervasyon", h_cpu_reservation),
    (r"cpu\s*limiti\s*uygulanmış|cpu\s*limit\s*olan", h_cpu_limit),

    # RAM
    (r"bellek\s*kullanımı\s*%?\s*90|ram\s*kullanımı\s*%?\s*90|ram.?i\s*%?\s*90", h_ram_usage_over_90),
    (r"ballooning|memory\s*balloon|balon", h_ballooning),
    (r"swap\s*kullanan|memory\s*swap", h_swap),
    (r"memory\s*hot\s*add|hot.?add.*?(ram|memory|bellek)", h_memory_hot_add),
    (r"en\s*fazla\s*ram.a\s*sahip|en\s*fazla\s*ram'e\s*sahip|en\s*çok\s*ram\s*atanmış", h_highest_ram),
    (r"ortalama\s*ram\s*kullanımına\s*göre|ram.*ilk\s*20|en\s*çok\s*ram\s*tüketen", h_avg_ram_top20),
    (r"host\s*bazında\s*ram\s*doluluk|host.*ram\s*doluluk", h_host_ram_fill),
    (r"ram\s*kullanımında\s*ani\s*artış", h_ram_usage_over_90),
    (r"memory\s*reservation|bellek\s*rezervasyon", h_memory_reservation),
    (r"bellek\s*yetersizliği\s*yaşayan\s*host|ram\s*yetersiz.*host|memory\s*pressure", h_host_ram_insufficient),

    # Disk
    (r"disk\s*kullanımı\s*%?\s*90|guest\s*disk.*90|disk.?i\s*%?\s*90", h_guest_disk_usage_over_90),
    (r"snapshot\s*bulunan\s*vm|snapshot.?ı\s*olan|hangi\s*vm.*snapshot", h_snapshot_vms),
    (r"\d+\s*(saat|gün|hafta|ay|yıl|sene)\w*\s*eski\s*snapshot|eski\s*snapshot", h_old_snapshots),
    (r"en\s*büyük\s*snapshot", h_largest_snapshot),
    (r"thin\s*provision|thick\s*provision|disk\s*provision", h_disk_provisioning),
    (r"en\s*fazla\s*disk\s*io|disk\s*io\s*yoğunluğu|iops\s*yüksek", h_disk_iops_top),
    (r"disk\s*latency|storage\s*latency|disk\s*gecikme", h_disk_latency),
    (r"boşta\s*duran\s*disk|attached\s*olup\s*kullanılmayan|kullanılmayan\s*disk", h_idle_disks),

    # Network
    (r"aynı\s*ip.yi\s*kullanan|aynı\s*ip'yi\s*kullanan|duplicate\s*ip|çakışan\s*ip", h_duplicate_ip),
    (r"ip\s*adresi\s*olmayan\s*çalışan|ip.?si\s*olmayan\s*vm|ip\s*adresi\s*görünmeyen", h_no_ip_running),
    (r"guest\s*agent\s*çalışmayan|guest\s*agent\s*down|qemu\s*agent\s*çalışmayan", h_guest_agent_down),
    (r"vlan\s*(id|ids|bilgi)|vm.*vlan|vlan.*vm|port\s*group|portgroup|hangi\s*vlan|vlan.?leri", h_vm_vlans),
    (r"en\s*fazla\s*network\s*trafiği|outbound\s*trafik|inbound\s*trafik|network\s*throughput|ağ\s*trafiği\s*en\s*yüksek", h_network_traffic_top),
    (r"adapter\s*disconnected|nic\s*disconnected|ağ\s*adaptörü\s*kopuk", h_adapter_disconnected),
    (r"ağ\s*hatası|network\s*error|packet\s*drop|ağ\s*hatası\s*var\s*mı", h_network_errors),

    # Host Sağlığı
    (r"ram\s*kullanımı\s*en\s*yüksek\s*host|en\s*yoğun\s*ram\s*host", h_busiest_host_ram),
    (r"storage\s*kullanımı\s*en\s*yüksek\s*host", h_busiest_host_storage),
    (r"maintenance\s*modunda\s*host|bakım\s*modunda\s*host", h_maintenance_hosts),
    (r"ha.dan\s*çıkan\s*host|ha'dan\s*çıkan\s*host", h_cluster_ha_drs),
    (r"network\s*bağlantısını\s*kaybeden\s*host|host.*disconnect", h_host_disconnected),
    (r"dengesiz\s*yük\s*dağılımı|yük\s*dengesiz|load\s*imbalance|host.?lar\s*arası\s*yük", h_cluster_imbalance),
    (r"host\s*hataları\s*neler|host.*hataları|host\s*error", h_host_events_30d),
    (r"en\s*fazla\s*vm\s*barındıran\s*host|en\s*kalabalık\s*host", h_host_most_vms),
    (r"reboot\s*olan\s*host|host\s*reboot", h_host_events_30d),

    # Cluster
    (r"cluster\s*bazında\s*cpu|cluster\s*bazında\s*ram|cluster.*cpu.*ram", h_cluster_cpu_ram),
    (r"ha\s*aktif\s*olmayan\s*cluster|drs.*çalışıyor\s*mu|drs.*load\s*balancing|ha\s*/?\s*drs|cluster\s*ha|ha\s*drs\s*durum", h_cluster_ha_drs),
    (r"cluster\s*kapasitesi\s*ne\s*kadar\s*dolu|en\s*yoğun\s*cluster|kapasite\s*yetersizliği\s*riski", h_cluster_cpu_ram),
    (r"cluster\s*alarmı", h_critical_alarms_24h),
    (r"cluster\s*bazında\s*vm\s*say", h_cluster_vm_counts),
    (r"cluster\s*bazında\s*kullanılabilir\s*kaynak", h_cluster_cpu_ram),

    # Storage
    (r"ne\s*kadar\s*boş|boş\s*kayna[gğk]\w*|free\s*capacity|kaynak\s*boşlu[gğ]u|kapasite\s*boşlu[gğ]u", h_free_resources),
    (r"datastore\s*dağılım|vm.*datastore.*dağılım|datastore.*bazında.*vm|vm.*datastore.*bazında", h_datastore_by_disk),
    (r"datastore\s*kapasite|datastore.*boş|boş\s*datastore|datastore\s*doluluk|ne\s*kadar\s*boş.*(?:disk|datastore|depolama)|(?:disk|datastore|depolama).*(?:ne\s*kadar\s*boş|free)", h_datastore_by_disk),
    (r"en\s*dolu\s*datastore|85\s*%?\s*üzeri\s*dolu\s*datastore|%?\s*85\s*%?\s*üzeri\s*dolu\s*datastore|datastore.*%?\s*85", h_datastore_over_85),
    (r"storage\s*latency\s*yüksek", h_disk_latency),
    (r"storage\s*bağlantı\s*problemi|datastore.a\s*erişemeyen|datastore'a\s*erişemeyen|datastore\s*erişim\s*durumu", h_datastore_accessibility),
    (r"storage\s*alarm", h_storage_alarms_30d),
    (r"en\s*fazla\s*vm\s*barındıran\s*datastore|en\s*büyük\s*datastore", h_largest_datastore),
    (r"kullanılmayan\s*datastore", h_unused_datastore),
    (r"storage\s*performansı\s*son\s*bir\s*haftada", h_disk_latency),
    (r"datastore\s*doluluk\s*rapor", h_datastore_by_disk),

    # Olaylar ve Alarm
    (r"oluşan\s*kritik\s*alarm|kritik\s*alarmları\w*\s*göster|son\s*24\s*saat.*kritik\s*alarm|kritik\s*alarm", h_critical_alarms_24h),
    (r"en\s*fazla\s*alarm.*üreten\s*vm", h_vm_most_alarms_7d),
    (r"alarmı\s*çözülmemiş\s*vm|açık\s*alarm.*vm", h_unresolved_alarm_vms),
    (r"ha\s*olayları\s*neler|oluşan\s*ha\s*olayları", h_cluster_ha_drs),
    (r"migration\s*başarısız|vmotion\s*başarısız", h_migration_events),
    (r"backup\s*başarısız|yedekleme\s*başarısız", h_events_keyword_search),
    (r"snapshot\s*silme\s*hatası", h_events_keyword_search),
    (r"storage\s*disconnect\s*yaşandı", h_host_disconnect_events),
    (r"host\s*disconnect\s*oldu", h_host_disconnect_events),
    (r"vm\s*crash\s*tespit|vm\s*çöktü|guest\s*crash", h_events_keyword_search),

    # Envanter meta
    (r"işletim\s*sistemi\s*bilinmeyen\s*vm|os.?u\s*bilinmeyen|os\s*bilgisi\s*eksik", h_unknown_os),
    (r"tools.*qemu\s*agent\s*güncel\s*olmayan|vmware\s*tools.*güncel\s*olmayan|tools\s*güncel\s*olmayan", h_tools_version_outdated),
    (r"son\s*\d+\s*(saat|gün|hafta|ay|yıl|sene)\w*\s*açıl(mayan|mamış)|1\s*yıldır\s*açılmayan", h_unbooted_1y),
    (r"owner\s*bilgisi\s*olmayan|sahip\s*bilgisi\s*olmayan", h_no_owner),
    (r"etiketi?\s*olmayan|tag.?etiket|etiket.*eksik|custom\s*attribute|tag.?i?\s*olmayan", h_no_tag),
    (r"aynı\s*isimde\s*birden\s*fazla\s*vm|duplicate\s*vm\s*name|çakışan\s*vm\s*adı", h_duplicate_names),
    (r"üretim\s*ortamında\s*test\s*olarak\s*işaretlenmiş|prod.*test.*isim", h_prod_marked_test),

    # Raporlama kısayolları
    (r"vm\s*restart\s*rapor|restart\s*raporu", h_restart_report_30d),
    (r"alarm\s*trend\s*rapor|en\s*çok\s*tekrar\s*eden\s*alarm", h_alarm_trend),
    (r"host\s*bakım\s*geçmişi|maintenance\s*moda\s*alınan\s*host", h_host_events_30d),
    (r"migration\s*geçmişi\s*rapor", h_migration_events),
    (r"işletim\s*sistemi\s*bilgisi\s*eksik", h_unknown_os),
    (r"owner\s*bilgisi\s*olmayan\s*vm\s*rapor", h_no_owner),
    (r"tag.etiket.*eksik\s*vm.*rapor|etiket\s*bilgisi\s*eksik|etiketi?\s*olmayan\s*vm", h_no_tag),
    (r"üretim.test\s*ayrımı\s*yapılmamış", h_prod_marked_test),
    (r"guest\s*agent.tools\s*kurulu\s*olmayan\s*vm\s*rapor", h_no_tools),
    (r"kullanılmayan\s*datastore", h_unused_datastore),
    (r"kaynak\s+kullanımına\s+göre\s+optimize|optimize\s+edilmesi\s+gereken\s+vm|konsolidasyon\s*rapor", h_resource_optimization),
    (r"ortamın\s+genel\s+(sağlık\s+durumunu\s+özetle|durum)|genel\s+sağlık\s+durumunu\s+özetle", h_health_summary_md),
]


def try_deterministic_answer(db: Session, question: str) -> Optional[str]:
    """QA_RULES tablosunda eşleşen ilk kuralı çalıştırır. Hata olursa None döner (LLM yoluna düşer)."""
    q = _normalize_numbers(_tr_lower(question))
    for pattern, handler in QA_RULES:
        try:
            if re.search(pattern, q, re.IGNORECASE):
                result = handler(db, question)
                if isinstance(result, str) and result.strip():
                    return result
        except Exception as exc:
            logger.warning("[HVIntelligence] deterministic handler error (pattern=%s): %s", pattern, exc, exc_info=True)
            return None
    return None


# ── Ana sorgulama fonksiyonu ─────────────────────────────────────────────────

def answer_report_question(
    db: Session,
    question: str,
    report_type: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Rapor üret, LLM ile Türkçe analiz özeti ekle ve döndür.
    """
    from app.services.report_engine import generate_report, format_report_as_markdown, REPORT_TITLES

    t0 = datetime.utcnow()
    data = generate_report(db, report_type, save=True)
    md_preview = format_report_as_markdown(report_type, data)

    active_model = model or get_active_model(db)
    title = REPORT_TITLES.get(report_type, report_type)

    prompt = f"""{_VIRTUALIZATION_PERSONA}

Aşağıdaki rapor verisini bu uzmanlığınla analiz et ve Türkçe, pratik bir özet yaz.

RAPOR: {title}
{md_preview[:3000]}

Kullanıcı sorusu: {question}

Raporu şu başlıklar altında özetle:
1. Genel Durum (1-2 cümle)
2. Öne çıkan bulgular (madde madde, somut sayılar ver)
3. Öneriler (en kritik 3 aksiyon)

KRİTİK: Raporda yazan host/VM/CPU/RAM sayılarını aynen kullan. "Bilinmiyor", "kaç VM host'ta çalışıyor bilinmiyor" gibi ifadeler YASAK — sayılar raporda varsa mutlaka yaz.
Tabloları doğrudan kopyalama, anlamlı yorum ekle. Cevabı markdown formatında yaz."""

    answer = md_preview  # fallback
    error = None
    try:
        data = llm_gateway.generate_sync(model=active_model, prompt=prompt, timeout=120)
        if not data.get("error"):
            answer = (data.get("response") or "").strip() or md_preview
        else:
            error = data["error"]
    except Exception as e:
        error = str(e)

    latency_ms = int((datetime.utcnow() - t0).total_seconds() * 1000)
    return {
        "answer": answer,
        "report_type": report_type,
        "report_title": title,
        "report_data": data,
        "report_markdown": md_preview,
        "intents": ["report", report_type],
        "model": active_model,
        "latency_ms": latency_ms,
        "error": error,
    }


def answer_hypervisor_question(
    db: Session,
    question: str,
    model: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Doğal dil sorusunu alır, context oluşturur, Ollama ile yanıtlar.

    Aynı soru tekrar sorulduğunda önbellekten anında döner — LLM'i veya
    deterministik DB/vCenter sorgusunu tekrar çalıştırmaz. Ne kadar sık
    sorulursa önbellek süresi o kadar uzar (bkz. `qa_cache.py`).

    Not: Deterministik katmandan gelen cevaplar (şablon tabanlı, konuşma
    bağlamından bağımsız) konuşma geçmişi olsa bile önbelleğe yazılır —
    "VM listesi" gibi sorular hangi sohbette sorulursa sorulsun aynıdır.
    LLM'in ürettiği serbest metin cevaplar ise sadece bağımsız (geçmişsiz)
    sorularda önbelleğe yazılır; bağlama bağlı takip soruları ("peki ya CPU?")
    hiç önbelleklenmez.

    Returns:
        {answer, intents, context_summary, model, latency_ms}
    """
    from app.services import qa_cache

    t0 = datetime.utcnow()

    # Takip sorularinda (conversation_history varsa) cache'e bakilmiyor — aksi halde
    # "peki cpu?" gibi baglama bagli bir soru, izole/eski bir soruyla metin benzerligi
    # yuzunden yanlislikla eslesip bu oturumun gecmisini yok sayan bir cevap donebilir.
    cached = qa_cache.get_cached_answer(question, model) if not conversation_history else None
    if cached is not None:
        hits = cached.pop("_cache_hits", None)
        cached["cached"] = True
        cached["latency_ms"] = int((datetime.utcnow() - t0).total_seconds() * 1000)
        logger.info(
            "[HVIntelligence] cache HIT (hits=%s) q=%r", hits, question[:80]
        )
        return cached

    result = _compute_hypervisor_answer(db, question, model, conversation_history)

    # Deterministik cevaplar şablon; LLM serbest metinde bilinmiyor kaçışını temizle
    if result.get("answer") and result.get("intents") != ["deterministic"]:
        from app.services.answer_sanitize import sanitize_llm_answer
        result["answer"] = sanitize_llm_answer(result.get("answer") or "")

    is_deterministic = result.get("intents") == ["deterministic"]
    should_cache = (is_deterministic or not conversation_history) and not result.get("error")
    if should_cache:
        qa_cache.set_cached_answer(question, result, model)

    return result


def _compute_hypervisor_answer(
    db: Session,
    question: str,
    model: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    t0 = datetime.utcnow()

    # 1) Deterministik katman — "100+ soru" kataloğundaki kesin cevaplanabilir
    #    sorular için DB/canlı vCenter sorgusuyla hızlı ve %100 veri-doğru yanıt.
    det_answer = try_deterministic_answer(db, question)
    if det_answer:
        latency_ms = int((datetime.utcnow() - t0).total_seconds() * 1000)
        logger.info(f"[HVIntelligence] deterministic answer latency={latency_ms}ms")
        return {
            "answer": det_answer,
            "intents": ["deterministic"],
            "context_lines": 0,
            "vm_count_in_context": len(_get_vms(db)),
            "model": None,
            "latency_ms": latency_ms,
            "error": None,
        }

    # 2) Rapor sorusu mu kontrol et
    report_type = detect_report_type(question)
    if report_type:
        return answer_report_question(db, question, report_type, model)

    intents = detect_intent(question)

    # VM adları soru içinde geçiyor mu?
    from app.services.platform_scope import vm_filter_condition
    all_vm_names = [vm.name for vm in db.query(Server.name).filter(vm_filter_condition()).all()]
    vm_names_to_compare = _extract_vm_names(question, [r[0] for r in all_vm_names]) if "compare_vms" in intents else None

    context = build_context(db, question, vm_names_to_compare)

    # System prompt
    system_prompt = (
        _VIRTUALIZATION_PERSONA + "\n\n"
        "Sana sağlanan gerçek veri üzerinden Türkçe, kısa, net ve pratik yanıtlar ver. "
        "Sayısal değerleri gerektiğinde tablo veya liste halinde sun ama gereksiz uzatma. "
        "Kullanıcı açıkça detay istemedikçe kapasite uyarısı/risk/öneri gibi ek yorumları "
        "sadece gerçekten ilgiliyse ve kısaca ekle. "
        "Veri bloğunda yoksa 'bilinmiyor/erişim yok' deme; 'canlı sorguda bu alan dönmedi' de, uydurma."
    )

    # Konuşma geçmişi + güncel soru
    messages_block = ""
    if conversation_history:
        for msg in conversation_history[-4:]:  # son 4 mesaj
            role = "Kullanıcı" if msg["role"] == "user" else "Asistan"
            messages_block += f"\n{role}: {msg['content']}"
        messages_block += "\n"

    prompt = f"""{system_prompt}

=== CANLI ALTYAPI VERİSİ ===
{context}
=== VERİ SONU ===
{messages_block}
Kullanıcı Sorusu: {question}

Lütfen yanıtını ver:"""

    active_model = model or get_active_model(db)
    answer = ""
    error = None

    try:
        data = llm_gateway.generate_sync(model=active_model, prompt=prompt, timeout=120)
        if not data.get("error"):
            answer = (data.get("response") or "").strip()
        else:
            error = data["error"]
            answer = error
    except requests.exceptions.ConnectionError:
        error = "LLM bağlantı hatası"
        answer = error
    except requests.exceptions.Timeout:
        error = "LLM yanıt süresi aşıldı (120s)"
        answer = error

    latency_ms = int((datetime.utcnow() - t0).total_seconds() * 1000)
    logger.info(f"[HVIntelligence] intents={intents} latency={latency_ms}ms model={active_model}")

    return {
        "answer": answer,
        "intents": intents,
        "context_lines": len(context.splitlines()),
        "vm_count_in_context": len(_get_vms(db)),
        "model": active_model,
        "latency_ms": latency_ms,
        "error": error,
    }
