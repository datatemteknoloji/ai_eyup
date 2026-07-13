"""
RAG servisi: Runbook, Incident ve Metrik açıklamaları için context üretir.
Chat prompt'una eklenecek metinleri döndürür.
"""
import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.embedding import get_embedding
from app.services.rag_store import (
    add_chunks,
    query_collection,
    clear_collection,
    COLLECTION_RUNBOOK,
    COLLECTION_INCIDENTS,
    COLLECTION_METRICS,
)

logger = logging.getLogger(__name__)

# Runbook chunk boyutu (karakter)
RUNBOOK_CHUNK_SIZE = 800
RUNBOOK_CHUNK_OVERLAP = 100


def chunk_text(text: str, chunk_size: int = RUNBOOK_CHUNK_SIZE, overlap: int = RUNBOOK_CHUNK_OVERLAP) -> List[str]:
    """Metni paragraf/ cümle sınırlarına yakın chunk'lara böl."""
    text = (text or "").strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            # Sonraki boşluğa veya satır sonuna kadar genişlet
            for sep in ["\n\n", "\n", ". ", " "]:
                idx = text.rfind(sep, start, end + 1)
                if idx > start:
                    end = idx + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap if overlap < (end - start) else end
    return chunks


async def ingest_runbook(title: str, content: str) -> int:
    """Runbook dokümanını chunk'la, embed'le ve runbook collection'a ekle."""
    if not content or not content.strip():
        return 0
    chunks = chunk_text(content.strip())
    if not chunks:
        return 0
    from app.services.embedding import get_embeddings_batch
    embeddings = await get_embeddings_batch(chunks)
    ids = [str(__import__("uuid").uuid4()) for _ in chunks]
    metadatas = [{"title": title or "Runbook", "index": i} for i in range(len(chunks))]
    add_chunks(COLLECTION_RUNBOOK, ids=ids, documents=chunks, metadatas=metadatas, embeddings=embeddings)
    return len(chunks)


async def ingest_runbook_append(title: str, content: str) -> int:
    """Mevcut runbook'lara yeni doküman ekle (clear etmeden)."""
    return await ingest_runbook(title, content)


def _incident_to_text(incident) -> str:
    """Incident modelinden aranabilir metin üret."""
    parts = [
        incident.title or "",
        incident.description or "",
        incident.root_cause or "",
        incident.resolution or "",
        f"Severity: {incident.severity or ''}",
        f"Status: {incident.status or ''}",
    ]
    return "\n".join(p for p in parts if p).strip()


async def ingest_incidents_from_db(db: Session) -> int:
    """Incidents tablosundaki kayıtları RAG'e ekle. Mevcut incidents collection temizlenir."""
    from app.models.event import Incident
    clear_collection(COLLECTION_INCIDENTS)
    rows = db.query(Incident).order_by(Incident.id).all()
    ids, texts, metadatas = [], [], []
    for r in rows:
        t = _incident_to_text(r)
        if not t:
            continue
        ids.append(f"incident_{r.id}")
        texts.append(t)
        metadatas.append({"incident_id": r.id, "title": (r.title or "")[:200], "severity": r.severity or ""})
    if not texts:
        return 0
    from app.services.embedding import get_embeddings_batch
    embeddings = await get_embeddings_batch(texts)
    add_chunks(COLLECTION_INCIDENTS, ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
    return len(ids)


def _event_to_text(event) -> str:
    """SystemEvent'ten aranabilir metin."""
    parts = [event.title or "", event.description or "", f"Type: {event.event_type or ''}", f"Severity: {event.severity or ''}"]
    return "\n".join(p for p in parts if p).strip()


async def ingest_events_from_db(db: Session) -> int:
    """SystemEvent kayıtlarını RAG'e ekle (incidents ile aynı collection'da)."""
    from app.models.event import SystemEvent
    rows = db.query(SystemEvent).order_by(SystemEvent.id.desc()).limit(500).all()
    ids, texts, metadatas = [], [], []
    for r in rows:
        t = _event_to_text(r)
        if not t:
            continue
        ids.append(f"event_{r.id}")
        texts.append(t)
        metadatas.append({"event_id": r.id, "title": (r.title or "")[:200], "event_type": r.event_type or ""})
    if not texts:
        return 0
    from app.services.embedding import get_embeddings_batch
    embeddings = await get_embeddings_batch(texts)
    add_chunks(COLLECTION_INCIDENTS, ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
    return len(ids)


async def ingest_metric_descriptions(items: List[dict]) -> int:
    """
    items: [{"name": "node_cpu_seconds_total", "description": "..."}, ...]
    Mevcut metric_descriptions collection temizlenir.
    """
    clear_collection(COLLECTION_METRICS)
    if not items:
        return 0
    documents = []
    metadatas = []
    for it in items:
        name = it.get("name") or it.get("metric") or ""
        desc = it.get("description") or it.get("desc") or ""
        text = f"Metrik: {name}\nAçıklama: {desc}".strip()
        if not text:
            continue
        documents.append(text)
        metadatas.append({"metric_name": name})
    if not documents:
        return 0
    from app.services.embedding import get_embeddings_batch
    embeddings = await get_embeddings_batch(documents)
    ids = [f"metric_{i}" for i in range(len(documents))]
    add_chunks(COLLECTION_METRICS, ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    return len(ids)


async def get_runbook_context(message: str, top_k: Optional[int] = None) -> str:
    """Soruya göre runbook chunk'larını getir."""
    top_k = top_k or settings.RAG_RUNBOOK_TOP_K
    try:
        emb = await get_embedding(message)
        hits = query_collection(COLLECTION_RUNBOOK, query_embedding=emb, n_results=top_k)
        if not hits:
            return ""
        parts = [h["document"] for h in hits if h.get("document")]
        return "\n\n---\n\n".join(parts)
    except Exception as e:
        logger.warning(f"Runbook RAG error: {e}")
        return ""


async def get_incidents_context(message: str, top_k: Optional[int] = None) -> str:
    """Soruya göre incident/event chunk'larını getir."""
    top_k = top_k or settings.RAG_INCIDENTS_TOP_K
    try:
        emb = await get_embedding(message)
        hits = query_collection(COLLECTION_INCIDENTS, query_embedding=emb, n_results=top_k)
        if not hits:
            return ""
        parts = [h["document"] for h in hits if h.get("document")]
        return "\n\n---\n\n".join(parts)
    except Exception as e:
        logger.warning(f"Incidents RAG error: {e}")
        return ""


async def get_metrics_context(message: str, top_k: Optional[int] = None) -> str:
    """Metrik açıklamalarından ilgili olanları getir."""
    top_k = top_k or settings.RAG_METRICS_TOP_K
    try:
        emb = await get_embedding(message)
        hits = query_collection(COLLECTION_METRICS, query_embedding=emb, n_results=top_k)
        if not hits:
            return ""
        parts = [h["document"] for h in hits if h.get("document")]
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning(f"Metrics RAG error: {e}")
        return ""


async def get_rag_context_for_message(message: str) -> dict:
    """
    Chat için tek çağrıda üç RAG context'ini topla.
    Dönen dict: runbook, incidents, metrics (her biri string, boş olabilir).
    """
    runbook = await get_runbook_context(message)
    incidents = await get_incidents_context(message)
    metrics = await get_metrics_context(message)
    return {"runbook": runbook, "incidents": incidents, "metrics": metrics}
