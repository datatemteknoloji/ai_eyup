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


def check_text(
    text: str,
    facts: Mapping[str, Any],
    *,
    section_id: Optional[str] = None,
    require_number: bool = False,
) -> Dict[str, Any]:
    """Eşitlik kapısı. Geçmezse reason döner; metni yeniden yazmaz."""
    labels = section_labels(facts, section_id)
    found = extract_numbers(text, labels)
    if require_number and not found:
        return {"ok": False, "reason": "sayısız_metin", "found": found, "rejected": []}
    allowed = allowed_displays(facts, section_id)
    rejected = [token for token in found if token not in allowed]
    if rejected:
        return {"ok": False, "reason": "display_disi", "found": found, "rejected": rejected}
    return {"ok": True, "reason": None, "found": found, "rejected": []}
