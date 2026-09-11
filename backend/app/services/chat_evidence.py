"""Sohbet final cevabı için kanıt guard (virt + Unified ortak).

Araç/collect çıktısı varken modelin 'canlı veri yok' demesini yakalar.
Virt yolu bunu hypervisor_intelligence içinde kullanır; Unified final
stream aynı kararı `maybe_fix_no_data_answer` ile uygular.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_ANCHOR_RE = re.compile(r"\d+[\.,]?\d*|\b(?:\d{1,3}\.){3}\d{1,3}\b")

RETRY_ADDENDUM = (
    "\n\nUYARI: Yukarıdaki BAĞLAM / ARAÇ SONUÇLARI bölümü DOLU ve geçerli. "
    "'Veri yok / kayıt dönmedi / bağlantı sağlanamadı / canlı veri mevcut değil' "
    "demen yasak. O bölümdeki sayısal değerleri (host adı, yüzdeler, sayaçlar) "
    "cevabında AYNEN kullan."
)

GenerateFn = Callable[..., Any]


def has_meaningful_evidence(evidence: str, min_chars: int = 80) -> bool:
    return len((evidence or "").strip()) >= min_chars


def collect_unified_live_evidence(
    *,
    tool_text: str = "",
    linux_ctx: str = "",
    windows_ctx: str = "",
) -> str:
    """RAG/overview değil — bu turda toplanmış canlı/tool metni."""
    chunks = []
    for raw in (tool_text, linux_ctx, windows_ctx):
        text = (raw if isinstance(raw, str) else str(raw or "")).strip()
        if len(text) >= 80:
            chunks.append(text)
    return "\n\n".join(chunks)


def answer_ignores_evidence(answer: str, evidence: str, max_len: int = 400) -> bool:
    """Kısa cevap, kanıttaki hiçbir somut değeri içermiyor mu?"""
    if not answer or not evidence or len(answer) > max_len:
        return False
    anchors = {a for a in _ANCHOR_RE.findall(evidence) if len(a) >= 2}
    if len(anchors) < 3:
        return False
    return not any(a in answer for a in anchors)


def needs_evidence_retry(answer: str, evidence: str) -> bool:
    if not has_meaningful_evidence(evidence):
        return False
    from app.services.chat_coverage import looks_like_no_data_answer
    return looks_like_no_data_answer(answer) or answer_ignores_evidence(answer, evidence)


def retry_answer_is_usable(retry_answer: str, evidence: str) -> bool:
    from app.services.chat_coverage import looks_like_no_data_answer
    text = (retry_answer or "").strip()
    if not text:
        return False
    if looks_like_no_data_answer(text):
        return False
    if answer_ignores_evidence(text, evidence):
        return False
    return True


def render_raw_evidence_fallback(evidence: str, max_chars: int = 4000) -> str:
    block = (evidence or "").strip()
    if not block:
        return "Araç çıktısı bu turda boş döndü."
    return (
        "Model bu turda araç çıktısını özetleyemedi; toplanan canlı veriyi "
        "olduğu gibi veriyorum:\n\n```\n"
        + block[:max_chars]
        + ("\n… (kısaltıldı)" if len(block) > max_chars else "")
        + "\n```"
    )


def maybe_fix_no_data_answer(
    *,
    answer: str,
    evidence: str,
    prompt: str,
    model: str,
    generate_sync: Optional[GenerateFn] = None,
    timeout: float = 120.0,
) -> tuple[str, str]:
    """Kanıt varken 'veri yok' cevabını düzelt.

    Döner: (yeni_cevap, reason) — reason: '' | 'retry' | 'fallback'
    generate_sync verilmezse llm_gateway.generate_sync kullanılır.
    """
    if not needs_evidence_retry(answer, evidence):
        return answer, ""
    logger.warning(
        "[ChatEvidence] kanıt varken 'veri yok' — yeniden deneniyor (q_len=%s ev_len=%s)",
        len(prompt or ""),
        len(evidence or ""),
    )
    fn = generate_sync
    if fn is None:
        from app.services import llm_gateway
        fn = llm_gateway.generate_sync
    retry_answer = ""
    try:
        retry = fn(model=model, prompt=(prompt or "") + RETRY_ADDENDUM, timeout=timeout)
        retry_answer = ((retry or {}).get("response") or "").strip()
    except Exception as exc:
        logger.debug("kanıt guard retry hatası: %s", exc)
    if retry_answer_is_usable(retry_answer, evidence):
        return retry_answer, "retry"
    return render_raw_evidence_fallback(evidence), "fallback"
