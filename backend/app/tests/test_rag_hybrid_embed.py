"""RAG hibrit arama, embedding boyutu ve model tutarlılığı."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.embedding import EmbedResult, _validate_dim
from app.services.rag_store import reciprocal_rank_fusion


def test_validate_dim_rejects_mismatch_no_pad():
    vec, err = _validate_dim([0.1] * 384, expected=768)
    assert vec is None and err and "pad" in err
    vec, err = _validate_dim([0.1] * 1024, expected=768)
    assert vec is None and err and "pad" in err
    vec, err = _validate_dim([0.1] * 768, expected=768)
    assert vec is not None and len(vec) == 768 and err is None


def test_rrf_merges_vector_and_fts_ranks():
    vec = [
        {"id": "a", "document": "cpu", "distance": 0.1},
        {"id": "b", "document": "mem", "distance": 0.2},
    ]
    fts = [
        {"id": "b", "document": "mem", "distance": 0.05},
        {"id": "c", "document": "disk", "distance": 0.1},
    ]
    out = reciprocal_rank_fusion([vec, fts], n_results=3)
    ids = [h["id"] for h in out]
    assert "b" in ids
    assert ids[0] == "b"
    assert set(ids) <= {"a", "b", "c"}


@pytest.mark.asyncio
async def test_embed_text_uses_truncate_false_on_api_embed():
    from app.services import embedding as emb

    captured = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"embeddings": [[0.01] * 768]}

    async def fake_post(url, json=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return _Resp()

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = fake_post

    with patch.object(emb.httpx, "AsyncClient", return_value=client), patch.object(
        emb, "embed_base_url", return_value="http://ollama:11434"
    ), patch.object(emb, "embed_model_name", return_value="nomic-embed-text"):
        res = await emb.embed_text("kısa metin")
    assert isinstance(res, EmbedResult)
    assert res.usable_for_vector_search
    assert captured["json"].get("truncate") is False
    assert "/api/embed" in captured["url"]


@pytest.mark.asyncio
async def test_remote_model_mismatch_returns_no_vector():
    from app.services import embedding as emb

    class _FailLocal:
        status_code = 500
        text = "fail"

        def json(self):
            return {}

    async def fake_post(url, json=None, **kwargs):
        return _FailLocal()

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = fake_post

    settings = MagicMock()
    settings.REMOTE_LLM_URL = "https://remote.example"
    settings.REMOTE_LLM_API_KEY = "k"
    settings.REMOTE_LLM_VIRTUAL_KEY = ""
    settings.REMOTE_LLM_EMBED_MODEL = "text-embedding-3-small"
    settings.OLLAMA_EMBED_MODEL = "nomic-embed-text"
    settings.EMBEDDING_URL = ""
    settings.OLLAMA_URL = "http://ollama:11434"

    with patch.object(emb.httpx, "AsyncClient", return_value=client), patch.object(
        emb, "settings", settings
    ), patch.object(emb, "remote_llm_enabled", return_value=True), patch.object(
        emb, "embed_model_name", return_value="nomic-embed-text"
    ), patch.object(
        emb, "remote_embed_model_name", return_value="text-embedding-3-small"
    ), patch.object(emb, "embed_base_url", return_value="http://ollama:11434"):
        res = await emb.embed_text("metin")
    assert not res.usable_for_vector_search
    assert res.vector is None
    assert res.error and "farklı" in res.error


@pytest.mark.asyncio
async def test_chat_rag_falls_back_to_fts_when_embed_fails():
    from app.services import rag_service

    async def boom(_t):
        return EmbedResult(
            vector=None,
            model="nomic-embed-text",
            dim=0,
            error="down",
            usable_for_vector_search=False,
        )

    with patch.object(rag_service, "embed_text", side_effect=boom), patch.object(
        rag_service,
        "hybrid_search_collection",
        return_value=[{
            "id": "1",
            "document": "disk doldu",
            "metadata": {"title": "x"},
            "distance": 0.2,
        }],
    ) as hyb, patch.object(
        rag_service,
        "format_runbook_hits",
        side_effect=lambda hits: hits,
    ):
        out = await rag_service.search_runbook_documents("disk", top_k=3)
        assert out.get("hits")
        assert out.get("mode") == "fts"
        hyb.assert_called()
        assert hyb.call_args.kwargs.get("query_embedding") is None
