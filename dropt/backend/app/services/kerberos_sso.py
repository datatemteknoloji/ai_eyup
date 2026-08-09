"""Kerberos / keytab helpers for portal SSO."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.models.identity import IdentityConfig

KEYTAB_DIR = Path(os.environ.get("PORTAL_KEYTAB_DIR", "/keytabs"))


def ensure_keytab_dir() -> Path:
    KEYTAB_DIR.mkdir(parents=True, exist_ok=True)
    return KEYTAB_DIR


def keytab_status(cfg: IdentityConfig) -> dict:
    path = (cfg.kerberos_keytab_path or "").strip()
    uploaded = bool(path) and Path(path).is_file()
    size = Path(path).stat().st_size if uploaded else 0
    return {
        "uploaded": uploaded,
        "path": path if uploaded else "",
        "size": size,
    }


def save_keytab_bytes(data: bytes, filename: str = "portal.keytab") -> str:
    ensure_keytab_dir()
    safe = "".join(c for c in filename if c.isalnum() or c in "._-") or "portal.keytab"
    if not safe.endswith(".keytab"):
        safe += ".keytab"
    dest = KEYTAB_DIR / safe
    dest.write_bytes(data)
    os.chmod(dest, 0o600)
    return str(dest)


def test_kerberos_config(cfg: IdentityConfig) -> tuple[bool, str]:
    if not (cfg.kerberos_realm or "").strip():
        return False, "Kerberos Realm gerekli"
    if not (cfg.kerberos_spn or "").strip():
        return False, "SPN gerekli"
    st = keytab_status(cfg)
    if not st["uploaded"]:
        return False, "Keytab yüklenmemiş"
    path = st["path"]
    # Prefer klist if available
    try:
        proc = subprocess.run(
            ["klist", "-k", path],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if proc.returncode == 0:
            return True, f"Keytab OK · {cfg.kerberos_spn} @ {cfg.kerberos_realm}"
        return False, f"klist başarısız: {(proc.stderr or proc.stdout or '')[:300]}"
    except FileNotFoundError:
        # No krb5 tools — accept file presence for lab
        return True, f"Keytab dosyası mevcut ({st['size']} byte). klist yok — SPN/Realm kaydedildi."
    except Exception as exc:  # noqa: BLE001
        return False, f"Keytab test hatası: {exc}"


def try_accept_negotiate(cfg: IdentityConfig, token_b64: str) -> str | None:
    """
    Accept SPNEGO token; return client username (short) or None.
    Requires pyspnego/gssapi + valid keytab in environment.
    """
    if not token_b64 or not keytab_status(cfg)["uploaded"]:
        return None
    keytab = cfg.kerberos_keytab_path
    spn = (cfg.kerberos_spn or "").strip()
    realm = (cfg.kerberos_realm or "").strip().upper()
    os.environ["KRB5_KTNAME"] = keytab
    try:
        import spnego

        ctx = spnego.server(
            hostname=spn.split("/", 1)[-1].split("@", 1)[0] if "/" in spn else None,
            service=spn.split("/", 1)[0] if "/" in spn else "HTTP",
            protocol="kerberos",
        )
        import base64

        in_token = base64.b64decode(token_b64)
        _out = ctx.step(in_token)
        # client principal
        client = getattr(ctx, "client_principal", None) or getattr(ctx, "_context", None)
        principal = None
        if isinstance(client, str):
            principal = client
        else:
            principal = str(getattr(ctx, "client_principal", "") or "")
        if not principal:
            # pyspnego: ctx.client_principal after accept
            principal = getattr(ctx, "client_principal", None)
        if not principal:
            return None
        name = str(principal)
        if "@" in name:
            name = name.split("@", 1)[0]
        if name.upper().endswith("$"):
            return None
        return name
    except Exception:
        return None
