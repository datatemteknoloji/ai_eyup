"""Gelişmiş ayarlar — LLM context / keep_alive doğrulama."""
from __future__ import annotations

import pytest

from app.services.runtime_settings import (
    ADVANCED_SCHEMA,
    validate_advanced_value,
)


def test_context_choices_include_range_bounds():
    for key in ("llm_context_token_budget", "llm_context_hard_cap_tokens"):
        meta = ADVANCED_SCHEMA[key]
        assert meta["min"] == 4096
        assert meta["max"] == 131072
        assert "4096" in meta["choices"]
        assert "131072" in meta["choices"]
        assert meta.get("requires_restart") in (None, False)
        assert meta.get("notes")


def test_validate_context_ok():
    assert validate_advanced_value("llm_context_token_budget", "32768") == "32768"
    assert validate_advanced_value("llm_context_token_budget", "4096") == "4096"
    assert validate_advanced_value("llm_context_hard_cap_tokens", "131072") == "131072"


def test_validate_context_rejects_invalid():
    with pytest.raises(ValueError, match="geçersiz"):
        validate_advanced_value("llm_context_token_budget", "2048")
    with pytest.raises(ValueError, match="geçersiz"):
        validate_advanced_value("llm_context_token_budget", "999999")


def test_all_context_choices_within_min_max():
    for key in ("llm_context_token_budget", "llm_context_hard_cap_tokens"):
        meta = ADVANCED_SCHEMA[key]
        for c in meta["choices"]:
            n = int(c)
            assert meta["min"] <= n <= meta["max"]


def test_validate_keep_alive_choices():
    assert validate_advanced_value("ollama_keep_alive", "-1") == "-1"
    assert validate_advanced_value("ollama_keep_alive", "10m") == "10m"
    with pytest.raises(ValueError, match="geçersiz"):
        validate_advanced_value("ollama_keep_alive", "xyz")
