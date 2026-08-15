"""pgvector store smoke — canlı DB gerekir."""
from app.services.rag_store import (
    ensure_schema,
    upsert_chunks,
    query_collection,
    count_collection,
    delete_chunk_ids,
    COLLECTION_METRICS,
)


def test_pgvector_upsert_and_query():
    ensure_schema()
    cid = "test_metric_pgvector_1"
    emb = [0.01] * 768
    emb[0] = 1.0
    upsert_chunks(
        COLLECTION_METRICS,
        [cid],
        ["CPU kullanım metriği test"],
        [{"metric_name": "cpu_test"}],
        [emb],
    )
    n = count_collection(COLLECTION_METRICS)
    assert n >= 1
    hits = query_collection(COLLECTION_METRICS, emb, n_results=3)
    assert hits
    assert any(h["id"] == cid for h in hits)
    delete_chunk_ids(COLLECTION_METRICS, [cid])
