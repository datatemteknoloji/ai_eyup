"""AutomicSystem → AutomicSource."""
from __future__ import annotations

import os
from typing import Any

from app.core.encryption import decrypt_secret

from ..defaults import effective_settings
from .base import AutomicSource, SourceError


def fake_mode_enabled() -> bool:
    return (os.environ.get("AUTOMIC_FAKE") or "0").strip().lower() in ("1", "true", "yes", "on")


def build_source(system: Any) -> AutomicSource:
    settings = effective_settings(system.settings)
    secret = None
    if system.secret_enc:
        try:
            secret = decrypt_secret(system.secret_enc)
        except Exception as exc:
            raise SourceError("Kayıtlı şifre çözülemedi (SECRET_KEY değişmiş olabilir).",
                              code="secret", retryable=False) from exc
    st = (system.source_type or "db_oracle").lower()
    args = (system.id, system.connection or {}, secret, settings, system.capability or {})
    if st == "fake" or fake_mode_enabled():
        from .fake import FakeSource
        return FakeSource(*args)
    if st == "db_oracle":
        from .oracle import OracleSource
        return OracleSource(*args)
    raise SourceError(f"'{st}' kaynak tipi bu sürümde desteklenmiyor (yalnızca Oracle).",
                      code="unsupported", retryable=False)
