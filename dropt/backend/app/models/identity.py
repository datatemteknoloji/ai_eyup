from typing import Optional

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class IdentityConfig(SQLModel, table=True):
    """Singleton portal identity settings (id=1)."""

    __tablename__ = "identity_config"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Active Directory / LDAP
    ad_enabled: bool = Field(default=False)
    ad_ldap_url: str = Field(default="", max_length=512)  # derived / legacy
    ad_host: str = Field(default="", max_length=255)
    ad_port: int = Field(default=636, ge=1, le=65535)
    ad_use_ssl: bool = Field(default=True)
    ad_tls_verify: bool = Field(default=False)
    ad_ca_cert_pem: str = Field(default="", sa_column=Column(Text, default="", nullable=False))
    ad_domain: str = Field(default="", max_length=255)
    ad_base_dn: str = Field(default="", max_length=512)
    ad_bind_dn: str = Field(default="", max_length=512)
    ad_bind_password_enc: str = Field(default="", max_length=1024)
    ad_user_filter: str = Field(
        default="(|(sAMAccountName={username})(userPrincipalName={username}))",
        max_length=512,
    )
    ad_admin_group: str = Field(default="", max_length=512)
    ad_operator_group: str = Field(default="", max_length=512)

    # SSO — Kerberos (primary)
    sso_enabled: bool = Field(default=False)
    sso_mode: str = Field(default="kerberos", max_length=32)  # kerberos | oidc
    kerberos_realm: str = Field(default="", max_length=255)
    kerberos_spn: str = Field(default="", max_length=512)
    kerberos_keytab_path: str = Field(default="", max_length=512)

    # SSO — OIDC (advanced)
    sso_issuer: str = Field(default="", max_length=512)
    sso_client_id: str = Field(default="", max_length=255)
    sso_client_secret_enc: str = Field(default="", max_length=1024)
    sso_redirect_uri: str = Field(default="", max_length=512)
    sso_scopes: str = Field(default="openid profile email", max_length=255)
    sso_admin_group: str = Field(default="", max_length=512)
    sso_operator_group: str = Field(default="", max_length=512)
    sso_frontend_redirect: str = Field(default="http://localhost:3000/", max_length=512)
