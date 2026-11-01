"""Adım 8a — «ainew'de olmayan bilgi» dürüstlüğü (LLM'siz sabit cümle + hafif [Not] hint).

Sınıflar:
  * ``license``   — lisans maliyeti/sayısı/bitişi: ainew lisans verisi tutmaz.
  * ``customer``  — müşteri / iş etkisi sahibi: tutulmaz.
  * ``contract``  — destek/hizmet sözleşmesi, SLA taahhüdü: tutulmaz (olay-türevli uptime raporu AYRIDIR).
  * ``owner``     — iş sahibi / sorumlu / departman: «kavram var, veri yok» — yalnız ``business_service_map``
                    (sohbet araçları okumaz); uydurma YASAK (ör. envanterdeki sunucu adını sahip diye sunmak).
  * ``cost``      — aylık/toplam maliyet: yalnız TAHMİNİ tahsisat maliyeti (tüm açık VM'ler; cluster/şirket bazı yok).
                    Birim fiyat yapılandırılmamışsa (``cost_config`` boş) RAKAM VERİLMEZ (K2).

Saf modül davranışı: ``answer(message)`` → sabit cevap veya ``None`` (normal akış). Zararsız komşu sorular
(«maliyet raporu», «owner bilgisi olmayan VM'ler», «Windows lisans durumu», «SLA ihlali olayı») TETİKLEMEZ.
DB okuması yalnız cevap kurulurken ve salt-okunur (``count(*)`` / ``cost_config`` / finans raporu).
Uygulama verisi YAZILMAZ. Automic platformu kapsam dışıdır (kendi kodu var).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_TR = str.maketrans("çğıöşüâîûÇĞİÖŞÜ", "cgiosuaiuCGIOSU")


def _fold(s: str) -> str:
    return (s or "").replace("İ", "i").replace("I", "ı").lower().translate(_TR)


# ── Tetikleyiciler (katlanmış, ASCII) ───────────────────────────────────────────
_MAX_LEN = 160
# Veri/liste isteği içeren karma sorular normal akışa gider (bu modül yalnız SAF dürüstlük sorusunu yakalar).
_DATA_WORDS = re.compile(
    r"\b(listele|listesi|goster|tablo|sirala|en\s*cok|en\s*yuksek|en\s*az|top\s*\d+|kac\s+(vm|sunucu|host|pod|node)|"
    r"raporu|rapor\s+uret|rapor\s+ver|rapor\s+hazirla|analiz|karsilastir|ozetle|olay(lar)?i?|ihlal|alarm)\b"
)
# Zararsız / mevcut kural alanı
_BENIGN = re.compile(
    r"(sahip\w*\s+(bilgisi\s+)?olmayan|owner\s+(bilgisi\s+)?olmayan|atanmamis|atamasi\s+yapilmamis|bilgisi\s+eksik|"
    r"lisans\w*\s+(durum|etkin|activation|aktivasyon)|windows\s+lisans|slmgr|activation|"
    r"without\s+owner|no\s+owner|unassigned)"
)

_LICENSE = re.compile(
    r"(?<![a-z0-9])(lisans|licen[cs]e|licensing)\w*"
    r".{0,60}(maliyet|ucret|fiyat|tutar|bedel|ne\s+kadar|kac|adet|sayisi|bitis|son\s+kullanma|sure|cost|price|expire|expiry|how\s+many|how\s+much)"
    r"|(maliyet|ucret|fiyat|bedel|cost|price)\w*.{0,40}(?<![a-z0-9])(lisans|licen[cs]e)\w*"
    r"|(?<![a-z0-9])kac\s+(adet\s+)?(lisans|licen[cs]e)\w*"
)
_CUSTOMER = re.compile(
    r"(hangi\s+musteri|musteri\w*\s+(kim|hangi|bilgi|adi|ait)|musteriye\s+ait|kimin\s+musteri|"
    r"which\s+customer|customer\s+of|who\s+is\s+the\s+customer|customer\s+(name|info))"
)
_CONTRACT = re.compile(
    r"((destek|hizmet|bakim|garanti)\s+sozlesme\w*|sozlesme\s+(bitis|suresi|tarih|no|numara)\w*|sla\s+(taahhut|sozlesme|suresi|orani\s+ne)\w*|"
    r"(support|service|maintenance)\s+contract|warranty\s+(end|expir|period)|sla\s+commitment)"
)
_OWNER = re.compile(
    r"((is\s+)?sahib\w*\s+(kim|kimdir|nedir|hangi)|(sahibi|sorumlusu|yoneticisi)\s+kim|kime\s+ait|kimin\s+(vm|sunucu|sanal|host|namespace|proje|uygulama|cluster)|"
    r"hangi\s+(departman|birim|ekip|bolum)\w*(?:\s+\w+){0,3}\s+(ait|kullan\w*|sahip)|(departman|birim|ekip)\w*\s+(hangi|ne|nedir)|"
    r"who\s+(owns|is\s+the\s+owner|is\s+responsible)|owner\s+of|whose\s+(vm|server|host)|"
    r"(owner|sahip)\w*\s+(kim|kimdir|nedir|who))"
)
_COST = re.compile(
    r"((aylik|yillik|toplam|genel|guncel|tahmini|monthly|annual|yearly|total)\s+(altyapi\s+)?(maliyet|masraf|gider|cost|spend)\w*|"
    r"maliyet\w*\s+(ne\s+kadar|nedir|kac|kaç|tl|usd|dolar|euro)|ne\s+kadara\s+mal|kac\s+(tl|dolar|usd|euro)|"
    r"how\s+much\s+(does|do|is|are)\b.{0,40}\bcost|what\s+is\s+the\s+(monthly|total|annual)\s+cost|"
    r"(butce|fatura|invoice|bill)\w*\s+(ne\s+kadar|kac|nedir|how\s+much))"
)
_ENGLISH_HINT = re.compile(
    r"\b(how|what|which|who|whose|monthly|annual|total|cost|price|owner|owns|customer|contract|license|licence|vm|vms|server|cluster|the|is|are|of)\b"
)
_TR_CHARS = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
_TR_WORDS = re.compile(r"\b(ne|kim|kac|hangi|mi|mu|nedir|kadar|icin|aylik|maliyeti|sahibi|musteri|lisans|sunucu|kime|kimin|ait|bu|var|yok|olan|ile)\b")

_STOP_OBJ = {"bu", "su", "şu", "o", "tum", "tüm", "butun", "bütün", "her", "bir", "the", "this", "that", "all", "our", "bizim", "sirketin", "şirketin"}
_OBJ_RE = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9_.\-]{1,60})(?:'?[a-zçğıöşü]*)?\s+(?:vm|sanal\s+makine|sunucu|sunucusu|host|cluster|namespace|proje|node|pod|uygulama|server)\b",
    re.I,
)


def _is_english(message: str) -> bool:
    f = _fold(message)
    if _TR_CHARS.search(message or "") or _TR_WORDS.search(f):
        return False
    return bool(_ENGLISH_HINT.search(f))


def classify(message: str) -> Optional[str]:
    """Saf dürüstlük sınıfı: license|customer|contract|owner|cost veya None."""
    raw = (message or "").strip()
    if not raw or len(raw) > _MAX_LEN or "\n" in raw:
        return None
    f = _fold(raw)
    if _BENIGN.search(f) or _DATA_WORDS.search(f):
        return None
    if _OWNER.search(f):
        return "owner"
    if _LICENSE.search(f):
        return "license"
    if _CONTRACT.search(f):
        return "contract"
    if _CUSTOMER.search(f):
        return "customer"
    if _COST.search(f):
        return "cost"
    return None


def _object_name(message: str) -> str:
    m = _OBJ_RE.search(message or "")
    if not m:
        return ""
    name = m.group(1).strip(".-_")
    return "" if name.lower() in _STOP_OBJ else name


# ── Sabit cümleler ────────────────────────────────────────────────────────────────
_NOT_IN_AINEW_TR = {
    "license": ("lisans bilgisi — maliyet, adet, bitiş tarihi", "Gösterebileceklerim: VM/host envanteri, işletim sistemi ve sürüm bilgileri, vCenter/ESXi sürümleri."),
    "customer": ("müşteri bilgisi", "Gösterebileceklerim: VM/sunucu envanteri, kaynak kullanımı ve olaylar."),
    "contract": ("destek/hizmet sözleşmesi ve SLA taahhüdü", "Gösterebileceklerim: olay kayıtlarından türetilen uptime tahmini (SLA raporu) ve alarm geçmişi."),
}
_NOT_IN_AINEW_EN = {
    "license": ("license information — cost, count, expiry", "I can show: VM/host inventory, OS and version details, vCenter/ESXi versions."),
    "customer": ("customer information", "I can show: VM/server inventory, resource usage and events."),
    "contract": ("support/service contracts and SLA commitments", "I can show: an uptime estimate derived from event records (SLA report) and alarm history."),
}


def _bsm_count() -> Optional[int]:
    try:
        from sqlalchemy import text
        from app.core.database import ThreadSessionLocal
        db = ThreadSessionLocal()
        try:
            return int(db.execute(text("SELECT count(*) FROM business_service_map")).scalar() or 0)
        finally:
            db.close()
    except Exception:
        logger.debug("business_service_map sayımı atlandı", exc_info=True)
        return None


def _owner_answer(message: str, english: bool) -> str:
    n = _bsm_count()
    obj = _object_name(message)
    if english:
        what = f" for `{obj}`" if obj else ""
        base = ("**The owner/department is not available in ainew data** — it exists only as a Business Service Map assignment")
        if n is None:
            tail = ", and this chat does not read those assignments."
        elif n == 0:
            tail = ": there are currently no assignments (no owner has been assigned to any VM/server)."
        else:
            tail = f": {n} assignment(s) exist, but this chat does not read them."
        return (f"{base}{tail} I cannot state an owner{what}, and I do not infer one from names or addresses in the inventory.")
    what = f" `{obj}` için" if obj else ""
    base = "**İş sahibi/departman bilgisi ainew verisinde yok** — yalnız «Business Service Map» ataması olarak tutulur"
    if n is None:
        tail = " ve bu sohbet o atamaları okumaz."
    elif n == 0:
        tail = ": şu an hiç atama yapılmamış (hiçbir VM/sunucu için sahip tanımlı değil)."
    else:
        tail = f": şu an {n} atama kayıtlı, ancak bu sohbet atamaları sorgulamaz."
    return (f"{base}{tail} Envanterdeki ad veya IP'lerden sahip tahmin etmem;{what} sahip belirtemem. "
            "Sahip eşlemesini Raporlar → İş Servisi Haritası üzerinden tanımlayabilirsiniz.")


def _cost_answer(english: bool) -> str:
    cfg = None
    report: Optional[Dict[str, Any]] = None
    try:
        from app.core.database import ThreadSessionLocal
        from app.models.infrastructure_report import CostConfig
        db = ThreadSessionLocal()
        try:
            cfg = db.query(CostConfig).first()
            if cfg is not None:
                from app.services.report_engine import generate_finance_report
                report = generate_finance_report(db)
        finally:
            db.close()
    except Exception:
        logger.debug("maliyet cevabı: veri okunamadı", exc_info=True)
        cfg = None
        report = None
    if report is None:
        if english:
            return ("**Actual cost is not available in ainew data** (no invoices, licenses or real consumption are stored), "
                    "and the cost unit prices are not configured, so I do not state an amount. Once unit prices are defined, "
                    "the Finance report calculates an ESTIMATED, allocation-based cost for all powered-on VMs "
                    "(not per cluster or company).")
        return ("**Gerçek maliyet ainew verisinde yok** (fatura, lisans veya gerçek tüketim tutulmaz) ve maliyet birim "
                "fiyatları yapılandırılmamış; bu yüzden tutar vermiyorum. Birim fiyatlar tanımlandığında Finans raporu, "
                "tüm açık VM'ler için kaynak tahsisatına dayalı TAHMİNİ bir maliyet hesaplar (cluster veya şirket "
                "bazında değil).")
    cur = report.get("currency") or "TL"
    total = float(report.get("total_monthly_cost") or 0)
    rates = report.get("rates") or {}
    if english:
        return (f"**Estimated, allocation-based monthly cost: {total:,.0f} {cur}** (not actual consumption or invoices). "
                f"Scope: all powered-on VMs across all hypervisors and OpenShift Virtualization — there is no per-cluster or "
                f"company-level split. Unit prices: {rates.get('cpu_per_core')} {cur}/core, {rates.get('ram_per_gb')} {cur}/GB RAM, "
                f"{rates.get('storage_per_gb')} {cur}/GB disk.")
    return (f"**Tahmini, tahsisat bazlı aylık maliyet: {total:,.0f} {cur}** (gerçek tüketim veya fatura değildir). "
            f"Kapsam: tüm hypervisor ve OpenShift Virtualization kayıtlarındaki açık VM'ler — cluster veya şirket bazında "
            f"ayrım yok. Birim fiyatlar: {rates.get('cpu_per_core')} {cur}/çekirdek, {rates.get('ram_per_gb')} {cur}/GB RAM, "
            f"{rates.get('storage_per_gb')} {cur}/GB disk.")


# ── Grafik isteği (Adım 8 K8 → Adım 8G ile DEĞİŞTİ) ───────────────────────────────────────────────────
# Artık «… grafikte göster» /graph yazmadan gerçek grafik üretir (chat_charts.graph_request_kind == "chart").
# Bu kapı YALNIZ zaman serisi olmayan istekler için (pasta/çubuk türü, restart/sayı/dağılım konuları):
# LLM metin çubuğu (█) çizmesin diye tek dürüst cümle.
_CHART_TR = ("**Sohbette yalnızca zaman serisi (çizgi) grafik çiziyorum** — CPU, bellek, disk, ağ, IOPS, gecikme gibi "
             "metrikler için; pasta/çubuk dağılımı, sayı veya restart grafiği çizmem. Örnek: "
             "`en çok cpu kullanan 5 VM'i grafikte göster` (varsayılan son 6 saat) veya `/graph web01 cpu son 2 saat`.")
_CHART_EN = ("**In chat I only draw time-series (line) charts** — CPU, memory, disk, network, IOPS, latency; "
             "I do not draw pie/bar distributions, counts or restart charts. Example: "
             "`show the top 5 VMs by cpu as a chart` (default last 6 hours) or `/graph web01 cpu last 2 hours`.")


def is_chart_request(message: str) -> bool:
    """Zaman serisi olmayan grafik isteği mi (sabit cümle)? Çizilebilir istek → False (grafik hattı çalışır)."""
    raw = (message or "").strip()
    if not raw or len(raw) > _MAX_LEN or "\n" in raw:
        return False
    try:
        from app.services.chat_charts import graph_request_kind
        return graph_request_kind(raw) == "unsupported"
    except Exception:
        return False


# ── Donanım sağlayıcısı yok (Adım 12) ─────────────────────────────────────────────
# Satıcı adı (iDRAC/iLO/OneView/OpenManage/OVGD) + ESTATE veri isteği + yetenek YOK → sabit cevap. Kavramsal sorular
# («iDRAC nedir», «iLO nasıl güncellenir») ve donanım yeteneği açıkken normal akış.
_HW_DATA = re.compile(r"\b(sunucu\w*|server\w*|blade\w*|alarm\w*|uyari\w*|garanti\w*|warranty|saglik\w*|health|durum\w*|status|"
                      r"kritik|critical|kac|hangi\w*|listele\w*|list|ip\s+adres\w*|seri\w*|firmware|surum\w*|version)\b")
_HW_CONCEPT = re.compile(r"\b(nedir|nasil|ne\s+demek|farki|fark\s+nedir|ne\s+ise\s+yarar|what\s+is|how\s+(to|do)|difference)\b")
_HW_NA_TR = ("**Donanım yönetimi entegrasyonu tanımlı değil:** Dell OpenManage Enterprise veya HPE OneView / Global Dashboard "
             "bağlı olmadığı için iDRAC/iLO, fiziksel sunucu sağlığı, donanım alarmı ve garanti bilgisi ainew'de yok. "
             "Entegrasyonlar → Donanım yönetimi bölümünden tanımlandığında bu sorular cevaplanır. "
             "Gösterebileceklerim: VM/host envanteri, vCenter/ESXi sağlık ve olayları.")
_HW_NA_EN = ("**No hardware-management integration is configured:** Dell OpenManage Enterprise or HPE OneView / Global Dashboard "
             "is not connected, so iDRAC/iLO, physical-server health, hardware alerts and warranty data are not in ainew. "
             "Add one under Integrations → Hardware management. I can show: VM/host inventory and vCenter/ESXi health and events.")


def _hw_unavailable(message: str) -> bool:
    raw = (message or "").strip()
    if not raw or len(raw) > 240 or "\n" in raw:
        return False
    try:
        from app.services.hw.intent import hw_active, hw_vendor_signal
        if not hw_vendor_signal(raw) or hw_active():
            return False
    except Exception:
        return False
    f = _fold(raw)
    return bool(_HW_DATA.search(f)) and not _HW_CONCEPT.search(f)


# ── Donanım yeteneği VAR ama BMC IP / seri / service tag / firmware sohbete verilmez (Adım 12) ────────────────────────
# Model «bu bilgi mevcut değil» (yanlış) yerine doğru gerekçeyi söylesin diye deterministik. «nedir» kavram sayılmaz
# («iDRAC IP adresi nedir?» veri isteğidir); «nasıl değiştirilir / ne işe yarar» kavramsal → normal akış.
_HW_WITHHELD = re.compile(r"\b((idrac|ilo|bmc|ipmi)\w*\s+(ip|adres)\w*|ip\s+adres\w*.{0,40}\b(idrac|ilo|bmc)\b|"
                          r"seri\s*(no|numara)\w*|service\s*tag|servis\s*tag|serial\s*(number|no)|firmware|bios\s+surum\w*|"
                          r"(idrac|ilo|bmc)\w*\s+surum\w*|\buuid\w*|\bguid\w*|(management|mgmt|yonetim)\s+ip\w*|\bredfish\b|"
                          r"web\s+(arayuz|url|link|adres)\w*|(idrac|ilo|bmc|ome|oneview)\w*\s+(kullanici|parola|sifre|password|credential)\w*|"
                          r"(parola|sifre|password)\w*\s+.{0,30}\b(idrac|ilo|bmc|ome|oneview)\b)")
_HW_HOWTO = re.compile(r"\b(nasil|ne\s+ise\s+yarar|ne\s+demek|farki|how\s+(to|do)|what\s+is\s+the\s+difference)\b")
_HW_WH_TR = ("**Bu bilgi sohbette paylaşılmaz:** BMC (iDRAC/iLO) IP/yönetim adresi, seri numarası / service tag, UUID, firmware sürümü, "
             "web adresi ve kimlik bilgileri güvenlik gereği sohbete aktarılmaz. Yetkili kullanıcılar bunları **Donanım** sayfasında görebilir. "
             "Sohbette sunucu sağlığı, alarmlar, kasa/yuva ve garanti bitiş tarihini sorabilirsiniz.")
_HW_WH_EN = ("**This is not shared in chat:** BMC (iDRAC/iLO) IP/management address, serial number / service tag, UUID, firmware version, web URL and credentials are "
             "not passed to chat for security reasons. Authorised users can see them on the **Hardware** page. "
             "You can ask about server health, alarms, enclosure/bay and warranty end date here.")


def _hw_withheld(message: str) -> bool:
    raw = (message or "").strip()
    if not raw or len(raw) > 240 or "\n" in raw:
        return False
    try:
        from app.services.hw.intent import hw_active, hw_intent
        if not hw_active() or not hw_intent(raw):
            return False
    except Exception:
        return False
    f = _fold(raw)
    return bool(_HW_WITHHELD.search(f)) and not _HW_HOWTO.search(f)


_HW_DENY_TR = ("**Bu bilgi için yetkiniz yok:** fiziksel sunucu donanım verisi (sağlık, alarm, garanti) `hardware` modülü gerektirir. "
               "Yöneticinizden bu modül için yetki isteyebilirsiniz.")
_HW_DENY_EN = ("**You are not authorised for this:** physical-server hardware data (health, alerts, warranty) requires the "
               "`hardware` module. Ask your administrator for access.")


def _hw_denied(message: str, platform: Optional[str], allowed_modules: Any) -> bool:
    """Yetenek VAR, kullanıcıda `hardware` modülü YOK (allowed_modules None = yönetici/tümü) → LLM'e gitmeden sabit ret."""
    if allowed_modules is None or (platform or "").strip().lower() not in ("unified", ""):
        return False
    try:
        if "hw" in set(allowed_modules):
            return False
        from app.services.hw.intent import hw_active, hw_data_question, hw_intent
        raw = (message or "").strip()
        if not raw or len(raw) > 240 or "\n" in raw or not hw_active() or not hw_intent(raw):
            return False
        f = _fold(raw)
        strong = re.sub(r"fiziksel\s+sunucu\w*", " ", raw, flags=re.IGNORECASE)   # tek başına «fiziksel sunucu» zayıf sinyal
        return hw_intent(strong) and hw_data_question(raw) and not _HW_HOWTO.search(f)
    except Exception:
        return False


def answer(message: str, *, platform: Optional[str] = None, allowed_modules: Any = None) -> Optional[Tuple[str, str]]:
    """(cevap, sınıf) veya None. Automic platformunda çalışmaz."""
    if (platform or "").strip().lower() == "automic":
        return None
    if is_chart_request(message):
        return (_CHART_EN if _is_english(message) else _CHART_TR), "chart"
    if _hw_unavailable(message):
        return (_HW_NA_EN if _is_english(message) else _HW_NA_TR), "hw_unavailable"
    if _hw_denied(message, platform, allowed_modules):
        return (_HW_DENY_EN if _is_english(message) else _HW_DENY_TR), "hw_denied"
    if _hw_withheld(message):
        return (_HW_WH_EN if _is_english(message) else _HW_WH_TR), "hw_withheld"
    cls = classify(message)
    if cls is None:
        return None
    english = _is_english(message)
    if cls == "owner":
        return _owner_answer(message, english), cls
    if cls == "cost":
        return _cost_answer(english), cls
    what, alt = (_NOT_IN_AINEW_EN if english else _NOT_IN_AINEW_TR)[cls]
    if english:
        return (f"**This information is not available in ainew data:** {what}. {alt}", cls)
    return (f"**Bu bilgi ainew verisinde yok:** {what}. {alt}", cls)


def respond(message: str, *, platform: Optional[str] = None, allowed_modules: Any = None) -> Optional[str]:
    """`canned_chitchat_answer` kapısı: şablon cevap veya None. Hata → None (normal akış). İz: qa_rule."""
    try:
        got = answer(message, platform=platform, allowed_modules=allowed_modules)
        if got is None:
            return None
        text, cls = got
        try:
            from app.services.chat_quality import trace as cq_trace
            cq_trace.note_path("qa_rule", handler=f"unavailable_info.{cls}", rule="unavailable_info",
                               topic=cls, platform=platform or "")
        except Exception:
            pass
        logger.info("[UnavailableInfo] class=%s platform=%s", cls, platform)
        return text
    except Exception:
        logger.debug("unavailable_info atlandı", exc_info=True)
        return None


# ── Hafif [Not] hint (karma/belirsiz sorular için; LLM yolu) ─────────────────────────
_HINT_RE = re.compile(
    r"(maliyet|fiyat|ucret|butce|fatura|lisans|licen[cs]e|musteri|customer|sozlesme|contract|\bsla\b|sahib\w*|owner|sorumlu|departman|cost|price)"
)


def hint(message: str) -> str:
    """Mesajda ainew'de tutulmayan kavramlar geçiyorsa tek satırlık not (kodla eklenir); aksi hâlde ''."""
    f = _fold(message or "")
    if not f or not _HINT_RE.search(f):
        return ""
    return ("[Not: ainew lisans, müşteri, sözleşme/SLA taahhüdü, fatura ve gerçek maliyet bilgisi TUTMAZ; "
            "maliyet yalnız tahsisat bazlı TAHMİNDİR (tüm açık VM'ler; cluster/şirket bazı yok); iş sahibi yalnız "
            "Business Service Map ataması olarak vardır. Soru buna ilişkinse 'ainew verisinde yok' de; envanterdeki "
            "bir adı/IP'yi sahip, müşteri veya maliyet diye sunma.]")
