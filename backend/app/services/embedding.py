"""
Ollama tabanlı embedding servisi - RAG için metin vektörleme.
nomic-embed-text (768 boyut) kullanılır.
"""
import logging
from typing import List

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

OLLAMA_EMBED_TIMEOUT = 30.0


async def get_embedding(text: str) -> List[float]:
    """Tek bir metin için embedding döndür."""
    if not text or not text.strip():
        return [0.0] * 768  # nomic-embed-text boyutu
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_EMBED_TIMEOUT) as client:
            r = await client.post(
                f"{settings.OLLAMA_URL}/api/embeddings",
                json={"model": settings.OLLAMA_EMBED_MODEL, "prompt": text.strip()},
            )
            if r.status_code != 200:
                logger.warning(f"Ollama embed failed: {r.status_code} {r.text}")
                return [0.0] * 768
            data = r.json()
            return data.get("embedding", [0.0] * 768)
    except Exception as e:
        logger.warning(f"Embedding error: {e}")
        return [0.0] * 768


async def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Birden fazla metin için embedding (sırayla; Ollama batch desteklemiyor)."""
    result = []
    for t in texts:
        result.append(await get_embedding(t))
    return result


def get_embedding_sync(text: str) -> List[float]:
    """Senkron embedding (Chroma embedding function için)."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(get_embedding(text))
