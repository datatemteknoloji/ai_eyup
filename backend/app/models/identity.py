"""Uygulama geneli kimlik yapılandırması (singleton id=1)."""
from sqlalchemy import Boolean, Column, Integer, String, Text

from app.core.database import Base


class IdentityConfig(Base):
    __tablename__ = "identity_config"

    id = Column(Integer, primary_key=True, default=1)

    ad_enabled = Column(Boolean, default=False, nullable=False)
    ad_host = Column(String(255), default="", nullable=False)
    ad_port = Column(Integer, default=636, nullable=False)
    ad_use_ssl = Column(Boolean, default=True, nullable=False)
    ad_tls_verify = Column(Boolean, default=False, nullable=False)
    ad_ca_cert_pem = Column(Text, default="", nullable=False)
    ad_domain = Column(String(255), default="", nullable=False)
    ad_base_dn = Column(String(512), default="", nullable=False)
    ad_bind_dn = Column(String(512), default="", nullable=False)
    ad_bind_password_enc = Column(String(1024), default="", nullable=False)
    ad_user_filter = Column(
        String(512),
        default="(|(sAMAccountName={username})(userPrincipalName={username}))",
        nullable=False,
    )
    ad_admin_group = Column(String(512), default="", nullable=False)
    ad_operator_group = Column(String(512), default="", nullable=False)
    ad_viewer_group = Column(String(512), default="", nullable=False)
    # Sync dışı geçerli AD login → otomatik kullanıcı oluştur
    ad_jit_enabled = Column(Boolean, default=True, nullable=False)

    sso_enabled = Column(Boolean, default=False, nullable=False)
    sso_mode = Column(String(32), default="oidc", nullable=False)
    sso_issuer = Column(String(512), default="", nullable=False)
    sso_client_id = Column(String(255), default="", nullable=False)
    sso_client_secret_enc = Column(String(1024), default="", nullable=False)
    sso_redirect_uri = Column(String(512), default="", nullable=False)
    sso_scopes = Column(String(255), default="openid profile email", nullable=False)
    sso_admin_group = Column(String(512), default="", nullable=False)
    sso_operator_group = Column(String(512), default="", nullable=False)
    sso_viewer_group = Column(String(512), default="", nullable=False)
    sso_frontend_redirect = Column(String(512), default="/", nullable=False)
