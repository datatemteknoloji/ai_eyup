"""probe_embedding light vs full — httpx mock."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import embedding as emb


@pytest.mark.asyncio
async def test_probe_light_ok_when_tags_list_model():
    tags_resp = MagicMock()
    tags_resp.status_code = 200
    tags_resp.json.return_value = {
        "models": [{"name": "nomic-embed-text:latest"}, {"name": "llama3"}],
    }

    client = AsyncMock()
    client.get = AsyncMock(return_value=tags_resp)
    client.post = AsyncMock(side_effect=AssertionError("light mode must not embed"))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(emb.httpx, "AsyncClient", return_value=client):
        with patch.object(emb, "embed_base_url", return_value="http://ollama:11434"):
            with patch.object(emb, "embed_model_name", return_value="nomic-embed-text"):
                out = await emb.probe_embedding(mode="light")

    assert out["ok"] is True
    assert out["probe_mode"] == "light"
    assert out["model_present"] is True
    assert out["error"] is None
    client.post.assert_not_called()


@pytest.mark.asyncio
async def test_probe_light_fails_when_model_missing():
    tags_resp = MagicMock()
    tags_resp.status_code = 200
    tags_resp.json.return_value = {"models": [{"name": "llama3"}]}

    client = AsyncMock()
    client.get = AsyncMock(return_value=tags_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(emb.httpx, "AsyncClient", return_value=client):
        with patch.object(emb, "embed_base_url", return_value="http://ollama:11434"):
            with patch.object(emb, "embed_model_name", return_value="nomic-embed-text"):
                out = await emb.probe_embedding(mode="light")

    assert out["ok"] is False
    assert out["model_present"] is False
    assert "listede yok" in (out["error"] or "")


@pytest.mark.asyncio
async def test_probe_full_calls_embed():
    tags_resp = MagicMock()
    tags_resp.status_code = 200
    tags_resp.json.return_value = {"models": [{"name": "nomic-embed-text"}]}

    client = AsyncMock()
    client.get = AsyncMock(return_value=tags_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(emb.httpx, "AsyncClient", return_value=client):
        with patch.object(emb, "embed_base_url", return_value="http://ollama:11434"):
            with patch.object(emb, "embed_model_name", return_value="nomic-embed-text"):
                with patch.object(
                    emb,
                    "_post_embed",
                    AsyncMock(return_value=([0.1] * 768, None)),
                ) as post:
                    out = await emb.probe_embedding(mode="full")

    assert out["ok"] is True
    assert out["probe_mode"] == "full"
    assert out.get("dim") == 768
    post.assert_awaited()
