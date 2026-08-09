"""IdentityConfig singleton helpers."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.encryption import decrypt_secret, encrypt_secret
from app.models.identity import IdentityConfig


def get_or_create_identity(db: Session) -> IdentityConfig:
    row = db.query(IdentityConfig).filter(IdentityConfig.id == 1).first()
    if row is None:
        row = IdentityConfig(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def decrypt_ad_bind_password(cfg: IdentityConfig) -> str:
    return decrypt_secret(cfg.ad_bind_password_enc) or ""


def decrypt_sso_client_secret(cfg: IdentityConfig) -> str:
    return decrypt_secret(cfg.sso_client_secret_enc) or ""


def build_ldap_url(*, host: str, port: int, use_ssl: bool) -> str:
    scheme = "ldaps" if use_ssl else "ldap"
    return f"{scheme}://{host}:{port}"


def identity_public(cfg: IdentityConfig) -> dict:
    return {
        "ad_enabled": bool(cfg.ad_enabled),
        "ad_host": cfg.ad_host or "",
        "ad_port": int(cfg.ad_port or 636),
        "ad_use_ssl": bool(cfg.ad_use_ssl),
        "ad_tls_verify": bool(cfg.ad_tls_verify),
        "ad_ca_cert_configured": bool((cfg.ad_ca_cert_pem or "").strip()),
        "ad_domain": cfg.ad_domain or "",
        "ad_base_dn": cfg.ad_base_dn or "",
        "ad_bind_dn": cfg.ad_bind_dn or "",
        "ad_bind_password_set": bool((cfg.ad_bind_password_enc or "").strip()),
        "ad_user_filter": cfg.ad_user_filter
        or "(|(sAMAccountName={username})(userPrincipalName={username}))",
        "ad_admin_group": cfg.ad_admin_group or "",
        "ad_operator_group": cfg.ad_operator_group or "",
        "ad_viewer_group": cfg.ad_viewer_group or "",
        "ad_jit_enabled": bool(cfg.ad_jit_enabled),
        "sso_enabled": bool(cfg.sso_enabled),
        "sso_mode": cfg.sso_mode or "oidc",
        "sso_issuer": cfg.sso_issuer or "",
        "sso_client_id": cfg.sso_client_id or "",
        "sso_client_secret_set": bool((cfg.sso_client_secret_enc or "").strip()),
        "sso_redirect_uri": cfg.sso_redirect_uri or "",
        "sso_scopes": cfg.sso_scopes or "openid profile email",
        "sso_admin_group": cfg.sso_admin_group or "",
        "sso_operator_group": cfg.sso_operator_group or "",
        "sso_viewer_group": cfg.sso_viewer_group or "",
        "sso_frontend_redirect": cfg.sso_frontend_redirect or "/",
    }


def apply_identity_update(db: Session, cfg: IdentityConfig, data: dict) -> IdentityConfig:
    bool_fields = (
        "ad_enabled", "ad_use_ssl", "ad_tls_verify", "ad_jit_enabled", "sso_enabled",
    )
    str_fields = (
        "ad_host", "ad_domain", "ad_base_dn", "ad_bind_dn", "ad_user_filter",
        "ad_admin_group", "ad_operator_group", "ad_viewer_group",
        "sso_mode", "sso_issuer", "sso_client_id", "sso_redirect_uri", "sso_scopes",
        "sso_admin_group", "sso_operator_group", "sso_viewer_group", "sso_frontend_redirect",
    )
    for k in bool_fields:
        if k in data and data[k] is not None:
            setattr(cfg, k, bool(data[k]))
    for k in str_fields:
        if k in data and data[k] is not None:
            setattr(cfg, k, str(data[k]))
    if "ad_port" in data and data["ad_port"] is not None:
        cfg.ad_port = max(1, min(65535, int(data["ad_port"])))
    if "ad_ca_cert_pem" in data and data["ad_ca_cert_pem"] is not None:
        cfg.ad_ca_cert_pem = str(data["ad_ca_cert_pem"])
    if data.get("ad_clear_ca"):
        cfg.ad_ca_cert_pem = ""
    if data.get("ad_bind_password"):
        cfg.ad_bind_password_enc = encrypt_secret(str(data["ad_bind_password"])) or ""
    if data.get("sso_client_secret"):
        cfg.sso_client_secret_enc = encrypt_secret(str(data["sso_client_secret"])) or ""
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg
