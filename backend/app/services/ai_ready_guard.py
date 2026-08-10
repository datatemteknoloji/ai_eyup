"""AI Ready auth-fail backoff helpers (account lockout koruması)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm.attributes import flag_modified

AUTH_FAIL_UNTIL_KEY = "ai_ready_auth_fail_until"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def parse_auth_fail_until(raw: Any) -> Optional[datetime]:
    if raw is None or raw is False or raw == "":
        return None
    if isinstance(raw, datetime):
        return _as_aware(raw)
    try:
        text = str(raw).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return _as_aware(datetime.fromisoformat(text))
    except Exception:
        return None


def get_auth_fail_until(connection_config: Optional[dict]) -> Optional[datetime]:
    cfg = connection_config if isinstance(connection_config, dict) else {}
    return parse_auth_fail_until(cfg.get(AUTH_FAIL_UNTIL_KEY))


def is_auth_fail_backoff_active(
    connection_config: Optional[dict],
    *,
    now: Optional[datetime] = None,
) -> bool:
    until = get_auth_fail_until(connection_config)
    if until is None:
        return False
    now = now or _utc_now()
    return until > now


def set_auth_fail_backoff(server, *, backoff_sec: int, now: Optional[datetime] = None) -> None:
    """SSH/WinRM AI Ready başarısız → arka plan yeniden denemeyi ertele."""
    now = now or _utc_now()
    until = now + timedelta(seconds=max(60, int(backoff_sec)))
    cfg = dict(server.connection_config or {})
    cfg[AUTH_FAIL_UNTIL_KEY] = until.isoformat()
    server.connection_config = cfg
    flag_modified(server, "connection_config")


def clear_auth_fail_backoff(server) -> None:
    cfg = dict(server.connection_config or {})
    if AUTH_FAIL_UNTIL_KEY not in cfg:
        return
    cfg.pop(AUTH_FAIL_UNTIL_KEY, None)
    server.connection_config = cfg
    flag_modified(server, "connection_config")
