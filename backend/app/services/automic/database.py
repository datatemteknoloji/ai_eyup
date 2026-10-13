"""Automic modül veritabanı — ayrı Postgres/TimescaleDB konteyneri (:5435).

ainew ana DB'den bağımsız. Bağlantı yoksa modül devre dışı kalır,
ainew çalışmaya devam eder.
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import logging
import os
import threading
from typing import Generator, Optional
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

AutomicBase = declarative_base()

_engine = None
_session_factory = None
_thread_engine = None
_thread_session_factory = None
_schema_ready = False
_schema_lock = threading.Lock()


def _get_url() -> str:
    url = os.environ.get("AUTOMIC_DATABASE_URL", "").strip()
    if url:
        return url
    user = os.environ.get("AUTOMIC_DB_USER", "automic")
    pwd = os.environ.get("AUTOMIC_DB_PASSWORD", "")
    host = os.environ.get("AUTOMIC_DB_HOST", "localhost")
    port = os.environ.get("AUTOMIC_DB_PORT", "5435")
    name = os.environ.get("AUTOMIC_DB_NAME", "automic")
    return f"postgresql://{quote_plus(user)}:{quote_plus(pwd)}@{host}:{port}/{name}"


def _ensure_engine():
    global _engine, _session_factory
    if _engine is not None:
        return
    _engine = create_engine(
        _get_url(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_timeout=15,
        pool_recycle=1800,
        connect_args={"connect_timeout": 5},
    )
    _session_factory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _ensure_thread_engine():
    global _thread_engine, _thread_session_factory
    if _thread_engine is not None:
        return
    _thread_engine = create_engine(_get_url(), poolclass=NullPool, connect_args={"connect_timeout": 5})
    _thread_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=_thread_engine)


def get_engine():
    _ensure_engine()
    return _engine


def get_automic_db() -> Generator[Session, None, None]:
    """FastAPI dependency — Automic modül DB session."""
    _ensure_engine()
    ensure_schema()
    db = _session_factory()
    try:
        yield db
    finally:
        db.close()


def get_automic_thread_session() -> Optional[Session]:
    """Arka plan iş parçacıkları için session (NullPool)."""
    try:
        _ensure_thread_engine()
        ensure_schema()
        return _thread_session_factory()
    except Exception as exc:
        logger.warning("Automic DB session açılamadı: %s", exc)
        return None


_avail_cache = {"at": 0.0, "ok": False}


def automic_db_available(cache_sec: float = 30.0) -> bool:
    import time as _time

    now = _time.monotonic()
    if cache_sec and now - _avail_cache["at"] < cache_sec:
        return _avail_cache["ok"]
    try:
        _ensure_engine()
        with _engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        ok = True
    except Exception:
        ok = False
    _avail_cache.update(at=now, ok=ok)
    return ok


_HYPERTABLES = (
    # (tablo, zaman kolonu, chunk aralığı, compress_segmentby, compress_orderby)
    ("automic_executions", "activation_time", "1 day", "system_id, client", "activation_time DESC"),
    ("automic_report_excerpts", "end_time", "1 day", None, None),
    ("automic_failed_index", "day", "1 month", None, None),
    ("automic_daily_aggregates", "day", "1 month", "system_id, client", "day DESC"),
)


# create_all mevcut tabloya kolon eklemez; sonradan eklenen (nullable) kolonlar için idempotent ALTER.
_ADD_COLUMNS = (
    ("automic_executions", "run_time_sec", "INTEGER"),
    ("automic_executions", "ert_sec", "INTEGER"),
    ("automic_active", "top_run_id", "BIGINT"),
    ("automic_active", "folder", "VARCHAR(400)"),
    ("automic_active", "platform", "VARCHAR(32)"),
    ("automic_active", "queue", "VARCHAR(200)"),
    ("automic_active", '"user"', "VARCHAR(200)"),
    ("automic_active", "run_time_sec", "INTEGER"),
    ("automic_active", "ert_sec", "INTEGER"),
    ("automic_active", "ert_end_time", "TIMESTAMPTZ"),
    ("automic_active", "ert_calc", "INTEGER"),
    ("automic_active", "signal", "INTEGER"),
    ("automic_active", "mrt_sec", "INTEGER"),
    ("automic_active", "srt_sec", "INTEGER"),
    ("automic_object_headers", "ert_sec", "INTEGER"),
    ("automic_collector_state", "backfill_run_id_cursor", "BIGINT"),
    ("automic_collector_state", "jpp_oh_id_cursor", "BIGINT"),
    ("automic_collector_state", "jpp_synced_at", "TIMESTAMPTZ"),
    ("automic_collector_state", "script_oh_id_cursor", "BIGINT"),
    ("automic_collector_state", "script_synced_at", "TIMESTAMPTZ"),
    ("automic_collector_state", "users_oh_id_cursor", "BIGINT"),
    ("automic_collector_state", "users_synced_at", "TIMESTAMPTZ"),
    ("automic_collector_state", "infra_synced_at", "TIMESTAMPTZ"),
    ("automic_collector_state", "infra_source_now", "TIMESTAMPTZ"),
    ("automic_collector_state", "infra_warning", "TEXT"),
    ("automic_collector_state", "reconcile_at", "TIMESTAMPTZ"),
    ("automic_collector_state", "source_min_by_client", "JSONB"),
    ("automic_collector_state", "run_id_watermark_by_client", "JSONB"),
    ("automic_executions", "user_idnr", "BIGINT"),
    ("automic_executions", "user_name_at_run", "VARCHAR(200)"),
    ("automic_executions", "agent_group", "VARCHAR(200)"),
    ("automic_executions", "agent_assigned", "VARCHAR(200)"),
    ("automic_active", "user_idnr", "BIGINT"),
    ("automic_active", "user_name_at_run", "VARCHAR(200)"),
    ("automic_active", "agent_group", "VARCHAR(200)"),
    ("automic_active", "agent_assigned", "VARCHAR(200)"),
    ("automic_collector_state", "step_state", "JSONB"),
    ("automic_collector_runs", "step_metrics", "JSONB"),
    ("automic_object_headers", "archive1", "VARCHAR(512)"),
    ("automic_object_headers", "archive2", "VARCHAR(512)"),
)


def _executions_pk_time_col(conn) -> Optional[str]:
    """PK içindeki zaman kolonu (end_time | activation_time) veya None."""
    try:
        rows = conn.execute(text(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = 'automic_executions'::regclass AND i.indisprimary "
            "AND a.attname IN ('end_time', 'activation_time')"
        )).all()
        names = {r[0] for r in rows}
        if "activation_time" in names and "end_time" not in names:
            return "activation_time"
        if "end_time" in names:
            return "end_time"
        if "activation_time" in names:
            return "activation_time"
    except Exception as _e:
        note_error("database._executions_pk_time_col", _e)
    return None


def _migrate_executions_to_activation_time(conn) -> None:
    """end_time partition/PK → activation_time. İdempotent; veri korunur."""
    try:
        exists = conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='automic_executions'"
        )).first()
    except Exception as _exc:
        note_error("database.silent_196", _exc)
        return
    if not exists:
        return
    pk_time = _executions_pk_time_col(conn)
    if pk_time == "activation_time":
        return
    logger.info("Automic: automic_executions partition/PK → activation_time migration")
    conn.execute(text("DROP TABLE IF EXISTS automic_executions_new CASCADE"))
    conn.execute(text("""
        CREATE TABLE automic_executions_new (
            system_id INTEGER NOT NULL,
            client INTEGER NOT NULL,
            run_id BIGINT NOT NULL,
            activation_time TIMESTAMPTZ NOT NULL,
            end_time TIMESTAMPTZ NOT NULL,
            parent_run_id BIGINT,
            top_run_id BIGINT,
            restart_ref_run_id BIGINT,
            object_name VARCHAR(200) NOT NULL,
            object_type VARCHAR(16),
            folder VARCHAR(400),
            status_code INTEGER,
            status_class VARCHAR(16) NOT NULL,
            start_time TIMESTAMPTZ,
            duration_sec DOUBLE PRECISION,
            agent VARCHAR(200),
            platform VARCHAR(32),
            queue VARCHAR(200),
            "user" VARCHAR(200),
            user_idnr BIGINT,
            user_name_at_run VARCHAR(200),
            return_code INTEGER,
            run_time_sec INTEGER,
            ert_sec INTEGER,
            PRIMARY KEY (system_id, client, run_id, activation_time)
        )
    """))
    conn.execute(text("""
        INSERT INTO automic_executions_new (
            system_id, client, run_id, activation_time, end_time,
            parent_run_id, top_run_id, restart_ref_run_id, object_name, object_type, folder,
            status_code, status_class, start_time, duration_sec, agent, platform, queue,
            "user", user_idnr, user_name_at_run, return_code, run_time_sec, ert_sec
        )
        SELECT DISTINCT ON (
            system_id, client, run_id, COALESCE(activation_time, start_time, end_time)
        )
            system_id, client, run_id,
            COALESCE(activation_time, start_time, end_time),
            end_time,
            parent_run_id, top_run_id, restart_ref_run_id, object_name, object_type, folder,
            status_code, status_class, start_time, duration_sec, agent, platform, queue,
            "user", user_idnr, user_name_at_run, return_code, run_time_sec, ert_sec
        FROM automic_executions
        ORDER BY system_id, client, run_id,
                 COALESCE(activation_time, start_time, end_time),
                 end_time DESC NULLS LAST
    """))
    n = conn.execute(text("SELECT count(*) FROM automic_executions_new")).scalar()
    conn.execute(text("DROP TABLE automic_executions CASCADE"))
    conn.execute(text("ALTER TABLE automic_executions_new RENAME TO automic_executions"))
    for ddl in (
        "CREATE INDEX IF NOT EXISTS ix_automic_exec_obj ON automic_executions "
        "(system_id, client, object_name, end_time)",
        "CREATE INDEX IF NOT EXISTS ix_automic_exec_class ON automic_executions "
        "(system_id, status_class, end_time)",
        "CREATE INDEX IF NOT EXISTS ix_automic_exec_run ON automic_executions (system_id, run_id)",
        "CREATE INDEX IF NOT EXISTS ix_automic_exec_parent ON automic_executions "
        "(system_id, parent_run_id)",
        "CREATE INDEX IF NOT EXISTS ix_automic_exec_user ON automic_executions "
        "(system_id, client, user_idnr)",
        "CREATE INDEX IF NOT EXISTS ix_automic_exec_end ON automic_executions (system_id, end_time)",
        "CREATE INDEX IF NOT EXISTS ix_automic_executions_activation_time_idx "
        "ON automic_executions (activation_time DESC)",
    ):
        try:
            conn.execute(text(ddl))
        except Exception as exc:
            note_error("database._migrate_executions_to_activation_time", exc)
    logger.info("Automic: activation_time migration tamam (%s satır)", n)


def _timescale_available(conn) -> bool:
    try:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        return True
    except Exception as exc:
        logger.info("Automic DB: TimescaleDB yok, düz Postgres ile devam (%s)", exc)
        return False


def ensure_schema(force: bool = False) -> bool:
    """Tabloları + (varsa) hypertable/compression ayarlarını oluşturur. İdempotent."""
    global _schema_ready
    if _schema_ready and not force:
        return True
    with _schema_lock:
        if _schema_ready and not force:
            return True
        _ensure_engine()
        import app.models.automic  # noqa: F401 — modelleri metadata'ya kaydet

        AutomicBase.metadata.create_all(bind=_engine)
        with _engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            for tbl, col, typ in _ADD_COLUMNS:
                try:
                    conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} {typ}"))
                except Exception as exc:
                    logger.warning("Automic kolon ekleme %s.%s: %s", tbl, col, exc)
            try:
                _migrate_executions_to_activation_time(conn)
            except Exception as exc:
                logger.exception("Automic executions activation_time migration: %s", exc)
                raise
            ts = _timescale_available(conn)
            if ts:
                for tbl, col, chunk, seg, order in _HYPERTABLES:
                    try:
                        conn.execute(text(
                            f"SELECT create_hypertable('{tbl}', '{col}', "
                            f"chunk_time_interval => INTERVAL '{chunk}', "
                            f"if_not_exists => TRUE, migrate_data => TRUE)"
                        ))
                    except Exception as exc:
                        logger.warning("Automic hypertable %s: %s", tbl, exc)
                for tbl, _col, _chunk, seg, order in _HYPERTABLES:
                    if not seg:
                        continue
                    try:
                        conn.execute(text(
                            f"ALTER TABLE {tbl} SET (timescaledb.compress, "
                            f"timescaledb.compress_segmentby = '{seg}', "
                            f"timescaledb.compress_orderby = '{order}')"
                        ))
                    except Exception as exc:
                        note_error("database.ensure_schema", exc)
                for tbl, after in (("automic_executions", "7 days"), ("automic_daily_aggregates", "30 days")):
                    try:
                        conn.execute(text(
                            f"SELECT add_compression_policy('{tbl}', INTERVAL '{after}', if_not_exists => TRUE)"
                        ))
                    except Exception as exc:
                        note_error("database.ensure_schema", exc)
            try:
                conn.execute(text(
                    "ALTER TABLE automic_report_excerpts ALTER COLUMN content SET COMPRESSION lz4"
                ))
            except Exception as _e:
                note_error("database.ensure_schema", _e)
        _schema_ready = True
        logger.info("Automic DB şeması hazır (%d tablo)", len(AutomicBase.metadata.tables))
        return True


def timescale_enabled(db: Session) -> bool:
    try:
        row = db.execute(text("SELECT 1 FROM pg_extension WHERE extname='timescaledb'")).first()
        return bool(row)
    except Exception as _exc:
        note_error("database.silent_355", _exc)
        return False


def database_size_bytes(db: Session) -> int:
    try:
        return int(db.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0)
    except Exception as _exc:
        note_error("database.silent_362", _exc)
        return 0
