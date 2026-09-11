"""Sohbet kanıt rozeti — model güveni değil, bu turdaki kanıt.

NLI / cümle sayacı yok. Kavramsal/selam yanıtında rozet yok (yanıltır).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

HIDDEN = "hidden"
HIGH = "high"
MEDIUM = "medium"
LOW = "low"

_LEVELS = (HIDDEN, HIGH, MEDIUM, LOW)


def _badge(level: str, reason: str) -> Dict[str, str]:
    return {"level": level, "reason": reason}


def collect_had_failure(collection_summary: str) -> bool:
    text = collection_summary or ""
    return "STATUS=FAILED" in text or "STATUS=TIMEOUT" in text


def score_evidence_badge(
    *,
    kind: str,
    tools_used: Optional[Sequence[str]] = None,
    has_tool_text: bool = False,
    has_collect: bool = False,
    collect_failed: bool = False,
    has_evidence: bool = False,
    answer_no_data: bool = False,
) -> Dict[str, str]:
    """kind: live | knowledge | chitchat | planning | cache | deterministic"""
    k = (kind or "").strip().lower()
    tools = [t for t in (tools_used or []) if t]

    if k in ("chitchat", "knowledge", "planning", "planning_clarify"):
        return _badge(HIDDEN, "kavramsal veya selam — kanıt rozeti yok")
    if k == "deterministic":
        return _badge(HIGH, "deterministik envanter tablosu")
    if k == "cache":
        return _badge(MEDIUM, "önbellek yanıtı; bu turda yeniden doğrulanmadı")

    if answer_no_data and has_evidence:
        return _badge(LOW, "kanıt varken 'veri yok' cümlesi")
    if has_evidence and tools:
        return _badge(HIGH, "araç ve canlı collect kanıtı var")
    if has_evidence:
        return _badge(HIGH, "bu turda canlı collect kanıtı var")
    if tools and has_tool_text and not collect_failed:
        return _badge(HIGH, "araç sonucu var")
    if tools and has_tool_text:
        return _badge(MEDIUM, "araç var, collect kısmi veya hatalı")
    if tools:
        return _badge(MEDIUM, "araç çağrıldı, çıktı zayıf")
    if has_collect and not collect_failed:
        return _badge(MEDIUM, "sabit collect var, araç yok")
    if collect_failed:
        return _badge(LOW, "collect başarısız veya zaman aşımı")
    if k == "live":
        return _badge(LOW, "canlı soru; bu turda kanıt yok")
    return _badge(HIDDEN, "")


def merge_evidence_meta(meta: Optional[Dict[str, Any]], badge: Optional[Dict[str, str]]) -> Dict[str, Any]:
    out = dict(meta or {})
    if badge and badge.get("level") in (HIGH, MEDIUM, LOW):
        out["evidence"] = {"level": badge["level"], "reason": badge.get("reason") or ""}
    return out


def evidence_sse_field(badge: Optional[Dict[str, str]]) -> Dict[str, Any]:
    if badge and badge.get("level") in (HIGH, MEDIUM, LOW):
        return {"evidence": {"level": badge["level"], "reason": badge.get("reason") or ""}}
    return {}
