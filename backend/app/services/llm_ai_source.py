"""AI kaynağı — gateway / bütçe / yetenek profili için ileriye dönük soyutlama.

Şimdilik tek kaynak vardır: ``default`` (global REMOTE_LLM + Ollama + Gelişmiş
Ayarlar). Gateway fonksiyonları opsiyonel ``ai_source`` alır; verilmezse veya
bilinmeyen id gelirse varsayılan kaynak kullanılır.

UI / modül eşlemesi yok — sonraki adımda kayıt defteri eklenebilir.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union

DEFAULT_AI_SOURCE_ID = "default"


@dataclass(frozen=True)
class AiSource:
    """Bir LLM uç noktası + bütçe/taşıma tercihleri.

    ``None`` alanlar global ayara düşer (settings / runtime_settings).
    """

    id: str = DEFAULT_AI_SOURCE_ID
    label: str = "Varsayılan"
    context_token_budget: Optional[int] = None
    context_hard_cap_tokens: Optional[int] = None
    transport_mode: Optional[str] = None  # auto | ollama | openai
    keep_alive: Optional[Any] = None
    remote_llm_url: Optional[str] = None
    ollama_url: Optional[str] = None
    model: Optional[str] = None


AiSourceRef = Optional[Union[AiSource, str]]


def get_default_ai_source() -> AiSource:
    return AiSource(id=DEFAULT_AI_SOURCE_ID, label="Varsayılan")


def resolve_ai_source(source: AiSourceRef = None) -> AiSource:
    """Çağıranın verdiği kaynak; yoksa / bilinmiyorsa varsayılan."""
    if source is None:
        return get_default_ai_source()
    if isinstance(source, AiSource):
        return source
    sid = str(source).strip()
    if not sid or sid == DEFAULT_AI_SOURCE_ID:
        return get_default_ai_source()
    # Kayıt defteri yok — bilinmeyen id sessizce varsayılana düşer
    return get_default_ai_source()


@dataclass(frozen=True)
class AiCapabilityProfile:
    """Kaynağa göre hesaplanmış yetenek / bütçe özeti."""

    source_id: str
    transport: str
    transport_mode: str
    configured_budget: int
    hard_cap: int
    discovered_context_length: Optional[int]
    effective_context_tokens: int
    keep_alive: Any
    model: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "transport": self.transport,
            "transport_mode": self.transport_mode,
            "configured_budget": self.configured_budget,
            "hard_cap": self.hard_cap,
            "discovered_context_length": self.discovered_context_length,
            "effective_context_tokens": self.effective_context_tokens,
            "keep_alive": self.keep_alive,
            "model": self.model,
        }


def build_capability_profile(
    ai_source: AiSourceRef = None,
    *,
    model: Optional[str] = None,
    allow_discover: bool = True,
) -> AiCapabilityProfile:
    """Kaynak için taşıma + etkin context bütçesi profili."""
    from app.services import llm_transport as tr
    from app.services.llm_context_budget import (
        get_context_token_budget,
        get_gateway_hard_cap_tokens,
    )
    from app.services.ollama_runtime import get_keep_alive

    src = resolve_ai_source(ai_source)
    want = (model or src.model or "").strip() or None
    transport = tr.resolve_active_transport(ai_source=src)
    mode = tr.get_transport_mode(ai_source=src)
    desired = get_context_token_budget(ai_source=src)
    hard = get_gateway_hard_cap_tokens(ai_source=src)
    disc = None
    if allow_discover:
        disc = tr.discover_model_context_length(model=want, ai_source=src)
    else:
        disc = tr.get_discovered_context_length(ai_source=src)
    effective = tr.get_effective_context_tokens(
        model=want, ai_source=src, allow_discover=allow_discover,
    )
    return AiCapabilityProfile(
        source_id=src.id,
        transport=transport,
        transport_mode=mode,
        configured_budget=desired,
        hard_cap=hard,
        discovered_context_length=disc,
        effective_context_tokens=effective,
        keep_alive=get_keep_alive(ai_source=src),
        model=want,
    )
