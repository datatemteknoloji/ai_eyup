"""
Fleet arka plan görevleri için overlap koruması.

Önceki tur bitmeden aynı fleetin yeniden başlamasını engeller
(health / log / onboarding). blocking=False — kaçırılan tur bir
sonraki interval'da alınır.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Dict, Iterator

logger = logging.getLogger(__name__)

_LOCKS: Dict[str, threading.Lock] = {
    "health": threading.Lock(),
    "logs": threading.Lock(),
    "onboarding": threading.Lock(),
    "metric_sync": threading.Lock(),
}


@contextmanager
def fleet_lock(name: str) -> Iterator[bool]:
    """True = kilit alındı (çalıştır); False = önceki tur hâlâ aktif (atla)."""
    lock = _LOCKS.get(name)
    if lock is None:
        yield True
        return
    acquired = lock.acquire(blocking=False)
    if not acquired:
        logger.info("Fleet '%s' atlandı: önceki tur hâlâ çalışıyor", name)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()
