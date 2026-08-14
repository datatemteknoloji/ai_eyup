"""
RAG vector store - ChromaDB ile runbook, incident ve metrik açıklamaları.
Embedding'ler dışarıdan verilir (Ollama async çağrı ile).
"""
import logging
import os
import threading
import uuid
from typing import List, Optional, Any

# Chroma 0.4.x PostHog telemetry'yi import'tan önce kapat (aksi halde ClientStartEvent ERROR)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings

logger = logging.getLogger(__name__)

# Path başına tek PersistentClient — her query'de yeni client DuckDB kilidinde asılıyor
_client_lock = threading.RLock()
_clients: dict = {}

COLLECTION_RUNBOOK = "runbook"
COLLECTION_INCIDENTS = "incidents"
COLLECTION_METRICS = "metric_descriptions"
COLLECTION_KNOWLEDGE = "knowledge_facts"

# nomic-embed-text
EMBEDDING_DIM = 768

# Bilgi Bankası için ayrı path: ana chroma çoğu kurulumda root-owned olup
# appuser yazamaz; uploads yazılabilir. Runbook/incident ana path'te kalır.
_KNOWLEDGE_CHROMA_FALLBACK = "/app/uploads/chroma_knowledge"
_cached_knowledge_path: Optional[str] = None


def _path_is_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_probe")
        with open(probe, "w") as f:
            f.write("1")
        os.remove(probe)
        return True
    except Exception:
        return False


def _knowledge_chroma_path() -> str:
    global _cached_knowledge_path
    if _cached_knowledge_path:
        return _cached_knowledge_path
    env = (os.getenv("RAG_KNOWLEDGE_CHROMA_PATH") or "").strip()
    if env:
        os.makedirs(env, exist_ok=True)
        _cached_knowledge_path = env
        return env
    primary = settings.RAG_CHROMA_PATH
    if _path_is_writable(primary):
        _cached_knowledge_path = primary
        return primary
    os.makedirs(_KNOWLEDGE_CHROMA_FALLBACK, exist_ok=True)
    logger.warning(
        "RAG chroma primary path not writable (%s); knowledge store → %s",
        primary,
        _KNOWLEDGE_CHROMA_FALLBACK,
    )
    _cached_knowledge_path = _KNOWLEDGE_CHROMA_FALLBACK
    return _cached_knowledge_path


def _get_client(path: Optional[str] = None):
    """Path başına tek PersistentClient (kilit altında çağırın)."""
    path = os.path.abspath(path or settings.RAG_CHROMA_PATH)
    os.makedirs(path, exist_ok=True)
    client = _clients.get(path)
    if client is None:
        client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        _clients[path] = client
        logger.info("RAG chroma client opened path=%s", path)
    return client


def _client_for_collection(name: str):
    if name == COLLECTION_KNOWLEDGE:
        return _get_client(_knowledge_chroma_path())
    return _get_client()


def _collection_unlocked(name: str):
    client = _client_for_collection(name)
    try:
        return client.get_collection(name=name)
    except Exception:
        return client.create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )


def get_collection(name: str):
    """Collection al veya oluştur. Embedding boyutu ilk add'da belirlenir."""
    with _client_lock:
        return _collection_unlocked(name)


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
    if metadatas is None:
        metadatas = [{}] * len(ids)
    with _client_lock:
        coll = _collection_unlocked(collection_name)
        coll.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
    logger.info(f"RAG store: added {len(ids)} chunks to {collection_name}")


def upsert_chunks(
    collection_name: str,
    ids: List[str],
    documents: List[str],
    metadatas: Optional[List[dict]] = None,
    embeddings: Optional[List[List[float]]] = None,
) -> None:
    """Chunk'ları ekle veya aynı id ile güncelle (incremental reindex için)."""
    if not ids or not documents:
        return
    if embeddings is not None and len(embeddings) != len(documents):
        raise ValueError("embeddings length must match documents")
    if metadatas is None:
        metadatas = [{}] * len(ids)
    with _client_lock:
        coll = _collection_unlocked(collection_name)
        coll.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
    logger.info(f"RAG store: upserted {len(ids)} chunks to {collection_name}")


def query_collection(
    collection_name: str,
    query_embedding: List[float],
    n_results: int = 5,
    where: Optional[dict] = None,
) -> List[dict]:
    """
    Benzer dokümanları getir. Her öğe: {"id", "document", "metadata", "distance"}.
    """
    with _client_lock:
        coll = _collection_unlocked(collection_name)
        try:
            total = int(coll.count() or 0)
        except Exception:
            total = 0
        if total <= 0:
            return []
        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": min(max(1, n_results), total, 100),
        }
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
    with _client_lock:
        client = _client_for_collection(collection_name)
        try:
            client.delete_collection(name=collection_name)
        except Exception:
            pass
        client.create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
    logger.info(f"RAG store: cleared {collection_name}")


def delete_chunk_ids(collection_name: str, ids: List[str]) -> int:
    """Belirli chunk id'lerini sil. Dönüş: silinen adet (best-effort)."""
    if not ids:
        return 0
    try:
        n = 0
        with _client_lock:
            coll = _collection_unlocked(collection_name)
            for i in range(0, len(ids), 400):
                batch = ids[i : i + 400]
                coll.delete(ids=batch)
                n += len(batch)
        logger.info("RAG store: deleted %s ids from %s", n, collection_name)
        return n
    except Exception as e:
        logger.warning("RAG delete_chunk_ids failed (%s): %s", collection_name, e)
        return 0


def prune_ids_not_in_keep(
    collection_name: str,
    keep_ids: set,
    *,
    id_prefix: str,
    scan_limit: int = 20000,
) -> int:
    """Collection'da id_prefix ile başlayan, keep_ids dışında kalan kayıtları sil (stale RAG)."""
    try:
        with _client_lock:
            coll = _collection_unlocked(collection_name)
            total = coll.count()
            if total == 0:
                return 0
            result = coll.get(include=[], limit=min(scan_limit, max(total, 1)))
        existing = result.get("ids") or []
        to_delete = [
            i for i in existing
            if str(i).startswith(id_prefix) and i not in keep_ids
        ]
        if not to_delete:
            return 0
        return delete_chunk_ids(collection_name, to_delete)
    except Exception as e:
        logger.warning("RAG prune failed (%s %s): %s", collection_name, id_prefix, e)
        return 0


def count_collection(collection_name: str) -> int:
    """Collection'daki kayıt sayısı."""
    try:
        with _client_lock:
            return _collection_unlocked(collection_name).count()
    except Exception:
        return 0


def list_runbook_documents(limit: int = 5000) -> List[dict]:
    """
    Runbook collection'daki dokümanları başlığa göre grupla.
    Dönen her öğe: {"title": str, "chunk_count": int, "chunk_ids": list}.
    """
    try:
        with _client_lock:
            coll = _collection_unlocked(COLLECTION_RUNBOOK)
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
        with _client_lock:
            coll = _collection_unlocked(COLLECTION_RUNBOOK)
            coll.delete(where={"title": title})
        logger.info(f"RAG store: deleted runbook document title={title!r} ({count} chunks)")
        return count
    except Exception as e:
        logger.warning(f"delete_runbook_by_title error: {e}")
        return 0
