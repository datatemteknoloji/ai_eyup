"""Kullanıcı mesajındaki özel ÇIKTI FORMATI komutları — /table, /json, /brief, /diagram.

Genel kural (tek bir soruya özel değil): bu komutlar HERHANGİ bir sohbet
platformunda (Linux/Windows/Unified/vCenter) ve HERHANGİ bir soru için aynı
şekilde çalışır:
  1) Regex ile mesajdan ayıklanır (büyük/küçük harf duyarsız, mesajın
     başında/ortasında/sonunda olabilir, Türkçe alias'lar da desteklenir).
  2) Komut token'ı temiz sorudan çıkarılır (LLM'e gönderilecek asıl soru
     komut metniyle kirlenmesin diye).
  3) İki farklı katmana uygulanır:
       a) LLM'e giden sistem/prompt talimatı (directive_system_addendum) —
          serbest metin cevaplarda.
       b) Deterministik (LLM'siz) tablo üretiminde — render_rows_as_json /
          render_rows_as_brief ile virt_inventory_contract gibi modüller
          kendi tablo şablonlarını JSON/özet formatına çevirebilir.
  /diagram ekstra LLM veya SSE event açmaz; aynı final çağrıya addendum ekler.
  /chart alias değildir — Timescale + Recharts yolu (metric_history) bozulmasın.
"""
from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple


class OutputDirective(str, Enum):
    NONE = "none"
    TABLE = "table"
    JSON = "json"
    BRIEF = "brief"
    DIAGRAM = "diagram"


# Türkçe + İngilizce alias'lar — kelime sınırlı ("/tablomsu" gibi bir kelimeyi
# YANLIŞLIKLA eşleştirmesin diye (?![\w]) ile sağdan sınırlanır).
_DIRECTIVE_PATTERNS: Tuple[Tuple[OutputDirective, "re.Pattern[str]"], ...] = (
    (OutputDirective.JSON, re.compile(r"(?<![\w/])/json(?![\w])", re.I)),
    (OutputDirective.TABLE, re.compile(r"(?<![\w/])/(?:table|tablo)(?![\w])", re.I)),
    (OutputDirective.DIAGRAM, re.compile(
        r"(?<![\w/])/(?:diagram|draw|gorsellestir|görselleştir|sema|şema)(?![\w])",
        re.I,
    )),
    (OutputDirective.BRIEF, re.compile(r"(?<![\w/])/(?:brief|kisa|kısa|ozet|özet)(?![\w])", re.I)),
)

# Kullanıcı birden fazla komut yazarsa (ör. "/table /brief") hepsi mesajdan
# temizlenir ama yalnız EN KATI/en belirgin olan uygulanır: JSON (makine
# formatı) > TABLE > DIAGRAM (görsel) > BRIEF (serbest metin özeti).
_PRIORITY: Tuple[OutputDirective, ...] = (
    OutputDirective.JSON,
    OutputDirective.TABLE,
    OutputDirective.DIAGRAM,
    OutputDirective.BRIEF,
)


def extract_output_directive(message: str) -> Tuple[str, OutputDirective]:
    """Mesajdan /table, /json, /brief, /diagram komutunu ayıklar.

    Döner: (komut(lar) temizlenmiş mesaj, en yüksek öncelikli komut).
    Hiçbir komut yoksa (orijinal mesaj (strip'lenmiş), OutputDirective.NONE).
    """
    if not message or not message.strip():
        return message, OutputDirective.NONE

    found = set()
    cleaned = message
    for directive, pattern in _DIRECTIVE_PATTERNS:
        if pattern.search(cleaned):
            found.add(directive)
        cleaned = pattern.sub(" ", cleaned)

    if not found:
        return message, OutputDirective.NONE

    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    chosen = next((d for d in _PRIORITY if d in found), OutputDirective.NONE)
    return (cleaned or message.strip()), chosen


_ADDENDUM: Dict[OutputDirective, str] = {
    OutputDirective.TABLE: (
        "\n\nÇIKTI FORMATI KOMUTU (/table): Kullanıcı bu turda YALNIZCA markdown "
        "tablo(lar) istedi. Cevabı tablo(lar) halinde ver; tablo öncesi/sonrası "
        "uzun paragraf açıklama EKLEME (gerekirse tek satırlık başlık/not yeterli)."
    ),
    OutputDirective.JSON: (
        "\n\nÇIKTI FORMATI KOMUTU (/json): Kullanıcı bu turda YALNIZCA JSON istedi. "
        "Cevabı geçerli bir JSON nesnesi/dizisi olarak, ```json kod bloğu içinde ver. "
        "JSON dışında hiçbir doğal dil cümlesi, açıklama veya markdown tablo EKLEME."
    ),
    OutputDirective.BRIEF: (
        "\n\nÇIKTI FORMATI KOMUTU (/brief): Kullanıcı bu turda EN FAZLA 2-3 CÜMLE ile "
        "öz ve doğrudan bir cevap istedi. Madde işareti, tablo, uzun açıklama veya alt "
        "başlık KULLANMA — yalnız doğrudan sonucu 2-3 cümleyle söyle."
    ),
    OutputDirective.DIAGRAM: (
        "\n\nÇIKTI FORMATI KOMUTU (/diagram): Kullanıcı bu turda teknik bir diyagram istedi. "
        "Aynı cevapta (ekstra adım yok) en uygun Mermaid tipini sen seç: flowchart, "
        "sequenceDiagram, erDiagram, stateDiagram-v2 veya gantt. Ağ/topoloji için flowchart "
        "kullan — SVG veya HTML üretme. Sayısal zaman serisi (son N saat CPU/RAM/disk) "
        "isteniyorsa xychart-beta yazma; kısa metin/tablo yeterli (mevcut Recharts yolu "
        "ayrı çalışır). En fazla bir ```mermaid kod bloğu üret; 15-20 düğüm/adımı geçme, "
        "büyük listeleri özetle. Düğüm/aktör etiketleri düz metin: en fazla 4-5 kelime; "
        "**kalın**, _italik_, `kod`, HTML veya markdown YASAK (Mermaid bunları çizmez, "
        "yıldızları gösterir). Dosya yolu etiketlerinde tırnak ZORUNLU: "
        "B[\"/boot\"] doğru; B[/boot] YASAK (Mermaid bunu şekil sanır, çizim kırılır). "
        "Windows yolu: A[\"C:\\\\Windows\"] — ters eğik çizgiyi de tırnak içine al. "
        "Gereksiz meta düğüm ekleme (ör. 'Sunucu Sorgusu'). "
        "Emin değilsen flowchart kullan. TİP:/GEREKÇE: satırı yazma. "
        "Cevap yapısı ZORUNLU: (1) isteğe bağlı tek satır başlık, (2) kapanmış ```mermaid "
        "bloğu, (3) hemen altında kısa yorum — 2-4 madde veya 2-3 cümle: diyagram neyi "
        "gösteriyor, ana adımlar/aktörler, okunan sonuç. Uzun makale, tekrarlayan özet "
        "veya diyagramı kelime kelime okuma YOK. Markdown liste/ASCII tek başına YETERLİ "
        "DEĞİL — mutlaka kapanmış ```mermaid bloğu + kısa yorum üret."
    ),
}


def directive_system_addendum(directive: Optional[OutputDirective]) -> str:
    """LLM'e eklenecek sistem/prompt talimatı; NONE/None için boş string."""
    if not directive or directive == OutputDirective.NONE:
        return ""
    return _ADDENDUM.get(directive, "")


def directive_label(directive: Optional[OutputDirective]) -> str:
    return {
        OutputDirective.TABLE: "/table",
        OutputDirective.JSON: "/json",
        OutputDirective.BRIEF: "/brief",
        OutputDirective.DIAGRAM: "/diagram",
    }.get(directive, "")


# ── Deterministik (LLM'siz) render yardımcıları ──────────────────────────────
# Herhangi bir modül (virt_inventory_contract, ocp_db_query, vb.) kendi satır
# listesini JSON/brief formatına çevirmek için bunları kullanabilir — kind'a
# özel değildir.

def render_rows_as_json(
    rows: Sequence[Dict[str, Any]],
    *,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """Satır listesini ```json kod bloğu içinde döndürür (LLM'siz, sözleşme birebir)."""
    payload: Dict[str, Any] = dict(meta or {})
    payload["count"] = len(rows)
    payload["items"] = list(rows)
    body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    return f"```json\n{body}\n```"


def render_rows_as_brief(
    rows: Sequence[Dict[str, Any]],
    *,
    subject: str,
    name_field: str = "name",
    extra: Optional[str] = None,
    max_names: int = 5,
) -> str:
    """Satır listesini EN FAZLA birkaç cümlelik özet metne çevirir."""
    n = len(rows)
    if n == 0:
        return f"{subject} için sonuç bulunamadı."
    names: List[str] = []
    for r in rows[:max_names]:
        if isinstance(r, dict):
            names.append(str(r.get(name_field) or "—"))
    sample = ", ".join(names)
    more = f" ve {n - len(names)} diğeri" if n > len(names) else ""
    sentence = f"{subject}: toplam {n} kayıt bulundu ({sample}{more})."
    if extra:
        sentence += f" {extra}"
    return sentence
