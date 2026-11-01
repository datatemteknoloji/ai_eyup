"""
Eski Chroma PersistentClient → pgvector bir kerelik taşıma.
chromadb yoksa veya volume boşsa no-op. Volume silinmez.

NOT: `chromadb` paketi artık ürün imajının bağımlılığı DEĞİLDİR (düzeltmesi olmayan açıklar taşıyordu ve
yalnızca bu bir kerelik taşıma için gerekiyordu; sistemin asıl RAG deposu pgvector'dır). Paket yoksa taşıma
atlanır; pgvector BOŞ iken eski Chroma verisi (chroma.sqlite3) bulunursa açık bir UYARI loglanır ve veri
dokunulmadan bırakılır. Eski veriyi taşımak için `pip install chromadb` ile geçici bir ortamda çalıştırın.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_COLLECTIONS = (
    "runbook",
    "incidents",
    "metric_descriptions",
    "knowledge_facts",
)


def _chroma_paths() -> list[str]:
    paths = []
    try:
        from app.core.config import settings
        primary = os.path.abspath(getattr(settings, "RAG_CHROMA_PATH", None) or "/app/chroma")
        paths.append(primary)
    except Exception:
        paths.append("/app/chroma")
    env = (os.getenv("RAG_KNOWLEDGE_CHROMA_PATH") or "").strip()
    if env:
        paths.append(os.path.abspath(env))
    fallback = "/app/uploads/chroma_knowledge"
    if os.path.isdir(fallback):
        paths.append(os.path.abspath(fallback))
    # unique preserve order
    seen = set()
    out = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _has_legacy_chroma_data() -> bool:
    """Taşınmamış eski Chroma verisi var mı (chroma.sqlite3)? Salt okunur kontrol."""
    for path in _chroma_paths():
        try:
            if os.path.isfile(os.path.join(path, "chroma.sqlite3")):
                return True
        except OSError:
            continue
    return False


def migrate_chroma_if_needed(*, force: bool = False) -> dict:
    """
    pgvector boşsa (veya force) Chroma koleksiyonlarını upsert eder.
    Dönüş: {collection: migrated_count}
    """
    from app.services.rag_store import (
        count_collection,
        ensure_schema,
        upsert_chunks,
    )

    ensure_schema()
    existing = sum(count_collection(c) for c in _COLLECTIONS)
    if existing > 0 and not force:
        logger.info("RAG pgvector zaten dolu (%s satır); Chroma migrate atlandı", existing)
        return {"skipped": True, "existing": existing}

    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
    except Exception as e:
        legacy = _has_legacy_chroma_data()
        if legacy:
            logger.warning(
                "pgvector boş ve eski Chroma verisi (chroma.sqlite3) var, ancak 'chromadb' paketi bu "
                "sürümde yüklü değil — eski RAG verisi TAŞINMADI (veri silinmedi, yerinde duruyor). "
                "Taşımak için geçici ortamda 'pip install chromadb' ile migrate_chroma_if_needed(force=True) "
                "çalıştırın veya RAG seed/ingest ile yeniden oluşturun. (%s)", e,
            )
        else:
            logger.info("chromadb yok, migrate atlandı: %s", e)
        return {"skipped": True, "reason": "no_chromadb", "legacy_data": legacy}

    migrated = {}
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    for path in _chroma_paths():
        if not os.path.isdir(path):
            continue
        try:
            client = chromadb.PersistentClient(
                path=path,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        except Exception as e:
            logger.warning("Chroma açılamadı path=%s: %s", path, e)
            continue
        for name in _COLLECTIONS:
            try:
                coll = client.get_collection(name=name)
            except Exception:
                continue
            try:
                total = int(coll.count() or 0)
            except Exception:
                total = 0
            if total <= 0:
                continue
            offset = 0
            batch = 200
            n = 0
            while offset < total:
                try:
                    got = coll.get(
                        include=["documents", "metadatas", "embeddings"],
                        limit=batch,
                        offset=offset,
                    )
                except Exception as e:
                    logger.warning("Chroma get failed %s %s: %s", path, name, e)
                    break
                ids = got.get("ids") or []
                if not ids:
                    break
                docs = got.get("documents") or [""] * len(ids)
                metas = got.get("metadatas") or [{}] * len(ids)
                embs = got.get("embeddings")
                if embs is None:
                    offset += len(ids)
                    continue
                keep_ids, keep_docs, keep_metas, keep_embs = [], [], [], []
                for i, cid in enumerate(ids):
                    emb = embs[i] if i < len(embs) else None
                    if not emb or all(abs(float(x)) < 1e-12 for x in emb):
                        continue
                    keep_ids.append(str(cid))
                    keep_docs.append(docs[i] if i < len(docs) else "")
                    keep_metas.append(metas[i] if i < len(metas) and isinstance(metas[i], dict) else {})
                    keep_embs.append(list(emb))
                if keep_ids:
                    upsert_chunks(name, keep_ids, keep_docs, keep_metas, keep_embs)
                    n += len(keep_ids)
                offset += len(ids)
            migrated[f"{path}:{name}"] = n
            logger.info("Chroma→pgvector %s/%s = %s", path, name, n)
        try:
            del client
        except Exception:
            pass
    return migrated
