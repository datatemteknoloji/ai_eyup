"""
RAG vector store — pgvector (TimescaleDB/Postgres).

Chroma PersistentClient process-safe olmadığı için runtime yolu tamamen
PostgreSQL `rag_embeddings` tablosudur. Eski Chroma verisi startup'ta
bir kez `rag_chroma_migrate` ile taşınır; chroma volume silinmez.

Not: Bazı eski CPU'larda (AVX'siz Xeon X56xx vb.) pgvector .so yüklenirken
SIGILL ile Postgres process'i düşer ve küme recovery'ye girer. Bu durumda
CREATE EXTENSION ASLA denenmez; marker dosyası ile kalıcı olarak atlanır.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, List, Optional

from sqlalchemy import text

from app.core.database import engine

logger = logging.getLogger(__name__)

COLLECTION_RUNBOOK = "runbook"
COLLECTION_INCIDENTS = "incidents"
COLLECTION_METRICS = "metric_descriptions"
COLLECTION_KNOWLEDGE = "knowledge_facts"

EMBEDDING_DIM = 768

_schema_lock = threading.Lock()
_schema_ready = False
_vector_disabled = False


def _unsupported_marker() -> Path:
    # /app/uploads compose'ta DATA_DIR/uploads'a mount edilir — kalıcı ve yazılabilir.
    for cand in ("/app/uploads", os.getenv("AINEW_DATA_DIR"), os.getenv("DATA_DIR")):
        if cand:
            return Path(cand) / ".pgvector_unsupported"
    return Path("/tmp/.pgvector_unsupported")


def _host_has_avx() -> bool:
    """pgvector binary'leri genelde AVX ister; yoksa CREATE EXTENSION SIGILL üretir."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.startswith("flags") or line.startswith("Features"):
                    flags = f" {line.split(':', 1)[-1]} "
                    return " avx " in flags or " avx2 " in flags
    except OSError:
        pass
    return True  # okunamazsa engelleme (modern host varsayımı)


def is_vector_disabled() -> bool:
    return _vector_disabled


def _vec_literal(embedding: List[float]) -> str:
    if not embedding:
        return "[" + ",".join(["0"] * EMBEDDING_DIM) + "]"
    if len(embedding) != EMBEDDING_DIM:
        # nomic-embed-text 768; sapma varsa kırp/pad
        if len(embedding) > EMBEDDING_DIM:
            embedding = embedding[:EMBEDDING_DIM]
        else:
            embedding = list(embedding) + [0.0] * (EMBEDDING_DIM - len(embedding))
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def ensure_schema() -> None:
    """Idempotent DDL — init_timescale da çağırır; store ilk kullanımda da güvence."""
    global _schema_ready, _vector_disabled
    if _schema_ready or _vector_disabled:
        return
    with _schema_lock:
        if _schema_ready or _vector_disabled:
            return

        marker = _unsupported_marker()
        if marker.is_file() or not _host_has_avx():
            _vector_disabled = True
            try:
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(
                    "pgvector skipped: host CPU lacks AVX (or previous SIGILL).\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
            logger.warning(
                "RAG pgvector atlandı (CPU AVX yok veya önceki SIGILL marker). "
                "Semantik RAG bu hostta kapalı; diğer özellikler etkilenmez."
            )
            return

        # Extension zaten yüklü mü? (yoksa CREATE denemeden önce kontrol)
        try:
            with engine.connect() as conn:
                installed = conn.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                ).scalar()
        except Exception as e:
            logger.warning("RAG pgvector extension kontrolü başarısız: %s", e)
            installed = None

        if not installed:
            try:
                with engine.begin() as conn:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            except Exception as e:
                # SIGILL sonrası bağlantı kopması / recovery — bir daha deneme.
                _vector_disabled = True
                try:
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text(f"pgvector CREATE EXTENSION failed: {e}\n", encoding="utf-8")
                except OSError:
                    pass
                logger.error(
                    "RAG pgvector CREATE EXTENSION başarısız (muhtemel CPU SIGILL): %s. "
                    "Marker yazıldı; sonraki başlangıçlarda atlanacak.",
                    e,
                )
                return

        ddl = [
            """
            CREATE TABLE IF NOT EXISTS rag_embeddings (
                id TEXT PRIMARY KEY,
                collection TEXT NOT NULL,
                document TEXT NOT NULL,
                embedding vector(768) NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_rag_embeddings_collection ON rag_embeddings (collection)",
            "CREATE INDEX IF NOT EXISTS ix_rag_embeddings_metadata_gin ON rag_embeddings USING gin (metadata jsonb_path_ops)",
            "CREATE INDEX IF NOT EXISTS ix_rag_embeddings_id_prefix ON rag_embeddings (collection, id text_pattern_ops)",
            """
            CREATE TABLE IF NOT EXISTS rag_seed_state (
                title TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
        ]
        with engine.begin() as conn:
            for sql in ddl:
                conn.execute(text(sql))
            try:
                conn.execute(text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_rag_embeddings_hnsw
                    ON rag_embeddings USING hnsw (embedding vector_cosine_ops)
                    """
                ))
            except Exception as e:
                logger.warning("RAG HNSW index atlandı: %s", e)
        _schema_ready = True
        logger.info("RAG pgvector schema hazır")



def _ensure_vector_ready() -> bool:
    """Schema hazır ve pgvector kullanılabilir mi?"""
    ensure_schema()
    return (not is_vector_disabled()) and _schema_ready

def _meta_json(metadatas: Optional[List[dict]], n: int) -> List[str]:
    if not metadatas:
        return ["{}"] * n
    out = []
    for m in metadatas:
        if not isinstance(m, dict):
            out.append("{}")
        else:
            out.append(json.dumps(m, ensure_ascii=False, default=str))
    if len(out) < n:
        out.extend(["{}"] * (n - len(out)))
    return out[:n]


def add_chunks(
    collection_name: str,
    ids: List[str],
    documents: List[str],
    metadatas: Optional[List[dict]] = None,
    embeddings: Optional[List[List[float]]] = None,
) -> None:
    if not ids or not documents:
        return
    if embeddings is None or len(embeddings) != len(documents):
        raise ValueError("embeddings length must match documents")
    if not _ensure_vector_ready():
        return
    metas = _meta_json(metadatas, len(ids))
    with engine.begin() as conn:
        for i, cid in enumerate(ids):
            conn.execute(
                text(
                    """
                    INSERT INTO rag_embeddings (id, collection, document, embedding, metadata, updated_at)
                    VALUES (:id, :coll, :doc, CAST(:emb AS vector), CAST(:meta AS jsonb), now())
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": str(cid),
                    "coll": collection_name,
                    "doc": documents[i] or "",
                    "emb": _vec_literal(embeddings[i]),
                    "meta": metas[i],
                },
            )
    logger.info("RAG store: added %s chunks to %s", len(ids), collection_name)


def upsert_chunks(
    collection_name: str,
    ids: List[str],
    documents: List[str],
    metadatas: Optional[List[dict]] = None,
    embeddings: Optional[List[List[float]]] = None,
) -> None:
    if not ids or not documents:
        return
    if embeddings is None or len(embeddings) != len(documents):
        raise ValueError("embeddings length must match documents")
    if not _ensure_vector_ready():
        return
    metas = _meta_json(metadatas, len(ids))
    with engine.begin() as conn:
        for i, cid in enumerate(ids):
            conn.execute(
                text(
                    """
                    INSERT INTO rag_embeddings (id, collection, document, embedding, metadata, updated_at)
                    VALUES (:id, :coll, :doc, CAST(:emb AS vector), CAST(:meta AS jsonb), now())
                    ON CONFLICT (id) DO UPDATE SET
                        collection = EXCLUDED.collection,
                        document = EXCLUDED.document,
                        embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()
                    """
                ),
                {
                    "id": str(cid),
                    "coll": collection_name,
                    "doc": documents[i] or "",
                    "emb": _vec_literal(embeddings[i]),
                    "meta": metas[i],
                },
            )
    logger.info("RAG store: upserted %s chunks to %s", len(ids), collection_name)


def query_collection(
    collection_name: str,
    query_embedding: List[float],
    n_results: int = 5,
    where: Optional[dict] = None,
) -> List[dict]:
    if not _ensure_vector_ready():
        return []
    k = min(max(1, int(n_results or 5)), 100)
    sql = """
        SELECT id, document, metadata,
               (embedding <=> CAST(:emb AS vector)) AS distance
        FROM rag_embeddings
        WHERE collection = :coll
    """
    params: dict[str, Any] = {
        "emb": _vec_literal(query_embedding),
        "coll": collection_name,
        "k": k,
    }
    if where:
        sql += " AND metadata @> CAST(:where AS jsonb)"
        params["where"] = json.dumps(where, ensure_ascii=False)
    sql += " ORDER BY embedding <=> CAST(:emb AS vector) LIMIT :k"
    out: List[dict] = []
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params)
        for row in rows:
            meta = row[2] or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            out.append({
                "id": row[0],
                "document": row[1] or "",
                "metadata": meta if isinstance(meta, dict) else {},
                "distance": float(row[3] or 0),
            })
    return out


def lexical_search_collection(
    collection_name: str,
    query: str,
    n_results: int = 8,
) -> List[dict]:
    """Embedding yokken ILIKE yedek arama."""
    q = (query or "").strip()
    if not q:
        return []
    if not _ensure_vector_ready():
        return []
    k = min(max(1, int(n_results or 8)), 40)
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    out: List[dict] = []
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, document, metadata, 0.35 AS distance
                FROM rag_embeddings
                WHERE collection = :coll
                  AND document ILIKE :like ESCAPE '\\'
                ORDER BY length(document) ASC
                LIMIT :k
                """
            ),
            {"coll": collection_name, "like": like, "k": k},
        )
        for row in rows:
            meta = row[2] or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            out.append({
                "id": row[0],
                "document": row[1] or "",
                "metadata": meta if isinstance(meta, dict) else {},
                "distance": float(row[3] or 0.35),
            })
    return out


def format_runbook_hits(hits: List[dict]) -> List[dict]:
    """UI kartları: title, sayfa, cosine benzerlik, snippet."""
    out: List[dict] = []
    for h in hits or []:
        meta = h.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        dist = float(h.get("distance") or 0)
        sim = max(0.0, min(1.0, 1.0 - dist))
        page = meta.get("page")
        try:
            page_n = int(page) if page is not None and str(page).strip() != "" else None
        except (TypeError, ValueError):
            page_n = None
        text = (h.get("document") or "").strip().replace("\x00", "")
        snippet = text[:420] + ("…" if len(text) > 420 else "")
        idx = meta.get("index")
        try:
            chunk_index = int(idx) if idx is not None else None
        except (TypeError, ValueError):
            chunk_index = None
        out.append({
            "id": h.get("id"),
            "title": str(meta.get("title") or "İsimsiz")[:300],
            "page": page_n,
            "chunk_index": chunk_index,
            "similarity": round(sim, 3),
            "snippet": snippet,
        })
    return out


def clear_collection(collection_name: str) -> None:
    if not _ensure_vector_ready():
        return
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM rag_embeddings WHERE collection = :coll"),
            {"coll": collection_name},
        )
    logger.info("RAG store: cleared %s", collection_name)


def delete_chunk_ids(collection_name: str, ids: List[str]) -> int:
    if not ids:
        return 0
    if not _ensure_vector_ready():
        return 0
    n = 0
    with engine.begin() as conn:
        for i in range(0, len(ids), 400):
            batch = [str(x) for x in ids[i : i + 400]]
            res = conn.execute(
                text(
                    "DELETE FROM rag_embeddings WHERE collection = :coll AND id = ANY(:ids)"
                ),
                {"coll": collection_name, "ids": batch},
            )
            n += int(res.rowcount or 0)
    logger.info("RAG store: deleted %s ids from %s", n, collection_name)
    return n


def prune_ids_not_in_keep(
    collection_name: str,
    keep_ids: set,
    *,
    id_prefix: str,
    scan_limit: int = 20000,
) -> int:
    if not _ensure_vector_ready():
        return 0
    keep = {str(x) for x in (keep_ids or set())}
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id FROM rag_embeddings
                WHERE collection = :coll AND id LIKE :pfx
                LIMIT :lim
                """
            ),
            {"coll": collection_name, "pfx": f"{id_prefix}%", "lim": int(scan_limit)},
        )
        existing = [r[0] for r in rows]
        to_delete = [i for i in existing if i not in keep]
        if not to_delete:
            return 0
    return delete_chunk_ids(collection_name, to_delete)


def count_collection(collection_name: str) -> int:
    try:
        if not _ensure_vector_ready():
            return 0
        with engine.connect() as conn:
            n = conn.execute(
                text("SELECT COUNT(*) FROM rag_embeddings WHERE collection = :coll"),
                {"coll": collection_name},
            ).scalar()
            return int(n or 0)
    except Exception:
        return 0


def list_runbook_documents(limit: int = 5000) -> List[dict]:
    try:
        if not _ensure_vector_ready():
            return []
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT COALESCE(metadata->>'title', 'İsimsiz') AS title,
                           COUNT(*) AS chunk_count,
                           array_agg(id) AS chunk_ids
                    FROM rag_embeddings
                    WHERE collection = :coll
                    GROUP BY 1
                    ORDER BY 1
                    LIMIT :lim
                    """
                ),
                {"coll": COLLECTION_RUNBOOK, "lim": int(limit)},
            )
            return [
                {
                    "title": r[0],
                    "chunk_count": int(r[1] or 0),
                    "chunk_ids": list(r[2] or []),
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("list_runbook_documents error: %s", e)
        return []


def delete_runbook_by_title(title: str) -> int:
    if not title or not title.strip():
        return 0
    title = title.strip()
    if not _ensure_vector_ready():
        return 0
    with engine.begin() as conn:
        res = conn.execute(
            text(
                """
                DELETE FROM rag_embeddings
                WHERE collection = :coll AND metadata->>'title' = :title
                """
            ),
            {"coll": COLLECTION_RUNBOOK, "title": title},
        )
        n = int(res.rowcount or 0)
    logger.info("RAG store: deleted runbook document title=%r (%s chunks)", title, n)
    return n


def load_seed_state() -> dict:
    if not _ensure_vector_ready():
        return {}
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT title, version FROM rag_seed_state"))
            return {str(r[0]): str(r[1]) for r in rows}
    except Exception:
        return {}


def save_seed_state(state: dict) -> None:
    if not _ensure_vector_ready():
        return
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM rag_seed_state"))
        for title, version in (state or {}).items():
            conn.execute(
                text(
                    """
                    INSERT INTO rag_seed_state (title, version, updated_at)
                    VALUES (:t, :v, now())
                    """
                ),
                {"t": str(title), "v": str(version)},
            )
