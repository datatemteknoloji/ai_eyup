from typing import Optional

from pydantic import BaseModel, Field


class IdentityPublic(BaseModel):
    ad_enabled: bool = False
    ad_ldap_url: str = ""
    ad_host: str = ""
    ad_port: int = 636
    ad_use_ssl: bool = True
    ad_tls_verify: bool = False
    ad_ca_cert_set: bool = False
    ad_ca_cert_pem: str = ""
    ad_domain: str = ""
    ad_base_dn: str = ""
    ad_bind_dn: str = ""
    ad_bind_password_set: bool = False
    ad_user_filter: str = ""
    ad_admin_group: str = ""
    ad_operator_group: str = ""

    sso_enabled: bool = False
    sso_mode: str = "kerberos"
    kerberos_realm: str = ""
    kerberos_spn: str = ""
    kerberos_keytab_uploaded: bool = False
    kerberos_keytab_path: str = ""

    sso_issuer: str = ""
    sso_client_id: str = ""
    sso_client_secret_set: bool = False
    sso_redirect_uri: str = ""
    sso_scopes: str = "openid profile email"
    sso_admin_group: str = ""
    sso_operator_group: str = ""
    sso_frontend_redirect: str = ""


class IdentityUpdate(BaseModel):
    ad_enabled: Optional[bool] = None
    ad_ldap_url: Optional[str] = Field(default=None, max_length=512)
    ad_host: Optional[str] = Field(default=None, max_length=255)
    ad_port: Optional[int] = Field(default=None, ge=1, le=65535)
    ad_use_ssl: Optional[bool] = None
    ad_tls_verify: Optional[bool] = None
    ad_ca_cert_pem: Optional[str] = None
    ad_domain: Optional[str] = Field(default=None, max_length=255)
    ad_base_dn: Optional[str] = Field(default=None, max_length=512)
    ad_bind_dn: Optional[str] = Field(default=None, max_length=512)
    ad_bind_password: Optional[str] = Field(default=None, max_length=512)
    ad_user_filter: Optional[str] = Field(default=None, max_length=512)
    ad_admin_group: Optional[str] = Field(default=None, max_length=512)
    ad_operator_group: Optional[str] = Field(default=None, max_length=512)

    sso_enabled: Optional[bool] = None
    sso_mode: Optional[str] = Field(default=None, max_length=32)
    kerberos_realm: Optional[str] = Field(default=None, max_length=255)
    kerberos_spn: Optional[str] = Field(default=None, max_length=512)

    sso_issuer: Optional[str] = Field(default=None, max_length=512)
    sso_client_id: Optional[str] = Field(default=None, max_length=255)
    sso_client_secret: Optional[str] = Field(default=None, max_length=512)
    sso_redirect_uri: Optional[str] = Field(default=None, max_length=512)
    sso_scopes: Optional[str] = Field(default=None, max_length=255)
    sso_admin_group: Optional[str] = Field(default=None, max_length=512)
    sso_operator_group: Optional[str] = Field(default=None, max_length=512)
    sso_frontend_redirect: Optional[str] = Field(default=None, max_length=512)


class AdTestRequest(BaseModel):
    username: Optional[str] = Field(default=None, max_length=128)
    password: Optional[str] = Field(default=None, max_length=256)


class AdTestResponse(BaseModel):
    ok: bool
    message: str
    role: Optional[str] = None
    groups: list[str] = Field(default_factory=list)
    resolved_host: Optional[str] = None
    ldap_url: Optional[str] = None
