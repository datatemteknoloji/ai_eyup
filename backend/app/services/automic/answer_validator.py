"""Çalışma zamanı cevap doğrulayıcısı — kullanıcıya gitmeden önce (Adım 7h).

Benchmark kalite kurallarıyla aynı kalıplar (tek kaynak mantığı).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Planlama / düşünme sızıntısı
_PLAN_LEAK_RE = re.compile(
    r"(?i)\b("
    r"Provide\b|Should\b|Let's\s+\w+|Let\s+us\b|We\s+need\s+to|We\s+should|"
    r"Probably\b|The\s+instruction:|I\s+need\s+to|I\s+should|Let\s+me\s+think|"
    r"Okay,?\s+so\b|First,?\s+I\b|User\s+asked|The\s+user\s+(?:wants|asked)|"
    r"bold\s+sentence|craft\s+(?:the\s+)?(?:answer|response)|"
    r"That's\s+fine|That\s+is\s+fine|analysis\s+channel|thinking\s*:|"
    r"Here'?s\s+(?:the\s+)?(?:answer|response)|I'll\s+(?:now\s+)?(?:write|craft)"
    r")"
)

# İç talimat / sistem prompt sızıntısı (yasaklı metin)
FORBIDDEN_PHRASES: Tuple[str, ...] = (
    "Sistem/ortam adı sunucu değildir",
    "sistem adı sunucu değildir",
    "Sistem/ortam adı (ör. DEV-FAKE) sunucu değildir",
    "sunucu = agent hostname/IP veya Engine IP",
    "IP/hostname kullan",
    "'En çok' yalnız bu sıralı listeden",
    "satır sırasından çıkarılmaz",
    "Oran filtrelenmiş kümeden HESAPLANMAZ",
    "Kendi 'Varsayım: dün",
    "araç çağrısında from/to/range VERME",
    "answer_language",
    "kullanim\":",
    "This is a read-only",
    "Do not invent",
    "Ortak noktalar YALNIZ",
)

_TOOL_CALL_RE = re.compile(r"(?i)\bautomic_[a-z_]+\s*\([^)\n]{0,200}\)")
_CODE_MEANING_SENT_RE = re.compile(
    r"[^.!?\n]*(?:"
    r"(?:return\s*code|dönüş\s*kodu|status\s*code|durum\s*kodu)[^.!?\n]*"
    r"(?:genellikle|genelde|anlamına|yorumlan|means|typically|usually)"
    r"|\b\d{1,5}\b\s*(?:kodu\s*)?(?:genellikle|genelde)\b[^.!?\n]*(?:hata|başar[ıi]s[ıi]z|yorumlan|anlam)"
    r"|(?:genellikle|genelde)\s+(?:genel\s+)?hata\s+olarak\s+yorumlan"
    r")[^.!?\n]*[.!?]?"
)
_TOOL_SYNTAX_RE = re.compile(
    r"(?i)\bautomic_[a-z_]+\b|\baspect\s*=\s*[\"']?\w+|\btemplate_id\s*=\s*[\"']?\w+"
)
_INTERNAL_LABEL_RE = re.compile(
    r"(?im)^[ \t]*(?:\*\*)?[ \t]*(?:Ainew-?meta|Follow-?ups?|Followups?)[ \t]*(?:\*\*)?[ \t]*:?[ \t]*$"
)
_FOLLOWUPS_HEAD_RE = re.compile(
    r"(?im)^[ \t]*(?:\*\*)?[ \t]*Follow-?ups?[ \t]*(?:\*\*)?[ \t]*:?[ \t]*\n?"
)
_CODE_MEANING_RE = re.compile(
    r"(?i)(?:return\s*code|dönüş\s*kodu|status\s*code|durum\s*kodu)\s*"
    r"(?:\d+\s*)?(?:genellikle|genelde|anlamına|olarak\s+yorumlan|means|typically|usually)"
    r"|(?:genellikle|genelde)\s+(?:genel\s+)?hata\s+olarak\s+yorumlan"
)
_STRAY_TICK_RE = re.compile(r"(?m)^[ \t]*`+[ \t]*$")
_EN_SENTENCE_IN_TR_RE = re.compile(
    r"(?m)^[ \t]*\*\*[\"']?\s*(?:That's|That is|Provide|Should|Let's|We need|Okay)[^*\n]{0,200}\*\*"
)


def _cut_spans(text: str, spans: List[Tuple[int, int]]) -> str:
    if not spans:
        return text
    spans = sorted(spans)
    out, pos = [], 0
    for a, b in spans:
        if a < pos:
            continue
        out.append(text[pos:a])
        pos = b
    out.append(text[pos:])
    return "".join(out)


def validate_answer(text: str, *, english: bool = False) -> Tuple[str, List[Dict[str, Any]]]:
    """Cevabı temizle → (yeni_metin, müdahaleler[{rule, excerpt}]).

    Meta çiti (```ainew-meta) korunur; gövde temizlenir.
    """
    if not text:
        return text, []
    idx = text.find("```ainew-meta")
    body, meta = (text[:idx], text[idx:]) if idx >= 0 else (text, "")
    interventions: List[Dict[str, Any]] = []

    def note(rule: str, excerpt: str) -> None:
        interventions.append({"rule": rule, "excerpt": (excerpt or "")[:120]})

    # 1) İngilizce planlama / "That's fine" kalın blok
    for m in list(_EN_SENTENCE_IN_TR_RE.finditer(body)) + list(_PLAN_LEAK_RE.finditer(body)):
        note("plan_leak", m.group(0))
    body2 = _EN_SENTENCE_IN_TR_RE.sub("", body)
    # Cümle/paragraf düzeyinde planlama satırlarını at
    lines_out = []
    for ln in body2.splitlines(keepends=True):
        if _PLAN_LEAK_RE.search(ln) and not re.search(r"[ğüşıöçĞÜŞİÖÇ]", ln):
            note("plan_leak_line", ln.strip())
            continue
        lines_out.append(ln)
    body = "".join(lines_out)

    # 2) Yasaklı iç talimat — cümlenin TAMAMI atılır (kalıntı "; ." / yarım cümle kalmasın)
    for phrase in FORBIDDEN_PHRASES:
        pat = re.compile(r"[^.!?\n]*" + re.escape(phrase) + r"[^.!?\n]*[.!?]?[ \t]*", re.I)
        if pat.search(body):
            note("forbidden_instruction", phrase)
            body = pat.sub("", body)

    # 3) Araç adı / aspect= (çağrı biçimi bütün olarak; sonra çıplak ad/argüman)
    for m in _TOOL_SYNTAX_RE.finditer(body):
        note("tool_syntax", m.group(0))
    body = _TOOL_CALL_RE.sub("", body)
    body = _TOOL_SYNTAX_RE.sub("", body)
    body = re.sub(r"\(\s*\)", "", body)

    # 4) İç etiket / Follow-ups → Takip
    if _INTERNAL_LABEL_RE.search(body) or _FOLLOWUPS_HEAD_RE.search(body):
        note("internal_label", "Ainew-meta/Follow-ups")
    body = _INTERNAL_LABEL_RE.sub("", body)
    body = _FOLLOWUPS_HEAD_RE.sub(("**Takip önerileri:**\n" if not english else "**Follow-ups:**\n"), body)

    # 5) Dönüş/durum koduna neden anlamı
    for m in _CODE_MEANING_SENT_RE.finditer(body):
        if m.group(0).strip():
            note("code_meaning", m.group(0).strip())
    # Cümleyi (noktaya kadar) kes — dönüş/durum koduna anlam yüklenen her cümle
    body = _CODE_MEANING_SENT_RE.sub("", body)

    # 6) Artık işaretler / kesim artıkları
    body = _STRAY_TICK_RE.sub("", body)
    body = re.sub(r"[ \t]*;[ \t]*\.", ".", body)
    body = re.sub(r"(?m)^[ \t]*[;.:]+[ \t]*$", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    # Art arda tekrarlanan olumsuzlama/varlık sözcüğü ("Kanıt yok yok", "var var") → tek
    body = re.sub(r"(?i)\b(yok|var|değil|bulunamadı)([ \t]+)\1\b", r"\1", body)
    body = re.sub(r"[ \t]{2,}", " ", body)
    body = body.strip() + ("\n" if body.strip() else "")

    return body + meta, interventions


def needs_regenerate(text: str, interventions: List[Dict[str, Any]]) -> bool:
    """Temizlik sonrası gövde çok kısaysa veya hâlâ sızıntı varsa yeniden üret."""
    idx = text.find("```ainew-meta")
    body = (text[:idx] if idx >= 0 else text).strip()
    if len(body) < 24:
        return True
    if _PLAN_LEAK_RE.search(body) or _EN_SENTENCE_IN_TR_RE.search(body):
        return True
    return False
