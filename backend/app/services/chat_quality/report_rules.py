"""Adım 21 — «Rapor soruları»: OpenShift ve Yönetici (Tüm Ortamlar) hazır raporlarını sohbetten üretir.

Sanallaştırma sohbetindeki «Rapor soruları» davranışının OpenShift / Doğal Dil Asistanı (Yönetici) karşılığı.
Fark: LLM YOK — rakamların tamamı rapor motorundan (`ocp_report_engine`, `exec_catalog_reports`) gelir ve
cevap motorun KISA özetidir (`generic_report.to_chat_markdown`). Böylece sayı uydurma riski sıfır, gecikme düşük.

İki parça:
  * ``detect`` — SAF (DB yok, async yolda güvenle çağrılır): mesaj bir rapor isteği mi, hangi motor/tip?
  * ``build_answer`` — SENKRON DB işi: çağıran ``core.chat_executor.run_chat_io`` ile ayrı iş parçacığında çalıştırır.

Kapsam kuralları:
  * Platform ``openshift`` → yalnız OpenShift raporları (14 tip, MTV dahil).
  * Platform ``unified`` → migrasyon/MTV sözcüğü + `executive` yetkisi → Yönetici «migration» raporu; diğer OpenShift
    sözcükleri (namespace/PVC/workload/kubevirt/openshift) → OpenShift raporu; aksi hâlde Yönetici raporu.
    Yalnız belirli bir platformu adlandıran istekler (Linux/Windows/Exadata/vCenter/ESX/VM) KAPSAM DIŞI
    (normal akış: ``infra_report`` aracı) — «tüm ortam» ifadesi varsa Yönetici raporu olur.
  * Rapor kelimesi yoksa, soru nedensellik/yöntem soruysa (neden/nasıl/nedir) veya mesaj uzunsa → None.
  * RBAC: ``ocp_ok`` / ``exec_ok`` çağıranda hesaplanır (Yönetici raporu `executive` modülü ister).
Raporlar ``save=True`` ile kaydedilir (Hazır Raporlar geçmişinde görünür; sanallaştırma sohbetiyle aynı).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

_TR = str.maketrans("çğıöşüâîûÇĞİÖŞÜ", "cgiosuaiuCGIOSU")
_MAX_LEN = 200


def _fold(s: str) -> str:
    return (s or "").replace("İ", "i").replace("I", "ı").lower().translate(_TR)


@dataclass(frozen=True)
class ReportIntent:
    scope: str          # "openshift" | "executive"
    report_type: str
    lang: str = field(default="tr", compare=False)   # cevap dili (mesajdan): "tr" | "en"


_REPORT_WORD = re.compile(r"\b(rapor\w*|report\w*)\b")
# Raporun kendisi hakkında açıklama/neden soruları: üretme, normal akışa bırak.
_EXPLAIN = re.compile(r"\b(neden|nasil|why|how|nedir|ne\s+demek|aciklar\s+misin|anlat)\b")
# Yalnız belirli bir platformu adlandıran istek (OpenShift/MTV hariç) → unified'da Yönetici raporu DEĞİL.
_OTHER_PLATFORM = re.compile(r"\b(linux|windows|exadata|vcenter|vmware|esxi?|hyper-?v|kvm|proxmox|olvm|ovirt|vm|vm'?ler\w*|sanal\w*|centrify|automic)\b")
_ALL_ENV = re.compile(r"(tum\s+(ortam|altyapi|platform)|butun\s+(ortam|altyapi)|tum\s+ortamlar|genel\s+altyapi|ortam\s+genel|all\s+environments?|whole\s+infra|fleet)")
_MIGRATION = re.compile(r"(mtv|forklift|migrasyon|migration)")
_OCP_WORD = re.compile(r"\b(openshift|ocp|mtv|forklift|kubevirt|namespace|pvc|workload)\w*")

# (rapor tipi, düzenli ifade) — SIRA önemlidir: özelden genele.
_OCP_MAP: List[Tuple[str, "re.Pattern[str]"]] = [
    ("mtv_readiness", re.compile(r"(mtv.*(hazirlik|readiness|uygun)|(migrasyon|migration)\s+hazirlik|hazirlik.*(mtv|migrasyon|migration)|readiness)")),
    ("mtv_migration", re.compile(r"(mtv|forklift|migrasyon|migration|tasima)")),
    ("capacity_plan", re.compile(r"(kapasite\s+plan|capacity\s+plan|n\s*\+\s*1)")),
    ("forecast", re.compile(r"(tahmin|forecast|tukenme|projeksiyon)")),
    ("capacity", re.compile(r"(kapasite|capacity)")),
    ("riskiest_assets", re.compile(r"(en\s+riskli|riskiest|riskli\s+varlik)")),
    ("risk", re.compile(r"\brisk")),
    ("namespace_usage", re.compile(r"(namespace|proje\s+(kullan|rapor)|projeler)")),
    ("storage", re.compile(r"(depolama|\bpvc\b|storage|persistent)")),
    ("workload_health", re.compile(r"(workload|is\s*yuku|pod\s+sagl|pod\s+durum)")),
    ("vm_health", re.compile(r"(kubevirt|sanal\s+makine|vm\s+sagl|vm\s+durum|\bvm\b)")),
    ("compliance_update", re.compile(r"(uyum|guncelleme|update|compliance|yama|surum)")),
    ("operations", re.compile(r"(operasyon|operation)")),
    ("executive_summary", re.compile(r"(executive|yonetici|ozet|genel\s+rapor|ortam\s+rapor|durum\s+rapor|summary)")),
]

_EXEC_MAP: List[Tuple[str, "re.Pattern[str]"]] = [
    ("migration", re.compile(r"(mtv|forklift|migrasyon|migration|tasima)")),
    ("forecast", re.compile(r"(tahmin|forecast|tukenme|projeksiyon)")),
    ("capacity", re.compile(r"(kapasite|capacity)")),
    ("riskiest_assets", re.compile(r"(en\s+riskli|riskiest|riskli\s+varlik)")),
    ("risk", re.compile(r"\brisk")),
    ("operations", re.compile(r"(operasyon|operation)")),
    ("sla", re.compile(r"(\bsla\b|erisilebilirlik|availability|uptime)")),
    ("patch_compliance", re.compile(r"(yama|uyum|patch|compliance|guvenlik\s+uyum)")),
    ("reclaim", re.compile(r"(geri\s+kazan|reclaim|right-?siz|atil|bosta)")),
    ("monitoring_coverage", re.compile(r"(izleme\s+kapsam|monitoring|izleme\s+rapor)")),
    ("executive_summary", re.compile(r"(executive|yonetici|ozet|genel\s+rapor|ortam\s+rapor|durum\s+rapor|summary)")),
]


def _pick(f: str, table: List[Tuple[str, "re.Pattern[str]"]]) -> Optional[str]:
    for rtype, pat in table:
        if pat.search(f):
            return rtype
    return None


def detect(message: Optional[str], *, platform: Optional[str], ocp_ok: bool = False,
           exec_ok: bool = False) -> Optional[ReportIntent]:
    """`_detect` + cevap dili (mesaj İngilizce ise rapor içeriği de İngilizce döner)."""
    from dataclasses import replace

    from app.services.report_i18n import lang_of

    it = _detect(message, platform=platform, ocp_ok=ocp_ok, exec_ok=exec_ok)
    return replace(it, lang=lang_of(message)) if it else None


def _detect(message: Optional[str], *, platform: Optional[str], ocp_ok: bool = False,
            exec_ok: bool = False) -> Optional[ReportIntent]:
    """Mesaj OpenShift/Yönetici hazır raporu isteği mi? SAF fonksiyon (DB yok). Emin değilse None."""
    raw = (message or "").strip()
    if not raw or len(raw) > _MAX_LEN:
        return None
    f = _fold(raw)
    if not _REPORT_WORD.search(f) or _EXPLAIN.search(f):
        return None
    plat = (platform or "").strip().lower()
    if plat == "openshift":
        if not ocp_ok:
            return None
        rtype = _pick(f, _OCP_MAP)
        return ReportIntent("openshift", rtype) if rtype else None
    if plat != "unified":
        return None
    if _MIGRATION.search(f) and exec_ok:
        # Unified'da migrasyon/MTV → Yönetici «Sanallaştırma → OpenShift Migrasyon» (hem plan geçmişi hem hazırlık)
        return ReportIntent("executive", "migration")
    if _OCP_WORD.search(f):
        if not ocp_ok:
            return None
        rtype = _pick(f, _OCP_MAP)
        return ReportIntent("openshift", rtype) if rtype else None
    if not exec_ok:
        return None
    if _OTHER_PLATFORM.search(f) and not _ALL_ENV.search(f):
        return None
    rtype = _pick(f, _EXEC_MAP)
    return ReportIntent("executive", rtype) if rtype else None


_FULL_HINT_EN = {
    "openshift": "_Full list, charts and method notes: **OpenShift → Infrastructure Reports** page._",
    "executive": "_Full list, coverage matrix and method notes: **Executive → All Environments Reports** page._",
}

_FULL_HINT = {
    "openshift": "_Tam liste, grafikler ve yöntem notları: **OpenShift → Altyapı Raporları** sayfası._",
    "executive": "_Tam liste, kapsam matrisi ve yöntem notları: **Yönetici → Tüm Ortamlar Raporları** sayfası._",
}


def build_answer(intent: ReportIntent) -> dict:
    """Raporu üretir (senkron DB; `run_chat_io` ile çağır). Hata yükseltir — çağıran normal akışa düşer."""
    from app.core.database import SessionLocal
    from app.services import generic_report as gr

    db = SessionLocal()
    try:
        if intent.scope == "openshift":
            from app.services import ocp_report_engine as eng
        else:
            from app.services import exec_catalog_reports as eng
        data = eng.generate(db, intent.report_type, save=True)
        title = eng.REPORT_TITLES.get(intent.report_type, intent.report_type)
        en = intent.lang == "en"
        if en:
            from app.services.report_i18n import t as _t

            title = _t(title, "en")
        md = gr.to_chat_markdown(data, full_hint=(_FULL_HINT_EN if en else _FULL_HINT)[intent.scope],
                                 lang=intent.lang)
        return {
            "answer": md,
            "report_type": f"{intent.scope}:{intent.report_type}",
            "report_title": title,
            "report_id": data.get("_report_id"),
        }
    finally:
        db.close()


def note_trace(intent: ReportIntent, platform: Optional[str]) -> None:
    """Tur izine qa_rule yolu (LLM yok). Hata sessiz."""
    try:
        from app.services.chat_quality import trace as cq_trace
        cq_trace.note_path("qa_rule", handler=f"report_rules.{intent.scope}", rule="report_rules",
                           topic=intent.report_type, platform=platform or "")
    except Exception:
        pass
    logger.info("[ReportRules] scope=%s type=%s platform=%s", intent.scope, intent.report_type, platform)

