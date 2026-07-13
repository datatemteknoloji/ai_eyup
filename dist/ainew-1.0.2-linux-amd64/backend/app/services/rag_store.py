"""
RAG vector store - ChromaDB ile runbook, incident ve metrik açıklamaları.
Embedding'ler dışarıdan verilir (Ollama async çağrı ile).
"""
import logging
import os
import uuid
from typing import List, Optional, Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings

logger = logging.getLogger(__name__)

COLLECTION_RUNBOOK = "runbook"
COLLECTION_INCIDENTS = "incidents"
COLLECTION_METRICS = "metric_descriptions"

# nomic-embed-text
EMBEDDING_DIM = 768


def _get_client():
    path = settings.RAG_CHROMA_PATH
    os.makedirs(path, exist_ok=True)
    return chromadb.PersistentClient(
        path=path,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_collection(name: str):
    """Collection al veya oluştur. Embedding boyutu ilk add'da belirlenir."""
    client = _get_client()
    try:
        return client.get_collection(name=name)
    except Exception:
        return client.create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )


def add_chunks(
    collection_name: str,
    ids: List[str],
    documents: List[str],
    metadatas: Optional[List[dict]] = None,
    embeddings: Optional[List[List[float]]] = None,
) -> None:
    """Chunk'ları collection'a ekle. embeddings verilmezse Chroma embed yapmaz; mutlaka verilmeli."""
    if not ids or not documents:
        return
    if embeddings is not None and len(embeddings) != len(documents):
        raise ValueError("embeddings length must match documents")
    coll = get_collection(collection_name)
    if metadatas is None:
        metadatas = [{}] * len(ids)
    coll.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )
    logger.info(f"RAG store: added {len(ids)} chunks to {collection_name}")


def query_collection(
    collection_name: str,
    query_embedding: List[float],
    n_results: int = 5,
    where: Optional[dict] = None,
) -> List[dict]:
    """
    Benzer dokümanları getir. Her öğe: {"id", "document", "metadata", "distance"}.
    """
    coll = get_collection(collection_name)
    kwargs = {"query_embeddings": [query_embedding], "n_results": min(n_results, 100)}
    if where:
        kwargs["where"] = where
    result = coll.query(**kwargs)
    out = []
    if result["ids"] and result["ids"][0]:
        for i, id_ in enumerate(result["ids"][0]):
            out.append({
                "id": id_,
                "document": (result["documents"][0][i] if result.get("documents") else "") or "",
                "metadata": (result["metadatas"][0][i] if result.get("metadatas") else {}) or {},
                "distance": (result["distances"][0][i] if result.get("distances") else 0),
            })
    return out


def clear_collection(collection_name: str) -> None:
    """Collection içeriğini sil (collection'ı silip yeniden oluşturur)."""
    client = _get_client()
    try:
        client.delete_collection(name=collection_name)
    except Exception:
        pass
    client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info(f"RAG store: cleared {collection_name}")


def count_collection(collection_name: str) -> int:
    """Collection'daki kayıt sayısı."""
    try:
        coll = get_collection(collection_name)
        return coll.count()
    except Exception:
        return 0


def list_runbook_documents(limit: int = 5000) -> List[dict]:
    """
    Runbook collection'daki dokümanları başlığa göre grupla.
    Dönen her öğe: {"title": str, "chunk_count": int, "chunk_ids": list}.
    """
    try:
        coll = get_collection(COLLECTION_RUNBOOK)
        total = coll.count()
        if total == 0:
            return []
        result = coll.get(
            include=["metadatas"],
            limit=min(limit, total),
        )
        ids = result.get("ids") or []
        metadatas = result.get("metadatas") or []
        by_title: dict = {}
        for id_, meta in zip(ids, metadatas):
            title = (meta or {}).get("title") or "İsimsiz"
            if title not in by_title:
                by_title[title] = {"title": title, "chunk_count": 0, "chunk_ids": []}
            by_title[title]["chunk_count"] += 1
            by_title[title]["chunk_ids"].append(id_)
        return list(by_title.values())
    except Exception as e:
        logger.warning(f"list_runbook_documents error: {e}")
        return []


def delete_runbook_by_title(title: str) -> int:
    """Runbook'da verilen başlıktaki tüm chunk'ları sil. Silinen chunk sayısını döndürür."""
    if not title or not title.strip():
        return 0
    title = title.strip()
    try:
        docs = list_runbook_documents()
        count = 0
        for d in docs:
            if d.get("title") == title:
                count = d.get("chunk_count", 0)
                break
        coll = get_collection(COLLECTION_RUNBOOK)
        coll.delete(where={"title": title})
        logger.info(f"RAG store: deleted runbook document title={title!r} ({count} chunks)")
        return count
    except Exception as e:
        logger.warning(f"delete_runbook_by_title error: {e}")
        return 0
