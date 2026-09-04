"""llm_context_budget unit tests."""
from app.services.llm_context_budget import (
    estimate_tokens,
    truncate_text_to_token_budget,
)


def test_estimate_tokens():
    assert estimate_tokens("hello") >= 1


def test_truncate_when_over_budget():
    big = "x" * 100000
    out, truncated = truncate_text_to_token_budget(big, 1000)
    assert truncated
    assert len(out) < len(big)
    assert "kısaltıldı" in out


def test_no_truncate_when_under_budget():
    small = "kısa metin"
    out, truncated = truncate_text_to_token_budget(small, 10000)
    assert not truncated
    assert out == small
