"""
Ollama tabanlı embedding servisi - RAG için metin vektörleme.
Varsayılan model: nomic-embed-text (768 boyut).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

OLLAMA_EMBED_TIMEOUT = float(os.getenv("OLLAMA_EMBED_TIMEOUT", "60"))
# Büyük PDF'lerde sıralı embed dakikalar sürer; paralel sınırla hızlandır
EMBED_CONCURRENCY = max(1, min(int(os.getenv("OLLAMA_EMBED_CONCURRENCY", "8")), 32))

# Son başarısız embedding ayrıntısı (UI/RuntimeError için)
_last_embed_error: Optional[str] = None


def get_last_embed_error() -> Optional[str]:
    return _last_embed_error


def _set_last_error(msg: str) -> None:
    global _last_embed_error
    _last_embed_error = (msg or "")[:500]


def _zero_vec(dim: int = 768) -> List[float]:
    return [0.0] * dim


def _parse_embedding_payload(data: dict) -> Optional[List[float]]:
    """Hem /api/embeddings hem /api/embed yanıtlarını destekle."""
    if not isinstance(data, dict):
        return None
    emb = data.get("embedding")
    if isinstance(emb, list) and emb:
        return emb
    embs = data.get("embeddings")
    if isinstance(embs, list) and embs:
        first = embs[0]
        if isinstance(first, list) and first:
            return first
    return None


async def _post_embed(client: httpx.AsyncClient, text: str) -> Tuple[Optional[List[float]], Optional[str]]:
    """Ollama'ya embedding isteği. (vector, error_msg)"""
    base = (settings.OLLAMA_URL or "").rstrip("/")
    model = settings.OLLAMA_EMBED_MODEL or "nomic-embed-text"
    prompt = text.strip()

    # 1) Klasik endpoint
    try:
        r = await client.post(
            f"{base}/api/embeddings",
            json={"model": model, "prompt": prompt},
        )
        if r.status_code == 200:
            vec = _parse_embedding_payload(r.json())
            if vec:
                return vec, None
            return None, f"{base}/api/embeddings: boş embedding döndü"
        err_body = (r.text or "")[:240]
        # 2) Yeni /api/embed fallback (bazı Ollama sürümleri)
        if r.status_code in (404, 405) or "not found" in err_body.lower():
            r2 = await client.post(
                f"{base}/api/embed",
                json={"model": model, "input": prompt},
            )
            if r2.status_code == 200:
                vec = _parse_embedding_payload(r2.json())
                if vec:
                    return vec, None
                return None, f"{base}/api/embed: boş embedding döndü"
            return None, f"HTTP {r2.status_code} {base}/api/embed: {(r2.text or '')[:200]}"
        return None, f"HTTP {r.status_code} {base}/api/embeddings model={model}: {err_body}"
    except Exception as e:
        return None, f"{base} erişilemedi ({type(e).__name__}: {e})"


async def get_embedding(text: str) -> List[float]:
    """Tek bir metin için embedding döndür. Başarısızsa sıfır vektör + last_error."""
    if not text or not text.strip():
        return _zero_vec()
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_EMBED_TIMEOUT) as client:
            vec, err = await _post_embed(client, text)
            if vec:
                return vec
            if err:
                _set_last_error(err)
                logger.warning("Ollama embed failed: %s", err)
            return _zero_vec()
    except Exception as e:
        msg = f"Embedding error: {e}"
        _set_last_error(msg)
        logger.warning(msg)
        return _zero_vec()


async def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Birden fazla metin için paralel embedding (semaphore ile sınırlı)."""
    if not texts:
        return []

    sem = asyncio.Semaphore(EMBED_CONCURRENCY)
    results: List[Optional[List[float]]] = [None] * len(texts)

    async with httpx.AsyncClient(timeout=OLLAMA_EMBED_TIMEOUT) as client:

        async def _one(i: int, t: str) -> None:
            if not t or not str(t).strip():
                results[i] = _zero_vec()
                return
            async with sem:
                vec, err = await _post_embed(client, str(t))
                if vec:
                    results[i] = vec
                else:
                    if err:
                        _set_last_error(err)
                        logger.warning("Ollama embed[%s] failed: %s", i, err)
                    results[i] = _zero_vec()

        # İlerleme logu (büyük PDF)
        total = len(texts)
        if total >= 20:
            logger.info(
                "RAG embed batch start: %s chunk, concurrency=%s, model=%s",
                total, EMBED_CONCURRENCY, settings.OLLAMA_EMBED_MODEL,
            )

        await asyncio.gather(*[_one(i, t) for i, t in enumerate(texts)])

    if total >= 20:
        ok = sum(1 for v in results if v and not all(abs(float(x)) < 1e-12 for x in v))
        logger.info("RAG embed batch done: %s/%s ok", ok, total)

    return [r if r is not None else _zero_vec() for r in results]


def get_embedding_sync(text: str) -> List[float]:
    """Senkron embedding (Chroma embedding function için)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Çalışan loop içindeyse yeni thread/loop kullan
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(get_embedding(text))).result()
        return loop.run_until_complete(get_embedding(text))
    except RuntimeError:
        return asyncio.run(get_embedding(text))
