"""Sohbet kanıt rozeti — model güveni değil, bu turdaki kanıt.

NLI / cümle sayacı yok. Kavramsal/selam yanıtında rozet yok (yanıltır).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

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


def _score(
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


def _tool_sources(tools: Sequence[str]) -> List[Dict[str, Any]]:
    """T.3: tool'dan gelen sayılar için kaynak satırı verisi — yöntem sınıfı method registry'den."""
    from app.services import method_registry as mr

    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out: List[Dict[str, Any]] = []
    seen = set()
    for t in tools:
        if not t or t in seen:
            continue
        seen.add(t)
        m = mr.resolve_tool(t)
        src: Dict[str, Any] = {"tool": t, "class": m.cls if m else None, "at": at}
        from app.services.backup.demo_gate import tool_is_demo
        if tool_is_demo(t):
            src["demo"] = True     # F.0: demo modunda kaynak satırı "DEMO veri" etiketi taşır
        out.append(src)
    return out


def score_evidence_badge(
    *,
    kind: str,
    tools_used: Optional[Sequence[str]] = None,
    has_tool_text: bool = False,
    has_collect: bool = False,
    collect_failed: bool = False,
    has_evidence: bool = False,
    answer_no_data: bool = False,
) -> Dict[str, Any]:
    """Rozet + (T.3) kaynak satırı verisi + 'AI genel bilgisi' işareti.

    `sources`: bu turda çağrılan araçlar ve yöntem sınıfları. `general`: yanıt araç/collect
    verisine dayanmıyor (kavramsal soru veya kanıtsız canlı soru) — UI 'ortamınızdan alınmadı' notu gösterir.
    """
    b: Dict[str, Any] = _score(
        kind=kind, tools_used=tools_used, has_tool_text=has_tool_text, has_collect=has_collect,
        collect_failed=collect_failed, has_evidence=has_evidence, answer_no_data=answer_no_data,
    )
    tools = [t for t in (tools_used or []) if t]
    if tools:
        b["sources"] = _tool_sources(tools)
    k = (kind or "").strip().lower()
    if k == "knowledge" or (not tools and not has_collect and not has_evidence and k == "live"):
        b["general"] = True
    return b


def _evidence_payload(badge: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"level": badge["level"], "reason": badge.get("reason") or ""}
    if badge.get("sources"):
        out["sources"] = badge["sources"]
    if badge.get("general"):
        out["general"] = True
    return out


def _visible(badge: Optional[Dict[str, Any]]) -> bool:
    if not badge:
        return False
    return badge.get("level") in (HIGH, MEDIUM, LOW) or bool(badge.get("general"))


def merge_evidence_meta(meta: Optional[Dict[str, Any]], badge: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(meta or {})
    if _visible(badge):
        out["evidence"] = _evidence_payload(badge)  # type: ignore[arg-type]
    return out


def evidence_sse_field(badge: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if _visible(badge):
        return {"evidence": _evidence_payload(badge)}  # type: ignore[arg-type]
    return {}
