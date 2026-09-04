"""
LLM context bütçesi — Gelişmiş Ayarlar (llm_context_token_budget) ile yapılandırılır.

Tüm chat yollarında prompt/metin kırpma için merkezi yardımcılar.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Çıkış + system rezervi (token)
_DEFAULT_RESERVE_TOKENS = 4096
_CHARS_PER_TOKEN_EST = 3.5


def get_context_token_budget() -> int:
    try:
        from app.services.runtime_settings import get_setting
        raw = get_setting("llm_context_token_budget")
        return int(raw) if raw is not None else 32768
    except Exception:
        return 32768


def get_input_token_budget(*, reserve: int = _DEFAULT_RESERVE_TOKENS) -> int:
    total = get_context_token_budget()
    return max(2048, total - reserve)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN_EST))


def truncate_text_to_token_budget(text: str, max_tokens: int, *, suffix: str = "\n\n…(context kısaltıldı)") -> Tuple[str, bool]:
    """Metni tahmini token bütçesine kırpar. (text, truncated?)"""
    if not text or max_tokens <= 0:
        return text or "", False
    est = estimate_tokens(text)
    if est <= max_tokens:
        return text, False
    max_chars = int(max_tokens * _CHARS_PER_TOKEN_EST)
    if max_chars <= len(suffix) + 100:
        return text[:max_chars], True
    cut = max_chars - len(suffix)
    logger.info(
        "LLM context kırpıldı: ~%d token → ~%d token budget",
        est, max_tokens,
    )
    return text[:cut] + suffix, True


def apply_prompt_budget(prompt: str, *, reserve: Optional[int] = None) -> Tuple[str, bool]:
    budget = get_input_token_budget(reserve=reserve or _DEFAULT_RESERVE_TOKENS)
    return truncate_text_to_token_budget(prompt, budget)


def apply_context_char_budget(text: str, max_tokens: Optional[int] = None) -> str:
    """unified_tool_chat context_str için."""
    budget = max_tokens or get_input_token_budget()
    out, _ = truncate_text_to_token_budget(text, budget)
    return out
