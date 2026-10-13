"""Centrify DEMO veri uçları (``/centrify-mgmt/demo/seed``) için tek kapı.

- Varsayılan KAPALI. Yalnız ``CENTRIFY_DEMO_ENABLED=true`` ortam değişkeni (geliştirme/demo ortamı) açar.
- Açık olsa bile uçlar yalnız ``admin`` rolüne açıktır (``core.module_policy.ROLE_RULES`` + uç bağımlılığı).
- ``DELETE`` demo ucu Centrify tablolarını boşaltır; kapalıyken de çağrılamaz (yanlışlıkla gerçek veri silinmesin).
"""
from __future__ import annotations

import os

from fastapi import HTTPException, status

ENV_FLAG = "CENTRIFY_DEMO_ENABLED"
DISABLED_MSG_TR = ("Centrify DEMO veri uçları kapalı. Yalnızca geliştirme/demo ortamında "
                   f"{ENV_FLAG}=true ortam değişkeniyle açılır.")


def demo_enabled() -> bool:
    """Ortam bayrağı (her çağrıda okunur)."""
    return os.getenv(ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def require_demo_enabled() -> None:
    """FastAPI bağımlılığı: bayrak kapalıysa 404 (uç yokmuş gibi davranır)."""
    if not demo_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=DISABLED_MSG_TR)
