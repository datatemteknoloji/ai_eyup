"""
RAG vector store — pgvector (TimescaleDB/Postgres).

Chroma PersistentClient process-safe olmadığı için runtime yolu tamamen
PostgreSQL `rag_embeddings` tablosudur. Eski Chroma verisi startup'ta
bir kez `rag_chroma_migrate` ile taşınır; chroma volume silinmez.

Not: Bazı eski CPU'larda (AVX'siz Xeon X56xx vb.) pgvector .so yüklenirken
SIGILL ile Postgres process'i düşer ve küme recovery'ye girer. Bu durumda
CREATE EXTENSION ASLA denenmez.

Marker (``.pgvector_unsupported``) yapışkan false-positive olmamalı:
- AVX yok → disable, CREATE yok.
- AVX var + eski AVX marker → yok say / sil, devam.
- Önceki CREATE hatası + extension yok → CREATE tekrarlanmaz (SIGILL riski);
  extension zaten yüklüyse marker temizlenir.
- ``RAG_PGVECTOR_FORCE=1`` → CREATE-failed kilidini de zorla yeniden dene.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.core.database import engine

logger = logging.getLogger(__name__)

COLLECTION_RUNBOOK = "runbook"
COLLECTION_INCIDENTS = "incidents"
COLLECTION_METRICS = "metric_descriptions"
COLLECTION_KNOWLEDGE = "knowledge_facts"

EMBEDDING_DIM = 768

_MARKER_AVX_TEXT = "pgvector skipped: host CPU lacks AVX (or previous SIGILL).\n"
_MARKER_CREATE_PREFIX = "pgvector CREATE EXTENSION failed:"

_schema_lock = threading.Lock()
_schema_ready = False
_vector_disabled = False
_vector_disable_reason: Optional[str] = None


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


def _pgvector_force() -> bool:
    return (os.getenv("RAG_PGVECTOR_FORCE") or "").strip().lower() in ("1", "true", "yes", "on")


def is_vector_disabled() -> bool:
    return _vector_disabled


def vector_disable_reason() -> Optional[str]:
    return _vector_disable_reason


def get_vector_store_status() -> Dict[str, Any]:
    """UI /rag/status için vektör deposu sağlığı (ensure_schema tetikler)."""
    ensure_schema()
    marker = _unsupported_marker()
    marker_present = False
    marker_preview = None
    try:
        marker_present = marker.is_file()
        if marker_present:
            marker_preview = (marker.read_text(encoding="utf-8", errors="replace") or "")[:240]
    except OSError:
        pass
    return {
        "ok": (not _vector_disabled) and _schema_ready,
        "disabled": bool(_vector_disabled),
        "schema_ready": bool(_schema_ready),
        "reason": _vector_disable_reason,
        "marker_path": str(marker),
        "marker_present": marker_present,
        "marker_preview": marker_preview,
        "host_has_avx": _host_has_avx(),
        "force_env": _pgvector_force(),
    }


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


def _read_marker_text(marker: Path) -> str:
    try:
        if marker.is_file():
            return marker.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


def _write_marker(marker: Path, content: str) -> None:
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(content, encoding="utf-8")
    except OSError as e:
        logger.warning("RAG pgvector marker yazılamadı (%s): %s", marker, e)


def _clear_marker(marker: Path) -> None:
    try:
        if marker.is_file():
            marker.unlink()
            logger.info("RAG pgvector unsupported marker silindi: %s", marker)
    except OSError as e:
        logger.warning("RAG pgvector marker silinemedi (%s): %s", marker, e)


def _probe_vector_extension() -> Optional[bool]:
    """True=yüklü, False=yok, None=sorgu hatası."""
    try:
        with engine.connect() as conn:
            installed = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
        return bool(installed)
    except Exception as e:
        logger.warning("RAG pgvector extension kontrolü başarısız: %s", e)
        return None


def _set_disabled(reason: str) -> None:
    global _vector_disabled, _vector_disable_reason
    _vector_disabled = True
    _vector_disable_reason = (reason or "")[:500]


def ensure_schema() -> None:
    """Idempotent DDL — init_timescale da çağırır; store ilk kullanımda da güvence."""
    global _schema_ready, _vector_disabled, _vector_disable_reason
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        # Process içi hard-fail: CREATE/SIGILL sonrası tekrar deneme.
        if _vector_disabled:
            return

        marker = _unsupported_marker()
        has_avx = _host_has_avx()
        force = _pgvector_force()
        marker_text = _read_marker_text(marker)
        create_failed_marker = _MARKER_CREATE_PREFIX in marker_text

        # AVX yok → CREATE asla; SIGILL riski.
        if not has_avx and not force:
            _set_disabled("CPU AVX yok; pgvector güvenli değil (SIGILL riski)")
            _write_marker(marker, _MARKER_AVX_TEXT)
            logger.warning(
                "RAG pgvector atlandı (CPU AVX yok). "
                "Semantik RAG bu hostta kapalı; diğer özellikler etkilenmez."
            )
            return

        installed = _probe_vector_extension()

        # Önceki CREATE hatası: AVX olsa bile CREATE'i tekrarlama (Postgres düşürebilir),
        # ta ki extension zaten yüklü olsun veya FORCE.
        if create_failed_marker and not force and installed is not True:
            reason = (marker_text.strip() or "CREATE EXTENSION previously failed")[:500]
            _set_disabled(reason)
            logger.warning(
                "RAG pgvector atlandı (önceki CREATE EXTENSION hatası; tekrar denenmiyor). "
                "Kurtarmak için extension'ı elle yükleyin veya RAG_PGVECTOR_FORCE=1. Marker: %s",
                marker,
            )
            return

        if marker.is_file() and has_avx and not create_failed_marker:
            # Stale AVX / generic marker on capable host (datatemkonsol vakası).
            logger.info(
                "RAG pgvector: AVX mevcut; eski unsupported marker yok sayılıyor (%s)",
                marker,
            )
            _clear_marker(marker)
        elif create_failed_marker and installed is True:
            logger.info(
                "RAG pgvector: vector extension yüklü; eski CREATE-failed marker temizleniyor (%s)",
                marker,
            )
            _clear_marker(marker)

        if installed is not True:
            try:
                with engine.begin() as conn:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            except Exception as e:
                # SIGILL sonrası bağlantı kopması / recovery — process içinde bir daha deneme.
                _set_disabled(f"CREATE EXTENSION failed: {e}")
                _write_marker(marker, f"{_MARKER_CREATE_PREFIX} {e}\n")
                logger.error(
                    "RAG pgvector CREATE EXTENSION başarısız (muhtemel CPU SIGILL): %s. "
                    "Marker yazıldı; AVX yoksa veya FORCE yoksa sonraki başlangıçlarda CREATE tekrarlanmaz.",
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
        _vector_disabled = False
        _vector_disable_reason = None
        if marker.is_file():
            _clear_marker(marker)
        logger.info("RAG pgvector schema hazır")


def _ensure_vector_ready() -> bool:
    """Schema hazır ve pgvector kullanılabilir mi?"""
    ensure_schema()
    return (not is_vector_disabled()) and _schema_ready


def _require_vector_ready() -> None:
    """Yazma yolları: kapalıysa sessizce yutma — net RuntimeError."""
    if _ensure_vector_ready():
        return
    reason = _vector_disable_reason or "pgvector kapalı"
    marker = _unsupported_marker()
    raise RuntimeError(
        f"RAG vektör deposu kullanılamıyor: {reason}. "
        f"Marker: {marker}. "
        "AVX'li hostta eski marker ise dosyayı silin veya backend'i yeniden başlatın; "
        "CREATE kilidi için RAG_PGVECTOR_FORCE=1 (dikkat: SIGILL riski)."
    )

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
    _require_vector_ready()
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
    _require_vector_ready()
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


_ORPHAN_SOURCES = {
    # id_prefix -> kaynak tablo (chunk id formatı: "<prefix><kaynak satır id>")
    "event_": "system_events",
    "incident_": "incidents",
}


def prune_orphan_source_chunks(
    collection_name: str,
    *,
    id_prefix: str,
    batch_size: int = 2000,
    max_delete: int = 50000,
    dry_run: bool = False,
) -> dict:
    """Kaynak satırı DB'de kalmayan chunk'ları siler (retention sonrası bakım).

    Event/incident retention temizliği kaynak tabloyu boşaltır ama gömme
    (embedding) satırları kalır; zamanla RAG store gereksiz büyür ve arama
    kalitesi düşer. Bu iş, silinmiş kayıtların chunk'larını SQL tarafında
    (NOT EXISTS) bulur — tüm id'leri Python'a çekmez.

    Kontrollü: `batch_size` kadar parçalar hâlinde siler, `max_delete` üst
    sınırını aşmaz ve `dry_run` ile yalnızca sayar.
    """
    source_table = _ORPHAN_SOURCES.get(id_prefix)
    if not source_table:
        raise ValueError(f"Bilinmeyen id_prefix: {id_prefix}")
    if not _ensure_vector_ready():
        return {"collection": collection_name, "prefix": id_prefix, "deleted": 0, "skipped": "vector_disabled"}

    like = f"{id_prefix}%"
    regex = f"^{id_prefix}[0-9]+$"
    offset = len(id_prefix) + 1  # SQL substring 1-tabanlı
    select_orphans = text(
        f"""
        SELECT r.id
        FROM rag_embeddings r
        WHERE r.collection = :coll
          AND r.id LIKE :like
          AND r.id ~ :regex
          AND NOT EXISTS (
              SELECT 1 FROM {source_table} s
              WHERE s.id = CAST(substring(r.id FROM :offset) AS BIGINT)
          )
        LIMIT :lim
        """
    )
    params = {
        "coll": collection_name,
        "like": like,
        "regex": regex,
        "offset": offset,
        "lim": int(batch_size),
    }

    if dry_run:
        with engine.connect() as conn:
            rows = conn.execute(select_orphans, {**params, "lim": int(max_delete)}).fetchall()
        return {
            "collection": collection_name,
            "prefix": id_prefix,
            "orphans": len(rows),
            "deleted": 0,
            "dry_run": True,
        }

    deleted = 0
    batches = 0
    while deleted < max_delete:
        with engine.connect() as conn:
            rows = conn.execute(
                select_orphans,
                {**params, "lim": min(int(batch_size), max_delete - deleted)},
            ).fetchall()
        ids = [str(r[0]) for r in rows]
        if not ids:
            break
        deleted += delete_chunk_ids(collection_name, ids)
        batches += 1
        if len(ids) < batch_size:
            break
    if deleted:
        logger.info(
            "RAG store: %s koleksiyonunda %s öksüz '%s' chunk silindi (%s parti)",
            collection_name, deleted, id_prefix, batches,
        )
    return {
        "collection": collection_name,
        "prefix": id_prefix,
        "deleted": deleted,
        "batches": batches,
        "capped": deleted >= max_delete,
    }


def existing_content_hashes(collection_name: str, ids: List[str]) -> dict:
    """`{chunk_id: metadata.chash}` — değişmemiş kaydı yeniden embed etmemek için.

    Yalnızca sorulan id'ler okunur (koleksiyon yüz binlerce satır olabilir).
    İçerik imzası (`chash`) eşitse o kayıt zaten indekslidir; embedding çağrısı
    hiç yapılmaz — periyodik reindex'in asıl maliyeti buradaydı.
    """
    if not ids:
        return {}
    try:
        if not _ensure_vector_ready():
            return {}
        out: dict = {}
        wanted = [str(x) for x in ids]
        with engine.connect() as conn:
            for i in range(0, len(wanted), 1000):
                rows = conn.execute(
                    text(
                        """
                        SELECT id, metadata->>'chash' AS chash
                        FROM rag_embeddings
                        WHERE collection = :coll AND id = ANY(:ids)
                        """
                    ),
                    {"coll": collection_name, "ids": wanted[i : i + 1000]},
                )
                for r in rows:
                    out[str(r[0])] = r[1] or ""
        return out
    except Exception as e:
        logger.warning("RAG store: content hash listesi okunamadı (%s): %s", collection_name, e)
        return {}


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
