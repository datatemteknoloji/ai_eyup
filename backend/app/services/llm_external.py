"""Groq / OpenAI / OpenRouter — OpenAI-uyumlu doğrudan hedef.

REMOTE_LLM (Bifrost) bu modülün işi değil. Anahtar yoksa None.
Anthropic Messages API burada yok (tool sözleşmesi farklı).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from app.core.config import settings


@dataclass(frozen=True)
class ExternalChatTarget:
    provider: str
    url: str
    api_key: str
    model: str
    extra_headers: Dict[str, str] = field(default_factory=dict)

    def headers(self) -> Dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        h.update(self.extra_headers)
        return h


def detect_provider(model: str) -> str:
    """chat.py / unified / windows ile aynı ad → sağlayıcı eşlemesi."""
    m = (model or "").lower()
    # Yerel varsayılan (OLLAMA_DEFAULT_MODEL=gpt-oss:20b) OpenAI gpt-* ile karışmasın.
    if "gpt-oss" in m:
        return "ollama"
    if m.startswith("groq:") or any(
        x in m
        for x in (
            "llama3-70b",
            "llama3-8b",
            "mixtral-8x7b",
            "gemma2-9b",
            "llama-3.1-70b",
            "llama-3.3-70b",
        )
    ):
        return "groq"
    if m.startswith("gpt-") or m.startswith("openai/") or m.startswith("o1") or m.startswith("o3"):
        return "openai"
    if m.startswith("claude") or m.startswith("anthropic/"):
        return "anthropic"
    if "/" in m and not m.startswith("http"):
        return "openrouter"
    return "ollama"


def strip_provider_prefix(model: str) -> str:
    return (model or "").replace("groq:", "").replace("openai/", "")


def resolve_external_chat_target(model: str) -> Optional[ExternalChatTarget]:
    """Anahtarlı Groq/OpenAI/OpenRouter hedefi; yoksa None (Ollama / REMOTE_LLM)."""
    provider = detect_provider(model)
    clean = strip_provider_prefix(model)
    if provider == "groq" and settings.GROQ_API_KEY:
        return ExternalChatTarget(
            provider="groq",
            url=settings.GROQ_API_URL,
            api_key=settings.GROQ_API_KEY,
            model=clean,
        )
    if provider == "openai" and settings.OPENAI_API_KEY:
        return ExternalChatTarget(
            provider="openai",
            url=settings.OPENAI_API_URL,
            api_key=settings.OPENAI_API_KEY,
            model=clean,
        )
    if provider == "openrouter" and settings.OPENROUTER_API_KEY:
        return ExternalChatTarget(
            provider="openrouter",
            url=settings.OPENROUTER_API_URL,
            api_key=settings.OPENROUTER_API_KEY,
            model=clean,
            extra_headers={
                "HTTP-Referer": "https://datatem.ai",
                "X-Title": "datatem AI",
            },
        )
    return None
