"""Yönetici özeti üretim sırasında yazılır. Sayfa model çağırmaz.

Model rakam yazmaz; {anahtar} yer tutucusu bırakır. Backend display değerini basar.
Kapıdan geçmezse şablon cümle kalır.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Mapping, Optional

from app.services.number_gate import check_text

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"\{([a-z0-9_]+)\}")
_BAD_WORD = re.compile(r"\b(closed|inactive|status|error|null|undefined|warning|critical)\b", re.I)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_INSTRUCTION = (
    "Türkçe, 3 ile 5 cümle yaz. Rakam, tarih ve yüzde yazma. "
    "Sayı yerine yalnız süslü parantez içindeki yer tutucuyu kullan: {anahtar}. "
    "Listelenmeyen anahtarı uydurma. Yer tutucuyu değiştirme."
)


def _sections(facts: List[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    out: List[Mapping[str, Any]] = []
    for item in facts or []:
        out.extend(item.get("sections") or [])
    return out


def bindings(facts: List[Mapping[str, Any]]) -> Dict[str, str]:
    """Yer tutucu → display. Demo sayısı buraya konmaz; paket gerçeklerindedir."""
    found: Dict[str, str] = {}
    for section in _sections(facts):
        for key, spec in (section.get("numbers") or {}).items():
            display = (spec or {}).get("display") or []
            if display:
                found[str(key)] = str(display[0])
    return found


def apply_placeholders(text: str, bound: Mapping[str, str]) -> str:
    def repl(match: re.Match) -> str:
        return bound.get(match.group(1), match.group(0))
    return _TOKEN.sub(repl, text or "")


def _disk_phrase(raw: str) -> str:
    try:
        value = float(raw.replace(".", "").replace(",", "."))
    except ValueError:
        return f"{raw} disk"
    if value >= 1024:
        text = f"{value / 1024:.1f}".replace(".", ",")
        if text.endswith(",0"):
            text = text[:-2]
        return f"{text} TB disk"
    return f"{raw} GB disk"


def template_sentences(bound: Mapping[str, str]) -> str:
    lines: List[str] = []
    if "powered_off" in bound and "wasted_vcpu" in bound:
        ram = bound.get("wasted_ram_gb", "")
        disk = bound.get("wasted_disk_gb", "")
        ram_bit = f", {ram} GB RAM" if ram else ""
        disk_bit = f" ve {_disk_phrase(disk)}" if disk else ""
        lines.append(
            f"Kapalı durumdaki {bound['powered_off']} VM toplam {bound['wasted_vcpu']} vCPU"
            + ram_bit + disk_bit + " ayırıyor."
        )
    if "hosts_needed" in bound:
        if bound["hosts_needed"] in ("0", "0 host"):
            lines.append("Önümüzdeki 12 ay için ek sunucu ihtiyacı görünmüyor.")
        else:
            lines.append(f"Önümüzdeki dönemde eklenecek sunucu ihtiyacı {bound['hosts_needed']}.")
    if not lines:
        lines.append("Ölçülen bölümler için sade özet cümlesi üretilemedi.")
    return " ".join(lines)


def _gate_facts(facts: List[Mapping[str, Any]]) -> Dict[str, Any]:
    return {"period": {}, "sections": list(_sections(facts))}


def compose_summary(
    facts: List[Mapping[str, Any]],
    generate: Optional[Callable[[str], str]] = None,
) -> Dict[str, str]:
    bound = bindings(facts)
    if generate is None:
        generate = _live_generate
    try:
        raw = generate(_INSTRUCTION + "\n" + ", ".join(f"{{{key}}}" for key in sorted(bound))) or ""
        if _TOKEN.search(raw) is None and re.search(r"\d", raw):
            raise ValueError("rakam")
        filled = apply_placeholders(raw, bound)
        if _TOKEN.search(filled):
            raise ValueError("bilinmeyen yer tutucu")
        if _BAD_WORD.search(filled) or len(_NUMBER.findall(filled)) >= 7:
            raise ValueError("anlamsız sayı listesi")
        gate = check_text(filled, _gate_facts(facts), require_number=False, all_sections=True)
        if not gate["ok"]:
            raise ValueError(gate.get("reason") or "kapı")
        text = filled.strip()
        if text:
            return {"text": text, "source": "ai"}
    except Exception as exc:
        logger.info("yönetici özeti şablona düştü: %s", exc)
    return {"text": template_sentences(bound), "source": "template"}


def _live_generate(prompt: str) -> str:
    from app.services.llm_gateway import generate_sync, resolve_model_for_tier

    model, _tier = resolve_model_for_tier("strong", None)
    out = generate_sync(model=model, prompt=prompt, timeout=60, think=False)
    if out.get("error"):
        raise RuntimeError(str(out.get("error"))[:200])
    return out.get("response") or ""
