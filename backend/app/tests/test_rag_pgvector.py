"""pgvector store smoke — İZOLE test veritabanında (canlı ``rag_embeddings`` ve ``/app/uploads`` marker'ına DOKUNMAZ)."""
import pytest

from app.services import rag_store
from app.services.rag_store import (
    ensure_schema,
    upsert_chunks,
    query_collection,
    count_collection,
    delete_chunk_ids,
    COLLECTION_METRICS,
)


@pytest.fixture()
def rag_isolated(_isolated_engine, monkeypatch, tmp_path):
    """rag_store'u izole DB'ye yönlendirir; süreç içi global durum ve marker dosyası test sonunda geri alınır."""
    monkeypatch.setattr(rag_store, "engine", _isolated_engine)
    monkeypatch.setattr(rag_store, "_schema_ready", False)
    monkeypatch.setattr(rag_store, "_vector_disabled", False)
    monkeypatch.setattr(rag_store, "_vector_disable_reason", "")
    monkeypatch.setattr(rag_store, "_unsupported_marker", lambda: tmp_path / ".pgvector_unsupported")
    return _isolated_engine


def test_pgvector_upsert_and_query(rag_isolated):
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
