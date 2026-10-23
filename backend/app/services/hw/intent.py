"""Donanım sohbet sinyali (sözcük sınırlı, LLM'siz) — bağımlılıksız; araç modülü (`agent.tools_hw`) ve rota/ret
katmanları (`unified_intent_router`, `chat_quality.unavailable_info`) bunu kullanır (döngüsel import yok)."""
from __future__ import annotations

import re

_L = r"a-zçğıöşüâîû0-9"
# Satıcı/ürün adları: kendi başlarına donanım yönetimi sinyali (Türkçe ek alabilir: iDRAC'ların, OneView'daki)
_VENDOR_RE = re.compile(
    rf"(?<![{_L}])(?:idrac\d?|redfish|oneview|one\s+view|openmanage|open\s+manage|ovgd|dell\s+ome|hpe\s+oneview)(?![{_L}])|"
    rf"(?<![{_L}])(?:idrac|oneview|openmanage)[{_L}]*|"
    rf"(?<![{_L}])ilo\d?(?![{_L}])",
    re.IGNORECASE)
# Donanım kavramları: yeterince özgül; yalın "ilo/kasa/appliance/firmware" gibi çok anlamlı sözcükler BURADA YOK
_CONCEPT_RE = re.compile(
    rf"(?<![{_L}])(?:bmc|blade[{_L}]*|enclosure[{_L}]*|service\s*tag|servis\s*tag|donan[ıi]m[{_L}]*|"
    rf"fiziksel\s+sunucu[{_L}]*|bare[\s-]?metal)(?![{_L}])",
    re.IGNORECASE)
_WARRANTY_RE = re.compile(rf"(?<![{_L}])(?:garanti[{_L}]*|warranty|support\s+expir[{_L}]*)", re.IGNORECASE)
_SERVER_WORD_RE = re.compile(rf"(?<![{_L}])(?:sunucu[{_L}]*|server[{_L}]*|blade[{_L}]*|host[{_L}]*|makine[{_L}]*)", re.IGNORECASE)
# Marka + sunucu sözcüğü: «Dell sunucu», «HPE sunucuların», «ProLiant host» (marka tek başına yetmez: «Dell EMC Unity»)
_BRAND_RE = re.compile(rf"(?<![{_L}])(?:dell|hpe?|hewlett[\s-]?packard|proliant|poweredge|synergy)(?![{_L}])", re.IGNORECASE)
_OTHER_PLATFORM_RE = re.compile(
    rf"(?<![{_L}])(?:linux|windows|rhel|centos|ubuntu|vcenter|esxi?|vmware|vsphere|openshift|ocp|kubernetes|k8s|pods?|"
    rf"vm[{_L}]*|sanal|hypervisor|datastore|cluster|olvm|ovirt)(?![{_L}])",
    re.IGNORECASE)


def hw_vendor_signal(message: str) -> bool:
    """iDRAC / iLO / OneView / OpenManage / OVGD adı geçiyor mu (yetenek yokken dürüst ret için yeterli kanıt)."""
    return bool(_VENDOR_RE.search(message or ""))


def hw_intent(message: str) -> bool:
    """Mesaj fiziksel sunucu donanım yönetimi (OME/OneView) niyeti taşıyor mu — sözcük sınırlı, LLM'siz.

    Tetikler: satıcı/ürün adı (iDRAC, iLO, OneView, OpenManage, OVGD) · donanım kavramı (BMC, blade, enclosure, service tag,
    «donanım», «fiziksel sunucu») · garanti/warranty + sunucu sözcüğü · marka (Dell/HPE/ProLiant/PowerEdge) + sunucu sözcüğü. Alt dize eşleşmesi YOK («kilo», «silo» tetiklemez)."""
    m = message or ""
    if _VENDOR_RE.search(m) or _CONCEPT_RE.search(m):
        return True
    if _WARRANTY_RE.search(m) and _SERVER_WORD_RE.search(m):
        return True
    return bool(_BRAND_RE.search(m) and _SERVER_WORD_RE.search(m))


def other_platform_signal(message: str) -> bool:
    """Mesajda donanım dışı platform sinyali var mı (varsa `hw` mevcut alanlara EKLENİR, tek başına kilitlemez)."""
    return bool(_OTHER_PLATFORM_RE.search(message or ""))


def hw_active() -> bool:
    """Gerçek sağlayıcı (`hw`) veya etiketli DEMO (`hw_demo`) yeteneği açık mı."""
    try:
        from app.services.capabilities import get_capabilities
        caps = get_capabilities()
        return "hw" in caps or "hw_demo" in caps
    except Exception:  # noqa: BLE001
        return False


# ── Zorunlu ön-çağrı planı (model aracı çağırmazsa «veri yok» uydurmasın) ─────────────────────────────────────────
_ALERT_RE = re.compile(rf"(?<![{_L}])(?:alarm[{_L}]*|uyar[ıi][{_L}]*|alert[{_L}]*|olay[{_L}]*|event[{_L}]*)", re.IGNORECASE)
_EXPIRED_RE = re.compile(rf"(?<![{_L}])(?:bit(?:miş|mis|ti|en|ik)[{_L}]*|dol(?:muş|mus|du|an)[{_L}]*|expired|sona\s+er(?:miş|mis|di|en))",
                         re.IGNORECASE)
_EXPIRING_RE = re.compile(rf"(?<![{_L}])(?:bitecek|bitmek\s+üzere|yaklaş[{_L}]*|yaklas[{_L}]*|expiring|dolacak)", re.IGNORECASE)
_CRIT_RE = re.compile(rf"(?<![{_L}])(?:kritik[{_L}]*|critical)", re.IGNORECASE)
_WARN_RE = re.compile(rf"(?<![{_L}])(?:uyar[ıi]\s+(?:durum|veren|seviye)[{_L}]*|warning)", re.IGNORECASE)
_HOURS_RE = re.compile(rf"son\s+(\d{{1,3}})\s*(saat|gün|gun)", re.IGNORECASE)
_NAME_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_.-])([A-Za-z][A-Za-z0-9_]*(?:[-.][A-Za-z0-9_]+)+)(?![A-Za-z0-9_.-])")
_ENCL_RE = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_]*-?Encl[A-Za-z0-9_-]*)", re.IGNORECASE)


def hw_prefetch_plan(message: str):
    """Mesajdan deterministik (tool, args) listesi. Yalnız donanım rotasında kullanılır; LLM'siz, tahmin yok."""
    m = message or ""
    plan = []
    alert = bool(_ALERT_RE.search(m)) and not _WARN_RE.search(m)
    hours = 24
    hm = _HOURS_RE.search(m)
    if hm:
        n = int(hm.group(1))
        hours = n if hm.group(2).lower() == "saat" else n * 24
        hours = max(1, min(hours, 24 * 14))
    sargs = {"limit": 100}
    if _EXPIRED_RE.search(m) and _WARRANTY_RE.search(m):
        sargs["warranty"] = "expired"
    elif _EXPIRING_RE.search(m) and _WARRANTY_RE.search(m):
        sargs["warranty"] = "expiring_90"
    if _CRIT_RE.search(m):
        sargs["health"] = "critical"
    elif _WARN_RE.search(m):
        sargs["health"] = "warning"
    low = m.lower()
    if re.search(r"(?<![a-z])dell(?![a-z])|poweredge|idrac", low):
        sargs["vendor"] = "dell"
    elif re.search(r"(?<![a-z])hpe?(?![a-z])|proliant|synergy|oneview|(?<![a-z])ilo\d?(?![a-z])", low):
        sargs["vendor"] = "hpe"
    em = _ENCL_RE.search(m)
    if em:
        sargs["enclosure"] = em.group(1)
    else:
        names = [t for t in _NAME_TOKEN_RE.findall(m) if not re.fullmatch(r"\d+(?:[.-]\d+)*", t)]
        if len(names) == 1:
            sargs["name"] = names[0]
    if "name" in sargs:
        sargs.pop("vendor", None)       # ad tek başına daha özgüldür; satıcı çıkarımı yanlış süzebilir
    if len(sargs) == 1 and not alert:
        sargs["limit"] = 30             # genel özet: sayılar `by_health_all`/`total`'dan gelir, uzun liste gerekmez
    alert_only = alert and not (sargs.keys() - {"limit"}) and not re.search(rf"(?<![{_L}])(?:sunucu|server|blade)", m, re.IGNORECASE)
    if alert:
        plan.append(("hw_alerts_summary", {"hours": hours}))
    if not alert_only:
        plan.append(("hw_server_status", sargs))
    return plan


_DATA_WORD_RE = re.compile(
    rf"(?<![{_L}])(?:durum[{_L}]*|sağlık[{_L}]*|saglik[{_L}]*|kaç|kac|hangi[{_L}]*|listele[{_L}]*|say[ıi][{_L}]*|alarm[{_L}]*|"
    rf"uyar[ıi][{_L}]*|garanti[{_L}]*|kritik[{_L}]*|bit(?:miş|mis|ecek)[{_L}]*|var\s+m[ıi]|sorun[{_L}]*|health|status)",
    re.IGNORECASE)


def hw_data_question(message: str) -> bool:
    """Donanım mesajı canlı/envanter VERİSİ mi istiyor (somut ad / durum-sayı-liste sözcüğü), yoksa saf kavram mı
    («BMC nedir?», «iDRAC ne işe yarar?»)? Veri sorusu «X nedir?» kalıbı yüzünden bilgi-yolu'na düşmemeli."""
    m = message or ""
    return bool(_NAME_TOKEN_RE.search(m) or _ENCL_RE.search(m) or _DATA_WORD_RE.search(m))
