"""
RAG servisi: Runbook, Incident, Metrik + Bilgi Bankası (LearnedFact) context üretir.
Chat prompt'una eklenecek metinleri döndürür.
"""
import logging
from collections import defaultdict
from typing import List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.embedding import get_embedding
from app.services.rag_store import (
    add_chunks,
    upsert_chunks,
    query_collection,
    clear_collection,
    count_collection,
    prune_ids_not_in_keep,
    COLLECTION_RUNBOOK,
    COLLECTION_INCIDENTS,
    COLLECTION_METRICS,
    COLLECTION_KNOWLEDGE,
)

logger = logging.getLogger(__name__)

RUNBOOK_CHUNK_SIZE = 800
RUNBOOK_CHUNK_OVERLAP = 100

# Wave 5: incremental incident reindex (full scan ~6 saatte bir)
_INCIDENT_FULL_INTERVAL_SEC = 6 * 3600
_last_full_incident_ingest = 0.0
# Knowledge: imza değişmediyse clear+embed atlanır
_knowledge_sig: Optional[tuple] = None


def _candidate_k(top_k: int) -> int:
    """Reranker açıksa embedding aramasından daha geniş bir aday kümesi çek —
    reranker bu adayları yeniden sıralayıp gerçek top_k'yı seçecek."""
    try:
        from app.services import runtime_settings
        from app.services.reranker import is_enabled
        if not is_enabled():
            return top_k
        candidates = runtime_settings.get_int("rag_reranker_candidates")
        return max(top_k, candidates)
    except Exception:
        return top_k


async def _rerank_hits(query: str, hits: List[dict], top_k: int) -> List[dict]:
    """Embedding sıralı `hits`'i reranker ile yeniden sırala ve en iyi top_k'yı
    döndür. Reranker kapalı/hatalıysa orijinal (embedding) sırayı korur.

    CPU-bound model çağrısı (`rerank`) bir thread executor'da çalıştırılır —
    hem event loop'u bloklamaz hem de dört RAG koleksiyonu (runbook/incidents/
    metrics/knowledge) gerçekten PARALEL rerank edilebilir (bkz.
    get_rag_context_for_message'daki asyncio.gather)."""
    if not hits:
        return hits
    try:
        import asyncio as _asyncio
        from app.services.reranker import rerank
        docs = [h.get("document") or "" for h in hits]
        loop = _asyncio.get_event_loop()
        order = await loop.run_in_executor(None, rerank, query, docs, top_k)
        if order:
            return [hits[i] for i in order]
    except Exception as e:
        logger.debug("RAG rerank atlandı: %s", e)
    return hits[:top_k]


def chunk_text(text: str, chunk_size: int = RUNBOOK_CHUNK_SIZE, overlap: int = RUNBOOK_CHUNK_OVERLAP) -> List[str]:
    """Metni paragraf/cümle sınırlarına yakın chunk'lara böl."""
    text = (text or "").strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
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


def _filter_valid_embeddings(texts, embeddings, metadatas, ids):
    """Sıfır vektör (Ollama down) chunk'larını at — anlamsız arama üretmesin."""
    keep_t, keep_e, keep_m, keep_i = [], [], [], []
    for t, e, m, i in zip(texts, embeddings, metadatas, ids):
        if not e or all(abs(float(x)) < 1e-12 for x in e):
            logger.warning("RAG: zero embedding atlandı id=%s", i)
            continue
        keep_t.append(t)
        keep_e.append(e)
        keep_m.append(m)
        keep_i.append(i)
    return keep_t, keep_e, keep_m, keep_i


async def ingest_runbook(title: str, content: str) -> int:
    if not content or not content.strip():
        return 0
    chunks = chunk_text(content.strip())
    if not chunks:
        return 0
    from app.services.embedding import get_embeddings_batch, get_last_embed_error
    logger.info(
        "RAG runbook ingest: title=%r chunks=%s (~%s chars)",
        (title or "")[:80], len(chunks), len(content),
    )
    embeddings = await get_embeddings_batch(chunks)
    ids = [str(__import__("uuid").uuid4()) for _ in chunks]
    metadatas = [{"title": title or "Runbook", "index": i} for i in range(len(chunks))]
    chunks, embeddings, metadatas, ids = _filter_valid_embeddings(chunks, embeddings, metadatas, ids)
    if not chunks:
        detail = get_last_embed_error() or "Ollama embedding sıfır vektör döndü"
        model = getattr(settings, "OLLAMA_EMBED_MODEL", "nomic-embed-text")
        url = getattr(settings, "OLLAMA_URL", "")
        raise RuntimeError(
            f"Embedding başarısız ({url} / {model}). {detail}. "
            f"Kontrol: `ollama pull {model}` ve OLLAMA_URL erişimi. Runbook eklenemedi."
        )
    add_chunks(COLLECTION_RUNBOOK, ids=ids, documents=chunks, metadatas=metadatas, embeddings=embeddings)
    return len(chunks)


async def ingest_runbook_append(title: str, content: str) -> int:
    return await ingest_runbook(title, content)


def _incident_to_text(incident) -> str:
    parts = [
        incident.title or "",
        incident.description or "",
        incident.root_cause or "",
        incident.resolution or "",
        f"Severity: {incident.severity or ''}",
        f"Status: {incident.status or ''}",
    ]
    return "\n".join(p for p in parts if p).strip()


async def ingest_incidents_from_db(db: Session, *, force_full: bool = False) -> int:
    """Incident'ları Chroma'ya upsert et.

    Varsayılan: son 14 günde oluşturulan/güncellenen kayıtlar.
    force_full veya ~6 saatte bir tam tarama (orphan id'ler kalabilir; kabul edilebilir).
    """
    import time
    from datetime import datetime, timedelta

    from sqlalchemy import or_
    from app.models.event import Incident
    from app.services.embedding import get_embeddings_batch, get_last_embed_error

    global _last_full_incident_ingest
    now_mono = time.monotonic()
    do_full = force_full or (_last_full_incident_ingest == 0.0) or (
        now_mono - _last_full_incident_ingest >= _INCIDENT_FULL_INTERVAL_SEC
    )

    q = db.query(Incident)
    if not do_full:
        cutoff = datetime.utcnow() - timedelta(days=14)
        q = q.filter(
            or_(
                Incident.updated_at >= cutoff,
                Incident.created_at >= cutoff,
            )
        )
    rows = q.order_by(Incident.id).all()
    ids, texts, metadatas = [], [], []
    for r in rows:
        t = _incident_to_text(r)
        if not t:
            continue
        ids.append(f"incident_{r.id}")
        texts.append(t)
        metadatas.append({"incident_id": r.id, "title": (r.title or "")[:200], "severity": r.severity or ""})
    if not texts:
        if do_full:
            _last_full_incident_ingest = now_mono
        return 0
    embeddings = await get_embeddings_batch(texts)
    texts, embeddings, metadatas, ids = _filter_valid_embeddings(texts, embeddings, metadatas, ids)
    if not texts:
        detail = get_last_embed_error() or "Ollama embedding başarısız (sıfır vektör)"
        raise RuntimeError(f"Incident RAG ingest: {detail}")
    upsert_chunks(COLLECTION_INCIDENTS, ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
    if do_full:
        _last_full_incident_ingest = now_mono
        try:
            # Stale incident_* chunk'larını temizle (DB'de olmayan id)
            all_ids = {f"incident_{i}" for (i,) in db.query(Incident.id).all()}
            pruned = prune_ids_not_in_keep(
                COLLECTION_INCIDENTS, all_ids, id_prefix="incident_",
            )
            if pruned:
                logger.info("RAG incidents prune: %s stale chunk silindi", pruned)
        except Exception as e:
            logger.warning("RAG incidents prune atlandı: %s", e)
    return len(ids)


def _event_to_text(event) -> str:
    parts = [
        event.title or "",
        event.description or "",
        f"Type: {event.event_type or ''}",
        f"Severity: {event.severity or ''}",
    ]
    return "\n".join(p for p in parts if p).strip()


async def ingest_events_from_db(db: Session, limit: int = 2000) -> int:
    from app.models.event import SystemEvent
    from app.services.embedding import get_embeddings_batch, get_last_embed_error

    rows = db.query(SystemEvent).order_by(SystemEvent.id.desc()).limit(max(100, min(limit, 5000))).all()
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
    embeddings = await get_embeddings_batch(texts)
    texts, embeddings, metadatas, ids = _filter_valid_embeddings(texts, embeddings, metadatas, ids)
    if not texts:
        detail = get_last_embed_error() or "Ollama embedding başarısız (sıfır vektör)"
        raise RuntimeError(f"Event RAG ingest: {detail}")
    upsert_chunks(COLLECTION_INCIDENTS, ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
    try:
        all_event_ids = {f"event_{i}" for (i,) in db.query(SystemEvent.id).all()}
        pruned = prune_ids_not_in_keep(
            COLLECTION_INCIDENTS, all_event_ids, id_prefix="event_",
        )
        if pruned:
            logger.info("RAG events prune: %s stale chunk silindi", pruned)
    except Exception as e:
        logger.warning("RAG events prune atlandı: %s", e)
    return len(ids)


async def ingest_metric_descriptions(items: List[dict]) -> int:
    from app.services.embedding import get_embeddings_batch, get_last_embed_error

    clear_collection(COLLECTION_METRICS)
    if not items:
        return 0
    documents, metadatas = [], []
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
    embeddings = await get_embeddings_batch(documents)
    ids = [f"metric_{i}" for i in range(len(documents))]
    documents, embeddings, metadatas, ids = _filter_valid_embeddings(documents, embeddings, metadatas, ids)
    if not documents:
        detail = get_last_embed_error() or "Ollama embedding başarısız (sıfır vektör)"
        raise RuntimeError(f"Metrik RAG ingest: {detail}")
    add_chunks(COLLECTION_METRICS, ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    return len(ids)


async def ingest_knowledge_from_db(db: Session, *, force: bool = False) -> int:
    """
    Bilgi Bankası → RAG knowledge_facts.
    Öncelik: learned_facts; yoksa linux_inventory + discovered_applications ile doldur.
    İmza (count/max id/max last_confirmed) değişmediyse yeniden index atlanır.
    """
    from sqlalchemy import func as sa_func
    from app.models.learned_fact import LearnedFact
    from app.models.server import Server
    from app.services.embedding import get_embeddings_batch, get_last_embed_error

    global _knowledge_sig
    agg = db.query(
        sa_func.count(LearnedFact.id),
        sa_func.max(LearnedFact.id),
        sa_func.max(LearnedFact.last_confirmed_at),
    ).one()
    sig = (int(agg[0] or 0), agg[1], str(agg[2]) if agg[2] else "")
    if (
        not force
        and _knowledge_sig == sig
        and count_collection(COLLECTION_KNOWLEDGE) > 0
    ):
        logger.debug("RAG knowledge: imza değişmedi, reindex atlandı")
        return 0

    clear_collection(COLLECTION_KNOWLEDGE)
    rows = db.query(LearnedFact).order_by(
        LearnedFact.server_id, LearnedFact.category, LearnedFact.key
    ).all()

    texts, ids, metadatas = [], [], []

    if rows:
        server_ids = {r.server_id for r in rows}
        servers = {
            s.id: s
            for s in db.query(Server).filter(Server.id.in_(list(server_ids))).all()
        } if server_ids else {}

        grouped = defaultdict(list)
        for r in rows:
            grouped[(r.server_id, r.category or "general")].append(r)

        for (sid, cat), facts in grouped.items():
            srv = servers.get(sid)
            sname = (srv.name if srv else f"server-{sid}") or f"server-{sid}"
            sip = (srv.ip_address if srv else "") or ""
            lines = [
                f"Sunucu bilgi bankası: {sname}" + (f" ({sip})" if sip else ""),
                f"Kategori: {cat}",
            ]
            for f in facts:
                val = (f.value or "").strip()
                if len(val) > 500:
                    val = val[:500] + "…"
                lines.append(f"- {f.key}: {val}")
            text = "\n".join(lines).strip()
            if not text:
                continue
            for i, ch in enumerate(chunk_text(text, chunk_size=1200, overlap=80) or [text]):
                ids.append(f"kb_{sid}_{cat}_{i}")
                texts.append(ch)
                metadatas.append({
                    "server_id": sid,
                    "server_name": sname[:200],
                    "category": str(cat)[:50],
                    "source": "knowledge_base",
                })
    else:
        # learned_facts boşsa envanter + keşfedilen uygulamalardan semantik bilgi üret
        texts, ids, metadatas = _knowledge_chunks_from_inventory(db)

    if not texts:
        _knowledge_sig = sig
        return 0
    embeddings = await get_embeddings_batch(texts)
    texts, embeddings, metadatas, ids = _filter_valid_embeddings(texts, embeddings, metadatas, ids)
    if not texts:
        detail = get_last_embed_error() or "Ollama embedding başarısız (sıfır vektör)"
        raise RuntimeError(f"Bilgi Bankası RAG ingest: {detail}")
    upsert_chunks(COLLECTION_KNOWLEDGE, ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
    _knowledge_sig = sig
    return len(ids)


def _knowledge_chunks_from_inventory(db: Session) -> Tuple[List[str], List[str], List[dict]]:
    """LinuxInventory + DiscoveredApplication → RAG chunk listeleri."""
    from app.models.linux_inventory import LinuxInventory
    from app.models.server import Server
    from app.models.discovered_application import DiscoveredApplication

    texts, ids, metadatas = [], [], []
    inv_rows = db.query(LinuxInventory).all()
    servers = {s.id: s for s in db.query(Server).all()}
    apps_by_sid: dict = defaultdict(list)
    try:
        for a in db.query(DiscoveredApplication).filter(
            DiscoveredApplication.status.in_(["running", "installed"])
        ).all():
            apps_by_sid[a.server_id].append(a)
    except Exception:
        pass

    for inv in inv_rows:
        srv = servers.get(inv.server_id)
        if not srv:
            continue
        sname = srv.name or f"server-{inv.server_id}"
        sip = srv.ip_address or ""
        lines = [
            f"Sunucu envanter özeti: {sname}" + (f" ({sip})" if sip else ""),
            f"FQDN: {inv.fqdn or '—'}",
            f"Datacenter: {inv.datacenter or '—'}",
            f"Uygulama: {inv.application or '—'} / owner={inv.application_owner or '—'}",
            f"Uptime(s): {inv.uptime_seconds}",
            f"CPU%: {inv.cpu_usage_percent}  RAM%: {inv.memory_usage_percent}  Disk%: {inv.disk_usage_percent}",
            f"Load: {inv.load_average_1m} / {inv.load_average_5m} / {inv.load_average_15m}",
            f"Son patch: {inv.last_patch_date}  Son reboot: {inv.last_reboot_date}",
            f"Toplama: {inv.collection_status} @ {inv.collection_time}",
        ]
        apps = apps_by_sid.get(inv.server_id) or []
        if apps:
            lines.append("Tespit edilen uygulamalar:")
            for a in apps[:30]:
                bits = [a.name]
                if a.version:
                    bits.append(f"v{a.version}")
                if a.port:
                    bits.append(f"port {a.port}")
                bits.append(a.status or "")
                lines.append("- " + " · ".join(str(b) for b in bits if b))
        text = "\n".join(str(x) for x in lines if x is not None).strip()
        for i, ch in enumerate(chunk_text(text, chunk_size=1200, overlap=80) or [text]):
            ids.append(f"inv_{inv.server_id}_{i}")
            texts.append(ch)
            metadatas.append({
                "server_id": inv.server_id,
                "server_name": sname[:200],
                "category": "inventory",
                "source": "linux_inventory",
            })

    # Envanteri olmayan ama app keşfi olan sunucular
    for sid, apps in apps_by_sid.items():
        if any(m.get("server_id") == sid for m in metadatas):
            continue
        srv = servers.get(sid)
        if not srv:
            continue
        sname = srv.name or f"server-{sid}"
        lines = [f"Sunucu uygulamaları: {sname} ({srv.ip_address or ''})"]
        for a in apps[:40]:
            lines.append(f"- {a.name} {a.version or ''} [{a.status}]")
        text = "\n".join(lines)
        ids.append(f"apps_{sid}_0")
        texts.append(text)
        metadatas.append({
            "server_id": sid,
            "server_name": sname[:200],
            "category": "applications",
            "source": "discovered_applications",
        })

    return texts, ids, metadatas


def format_knowledge_facts_for_servers(
    db: Session,
    server_ids: Sequence[int],
    *,
    max_facts: int = 120,
) -> str:
    """Seçili sunucuların Bilgi Bankası kayıtlarını doğrudan prompt’a verir."""
    if not server_ids:
        return ""
    from app.models.learned_fact import LearnedFact
    from app.models.server import Server

    sids = [int(x) for x in server_ids][:50]
    rows = (
        db.query(LearnedFact)
        .filter(LearnedFact.server_id.in_(sids))
        .order_by(LearnedFact.server_id, LearnedFact.category, LearnedFact.key)
        .limit(max_facts)
        .all()
    )
    if not rows:
        return ""
    servers = {s.id: s for s in db.query(Server).filter(Server.id.in_(sids)).all()}
    by_server = defaultdict(list)
    for r in rows:
        by_server[r.server_id].append(r)
    parts = []
    for sid, facts in by_server.items():
        srv = servers.get(sid)
        head = srv.name if srv else f"#{sid}"
        ip = f" ({srv.ip_address})" if srv and srv.ip_address else ""
        lines = [f"### {head}{ip}"]
        for f in facts:
            val = (f.value or "").replace("\n", " ").strip()
            if len(val) > 300:
                val = val[:300] + "…"
            lines.append(f"- [{f.category}] {f.key} = {val}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def get_runbook_context(message: str, top_k: Optional[int] = None) -> str:
    top_k = top_k or settings.RAG_RUNBOOK_TOP_K
    try:
        emb = await get_embedding(message)
        return await _format_collection_context(
            message, COLLECTION_RUNBOOK, emb, top_k, joiner="\n\n---\n\n"
        )
    except Exception as e:
        logger.warning(f"Runbook RAG error: {e}")
        return ""


async def get_incidents_context(message: str, top_k: Optional[int] = None) -> str:
    top_k = top_k or settings.RAG_INCIDENTS_TOP_K
    try:
        emb = await get_embedding(message)
        return await _format_collection_context(
            message, COLLECTION_INCIDENTS, emb, top_k, joiner="\n\n---\n\n"
        )
    except Exception as e:
        logger.warning(f"Incidents RAG error: {e}")
        return ""


async def get_metrics_context(message: str, top_k: Optional[int] = None) -> str:
    top_k = top_k or settings.RAG_METRICS_TOP_K
    try:
        emb = await get_embedding(message)
        return await _format_collection_context(
            message, COLLECTION_METRICS, emb, top_k, joiner="\n\n"
        )
    except Exception as e:
        logger.warning(f"Metrics RAG error: {e}")
        return ""


async def get_knowledge_context(message: str, top_k: Optional[int] = None) -> str:
    top_k = top_k or settings.RAG_KNOWLEDGE_TOP_K
    try:
        emb = await get_embedding(message)
        return await _format_collection_context(
            message, COLLECTION_KNOWLEDGE, emb, top_k, joiner="\n\n---\n\n"
        )
    except Exception as e:
        logger.warning(f"Knowledge RAG error: {e}")
        return ""


async def _format_collection_context(
    message: str,
    collection: str,
    emb: Optional[List[float]],
    top_k: int,
    *,
    joiner: str,
) -> str:
    if not emb or all(abs(float(x)) < 1e-12 for x in emb):
        return ""
    hits = query_collection(collection, query_embedding=emb, n_results=_candidate_k(top_k))
    hits = await _rerank_hits(message, hits, top_k)
    if not hits:
        return ""
    return joiner.join(h["document"] for h in hits if h.get("document"))


async def get_rag_context_for_message(
    message: str,
    *,
    db: Optional[Session] = None,
    server_ids: Optional[Sequence[int]] = None,
    include_server_facts: bool = False,
) -> dict:
    """
    Chat RAG: runbook (PDF), incidents, metrics, knowledge (Bilgi Bankası semantik).

    Dalga 3: soru için tek embedding; dört koleksiyon aynı vektörle sorgulanır
    (önceki 4× embed kalkar). Rerank hâlâ koleksiyon başına best-effort.

    Seçili sunucu fact'leri Chat tarafında zaten get_learned_facts_block ile gelir;
    burada varsayılan olarak semantik knowledge_facts araması kullanılır (filo geneli).
    include_server_facts=True ise seçili sunucu kayıtları da eklenir (preview / özel yollar).
    """
    import asyncio as _asyncio

    empty = {"runbook": "", "incidents": "", "metrics": "", "knowledge": ""}
    try:
        emb = await get_embedding(message)
    except Exception as e:
        logger.warning("RAG tek embed hatası: %s", e)
        return empty
    if not emb or all(abs(float(x)) < 1e-12 for x in emb):
        return empty

    rb_k = settings.RAG_RUNBOOK_TOP_K
    inc_k = settings.RAG_INCIDENTS_TOP_K
    met_k = settings.RAG_METRICS_TOP_K
    kn_k = settings.RAG_KNOWLEDGE_TOP_K

    runbook, incidents, metrics, knowledge = await _asyncio.gather(
        _format_collection_context(message, COLLECTION_RUNBOOK, emb, rb_k, joiner="\n\n---\n\n"),
        _format_collection_context(message, COLLECTION_INCIDENTS, emb, inc_k, joiner="\n\n---\n\n"),
        _format_collection_context(message, COLLECTION_METRICS, emb, met_k, joiner="\n\n"),
        _format_collection_context(message, COLLECTION_KNOWLEDGE, emb, kn_k, joiner="\n\n---\n\n"),
    )
    if include_server_facts and db is not None and server_ids:
        try:
            direct = format_knowledge_facts_for_servers(db, server_ids)
            if direct:
                knowledge = "\n\n".join(p for p in (direct, knowledge) if p).strip()
        except Exception as e:
            logger.warning("Knowledge server facts error: %s", e)
    return {
        "runbook": runbook,
        "incidents": incidents,
        "metrics": metrics,
        "knowledge": knowledge,
    }
