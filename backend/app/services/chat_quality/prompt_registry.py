"""Sistem prompt'u sızıntı denetimi için kayıtlı prompt metinlerinden 8 kelimelik parmak izleri."""
from __future__ import annotations

import logging
from typing import Optional

from app.services.chat_quality.claims import make_shingles

logger = logging.getLogger(__name__)
_CACHE: Optional[set] = None


def get_shingles() -> set:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    texts = []
    try:
        from app.services.chat_rules import (
            NUMBER_RULE_TR, ADVICE_RULE_TR, HONESTY_RULE_TR, USER_LANGUAGE_RULE_TR, OC_RULE_TR,
        )
        texts += [NUMBER_RULE_TR, ADVICE_RULE_TR, HONESTY_RULE_TR, USER_LANGUAGE_RULE_TR, OC_RULE_TR]
    except Exception:
        logger.debug("chat_rules yüklenemedi", exc_info=True)
    try:
        from app.services.hypervisor_intelligence import _VIRTUALIZATION_PERSONA
        texts.append(_VIRTUALIZATION_PERSONA)
    except Exception:
        logger.debug("virt persona yüklenemedi", exc_info=True)
    try:
        from app.services.unified_tool_chat import SYSTEM_PROMPT
        texts.append(SYSTEM_PROMPT)
    except Exception:
        logger.debug("SYSTEM_PROMPT yüklenemedi", exc_info=True)
    sh: set = set()
    for t in texts:
        sh |= make_shingles(t)
    _CACHE = sh
    return sh
