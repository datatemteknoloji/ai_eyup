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
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from app.core.database import engine

logger = logging.getLogger(__name__)

COLLECTION_RUNBOOK = "runbook"
COLLECTION_INCIDENTS = "incidents"
COLLECTION_METRICS = "metric_descriptions"
COLLECTION_KNOWLEDGE = "knowledge_facts"
COLLECTION_AUTOMIC = "automic"

# HNSW iterative scan (pgvector >= 0.8) — büyük koleksiyonlar
HNSW_ITERATIVE_SCAN = (os.getenv("RAG_HNSW_ITERATIVE_SCAN") or "relaxed_order").strip() or "relaxed_order"
HNSW_EF_SEARCH = max(40, min(400, int(os.getenv("RAG_HNSW_EF_SEARCH") or "100")))
# Bu eşiğin altında: B-tree collection filtresi + exact sıralama (HNSW yok)
EXACT_VECTOR_MAX_ROWS = max(1000, int(os.getenv("RAG_EXACT_VECTOR_MAX_ROWS") or "50000"))

_collection_count_cache: Dict[str, Tuple[float, int]] = {}
_COLLECTION_COUNT_TTL_SEC = 60.0

_IDENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+")
_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,5}\b")
_NUM_RE = re.compile(r"\b\d{3,5}\b")
_WORD_RE = re.compile(r"[\wçğıöşüÇĞİÖŞÜ]{5,}", re.U)
_LEX_STOP = {
    "nedir", "nasıl", "nerede", "hangi", "olarak", "kolondan", "tablodan",
    "değeri", "demek", "anlama", "geliyor", "arasındaki", "fark", "farkı",
    "bulunur", "okunur", "listele", "göster", "hakkında",
}


def query_terms(message: str) -> Dict[str, List[str]]:
    """Kod/identifier odaklı sorgu terimleri (EH_Signal, 1801, AH_Idnr…)."""
    msg = message or ""
    idents = list(dict.fromkeys(m.group(0) for m in _IDENT_RE.finditer(msg)))
    acr = list(dict.fromkeys(m.group(0) for m in _ACRONYM_RE.finditer(msg)))
    nums = list(dict.fromkeys(_NUM_RE.findall(msg)))
    words = [
        w for w in dict.fromkeys(w.lower() for w in _WORD_RE.findall(msg))
        if w not in _LEX_STOP
    ][:8]
    return {"idents": idents, "acronyms": acr, "numbers": nums, "words": words}


def lexical_bonus(doc: str, terms: Dict[str, List[str]]) -> float:
    """Identifier/kod eşleşmesi → mesafe düşürme (sıralama avantajı)."""
    low = (doc or "").lower()
    b = 0.0
    for t in terms.get("idents") or []:
        if t.lower() in low:
            b += 0.12
    for t in terms.get("acronyms") or []:
        if re.search(rf"\b{re.escape(t.lower())}", low):
            b += 0.07
    for t in terms.get("numbers") or []:
        if t in low:
            b += 0.07
    hits = sum(1 for w in (terms.get("words") or []) if w in low)
    b += min(hits, 4) * 0.015
    return min(b, 0.35)


def apply_code_lexical_rerank(
    hits: List[dict],
    query: str,
    *,
    n_results: int,
) -> List[dict]:
    """RRF/vektör adaylarına kod eşleşmesi bonusu uygula."""
    terms = query_terms(query)
    if not hits:
        return []
    if not any(terms.values()):
        return hits[: max(1, int(n_results))]
    ranked: List[dict] = []
    for h in hits:
        meta = h.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        blob = f"{meta.get('title') or ''}\n{h.get('document') or ''}"
        dist = float(h.get("distance") or 0.5)
        nh = dict(h)
        nh["distance"] = max(0.0, dist - lexical_bonus(blob, terms))
        nh["lexical_bonus"] = lexical_bonus(blob, terms)
        ranked.append(nh)
    ranked.sort(key=lambda x: float(x.get("distance") or 1.0))
    return ranked[: max(1, int(n_results))]


def cached_collection_count(collection_name: str) -> int:
    now = time.monotonic()
    hit = _collection_count_cache.get(collection_name)
    if hit and (now - hit[0]) < _COLLECTION_COUNT_TTL_SEC:
        return hit[1]
    n = count_collection(collection_name)
    _collection_count_cache[collection_name] = (now, n)
    return n


def invalidate_collection_count_cache(collection_name: Optional[str] = None) -> None:
    if collection_name:
        _collection_count_cache.pop(collection_name, None)
    else:
        _collection_count_cache.clear()


def collection_for_document_title(title: str) -> str:
    """Seed/başlık → koleksiyon (yeniden embed gerekmez; yazma anında seçilir)."""
    t = (title or "").strip()
    if t.upper().startswith("AUTOMIC-"):
        return COLLECTION_AUTOMIC
    return COLLECTION_RUNBOOK


def module_for_collection(collection_name: str) -> Optional[str]:
    if collection_name == COLLECTION_AUTOMIC:
        return "automic"
    return None


def migrate_automic_collection_scope() -> Dict[str, Any]:
    """AUTOMIC-* satırlarını runbook → automic koleksiyonuna taşı (vektör aynı kalır)."""
    if is_vector_disabled() or not _schema_ready:
        return {"skipped": True, "reason": "vector_disabled"}
    report = {"moved": 0, "module_tagged": 0}
    with engine.begin() as conn:
        r = conn.execute(
            text(
                """
                UPDATE rag_embeddings
                SET collection = :dst,
                    metadata = jsonb_set(
                        coalesce(metadata, '{}'::jsonb),
                        '{module}',
                        to_jsonb(CAST(:mod AS text)),
                        true
                    ),
                    updated_at = now()
                WHERE collection = :src
                  AND coalesce(metadata->>'title', '') ILIKE 'AUTOMIC-%'
                """
            ),
            {
                "dst": COLLECTION_AUTOMIC,
                "src": COLLECTION_RUNBOOK,
                "mod": "automic",
            },
        )
        report["moved"] = int(r.rowcount or 0)
        r2 = conn.execute(
            text(
                """
                UPDATE rag_embeddings
                SET metadata = jsonb_set(
                    coalesce(metadata, '{}'::jsonb),
                    '{module}',
                    to_jsonb(CAST(:mod AS text)),
                    true
                )
                WHERE collection = :dst
                  AND coalesce(metadata->>'module', '') = ''
                """
            ),
            {"dst": COLLECTION_AUTOMIC, "mod": "automic"},
        )
        report["module_tagged"] = int(r2.rowcount or 0)
    if report["moved"] or report["module_tagged"]:
        logger.info("RAG automic scope migration: %s", report)
    return report


EMBEDDING_DIM = 768
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
# FTS: 'simple' — kod/identifier (ORA-01017, EH_Signal, ENDED_NOT_OK) stemming bozmaz
FTS_CONFIG = "simple"
# ~2048 token üstü parçalara chash yazılmaz (yeniden parçalanıp embed edilsin)
MAX_CHUNK_TOKENS_FOR_CHASH = 2048

_MARKER_AVX_TEXT = "pgvector skipped: host CPU lacks AVX (or previous SIGILL).\n"
_MARKER_CREATE_PREFIX = "pgvector CREATE EXTENSION failed:"

_schema_lock = threading.Lock()
_schema_ready = False
_vector_disabled = False
_vector_disable_reason: Optional[str] = None
_metadata_migrated = False
_metadata_migrate_lock = threading.Lock()
_metadata_migrate_running = False


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


def _vec_literal(embedding: List[float], *, expected_dim: int = EMBEDDING_DIM) -> str:
    """Vektörü pg literal'e çevir. Boyut uyuşmazlığında ValueError — pad/kırp yok."""
    if not embedding:
        raise ValueError("boş embedding")
    if len(embedding) != int(expected_dim):
        raise ValueError(
            f"embedding boyut uyuşmazlığı: got={len(embedding)} expected={expected_dim}"
        )
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def _estimate_tokens(text: str) -> int:
    try:
        from app.services.llm_context_budget import estimate_tokens
        return int(estimate_tokens(text or ""))
    except Exception:
        return max(1, (len(text or "") + 2) // 3)


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
            "ALTER TABLE rag_embeddings ADD COLUMN IF NOT EXISTS embedding_model TEXT",
            "ALTER TABLE rag_embeddings ADD COLUMN IF NOT EXISTS embedding_dim INTEGER",
            "ALTER TABLE rag_embeddings ADD COLUMN IF NOT EXISTS document_tsv tsvector",
            "CREATE INDEX IF NOT EXISTS ix_rag_embeddings_collection ON rag_embeddings (collection)",
            "CREATE INDEX IF NOT EXISTS ix_rag_embeddings_metadata_gin ON rag_embeddings USING gin (metadata jsonb_path_ops)",
            "CREATE INDEX IF NOT EXISTS ix_rag_embeddings_id_prefix ON rag_embeddings (collection, id text_pattern_ops)",
            "CREATE INDEX IF NOT EXISTS ix_rag_embeddings_model_dim ON rag_embeddings (collection, embedding_model, embedding_dim)",
            # FTS GIN: CREATE INDEX CONCURRENTLY (transaction dışında) — ensure_fts_gin_index
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
        try:
            ensure_fts_gin_index()
        except Exception as e:
            logger.warning("RAG FTS GIN index atlandı: %s", e)
        try:
            migrate_automic_collection_scope()
        except Exception as e:
            logger.warning("RAG automic scope migration atlandı: %s", e)
        # Büyük tabloda migrate uzun sürer — şemayı kilitlemeden arka planda çalıştır
        skip_auto = (os.getenv("RAG_SKIP_AUTO_MIGRATE") or "").strip().lower() in (
            "1", "true", "yes", "on",
        )
        if not skip_auto:
            def _bg_migrate() -> None:
                try:
                    migrate_rag_embedding_metadata()
                except Exception as e:
                    logger.warning("RAG metadata migration atlandı: %s", e)

            threading.Thread(target=_bg_migrate, name="rag-meta-migrate", daemon=True).start()


def ensure_fts_gin_index(*, recreate: bool = False) -> Dict[str, Any]:
    """document_tsv GIN indeksini CONCURRENTLY oluştur (tablo kilidi yok)."""
    report: Dict[str, Any] = {"index": "ix_rag_embeddings_fts", "action": "noop"}
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        exists = conn.execute(
            text(
                """
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'ix_rag_embeddings_fts'
                """
            )
        ).scalar()
        if exists and recreate:
            conn.execute(text("DROP INDEX CONCURRENTLY IF EXISTS ix_rag_embeddings_fts"))
            exists = None
            report["action"] = "recreated"
        if not exists:
            conn.execute(
                text(
                    """
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_rag_embeddings_fts
                    ON rag_embeddings USING gin (document_tsv)
                    """
                )
            )
            if report["action"] == "noop":
                report["action"] = "created"
        else:
            report["action"] = "exists"
    logger.info("RAG FTS GIN: %s", report)
    return report


def migrate_rag_embedding_metadata(
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
    dim: int = EMBEDDING_DIM,
    force: bool = False,
    batch_size: int = 1000,
    phases: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Mevcut satırlara embedding_model/dim + FTS + eksik chash doldur (API embed yok).

    Cosine örneklemi ve >2048 token kuralları çağıran tarafından doğrulanmış olmalı.
    Büyük tablolarda tek UPDATE satır yeniden yazımını kilitlemesin diye ctid batch.
    phases: varsayılan ["chash","model_dim","tsv"]; yalnız chash için ["chash"].
    Process-içi threading + Postgres advisory lock (çok worker güvenli).
    """
    global _metadata_migrated, _metadata_migrate_running
    if _metadata_migrated and not force:
        return {"skipped": True, "reason": "already_migrated_this_process"}
    if is_vector_disabled() or not _schema_ready:
        return {"skipped": True, "reason": "vector_disabled"}
    if not _metadata_migrate_lock.acquire(blocking=False):
        return {"skipped": True, "reason": "migrate_already_running"}
    _metadata_migrate_running = True
    # sabit key — rag_embeddings metadata migrate
    adv_key = 872514301
    got_adv = False
    try:
        with engine.connect() as conn:
            got_adv = bool(
                conn.execute(
                    text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": adv_key},
                ).scalar()
            )
            conn.commit()
        if not got_adv:
            return {"skipped": True, "reason": "migrate_advisory_lock_held"}
        return _migrate_rag_embedding_metadata_locked(
            model=model, dim=dim, batch_size=batch_size, phases=phases,
        )
    finally:
        if got_adv:
            try:
                with engine.connect() as conn:
                    conn.execute(
                        text("SELECT pg_advisory_unlock(:k)"),
                        {"k": adv_key},
                    )
                    conn.commit()
            except Exception:
                pass
        _metadata_migrate_running = False
        _metadata_migrate_lock.release()


def _migrate_rag_embedding_metadata_locked(
    *,
    model: str,
    dim: int,
    batch_size: int,
    phases: Optional[List[str]] = None,
) -> Dict[str, Any]:
    global _metadata_migrated

    from app.services.rag_service import content_hash

    want = {p.strip() for p in (phases or ["chash", "model_dim", "tsv"])}
    batch = max(100, int(batch_size))
    report: Dict[str, Any] = {
        "model": model,
        "dim": dim,
        "phases": sorted(want),
        "model_dim_updated": 0,
        "tsv_updated": 0,
        "chash_written": 0,
        "chash_skipped_long": 0,
        "will_reembed": 0,
        "will_reembed_reasons": {},
    }

    # chash önce — yeniden-embed riskini keser; >2048 token yazılmaz
    # Keyset (id) ile PK taraması; her turda aynı satıra takılmamak için offset ilerler
    offset_id = ""
    while want & {"chash"}:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, document
                    FROM rag_embeddings
                    WHERE id > :oid
                      AND coalesce(metadata->>'chash', '') = ''
                      AND coalesce(metadata->>'_chash_skip', '') <> 'true'
                    ORDER BY id
                    LIMIT :lim
                    """
                ),
                {"oid": offset_id, "lim": batch},
            ).fetchall()
        if not rows:
            break
        offset_id = str(rows[-1][0])
        updates: List[tuple] = []
        skip_ids: List[str] = []
        for rid, doc in rows:
            toks = _estimate_tokens(doc or "")
            if toks > MAX_CHUNK_TOKENS_FOR_CHASH:
                report["chash_skipped_long"] += 1
                report["will_reembed"] += 1
                report["will_reembed_reasons"]["over_2048_tokens"] = (
                    report["will_reembed_reasons"].get("over_2048_tokens", 0) + 1
                )
                skip_ids.append(str(rid))
                continue
            updates.append((str(rid), content_hash(doc or "", model=model)))
        if skip_ids:
            # chash yazılmaz; döngüde tekrar seçilmesin diye geçici işaret
            skip_payload = json.dumps([{"id": i} for i in skip_ids], ensure_ascii=False)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE rag_embeddings AS r
                        SET metadata = jsonb_set(
                            coalesce(r.metadata, '{}'::jsonb),
                            '{_chash_skip}',
                            'true'::jsonb,
                            true
                        )
                        FROM jsonb_to_recordset(CAST(:payload AS jsonb)) AS v(id text)
                        WHERE r.id = v.id
                          AND coalesce(r.metadata->>'chash', '') = ''
                        """
                    ),
                    {"payload": skip_payload},
                )
        if updates:
            payload = json.dumps(
                [{"id": i, "ch": h} for i, h in updates],
                ensure_ascii=False,
            )
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE rag_embeddings AS r
                        SET metadata = jsonb_set(
                            coalesce(r.metadata, '{}'::jsonb),
                            '{chash}',
                            to_jsonb(v.ch),
                            true
                        ),
                        updated_at = now()
                        FROM jsonb_to_recordset(CAST(:payload AS jsonb))
                             AS v(id text, ch text)
                        WHERE r.id = v.id
                          AND coalesce(r.metadata->>'chash', '') = ''
                        """
                    ),
                    {"payload": payload},
                )
            report["chash_written"] += len(updates)
            if report["chash_written"] % 20000 < batch:
                logger.info("RAG migrate chash: %s", report["chash_written"])

    # model/dim — yalnızca boş kolonlar (dual-read NULL'ı da kabul eder)
    # rowcount bazı sürücülerde -1/0 dönebilir → EXISTS ile devam et
    while "model_dim" in want:
        with engine.connect() as conn:
            left = conn.execute(
                text(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM rag_embeddings
                        WHERE embedding_model IS NULL OR embedding_model = ''
                           OR embedding_dim IS NULL
                    )
                    """
                )
            ).scalar()
        if not left:
            break
        with engine.begin() as conn:
            r1 = conn.execute(
                text(
                    """
                    UPDATE rag_embeddings AS r
                    SET embedding_model = COALESCE(NULLIF(r.embedding_model, ''), :model),
                        embedding_dim = COALESCE(r.embedding_dim, :dim)
                    FROM (
                        SELECT ctid AS tid
                        FROM rag_embeddings
                        WHERE embedding_model IS NULL OR embedding_model = ''
                           OR embedding_dim IS NULL
                        LIMIT :lim
                    ) AS s
                    WHERE r.ctid = s.tid
                    """
                ),
                {"model": model, "dim": int(dim), "lim": batch},
            )
            n = r1.rowcount
        n = int(n) if n is not None and int(n) > 0 else 0
        if n == 0:
            logger.warning("RAG migrate model/dim: EXISTS ama 0 satır güncellendi — dur")
            break
        report["model_dim_updated"] += n
        if report["model_dim_updated"] % 20000 < batch:
            logger.info("RAG migrate model/dim: %s", report["model_dim_updated"])

    # FTS tsvector — yalnızca NULL (arama on-the-fly/ILIKE ile de çalışır)
    while "tsv" in want:
        with engine.connect() as conn:
            left = conn.execute(
                text(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM rag_embeddings WHERE document_tsv IS NULL
                    )
                    """
                )
            ).scalar()
        if not left:
            break
        with engine.begin() as conn:
            r2 = conn.execute(
                text(
                    """
                    UPDATE rag_embeddings AS r
                    SET document_tsv = to_tsvector(:fts, coalesce(r.document, ''))
                    FROM (
                        SELECT ctid AS tid
                        FROM rag_embeddings
                        WHERE document_tsv IS NULL
                        LIMIT :lim
                    ) AS s
                    WHERE r.ctid = s.tid
                    """
                ),
                {"lim": batch, "fts": FTS_CONFIG},
            )
            n = r2.rowcount
        n = int(n) if n is not None and int(n) > 0 else 0
        if n == 0:
            logger.warning("RAG migrate tsv: EXISTS ama 0 satır güncellendi — dur")
            break
        report["tsv_updated"] += n
        if report["tsv_updated"] % 20000 < batch:
            logger.info("RAG migrate tsv: %s", report["tsv_updated"])

    with engine.connect() as conn:
        still_missing = conn.execute(
            text(
                """
                SELECT count(*) FROM rag_embeddings
                WHERE coalesce(metadata->>'chash', '') = ''
                  AND coalesce(metadata->>'_chash_skip', '') <> 'true'
                """
            )
        ).scalar()
        skipped_long = conn.execute(
            text(
                """
                SELECT count(*) FROM rag_embeddings
                WHERE coalesce(metadata->>'_chash_skip', '') = 'true'
                  AND coalesce(metadata->>'chash', '') = ''
                """
            )
        ).scalar()
    report["chash_still_missing"] = int(still_missing or 0)
    report["chash_skipped_long"] = max(
        report["chash_skipped_long"], int(skipped_long or 0)
    )
    will = int(still_missing or 0) + int(skipped_long or 0)
    report["will_reembed"] = will
    if still_missing:
        report["will_reembed_reasons"]["missing_chash_after_backfill"] = int(still_missing)
    if skipped_long:
        report["will_reembed_reasons"]["over_2048_tokens"] = int(skipped_long)

    _metadata_migrated = True
    logger.info("RAG metadata migration: %s", report)
    return report


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
    *,
    embedding_model: Optional[str] = None,
    embedding_dim: Optional[int] = None,
) -> None:
    if not ids or not documents:
        return
    if embeddings is None or len(embeddings) != len(documents):
        raise ValueError("embeddings length must match documents")
    _require_vector_ready()
    model = (embedding_model or DEFAULT_EMBEDDING_MODEL).strip() or DEFAULT_EMBEDDING_MODEL
    dim = int(embedding_dim or EMBEDDING_DIM)
    metas = _meta_json(metadatas, len(ids))
    with engine.begin() as conn:
        for i, cid in enumerate(ids):
            try:
                emb_lit = _vec_literal(embeddings[i], expected_dim=dim)
            except ValueError as e:
                logger.error("RAG add_chunks atlandı id=%s: %s", cid, e)
                continue
            doc = documents[i] or ""
            conn.execute(
                text(
                    """
                    INSERT INTO rag_embeddings (
                        id, collection, document, embedding, metadata,
                        embedding_model, embedding_dim, document_tsv, updated_at
                    )
                    VALUES (
                        :id, :coll, :doc, CAST(:emb AS vector), CAST(:meta AS jsonb),
                        :model, :dim, to_tsvector(:fts, :doc), now()
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": str(cid),
                    "coll": collection_name,
                    "doc": doc,
                    "emb": emb_lit,
                    "meta": metas[i],
                    "model": model,
                    "dim": dim,
                    "fts": FTS_CONFIG,
                },
            )
    logger.info("RAG store: added %s chunks to %s model=%s", len(ids), collection_name, model)


def upsert_chunks(
    collection_name: str,
    ids: List[str],
    documents: List[str],
    metadatas: Optional[List[dict]] = None,
    embeddings: Optional[List[List[float]]] = None,
    *,
    embedding_model: Optional[str] = None,
    embedding_dim: Optional[int] = None,
) -> None:
    if not ids or not documents:
        return
    if embeddings is None or len(embeddings) != len(documents):
        raise ValueError("embeddings length must match documents")
    _require_vector_ready()
    model = (embedding_model or DEFAULT_EMBEDDING_MODEL).strip() or DEFAULT_EMBEDDING_MODEL
    dim = int(embedding_dim or EMBEDDING_DIM)
    metas = _meta_json(metadatas, len(ids))
    with engine.begin() as conn:
        for i, cid in enumerate(ids):
            try:
                emb_lit = _vec_literal(embeddings[i], expected_dim=dim)
            except ValueError as e:
                logger.error("RAG upsert atlandı id=%s: %s", cid, e)
                continue
            doc = documents[i] or ""
            conn.execute(
                text(
                    """
                    INSERT INTO rag_embeddings (
                        id, collection, document, embedding, metadata,
                        embedding_model, embedding_dim, document_tsv, updated_at
                    )
                    VALUES (
                        :id, :coll, :doc, CAST(:emb AS vector), CAST(:meta AS jsonb),
                        :model, :dim, to_tsvector(:fts, :doc), now()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        collection = EXCLUDED.collection,
                        document = EXCLUDED.document,
                        embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata,
                        embedding_model = EXCLUDED.embedding_model,
                        embedding_dim = EXCLUDED.embedding_dim,
                        document_tsv = EXCLUDED.document_tsv,
                        updated_at = now()
                    """
                ),
                {
                    "id": str(cid),
                    "coll": collection_name,
                    "doc": doc,
                    "emb": emb_lit,
                    "meta": metas[i],
                    "model": model,
                    "dim": dim,
                    "fts": FTS_CONFIG,
                },
            )
    logger.info("RAG store: upserted %s chunks to %s model=%s", len(ids), collection_name, model)


def _row_hit(row) -> dict:
    meta = row[2] or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return {
        "id": row[0],
        "document": row[1] or "",
        "metadata": meta if isinstance(meta, dict) else {},
        "distance": float(row[3] if len(row) > 3 and row[3] is not None else 0.5),
    }


def query_collection(
    collection_name: str,
    query_embedding: List[float],
    n_results: int = 5,
    where: Optional[dict] = None,
    *,
    embedding_model: Optional[str] = None,
    embedding_dim: Optional[int] = None,
) -> List[dict]:
    """Vektör arama — yalnız aynı model+dim satırları.

    Küçük koleksiyon (< EXACT_VECTOR_MAX_ROWS): collection B-tree + exact sıralama.
    Büyük koleksiyon: HNSW + iterative_scan=relaxed_order.
    """
    if not _ensure_vector_ready():
        return []
    if not query_embedding:
        return []
    model = (embedding_model or DEFAULT_EMBEDDING_MODEL).strip() or DEFAULT_EMBEDDING_MODEL
    dim = int(embedding_dim or EMBEDDING_DIM)
    try:
        emb_lit = _vec_literal(query_embedding, expected_dim=dim)
    except ValueError as e:
        logger.warning("RAG query_collection vektör atlandı: %s", e)
        return []
    k = min(max(1, int(n_results or 5)), 100)
    nrows = cached_collection_count(collection_name)
    use_exact = nrows < EXACT_VECTOR_MAX_ROWS
    where_sql = ""
    params: dict[str, Any] = {
        "emb": emb_lit,
        "coll": collection_name,
        "k": k,
        "model": model,
        "dim": dim,
    }
    if where:
        where_sql = " AND metadata @> CAST(:where AS jsonb)"
        params["where"] = json.dumps(where, ensure_ascii=False)

    if use_exact:
        # Önce collection B-tree ile daralt (MATERIALIZED), sonra exact mesafe sıralaması.
        # HNSW kullanılmaz; enable_indexscan kapatılmaz (btree kalsın).
        sql = f"""
            WITH filtered AS MATERIALIZED (
                SELECT id, document, metadata, embedding
                FROM rag_embeddings
                WHERE collection = :coll
                  AND embedding_model = :model
                  AND embedding_dim = :dim
                  {where_sql}
            )
            SELECT id, document, metadata,
                   (embedding <=> CAST(:emb AS vector)) AS distance
            FROM filtered
            ORDER BY distance ASC
            LIMIT :k
        """
    else:
        sql = f"""
            WITH relaxed AS MATERIALIZED (
                SELECT id, document, metadata,
                       (embedding <=> CAST(:emb AS vector)) AS distance
                FROM rag_embeddings
                WHERE collection = :coll
                  AND embedding_model = :model
                  AND embedding_dim = :dim
                  {where_sql}
                ORDER BY embedding <=> CAST(:emb AS vector)
                LIMIT :k
            )
            SELECT id, document, metadata, distance
            FROM relaxed
            ORDER BY distance ASC
        """

    out: List[dict] = []
    with engine.begin() as conn:
        if not use_exact:
            try:
                conn.execute(
                    text("SELECT set_config('hnsw.iterative_scan', :v, true)"),
                    {"v": HNSW_ITERATIVE_SCAN},
                )
                conn.execute(
                    text("SELECT set_config('hnsw.ef_search', :v, true)"),
                    {"v": str(HNSW_EF_SEARCH)},
                )
            except Exception as e:
                logger.warning("RAG HNSW iterative_scan ayarı atlandı: %s", e)
        rows = conn.execute(text(sql), params)
        for row in rows:
            hit = _row_hit(row)
            hit["source"] = "vector"
            hit["vector_mode"] = "exact" if use_exact else "hnsw_iterative"
            out.append(hit)
    return out


def _fts_match_sql(mode: str) -> str:
    """mode: and → plainto; or → lexeme OR (AND boşsa yedek)."""
    if mode == "or":
        # to_tsvector lexeme'lerinden OR — uzun sorularda AND aşırı sıkı kalmasın
        return """(
            SELECT COALESCE(
                to_tsquery(CAST(:fts AS regconfig), or_terms),
                plainto_tsquery(CAST(:fts AS regconfig), :q)
            )
            FROM (
                SELECT nullif(string_agg(lexeme, ' | '), '') AS or_terms
                FROM unnest(to_tsvector(CAST(:fts AS regconfig), :q)) AS u(lexeme, positions)
            ) s
        )"""
    return "plainto_tsquery(CAST(:fts AS regconfig), :q)"


def lexical_search_collection(
    collection_name: str,
    query: str,
    n_results: int = 8,
) -> List[dict]:
    """Tam metin arama — yalnız dolu document_tsv + GIN (FTS_CONFIG='simple')."""
    q = (query or "").strip()
    if not q:
        return []
    if not _ensure_vector_ready():
        return []
    k = min(max(1, int(n_results or 8)), 40)
    out: List[dict] = []
    with engine.connect() as conn:
        for mode in ("and", "or"):
            tsq = _fts_match_sql(mode)
            rows = conn.execute(
                text(
                    f"""
                    SELECT id, document, metadata,
                           greatest(0.0, 1.0 - ts_rank_cd(document_tsv, {tsq})) AS distance
                    FROM rag_embeddings
                    WHERE collection = :coll
                      AND document_tsv IS NOT NULL
                      AND document_tsv @@ {tsq}
                    ORDER BY ts_rank_cd(document_tsv, {tsq}) DESC
                    LIMIT :k
                    """
                ),
                {"coll": collection_name, "q": q, "k": k, "fts": FTS_CONFIG},
            ).fetchall()
            if rows:
                for row in rows:
                    hit = _row_hit(row)
                    hit["source"] = "fts"
                    out.append(hit)
                break
    return out


def reciprocal_rank_fusion(
    ranked_lists: List[List[dict]],
    *,
    k: int = 60,
    n_results: int = 8,
) -> List[dict]:
    """Reciprocal Rank Fusion — id bazlı birleştirme."""
    scores: Dict[str, float] = {}
    best: Dict[str, dict] = {}
    for lst in ranked_lists or []:
        for rank, hit in enumerate(lst or []):
            hid = str(hit.get("id") or "")
            if not hid:
                continue
            scores[hid] = scores.get(hid, 0.0) + 1.0 / (k + rank + 1)
            prev = best.get(hid)
            if prev is None or float(hit.get("distance") or 1) < float(prev.get("distance") or 1):
                best[hid] = dict(hit)
    ordered = sorted(scores.items(), key=lambda x: -x[1])[: max(1, int(n_results))]
    out = []
    for hid, sc in ordered:
        h = best[hid]
        h["rrf_score"] = sc
        h["distance"] = max(0.0, 1.0 - min(1.0, sc * 10))
        out.append(h)
    return out


def hybrid_search_collection(
    collection_name: str,
    query: str,
    *,
    query_embedding: Optional[List[float]] = None,
    embedding_model: Optional[str] = None,
    embedding_dim: Optional[int] = None,
    n_results: int = 8,
    where: Optional[dict] = None,
    code_rerank: bool = True,
) -> List[dict]:
    """Vektör (aynı model) + FTS birleşik arama (RRF) + kod/identifier lexical rerank."""
    k = min(max(1, int(n_results or 8)), 40)
    pool = max(k * 3, 24)
    lists: List[List[dict]] = []
    if query_embedding:
        vhits = query_collection(
            collection_name,
            query_embedding,
            n_results=pool,
            where=where,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
        )
        if vhits:
            lists.append(vhits)
    fhits = lexical_search_collection(collection_name, query, n_results=pool)
    if fhits:
        lists.append(fhits)
    if not lists:
        return []
    if len(lists) == 1:
        merged = lists[0][:pool]
    else:
        merged = reciprocal_rank_fusion(lists, n_results=pool)
    if code_rerank and (query or "").strip():
        return apply_code_lexical_rerank(merged, query, n_results=k)
    return merged[:k]


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
    """Runbook + modül koleksiyonları (automic) — seed/admin listesi."""
    try:
        if not _ensure_vector_ready():
            return []
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT COALESCE(metadata->>'title', 'İsimsiz') AS title,
                           COUNT(*) AS chunk_count,
                           array_agg(id) AS chunk_ids,
                           min(collection) AS collection
                    FROM rag_embeddings
                    WHERE collection IN (:rb, :au)
                    GROUP BY 1
                    ORDER BY 1
                    LIMIT :lim
                    """
                ),
                {
                    "rb": COLLECTION_RUNBOOK,
                    "au": COLLECTION_AUTOMIC,
                    "lim": int(limit),
                },
            )
            return [
                {
                    "title": r[0],
                    "chunk_count": int(r[1] or 0),
                    "chunk_ids": list(r[2] or []),
                    "collection": r[3],
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
                WHERE metadata->>'title' = :title
                  AND collection IN (:rb, :au)
                """
            ),
            {
                "title": title,
                "rb": COLLECTION_RUNBOOK,
                "au": COLLECTION_AUTOMIC,
            },
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
