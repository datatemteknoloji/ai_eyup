from collections.abc import Generator

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    """Add columns/enums introduced after first boot (no Alembic in early slices)."""
    statements = [
        "ALTER TABLE target_servers ADD COLUMN IF NOT EXISTS last_connection_message VARCHAR(1024) DEFAULT ''",
        "ALTER TABLE target_servers ADD COLUMN IF NOT EXISTS ssh_key_installed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE target_servers ADD COLUMN IF NOT EXISTS os_pretty VARCHAR(255) DEFAULT ''",
        "ALTER TABLE target_servers ADD COLUMN IF NOT EXISTS machine_type VARCHAR(32) DEFAULT ''",
        "ALTER TABLE target_servers ADD COLUMN IF NOT EXISTS virtualization VARCHAR(64) DEFAULT ''",
        "ALTER TABLE pkg_local_repos ADD COLUMN IF NOT EXISTS source_type VARCHAR(32) DEFAULT 'nfs'",
        "ALTER TABLE pkg_local_repos ADD COLUMN IF NOT EXISTS portal_path VARCHAR(512) DEFAULT ''",
        "ALTER TABLE pkg_local_repos ADD COLUMN IF NOT EXISTS file_glob VARCHAR(128) DEFAULT '*.rpm'",
        "ALTER TABLE identity_config ADD COLUMN IF NOT EXISTS ad_host VARCHAR(255) DEFAULT ''",
        "ALTER TABLE identity_config ADD COLUMN IF NOT EXISTS ad_port INTEGER DEFAULT 636",
        "ALTER TABLE identity_config ADD COLUMN IF NOT EXISTS ad_use_ssl BOOLEAN DEFAULT TRUE",
        "ALTER TABLE identity_config ADD COLUMN IF NOT EXISTS ad_tls_verify BOOLEAN DEFAULT FALSE",
        "ALTER TABLE identity_config ADD COLUMN IF NOT EXISTS ad_ca_cert_pem TEXT DEFAULT ''",
        "ALTER TABLE identity_config ADD COLUMN IF NOT EXISTS sso_mode VARCHAR(32) DEFAULT 'kerberos'",
        "ALTER TABLE identity_config ADD COLUMN IF NOT EXISTS kerberos_realm VARCHAR(255) DEFAULT ''",
        "ALTER TABLE identity_config ADD COLUMN IF NOT EXISTS kerberos_spn VARCHAR(512) DEFAULT ''",
        "ALTER TABLE identity_config ADD COLUMN IF NOT EXISTS kerberos_keytab_path VARCHAR(512) DEFAULT ''",
        "DO $$ BEGIN ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'none'; EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN ALTER TYPE serverstatus ADD VALUE IF NOT EXISTS 'unreachable'; EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS theme VARCHAR(16) DEFAULT 'dark'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS locale VARCHAR(8) DEFAULT 'tr'",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception:
                # identity_config may not exist yet on first boot before create_all order
                pass


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
