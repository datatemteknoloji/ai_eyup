"""Paylaşılan Redis istemcisi — fail-open (None döner)."""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_client: Any = None
_unavailable = False


def redis_url() -> str:
    return (os.environ.get("REDIS_URL") or "redis://localhost:6379/0").strip()


def get_redis(*, force_retry: bool = False):
    """decode_responses=True Redis client veya None (erişilemezse)."""
    global _client, _unavailable
    if _unavailable and not force_retry:
        return None
    if _client is not None:
        return _client
    with _lock:
        if _client is not None:
            return _client
        if _unavailable and not force_retry:
            return None
        try:
            import redis

            client = redis.from_url(
                redis_url(),
                socket_connect_timeout=1.5,
                socket_timeout=2.0,
                decode_responses=True,
            )
            client.ping()
            _client = client
            _unavailable = False
            return _client
        except Exception as exc:
            logger.warning("Redis kullanılamıyor: %s", exc)
            _unavailable = True
            _client = None
            return None


def reset_redis_client() -> None:
    """Test / reconnect için."""
    global _client, _unavailable
    with _lock:
        _client = None
        _unavailable = False
