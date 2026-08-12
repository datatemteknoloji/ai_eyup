"""
SECRET_KEY rotasyonu — Fernet ile şifrelenmiş alanları old→new yeniden şifreler.

JWT oturumları yeni key ile geçersiz olur (yeniden login gerekir).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger(__name__)

_JSON_SECRET_KEYS = ("password", "private_key", "sudo_password", "token", "api_key")


def fernet_from_secret(secret_key: str) -> Fernet:
    derived = hashlib.sha256((secret_key or "").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def _decrypt_with(f: Fernet, value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    try:
        return f.decrypt(value.encode()).decode()
    except (InvalidToken, Exception):
        # Legacy plaintext
        return value


def _encrypt_with(f: Fernet, value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    return f.encrypt(value.encode()).decode()


def reencrypt_value(old_f: Fernet, new_f: Fernet, value: Optional[str]) -> Tuple[Optional[str], bool]:
    """(new_value, changed)."""
    if not value:
        return value, False
    plain = _decrypt_with(old_f, value)
    if plain is None:
        return value, False
    new_v = _encrypt_with(new_f, plain)
    return new_v, new_v != value


def reencrypt_mapping(old_f: Fernet, new_f: Fernet, data: Optional[dict]) -> Tuple[dict, int]:
    if not isinstance(data, dict):
        return data or {}, 0
    out = dict(data)
    n = 0
    for k in _JSON_SECRET_KEYS:
        if k in out and out[k]:
            nv, ch = reencrypt_value(old_f, new_f, str(out[k]))
            if ch:
                out[k] = nv
                n += 1
    return out, n


def rotate_secret_key(db: Session, old_key: str, new_key: str) -> Dict[str, Any]:
    """
    Tüm bilinen Fernet alanlarını yeniden şifrele.
    Caller: commit + .env güncelle + process restart.
    """
    if not old_key or not new_key:
        raise ValueError("old_key ve new_key zorunlu")
    if old_key == new_key:
        raise ValueError("Yeni SECRET_KEY eskisiyle aynı olamaz")

    old_f = fernet_from_secret(old_key)
    new_f = fernet_from_secret(new_key)
    stats: Dict[str, Any] = {"fields": 0, "rows": 0, "details": {}}

    def bump(section: str, fields: int, rows: int = 1) -> None:
        stats["fields"] += fields
        stats["rows"] += rows if fields else 0
        d = stats["details"].setdefault(section, {"fields": 0, "rows": 0})
        d["fields"] += fields
        d["rows"] += rows if fields else 0

    # GlobalCredential
    from app.models.credential import GlobalCredential
    for c in db.query(GlobalCredential).all():
        n = 0
        for attr in ("password", "private_key", "sudo_password"):
            val = getattr(c, attr, None)
            nv, ch = reencrypt_value(old_f, new_f, val)
            if ch:
                setattr(c, attr, nv)
                n += 1
        if n:
            bump("global_credentials", n)

    # Servers.connection_config
    from app.models.server import Server
    for s in db.query(Server).all():
        cc = s.connection_config
        if not isinstance(cc, dict):
            continue
        new_cc, n = reencrypt_mapping(old_f, new_f, cc)
        # nested winrm
        if isinstance(new_cc.get("winrm"), dict):
            w, nw = reencrypt_mapping(old_f, new_f, new_cc["winrm"])
            if nw:
                new_cc["winrm"] = w
                n += nw
        if n:
            s.connection_config = new_cc
            flag_modified(s, "connection_config")
            bump("servers", n)

    # Hypervisors
    from app.models.hypervisor import Hypervisor
    for hv in db.query(Hypervisor).all():
        n = 0
        nv, ch = reencrypt_value(old_f, new_f, hv.password)
        if ch:
            hv.password = nv
            n += 1
        cc = hv.connection_config if isinstance(hv.connection_config, dict) else {}
        new_cc, nc = reencrypt_mapping(old_f, new_f, cc)
        if nc:
            hv.connection_config = new_cc
            flag_modified(hv, "connection_config")
            n += nc
        if n:
            bump("hypervisors", n)

    # OpenShift clusters
    try:
        from app.models.openshift import OpenShiftCluster
        for oc in db.query(OpenShiftCluster).all():
            cc = oc.connection_config if isinstance(oc.connection_config, dict) else {}
            new_cc, n = reencrypt_mapping(old_f, new_f, cc)
            if n:
                oc.connection_config = new_cc
                flag_modified(oc, "connection_config")
                bump("openshift", n)
    except Exception as e:
        logger.warning("openshift rotate skip: %s", e)

    # AppSettings sensitive
    from app.models.app_settings import AppSettings
    for row in db.query(AppSettings).filter(
        AppSettings.key.in_(["remote_llm_api_key", "remote_llm_virtual_key", "global_winrm_credential"])
    ).all():
        if not row.value:
            continue
        if row.key in ("remote_llm_api_key", "remote_llm_virtual_key"):
            nv, ch = reencrypt_value(old_f, new_f, row.value)
            if ch:
                row.value = nv
                bump("app_settings", 1)
        elif row.key == "global_winrm_credential":
            try:
                obj = json.loads(row.value)
            except Exception:
                continue
            if isinstance(obj, dict) and obj.get("password"):
                nv, ch = reencrypt_value(old_f, new_f, str(obj["password"]))
                if ch:
                    obj = dict(obj)
                    obj["password"] = nv
                    row.value = json.dumps(obj, ensure_ascii=False)
                    bump("app_settings", 1)

    # Identity
    try:
        from app.models.identity import IdentityConfig
        for cfg in db.query(IdentityConfig).all():
            n = 0
            for attr in ("ad_bind_password_enc", "sso_client_secret_enc"):
                val = getattr(cfg, attr, None) or ""
                if not val:
                    continue
                nv, ch = reencrypt_value(old_f, new_f, val)
                if ch:
                    setattr(cfg, attr, nv)
                    n += 1
            if n:
                bump("identity", n)
    except Exception as e:
        logger.warning("identity rotate skip: %s", e)

    # MFA TOTP
    try:
        from app.models.security import UserMfa
        for m in db.query(UserMfa).all():
            val = m.totp_secret_enc or ""
            if not val:
                continue
            nv, ch = reencrypt_value(old_f, new_f, val)
            if ch:
                m.totp_secret_enc = nv
                bump("mfa", 1)
    except Exception as e:
        logger.warning("mfa rotate skip: %s", e)

    # Repo / system update — plaintext olabilir; Fernet görünüyorsa çevir
    try:
        from app.models.repository import RepoSource
        for r in db.query(RepoSource).all():
            n = 0
            for attr in ("password", "mirror_password"):
                val = getattr(r, attr, None)
                if not val:
                    continue
                if str(val).startswith("gAAAA"):
                    nv, ch = reencrypt_value(old_f, new_f, val)
                    if ch:
                        setattr(r, attr, nv)
                        n += 1
            if n:
                bump("repositories", n)
    except Exception as e:
        logger.warning("repositories rotate skip: %s", e)

    try:
        from app.models.system_update import SystemUpdatePlan
        for p in db.query(SystemUpdatePlan).all():
            n = 0
            for attr in ("override_password", "override_sudo_password"):
                val = getattr(p, attr, None)
                if not val:
                    continue
                if str(val).startswith("gAAAA"):
                    nv, ch = reencrypt_value(old_f, new_f, val)
                    if ch:
                        setattr(p, attr, nv)
                        n += 1
            if n:
                bump("system_updates", n)
    except Exception as e:
        logger.warning("system_updates rotate skip: %s", e)

    db.flush()
    from app.services.secret_policy import secret_key_fingerprint
    stats["old_fingerprint"] = secret_key_fingerprint(old_key)
    stats["new_fingerprint"] = secret_key_fingerprint(new_key)
    return stats


def apply_runtime_secret_key(new_key: str) -> None:
    """Process içi SECRET_KEY + Fernet cache yenile (restart öncesi test için)."""
    import os
    from app.core import encryption
    from app.core.config import settings

    os.environ["SECRET_KEY"] = new_key
    settings.SECRET_KEY = new_key
    encryption._fernet.cache_clear()
