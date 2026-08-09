from __future__ import annotations

from sqlmodel import Session

from app.models.settings import (
    ASSISTANT_DIRECT_HOST_KEY,
    ASSISTANT_DIRECT_PORT_KEY,
    ASSISTANT_ENABLED_KEY,
    ASSISTANT_GATEWAY_API_KEY,
    ASSISTANT_GATEWAY_URL_KEY,
    ASSISTANT_MODEL_KEY,
    ASSISTANT_OLLAMA_MODE_KEY,
    AppSetting,
)
from app.services.credential_manager import CredentialCryptoError, CredentialManager


def _get(session: Session, key: str, default: str = "") -> str:
    row = session.get(AppSetting, key)
    return (row.value or "").strip() if row else default


def _set(session: Session, key: str, value: str) -> str:
    row = session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
    else:
        row.value = value
    session.add(row)
    session.commit()
    session.refresh(row)
    return row.value


def ensure_assistant_defaults(session: Session) -> None:
    defaults = {
        ASSISTANT_ENABLED_KEY: "0",
        ASSISTANT_OLLAMA_MODE_KEY: "direct",
        ASSISTANT_GATEWAY_URL_KEY: "",
        ASSISTANT_DIRECT_HOST_KEY: "",
        ASSISTANT_DIRECT_PORT_KEY: "11434",
        ASSISTANT_MODEL_KEY: "",
    }
    for key, val in defaults.items():
        if session.get(AppSetting, key) is None:
            session.add(AppSetting(key=key, value=val))
    session.commit()


def is_assistant_enabled(session: Session) -> bool:
    return _get(session, ASSISTANT_ENABLED_KEY, "0") in {"1", "true", "yes", "on"}


def set_assistant_enabled(session: Session, enabled: bool) -> bool:
    _set(session, ASSISTANT_ENABLED_KEY, "1" if enabled else "0")
    return enabled


def get_assistant_ollama_mode(session: Session) -> str:
    mode = _get(session, ASSISTANT_OLLAMA_MODE_KEY, "direct").lower()
    return mode if mode in {"gateway", "direct"} else "direct"


def set_assistant_ollama_mode(session: Session, mode: str) -> str:
    m = (mode or "").strip().lower()
    if m not in {"gateway", "direct"}:
        raise ValueError("Ollama modu gateway veya direct olmalı")
    return _set(session, ASSISTANT_OLLAMA_MODE_KEY, m)


def get_assistant_gateway_url(session: Session) -> str:
    return _get(session, ASSISTANT_GATEWAY_URL_KEY)


def set_assistant_gateway_url(session: Session, url: str) -> str:
    cleaned = (url or "").strip()
    if len(cleaned) > 512:
        raise ValueError("Gateway URL çok uzun")
    return _set(session, ASSISTANT_GATEWAY_URL_KEY, cleaned)


def gateway_api_key_is_set(session: Session) -> bool:
    row = session.get(AppSetting, ASSISTANT_GATEWAY_API_KEY)
    return bool(row and row.value.strip())


def get_assistant_gateway_api_key(session: Session) -> str | None:
    row = session.get(AppSetting, ASSISTANT_GATEWAY_API_KEY)
    if not row or not row.value.strip():
        return None
    try:
        return CredentialManager().decrypt(row.value.strip())
    except CredentialCryptoError:
        return None


def set_assistant_gateway_api_key(session: Session, key: str) -> None:
    cleaned = (key or "").strip()
    if not cleaned:
        # clear
        row = session.get(AppSetting, ASSISTANT_GATEWAY_API_KEY)
        if row:
            row.value = ""
            session.add(row)
            session.commit()
        return
    if len(cleaned) > 1024:
        raise ValueError("API key çok uzun")
    try:
        encrypted = CredentialManager().encrypt(cleaned)
    except CredentialCryptoError as exc:
        raise ValueError(str(exc)) from exc
    _set(session, ASSISTANT_GATEWAY_API_KEY, encrypted)


def get_assistant_direct_host(session: Session) -> str:
    return _get(session, ASSISTANT_DIRECT_HOST_KEY)


def set_assistant_direct_host(session: Session, host: str) -> str:
    cleaned = (host or "").strip()
    if len(cleaned) > 255:
        raise ValueError("Host çok uzun")
    if cleaned and any(c.isspace() for c in cleaned):
        raise ValueError("Host boşluk içeremez")
    return _set(session, ASSISTANT_DIRECT_HOST_KEY, cleaned)


def get_assistant_direct_port(session: Session) -> int:
    raw = _get(session, ASSISTANT_DIRECT_PORT_KEY, "11434") or "11434"
    try:
        port = int(raw)
    except ValueError:
        return 11434
    return port if 1 <= port <= 65535 else 11434


def set_assistant_direct_port(session: Session, port: int) -> int:
    p = int(port)
    if not 1 <= p <= 65535:
        raise ValueError("Port 1–65535 olmalı")
    _set(session, ASSISTANT_DIRECT_PORT_KEY, str(p))
    return p


def get_assistant_model(session: Session) -> str:
    return _get(session, ASSISTANT_MODEL_KEY)


def set_assistant_model(session: Session, model: str) -> str:
    cleaned = (model or "").strip()
    if len(cleaned) > 128:
        raise ValueError("Model adı çok uzun")
    return _set(session, ASSISTANT_MODEL_KEY, cleaned)
