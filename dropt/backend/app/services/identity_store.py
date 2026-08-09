"""Load / save singleton IdentityConfig."""

from __future__ import annotations

from urllib.parse import urlparse

from sqlmodel import Session, select

from app.models.identity import IdentityConfig
from app.schemas.identity import IdentityPublic, IdentityUpdate
from app.services.credential_manager import CredentialCryptoError, CredentialManager


def build_ldap_url(*, host: str, port: int, use_ssl: bool) -> str:
    host = (host or "").strip()
    if not host:
        return ""
    scheme = "ldaps" if use_ssl else "ldap"
    return f"{scheme}://{host}:{port}"


def sync_ldap_url_from_parts(cfg: IdentityConfig) -> None:
    """Keep ad_ldap_url in sync with host/port/ssl (or parse legacy URL into parts)."""
    if (cfg.ad_host or "").strip():
        cfg.ad_ldap_url = build_ldap_url(
            host=cfg.ad_host,
            port=int(cfg.ad_port or (636 if cfg.ad_use_ssl else 389)),
            use_ssl=bool(cfg.ad_use_ssl),
        )
        return
    # Legacy: only URL filled — parse into parts once
    url = (cfg.ad_ldap_url or "").strip()
    if not url:
        return
    parsed = urlparse(url if "://" in url else f"ldaps://{url}")
    if parsed.hostname:
        cfg.ad_host = parsed.hostname
        cfg.ad_use_ssl = (parsed.scheme or "ldaps").lower() == "ldaps"
        cfg.ad_port = parsed.port or (636 if cfg.ad_use_ssl else 389)
        cfg.ad_ldap_url = build_ldap_url(host=cfg.ad_host, port=cfg.ad_port, use_ssl=cfg.ad_use_ssl)


def get_or_create_identity(session: Session) -> IdentityConfig:
    row = session.exec(select(IdentityConfig).where(IdentityConfig.id == 1)).first()
    if row is None:
        row = session.exec(select(IdentityConfig)).first()
    if row is None:
        row = IdentityConfig(id=1)
        session.add(row)
        session.commit()
        session.refresh(row)
    # Backfill host/port from legacy URL if needed
    if not (row.ad_host or "").strip() and (row.ad_ldap_url or "").strip():
        sync_ldap_url_from_parts(row)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


from app.services.kerberos_sso import keytab_status


def identity_public(cfg: IdentityConfig) -> IdentityPublic:
    sync_ldap_url_from_parts(cfg)
    kt = keytab_status(cfg)
    return IdentityPublic(
        ad_enabled=bool(cfg.ad_enabled),
        ad_ldap_url=cfg.ad_ldap_url or "",
        ad_host=cfg.ad_host or "",
        ad_port=int(cfg.ad_port or 636),
        ad_use_ssl=bool(cfg.ad_use_ssl),
        ad_tls_verify=bool(cfg.ad_tls_verify),
        ad_ca_cert_set=bool((cfg.ad_ca_cert_pem or "").strip()),
        ad_ca_cert_pem="",
        ad_domain=cfg.ad_domain or "",
        ad_base_dn=cfg.ad_base_dn or "",
        ad_bind_dn=cfg.ad_bind_dn or "",
        ad_bind_password_set=bool(cfg.ad_bind_password_enc),
        ad_user_filter=cfg.ad_user_filter or "",
        ad_admin_group=cfg.ad_admin_group or "",
        ad_operator_group=cfg.ad_operator_group or "",
        sso_enabled=bool(cfg.sso_enabled),
        sso_mode=(cfg.sso_mode or "kerberos"),
        kerberos_realm=cfg.kerberos_realm or "",
        kerberos_spn=cfg.kerberos_spn or "",
        kerberos_keytab_uploaded=bool(kt["uploaded"]),
        kerberos_keytab_path=kt["path"] if kt["uploaded"] else "",
        sso_issuer=cfg.sso_issuer or "",
        sso_client_id=cfg.sso_client_id or "",
        sso_client_secret_set=bool(cfg.sso_client_secret_enc),
        sso_redirect_uri=cfg.sso_redirect_uri or "",
        sso_scopes=cfg.sso_scopes or "openid profile email",
        sso_admin_group=cfg.sso_admin_group or "",
        sso_operator_group=cfg.sso_operator_group or "",
        sso_frontend_redirect=cfg.sso_frontend_redirect or "",
    )


def apply_identity_update(session: Session, body: IdentityUpdate) -> IdentityConfig:
    cfg = get_or_create_identity(session)
    crypto = CredentialManager()
    data = body.model_dump(exclude_unset=True)

    secret_fields = {
        "ad_bind_password": "ad_bind_password_enc",
        "sso_client_secret": "sso_client_secret_enc",
    }
    for plain_key, enc_key in secret_fields.items():
        if plain_key in data:
            plain = data.pop(plain_key)
            if plain is None or plain == "":
                continue
            setattr(cfg, enc_key, crypto.encrypt(plain))

    if "ad_ca_cert_pem" in data:
        pem = data.pop("ad_ca_cert_pem")
        if pem is None:
            pass
        else:
            cfg.ad_ca_cert_pem = str(pem).strip()

    for key, value in data.items():
        if hasattr(cfg, key) and value is not None:
            setattr(cfg, key, value.strip() if isinstance(value, str) else value)

    sync_ldap_url_from_parts(cfg)
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    return cfg


def decrypt_ad_bind_password(cfg: IdentityConfig) -> str | None:
    if not cfg.ad_bind_password_enc:
        return None
    try:
        return CredentialManager().decrypt(cfg.ad_bind_password_enc)
    except CredentialCryptoError:
        return None


def decrypt_sso_client_secret(cfg: IdentityConfig) -> str | None:
    if not cfg.sso_client_secret_enc:
        return None
    try:
        return CredentialManager().decrypt(cfg.sso_client_secret_enc)
    except CredentialCryptoError:
        return None
