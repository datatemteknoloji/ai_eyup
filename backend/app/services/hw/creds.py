"""Kimlik bilgisi / meta okuma yardımcıları (parola yalnız bellekte; log'a yazılmaz)."""
from __future__ import annotations

import json
from typing import Any, Dict, Tuple

from app.core.encryption import decrypt_secret


def load_credentials(row) -> Tuple[str, str]:
    try:
        d = json.loads(decrypt_secret(row.credential_ref) or "{}") if row.credential_ref else {}
    except Exception:  # noqa: BLE001
        d = {}
    return str(d.get("username") or ""), str(d.get("password") or "")


def load_meta(row) -> Dict[str, Any]:
    try:
        return json.loads(row.meta_json) if row.meta_json else {}
    except Exception:  # noqa: BLE001
        return {}


def verify_arg(row, meta: Dict[str, Any]):
    """requests `verify`: özel CA paketi yolu varsa o, yoksa bool."""
    ca = (meta.get("ca_bundle_path") or "").strip()
    if ca and row.verify_ssl:
        return ca
    return bool(row.verify_ssl)


def base_url(endpoint: str, port: Any = None, default_port: int = 443) -> str:
    """`host`, `host:port` veya `https://host[:port]` → `https://host[:port]` (yol/sorgu atılır)."""
    e = (endpoint or "").strip()
    if not e:
        return ""
    if "://" not in e:
        e = "https://" + e
    scheme, rest = e.split("://", 1)
    host = rest.split("/", 1)[0]
    if ":" not in host.rsplit("]", 1)[-1] and port and int(port) != default_port:
        host = f"{host}:{int(port)}"
    return f"{scheme}://{host}"
