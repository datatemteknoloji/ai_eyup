from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings

_KEY = "assistant:pending:{user_id}"
_TTL = 900  # 15 minutes — sticky 24h pending was too aggressive


def _redis():
    import redis

    return redis.from_url(get_settings().redis_url, decode_responses=True)


def get_pending(user_id: int) -> dict[str, Any] | None:
    try:
        raw = _redis().get(_KEY.format(user_id=user_id))
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) and data.get("operation_id") else None
    except Exception:
        return None


def set_pending(
    user_id: int,
    operation_id: str,
    *,
    hint: str = "",
    reference_ids: list[int] | None = None,
    reference_hostnames: list[str] | None = None,
) -> None:
    payload = {
        "operation_id": (operation_id or "").strip(),
        "hint": (hint or "").strip()[:500],
        "reference_ids": [int(x) for x in (reference_ids or [])][:3],
        "reference_hostnames": [str(x) for x in (reference_hostnames or [])][:3],
    }
    if not payload["operation_id"]:
        clear_pending(user_id)
        return
    try:
        _redis().setex(_KEY.format(user_id=user_id), _TTL, json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


def clear_pending(user_id: int) -> None:
    try:
        _redis().delete(_KEY.format(user_id=user_id))
    except Exception:
        pass
