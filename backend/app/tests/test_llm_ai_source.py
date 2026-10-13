"""AiSource — varsayılan kaynak + kaynağa göre bütçe/yetenek profili."""
from __future__ import annotations

from app.services.llm_ai_source import (
    DEFAULT_AI_SOURCE_ID,
    AiSource,
    build_capability_profile,
    get_default_ai_source,
    resolve_ai_source,
)
from app.services.llm_context_budget import (
    get_context_token_budget,
    get_gateway_hard_cap_tokens,
    get_input_token_budget,
)
from app.services.llm_transport import get_effective_context_tokens


def test_resolve_none_and_default_id():
    a = resolve_ai_source(None)
    b = resolve_ai_source("default")
    c = get_default_ai_source()
    assert a.id == DEFAULT_AI_SOURCE_ID
    assert b.id == c.id == DEFAULT_AI_SOURCE_ID


def test_unknown_id_falls_back_to_default():
    assert resolve_ai_source("future-source-xyz").id == DEFAULT_AI_SOURCE_ID


def test_custom_source_budget_overrides(monkeypatch):
    src = AiSource(
        id="lab",
        label="Lab",
        context_token_budget=8192,
        context_hard_cap_tokens=16384,
    )
    assert get_context_token_budget(ai_source=src) == 8192
    assert get_gateway_hard_cap_tokens(ai_source=src) == 16384

    monkeypatch.setattr(
        "app.services.llm_transport.get_discovered_context_length",
        lambda **_k: None,
    )
    # keşif yok → min(8192, 16384) = 8192
    assert get_effective_context_tokens(ai_source=src, allow_discover=False) == 8192

    monkeypatch.setattr(
        "app.services.llm_transport.get_discovered_context_length",
        lambda **_k: 4096,
    )
    assert get_effective_context_tokens(ai_source=src, allow_discover=False) == 4096


def test_default_source_matches_global_settings():
    src = resolve_ai_source(None)
    assert get_context_token_budget(ai_source=src) == get_context_token_budget()
    assert get_gateway_hard_cap_tokens(ai_source=src) == get_gateway_hard_cap_tokens()
    assert get_input_token_budget(ai_source=src) == get_input_token_budget()


def test_capability_profile_default_source(monkeypatch):
    monkeypatch.setattr(
        "app.services.llm_transport.discover_model_context_length",
        lambda **_k: 8192,
    )
    monkeypatch.setattr(
        "app.services.llm_context_budget.get_context_token_budget",
        lambda **_k: 32768,
    )
    monkeypatch.setattr(
        "app.services.llm_context_budget.get_gateway_hard_cap_tokens",
        lambda **_k: 32768,
    )
    prof = build_capability_profile(allow_discover=True)
    assert prof.source_id == DEFAULT_AI_SOURCE_ID
    assert prof.effective_context_tokens == 8192
    assert prof.discovered_context_length == 8192
    d = prof.as_dict()
    assert d["source_id"] == "default"
    assert d["effective_context_tokens"] == 8192


def test_gateway_accepts_ai_source_kwarg():
    """İmza var; çağrı varsayılan kaynakla kırılmaz (ağ yok — hata beklenir)."""
    import inspect
    from app.services import llm_gateway

    for name in ("chat_sync", "generate_sync", "generate_async", "stream_generate"):
        sig = inspect.signature(getattr(llm_gateway, name))
        assert "ai_source" in sig.parameters
