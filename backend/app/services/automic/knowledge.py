"""Automic sohbeti için bilgi (RAG) alma.

Automic seed belgeleri `automic` koleksiyonunda tutulur (metadata.module=automic).
Sohbet yolu: `automic_rag_context` → `hybrid_search_collection` (vektör+FTS+RRF+kod rerank).
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import logging
from typing import List

from app.services.rag_store import lexical_bonus, query_terms  # noqa: F401 — testler re-export

logger = logging.getLogger(__name__)


async def automic_rag_context(message: str, *, top_k: int = 8, max_chars: int = 8000) -> str:
    """Soruya en uygun automic koleksiyon parçaları. Boşsa ''."""
    import time

    from app.services.embedding import embed_text
    from app.services.rag_store import (
        COLLECTION_AUTOMIC,
        DEFAULT_EMBEDDING_MODEL,
        EMBEDDING_DIM,
        hybrid_search_collection,
    )

    q = (message or "").strip()
    if not q:
        return ""
    t0 = time.perf_counter()
    emb = None
    try:
        res = await embed_text(q)
        if res.usable_for_vector_search and res.vector:
            emb = res.vector
    except Exception as exc:
        note_error("knowledge.automic_rag_context", exc)
    try:
        hits = hybrid_search_collection(
            COLLECTION_AUTOMIC,
            q,
            query_embedding=emb,
            embedding_model=DEFAULT_EMBEDDING_MODEL,
            embedding_dim=EMBEDDING_DIM,
            n_results=top_k,
            code_rerank=True,
        )
    except Exception as exc:
        logger.warning("Automic RAG okunamadı: %s", exc)
        hits = []
    try:
        from app.services import chat_request_metrics as crm
        crm.record_rag(COLLECTION_AUTOMIC, (time.perf_counter() - t0) * 1000)
    except Exception as _e:
        note_error("knowledge.automic_rag_context", _e)
    if not hits:
        return ""
    out: List[str] = []
    used = 0
    seen = set()
    for h in hits:
        doc = (h.get("document") or "").strip()
        key = doc[:80]
        if not doc or key in seen:
            continue
        seen.add(key)
        title = (h.get("metadata") or {}).get("title") or "automic"
        piece = f"[{title}]\n{doc}"
        if used + len(piece) > max_chars and out:
            break
        out.append(piece)
        used += len(piece)
        if len(out) >= top_k:
            break
    return "\n\n---\n\n".join(out)
