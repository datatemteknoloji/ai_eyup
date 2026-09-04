"""Kullanıcı mesajındaki özel ÇIKTI FORMATI komutları — /table, /json, /brief.

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


# Türkçe + İngilizce alias'lar — kelime sınırlı ("/tablomsu" gibi bir kelimeyi
# YANLIŞLIKLA eşleştirmesin diye (?![\w]) ile sağdan sınırlanır).
_DIRECTIVE_PATTERNS: Tuple[Tuple[OutputDirective, "re.Pattern[str]"], ...] = (
    (OutputDirective.JSON, re.compile(r"(?<![\w/])/json(?![\w])", re.I)),
    (OutputDirective.TABLE, re.compile(r"(?<![\w/])/(?:table|tablo)(?![\w])", re.I)),
    (OutputDirective.BRIEF, re.compile(r"(?<![\w/])/(?:brief|kisa|kısa|ozet|özet)(?![\w])", re.I)),
)

# Kullanıcı birden fazla komut yazarsa (ör. "/table /brief") hepsi mesajdan
# temizlenir ama yalnız EN KATI/en belirgin olan uygulanır: JSON (makine
# formatı) > TABLE > BRIEF (serbest metin özeti).
_PRIORITY: Tuple[OutputDirective, ...] = (OutputDirective.JSON, OutputDirective.TABLE, OutputDirective.BRIEF)


def extract_output_directive(message: str) -> Tuple[str, OutputDirective]:
    """Mesajdan /table, /json, /brief komutunu ayıklar.

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
