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
from app.models.hypervisor import Hypervisor
from app.models.server import Server

logger = logging.getLogger(__name__)

# ── Intent keywords ───────────────────────────────────────────────────────────
INTENT_PATTERNS = {
    "count_hosts":     r"kaç\s+(esx|host|sunucu)|how many.*(esx|host)",
    "vm_per_host":     r"hangi\s+esx.*kaç|hangi\s+host.*vm|vm.*dağılım|esx.*vm\s+sayı",
    "capacity":        r"doluluk|kapasite|boş.*yer|ne kadar dolu|cpu.*memory.*dolu|yoğun|kapasit",
    "compare_vms":     r"karşılaştır|compare|fark.*nedir|farkı|vs\b|versus",
    "tools_status":    r"vmware\s+tools|vm.*tools|tools\s+(olan|olmayan|yüklü|kurulu)",
    "os_filter":       r"\b(rhel|oel|oracle|windows|win\s*sunucu|ubuntu|centos|rocky|linux)\b",
    "powered_off":     r"kapalı|powered.off|shut.*down|çalışmayan",
    "assessment":      r"değerlendirme|assessment|genel\s+durum|rapor|özet|nasıl.*ortam|sağlık",
    "network":         r"network|ağ|10g|1g|bant\s*genişliği|interface",
    "snapshot":        r"snapshot|anlık\s+görüntü",
    "report":          r"rapor|report|üret|oluştur|göster.*rapor",
}

# ── Rapor intent eşleşme tablosu ─────────────────────────────────────────────
REPORT_KEYWORD_MAP = {
    "executive_summary":      [r"executive|yönetici\s+özet|genel\s+(sağlık|özet|durum)"],
    "capacity":               [r"kapasite\s+rapor|capacity\s+report|doluluk\s+rapor|ne\s+zaman\s+dol"],
    "risk":                   [r"risk\s+(dashboard|rapor)|kritik\s+risk|risk\s+özet"],
    "vm_health":              [r"vm\s+sağlık|sağlık\s+skor|health\s+scor"],
    "resource_usage":         [r"kaynak\s+kullanım|en\s+çok\s+(cpu|ram|disk)\s+tüketen|resource\s+usage"],
    "security_compliance":    [r"güvenlik.*uyum|compliance|security.*rapor"],
    "consolidation":          [r"konsolidasyon|boşta.*vm|kapalı.*vm.*rapor|israf"],
    "lifecycle":              [r"yaşam\s+döngüsü|lifecycle|eski.*sürüm|upgrade.*gerek"],
    "anomaly":                [r"anomali.*rapor|anormal.*rapor|tespit.*rapor"],
    "forecast":               [r"tahmin|forecast|3\s*ay|6\s*ay|12\s*ay|büyüme\s+tahmin"],
    "finance":                [r"maliyet|finans|finance|cost\s+report|para"],
    "riskiest_assets":        [r"en\s+riskli|riskiest|yüksek\s+risk.*varlık"],
    "operations":             [r"operasyon\s+rapor|ops.*report|aktivite\s+rapor"],
    "performance_bottleneck": [r"darboğaz|bottleneck|performans.*sorun|cpu\s+ready|latency"],
    "sla":                    [r"sla|erişilebilirlik|uptime|kesinti.*rapor"],
    "backup":                 [r"backup\s+rapor|yedek.*rapor|rpo|rto"],
    "dr_readiness":           [r"dr\s+hazırlık|disaster\s+recovery|felaket.*kurtarma"],
    "business_impact":        [r"iş\s+servisi|business\s+impact|servis\s+etki"],
    "chargeback":             [r"chargeback|showback|departman.*maliyet|birim.*maliyet"],
}


def detect_intent(question: str) -> List[str]:
    """Sorudan intent listesi çıkar (birden fazla olabilir)."""
    q = question.lower()
    intents = []
    for intent, pattern in INTENT_PATTERNS.items():
        if re.search(pattern, q, re.IGNORECASE):
            intents.append(intent)
    if not intents:
        intents = ["general"]
    return intents


def detect_report_type(question: str) -> Optional[str]:
    """Soru bir rapor isteği mi? Hangi rapor tipine karşılık geliyor?"""
    q = question.lower()
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


def _get_vms(db: Session, hypervisor_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """VM envanterini çek."""
    q = db.query(Server).filter(Server.hypervisor_id != None)  # noqa: E711
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
        host_lines.append(
            f"  - {h['host']} [{hv_name}]{maint}\n"
            f"    CPU: %{h['cpu_pct']} kullanımda (%{h['cpu_free_pct']} boş, {h['cpu_cores']} core)\n"
            f"    RAM: %{h['mem_pct']} kullanımda ({h['mem_free_gb']} GB boş / {h['mem_total_gb']} GB toplam)\n"
            f"    Disk: %{h['ds_pct']} kullanımda ({h['ds_free_gb']} GB boş / {h['ds_total_gb']} GB toplam)\n"
            f"    VM: {h['vms_running']} çalışan / {h['vms_total']} toplam"
        )
    parts.append(f"## ESX / KVM HOST'LARI ({len(esx_hosts)} adet)\n" + "\n".join(host_lines))

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

    # ── Bölüm 4: Datastore bazında VM disk özeti ─────────────────────────────
    # VM'lere hypervisor adını ekle (datastore grubu için)
    for vm in vms:
        vm["hypervisor"] = hv_map.get(vm["hypervisor_id"], {}).get("name", "Bilinmiyor")
    ds_summary = _datastore_vm_disk_summary(vms, esx_hosts)
    if ds_summary:
        parts.append(ds_summary)

    return "\n\n".join(parts)


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


def _datastore_vm_disk_summary(vms: List[Dict], esx_hosts: List[Dict]) -> str:
    """
    Datastore veya hypervisor bazında VM disk tahsisatını özetler.
    vm_datastore doluysa datastore'a, boşsa hypervisor adına göre gruplar.
    """
    from collections import defaultdict

    groups: Dict[str, List[Dict]] = defaultdict(list)
    for vm in vms:
        ds = (vm.get("datastore") or "").strip()
        key = ds if ds else f"Hypervisor: {vm.get('hypervisor', 'Bilinmiyor')}"
        groups[key].append(vm)

    if not groups:
        return ""

    # Tüm VM'lerin datastore boşsa başlığı farklı yaz
    all_hv_based = all(k.startswith("Hypervisor:") for k in groups)
    header_label = "HYPERVİSOR BAZINDA VM DİSK TAHSİSATI" if all_hv_based else "DATASTORE BAZINDA VM DİSK TAHSİSATI"

    # Host toplam disk bilgisi
    host_ds: Dict[str, Dict] = {h["host"]: h for h in esx_hosts}

    lines = [f"## {header_label}"]
    if all_hv_based:
        lines.append("  NOT: vm_datastore alanı henüz dolu değil; veriler hypervisor bazında gösteriliyor.")

    for group_name, group_vms in sorted(groups.items(), key=lambda x: -sum(v.get("disk_gb") or 0 for v in x[1])):
        allocated_gb = sum((v.get("disk_gb") or 0) for v in group_vms)
        powered_on   = sum(1 for v in group_vms if v["power_state"] in ("POWERED_ON", "up", "running", "poweredOn"))

        lines.append(f"\n### {group_name}")
        lines.append(f"  VM Sayısı        : {len(group_vms)} ({powered_on} çalışan)")
        lines.append(f"  Toplam Tahsis Disk: {round(allocated_gb, 1)} GB (vm_disk_gb toplamı)")
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

    prompt = f"""Sen bir VMware/KVM altyapı uzmanısın. Aşağıdaki rapor verisini analiz et ve Türkçe, pratik bir özet yaz.

RAPOR: {title}
{md_preview[:3000]}

Kullanıcı sorusu: {question}

Raporu şu başlıklar altında özetle:
1. Genel Durum (1-2 cümle)
2. Öne çıkan bulgular (madde madde, somut sayılar ver)
3. Öneriler (en kritik 3 aksiyon)

Tabloları doğrudan kopyalama, anlamlı yorum ekle. Cevabı markdown formatında yaz."""

    answer = md_preview  # fallback
    error = None
    try:
        resp = requests.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json={"model": active_model, "prompt": prompt, "stream": False},
            timeout=120,
        )
        if resp.status_code == 200:
            answer = resp.json().get("response", "").strip() or md_preview
        else:
            error = f"LLM HTTP {resp.status_code}"
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

    Returns:
        {answer, intents, context_summary, model, latency_ms}
    """
    t0 = datetime.utcnow()

    # Rapor sorusu mu kontrol et
    report_type = detect_report_type(question)
    if report_type:
        return answer_report_question(db, question, report_type, model)

    intents = detect_intent(question)

    # VM adları soru içinde geçiyor mu?
    all_vm_names = [vm.name for vm in db.query(Server.name).filter(Server.hypervisor_id != None).all()]  # noqa: E711
    vm_names_to_compare = _extract_vm_names(question, [r[0] for r in all_vm_names]) if "compare_vms" in intents else None

    context = build_context(db, question, vm_names_to_compare)

    # System prompt
    system_prompt = (
        "Sen bir VMware/KVM altyapı uzmanısın. "
        "Sana sağlanan gerçek veri üzerinden Türkçe, net ve pratik yanıtlar ver. "
        "Sayısal değerleri tablolar veya liste halinde sun. "
        "Yorum yaparken kapasite uyarıları, riskler ve önerileri belirt. "
        "Bilgi yoksa 'Bu veriye erişimim yok' de, uydurma."
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
        resp = requests.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json={"model": active_model, "prompt": prompt, "stream": False},
            timeout=120,
        )
        if resp.status_code == 200:
            answer = resp.json().get("response", "").strip()
        else:
            error = f"Ollama HTTP {resp.status_code}"
            answer = error
    except requests.exceptions.ConnectionError:
        error = "Ollama bağlantı hatası"
        answer = error
    except requests.exceptions.Timeout:
        error = "Ollama yanıt süresi aşıldı (120s)"
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
