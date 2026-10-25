"""Yönetici raporu AI metni. Kapıdan geçmeyen metin yayımlanmaz."""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Mapping

from app.services.number_gate import check_text

logger = logging.getLogger(__name__)

_INSTRUCTION = (
    "Aşağıdaki JSON rapor gerçekleridir. Yeni sayı, tarih veya yüzde üretme. "
    "Sayı yazacaksan yalnız numbers içindeki display değerlerinden birebir kopyala. "
    "labels içindeki adları kullanabilirsin; onlardaki rakamlar sayı değildir."
)


def prompt_payload(facts: Mapping[str, Any]) -> Dict[str, Any]:
    """VM listesi ve ham satır gitmez. Sayılar, agregatlar ve etiketler gider."""
    sections = []
    for section in facts.get("sections") or []:
        sections.append({
            "id": section.get("id"),
            "title": section.get("title"),
            "status": section.get("status"),
            "numbers": section.get("numbers") or {},
            "labels": section.get("labels") or {},
            "confidence": section.get("confidence"),
            "notes": section.get("notes") or [],
        })
    return {
        "report_type": facts.get("report_type"),
        "period": facts.get("period") or {},
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
        gate = check_text(text, facts, section_id=section_id, require_number=require_number)
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
