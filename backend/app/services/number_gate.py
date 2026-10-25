"""AI metnindeki sayıları rapor gerçeklerinin display kümesiyle birebir karşılaştırır.

Tolerans yok. Label içindeki rakamlar (esx03, "Edirne, bay 9") sayı sayılmaz.
A1 (require_number=True) sayısız metni reddeder; diğer bölümler sayısız yorumu geçirir.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

_TOKEN = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[./]\d{1,2}[./]\d{4}"
    r"|%\s?\d+(?:[.,]\d+)?"
    r"|\d+(?:[.,]\d+)?\s?%"
    r"|\d+(?:[.,]\d+)?\s*(?:gün|saat|dk|sn|saniye|ay|yıl|GB|MB|TB|GHz|MHz|vCPU|adet)"
    r"|\d+[.,]\d+"
    r"|\d+",
    re.IGNORECASE,
)


def _label_values(labels: Optional[Mapping[str, Any]]) -> List[str]:
    if not labels:
        return []
    out = []
    for value in labels.values():
        if isinstance(value, str) and value.strip():
            out.append(value)
        elif isinstance(value, (list, tuple)):
            out.extend(str(v) for v in value if str(v).strip())
    return sorted(out, key=len, reverse=True)


def _mask_labels(text: str, labels: Iterable[str]) -> str:
    masked = text
    for label in labels:
        if label:
            masked = masked.replace(label, " " * len(label))
    return masked


def extract_numbers(text: str, labels: Optional[Mapping[str, Any]] = None) -> List[str]:
    """Metindeki sayı tokenleri, uzun eşleşme kazanır, örtüşenler atılır."""
    masked = _mask_labels(text or "", _label_values(labels))
    spans = []
    for match in _TOKEN.finditer(masked):
        start, end = match.span()
        if any(start < e and end > s for s, e, _ in spans):
            continue
        spans.append((start, end, match.group(0).strip()))
    return [token for _, _, token in spans]


def allowed_displays(facts: Mapping[str, Any], section_id: Optional[str] = None) -> set:
    allowed = set()
    for section in facts.get("sections") or []:
        if section_id and section.get("id") != section_id:
            continue
        for spec in (section.get("numbers") or {}).values():
            if isinstance(spec, Mapping):
                for form in spec.get("display") or []:
                    allowed.add(str(form))
    return allowed


def section_labels(facts: Mapping[str, Any], section_id: Optional[str] = None) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for section in facts.get("sections") or []:
        if section_id and section.get("id") != section_id:
            continue
        merged.update(section.get("labels") or {})
    return merged


def period_labels(facts: Mapping[str, Any]) -> Dict[str, str]:
    """Dönem dizgisi label'dır. Saat parçası (00) kopyalanırsa sayı sanılmasın."""
    period = facts.get("period") or {}
    if not isinstance(period, Mapping):
        return {}
    out: Dict[str, str] = {}
    for key in ("start", "end"):
        raw = str(period.get(key) or "").strip()
        if not raw:
            continue
        out[f"period_{key}"] = raw
        day = raw[:10]
        if len(day) == 10 and day[4] == "-" and day != raw:
            out[f"period_{key}_day"] = day
    return out


def _thousands_canonical(token: str) -> Optional[str]:
    """533.816 ve 533,816 aynı tam sayıdır. 72,4 ondalıktır, buraya girmez."""
    match = re.fullmatch(r"(\d{1,3}(?:[.,]\d{3})+)(?:\s+(\S+))?", token.strip())
    if not match:
        return None
    bare = match.group(1).replace(".", "").replace(",", "")
    unit = match.group(2)
    return f"{bare} {unit}" if unit else bare


def _display_match(token: str, allowed: set) -> bool:
    if token in allowed:
        return True
    canon = _thousands_canonical(token)
    return bool(canon and canon in allowed)


def check_text(
    text: str,
    facts: Mapping[str, Any],
    *,
    section_id: Optional[str] = None,
    require_number: bool = False,
    all_sections: bool = False,
) -> Dict[str, Any]:
    """Eşitlik kapısı. Geçmezse reason döner; metni yeniden yazmaz.

    all_sections: prompt bütün raporu taşıyorsa kardeş bölümün display'i de geçerlidir.
    """
    labels = section_labels(facts, None if all_sections else section_id)
    labels.update(period_labels(facts))
    found = extract_numbers(text, labels)
    if require_number and not found:
        return {"ok": False, "reason": "sayısız_metin", "found": found, "rejected": []}
    allowed = allowed_displays(facts, None if all_sections else section_id)
    rejected = [token for token in found if not _display_match(token, allowed)]
    if rejected:
        return {"ok": False, "reason": "display_disi", "found": found, "rejected": rejected}
    return {"ok": True, "reason": None, "found": found, "rejected": []}
