"""
SSH kimlik bilgisi çözümleme — terminal, AI Ready ve bulk testlerde aynı mantık.

Öncelik:
  1) Sunucu connection_config (username / password / key / port)
  2) Yoksa varsayılan GlobalCredential
"""
from __future__ import annotations

from typing import Any, Optional

from app.core.encryption import decrypt_secret


def resolve_ssh_creds(
    server: Any = None,
    *,
    global_cred: Any = None,
    cfg: Optional[dict] = None,
    ip: Optional[str] = None,
    name: Optional[str] = None,
) -> dict:
    """SSHManager / connect_ssh için düz metin kimlik bilgisi dict'i döner."""
    cfg = dict(cfg or (getattr(server, "connection_config", None) or {}))
    gc = global_cred

    raw_pw = cfg.get("password") or (getattr(gc, "password", None) if gc else None)
    raw_key = cfg.get("private_key") or (getattr(gc, "private_key", None) if gc else None)
    raw_sudo = cfg.get("sudo_password") or (getattr(gc, "sudo_password", None) if gc else None)

    host = (ip or getattr(server, "ip_address", None) or "").strip()
    username = (
        cfg.get("username")
        or (getattr(gc, "username", None) if gc else None)
        or "root"
    )
    try:
        port = int(cfg.get("port") or (getattr(gc, "port", None) if gc else None) or 22)
    except Exception:
        port = 22

    password = decrypt_secret(raw_pw) if raw_pw else None
    private_key = decrypt_secret(raw_key) if raw_key else None
    sudo_password = decrypt_secret(raw_sudo) if raw_sudo else None

    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "private_key": private_key,
        "sudo_password": sudo_password or password,
        "has_secret": bool(password or private_key),
        "name": name or getattr(server, "name", None) or host,
    }
