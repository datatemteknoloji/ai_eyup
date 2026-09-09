"""Kullanıcı iptali — istek boyunca taşınan işbirlikçi (cooperative) bayrak.

Sorun: `cancel_turn` yalnız DB'de durumu "cancelled" yapıp SSE'ye bir olay
basıyordu. Çalışan pipeline bunu HİÇ görmediği için iptal KOZMETİKTİ: model
token üretmeye, araçlar çalışmaya, `ai_gate` kotası tutulmaya devam ediyordu.
Kullanıcı "durdur"a bastıktan sonra da uzak model faturası işliyordu.

Bu modül iptali pipeline'ın derinliklerine taşır. Üç kontrol noktası vardır:

  1. orchestrator akış döngüsü (token/olay başına)   → `service.run_turn`
  2. LLM stream okuma döngüsü (chunk başına)          → `llm_gateway`
  3. araç (tool) döngüsü, her tur başında            → `unified_tool_chat`

Neden contextvar: pipeline fonksiyonları turn_id'yi parametre olarak almıyor
(imzaları platformlar arasında farklı ve LLM katmanı çağrı zincirinin çok
altında). Contextvar, asyncio task'ına bağlı olduğu için eşzamanlı turlar
birbirinin bayrağını görmez.

Redis okuması `_CHECK_INTERVAL_SEC` ile kısılır: token başına Redis'e gitmek
gereksiz yük olurdu, 250 ms gecikme kullanıcı için görünmez.
"""
from __future__ import annotations

import logging
import time
from contextvars import ContextVar, Token
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SEC = 0.25

_turn_id: ContextVar[Optional[str]] = ContextVar("chat_cancel_turn_id", default=None)
#: (son_kontrol_zamanı, son_sonuç) — kısma için
_cache: ContextVar[Optional[Tuple[float, bool]]] = ContextVar("chat_cancel_cache", default=None)


class ChatCancelled(Exception):
    """Kullanıcı isteği iptal etti; kısmi cevap korunur."""


def bind(turn_id: Optional[str]) -> Optional[Token]:
    if not turn_id:
        return None
    _cache.set(None)
    return _turn_id.set(turn_id)


def unbind(token: Optional[Token]) -> None:
    if token is None:
        return
    try:
        _turn_id.reset(token)
    except Exception:
        pass


def current_turn_id() -> Optional[str]:
    return _turn_id.get()


def is_cancelled(*, force: bool = False) -> bool:
    """İptal istendi mi? (kısılmış Redis okuması)

    `force=True` kısmayı atlar — sonlandırma kararı verilirken kullanılır.
    """
    turn_id = _turn_id.get()
    if not turn_id:
        return False
    now = time.monotonic()
    cached = _cache.get()
    if not force and cached and (now - cached[0]) < _CHECK_INTERVAL_SEC:
        return cached[1]
    try:
        from app.services.chat_orchestrator import events

        flag = events.is_cancel_requested(turn_id)
    except Exception:
        flag = False
    _cache.set((now, flag))
    return flag


def is_cancelled_for(turn_id: Optional[str]) -> bool:
    """Belirli bir tur için bayrak kontrolü (contextvar'a bağlı olmadan)."""
    if not turn_id:
        return False
    try:
        from app.services.chat_orchestrator import events

        return events.is_cancel_requested(turn_id)
    except Exception:
        return False


def raise_if_cancelled() -> None:
    if is_cancelled():
        raise ChatCancelled("Kullanıcı isteği iptal etti")
