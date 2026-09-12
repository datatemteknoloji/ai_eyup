"""Virt sohbet LLM yoluna RAG (runbook / incident / metrik / bilgi bankası).

Deterministik QA_RULES envanter cevaplarına eklenmez.
Nasıl / neden / prosedür / benzer olay LLM turunda context olur.
Estate sayıları RAG'dan gelmez (DB / canlı merdiven).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def collect_virt_rag_block(message: str) -> str:
    """Senkron ask için RAG metni; boş veya hata → ''."""
    q = (message or "").strip()
    if not q:
        return ""
    try:
        from app.services.chat_source_planner import plan_sources
        from app.services.rag_service import get_rag_context_for_message

        plan = plan_sources(q, scope="virt", use_rag=True)
        if not plan.need_rag:
            return ""

        async def _run() -> Dict[str, Any]:
            return await get_rag_context_for_message(
                q, collections=plan.rag_collections or None,
            )

        try:
            ctx = asyncio.run(_run())
        except RuntimeError:
            # Zaten bir event loop varsa (nadir) ayrı thread'de çalıştır
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                ctx = pool.submit(lambda: asyncio.run(_run())).result(timeout=60)
        if not isinstance(ctx, dict):
            return ""
        parts = []
        if ctx.get("runbook"):
            parts.append("RUNBOOK:\n" + str(ctx["runbook"]).strip())
        if ctx.get("incidents"):
            parts.append("BENZER OLAYLAR:\n" + str(ctx["incidents"]).strip())
        if ctx.get("metrics"):
            parts.append("METRIK ACIKLAMALARI:\n" + str(ctx["metrics"]).strip())
        if ctx.get("knowledge"):
            parts.append("BILGI BANKASI / RAG:\n" + str(ctx["knowledge"]).strip())
        if not parts:
            return ""
        return (
            "RAG (prosedür / benzer olay / metrik tanımı — estate sayıları için kullanma):\n"
            + "\n\n".join(parts)
        )
    except Exception as e:
        logger.debug("virt RAG atlandı: %s", e)
        return ""
