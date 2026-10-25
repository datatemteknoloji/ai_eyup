"""Yönetici raporu AI metni. Kapıdan geçmeyen metin yayımlanmaz."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, Mapping

from app.services.number_gate import check_text

logger = logging.getLogger(__name__)

_INSTRUCTION = (
    "Aşağıdaki JSON rapor gerçekleridir. Yeni sayı, tarih veya yüzde üretme. "
    "Sayı yazacaksan yalnız numbers içindeki display değerlerinden birebir kopyala. "
    "Ondalık ayırıcıyı değiştirme. "
    "labels içindeki adları kullanabilirsin; onlardaki rakamlar sayı değildir. "
    "period alanını sayı gibi yazma."
)


def _labels_without_digits(labels: Mapping[str, Any]) -> Dict[str, Any]:
    """Etiket prompt'ta kalır; rakamları silinir ki IP ve sürüm sayı sanılmasın."""
    out: Dict[str, Any] = {}
    for key, value in labels.items():
        if isinstance(value, str):
            out[str(key)] = re.sub(r"\d+", "…", value)
        else:
            out[str(key)] = value
    return out


def _day(value: Any) -> str:
    raw = str(value or "").strip()
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    return raw


def prompt_payload(facts: Mapping[str, Any]) -> Dict[str, Any]:
    """VM listesi ve ham satır gitmez. Sayılar, agregatlar ve etiketler gider.

    Dönem tarihi prompt'a girmez. Model yılı ve günü sayı diye kopyalamasın.
    """
    sections = []
    for section in facts.get("sections") or []:
        sections.append({
            "id": section.get("id"),
            "title": section.get("title"),
            "status": section.get("status"),
            "numbers": section.get("numbers") or {},
            "labels": _labels_without_digits(section.get("labels") or {}),
            "confidence": section.get("confidence"),
            "notes": section.get("notes") or [],
        })
    period = facts.get("period") or {}
    start, end = _day(period.get("start")), _day(period.get("end"))
    return {
        "report_type": facts.get("report_type"),
        "period": {"label": "bu dönem"} if start or end else {},
        "data_readiness": facts.get("data_readiness") or [],
        "sections": sections,
    }


def template_summary(facts: Mapping[str, Any], section_id: str) -> str:
    """Kapıdan geçecek kural cümleleri. Yalnız display yazımları."""
    section = next((s for s in facts.get("sections") or [] if s.get("id") == section_id), None)
    if not section:
        return "Bu bölüm için sayı üretilemedi."
    if section.get("status") != "ok":
        note = (section.get("notes") or ["veri yok"])[0]
        return f"{section.get('title')}: {note}"
    bits = []
    for spec in (section.get("numbers") or {}).values():
        display = (spec or {}).get("display") or []
        if display:
            bits.append(str(display[0]))
    if not bits:
        return f"{section.get('title')} için yorum sayısız bırakıldı."
    return f"{section.get('title')}: " + ", ".join(bits) + "."


def publish_commentary(
    facts: Mapping[str, Any],
    section_id: str,
    generate: Callable[[str], str],
    *,
    require_number: bool = False,
) -> Dict[str, Any]:
    """Bir üretim, ret olursa bir kez daha. İkisi de ret ise AI metni yayımlanmaz."""
    payload = json.dumps(prompt_payload(facts), ensure_ascii=False)
    prompt = _INSTRUCTION + "\n" + payload

    def _once(extra: str = "") -> Dict[str, Any]:
        text = generate(prompt if not extra else prompt + "\n" + extra) or ""
        gate = check_text(
            text, facts, section_id=section_id, require_number=require_number, all_sections=True,
        )
        return {"text": text, "gate": gate}

    first = _once()
    if first["gate"]["ok"]:
        return {"published": first["text"], "source": "ai", "attempts": 1}
    logger.warning(
        "yönetici yorumu reddedildi section=%s reason=%s rejected=%s",
        section_id, first["gate"].get("reason"), first["gate"].get("rejected"),
    )
    second = _once("Önceki metin reddedildi. Yalnız display değerlerini kullan.")
    if second["gate"]["ok"]:
        return {"published": second["text"], "source": "ai", "attempts": 2}
    logger.warning(
        "yönetici yorumu ikinci kez reddedildi section=%s reason=%s rejected=%s",
        section_id, second["gate"].get("reason"), second["gate"].get("rejected"),
    )
    return {
        "published": None,
        "source": "template",
        "fallback": template_summary(facts, section_id),
        "attempts": 2,
    }
