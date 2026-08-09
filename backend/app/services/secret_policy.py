"""
Secret / .env güvenlik politikası.

Placeholder değerler (GENERATE_WITH_*, CHANGE_ME*, …) üretimde kabul edilmez.
"""
from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

# Bilinen şablon / örnek değerler
_PLACEHOLDER_PREFIXES = (
    "GENERATE_WITH_",
    "GENERATE_",
    "CHANGE_ME",
    "CHANGEME",
    "REPLACE-",
    "REPLACE_WITH_",
    "TODO",
    "YOUR_",
)

_PLACEHOLDER_EXACT = frozenset({
    "password",
    "secret",
    "changeme",
    "admin123",
})


def is_insecure_secret_value(value: Optional[str], *, min_len: int = 16) -> bool:
    """True = placeholder veya aşırı zayıf."""
    if value is None:
        return True
    v = str(value).strip()
    if not v:
        return True
    upper = v.upper()
    for p in _PLACEHOLDER_PREFIXES:
        if upper.startswith(p.upper()):
            return True
    if v.lower() in _PLACEHOLDER_EXACT:
        return True
    if len(v) < min_len:
        return True
    return False


def secret_key_fingerprint(secret_key: str) -> str:
    import hashlib
    dig = hashlib.sha256((secret_key or "").encode()).hexdigest()[:16]
    return f"sha256:{dig}"


def validate_runtime_secrets(
    *,
    secret_key: Optional[str] = None,
    postgres_password: Optional[str] = None,
    strict: Optional[bool] = None,
) -> Tuple[bool, List[str]]:
    """
    Dönüş: (ok, messages).
    strict=None → ALLOW_INSECURE_SECRETS env (true ise soft), yoksa STRICT_SECRETS
    veya prod benzeri varsayılan: placeholder SECRET_KEY fail.
    """
    sk = secret_key if secret_key is not None else os.getenv("SECRET_KEY", "")
    messages: List[str] = []

    allow = (os.getenv("ALLOW_INSECURE_SECRETS") or "").strip().lower() in ("1", "true", "yes", "on")
    if strict is None:
        if allow:
            strict = False
        else:
            # Varsayılan: SECRET_KEY placeholder ise sıkı (fail)
            strict = True

    if is_insecure_secret_value(sk, min_len=24):
        messages.append(
            "SECRET_KEY placeholder veya çok kısa. "
            "Kurulum: install-rhel.sh / scripts/dev-setup.sh; "
            "canlı ortam: scripts/rotate-secrets.sh"
        )

    # POSTGRES_PASSWORD — DATABASE_URL içinden de çıkarılabilir; opsiyonel uyarı
    pp = postgres_password
    if pp is None:
        pp = os.getenv("POSTGRES_PASSWORD") or ""
        if not pp:
            url = os.getenv("DATABASE_URL") or ""
            m = re.search(r"://[^:]+:([^@]+)@", url)
            if m:
                from urllib.parse import unquote
                pp = unquote(m.group(1))
    if pp and is_insecure_secret_value(pp, min_len=12):
        messages.append(
            "POSTGRES_PASSWORD placeholder veya zayıf görünüyor "
            "(scripts/rotate-secrets.sh --postgres ile güçlendirilebilir)."
        )

    if not messages:
        return True, []

    if strict and any("SECRET_KEY" in m for m in messages):
        return False, messages
    return True, messages  # soft: postgres zayıf → uyarı, devam
