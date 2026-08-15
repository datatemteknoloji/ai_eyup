"""
Initialize TimescaleDB hypertables for time-series data
"""
import logging
from sqlalchemy import text
from app.core.database import engine

logger = logging.getLogger(__name__)


def _run(conn, sql: str, label: str, ok_substrings: tuple = ()):
    """
    SQL çalıştır; hata olursa rollback yapıp devam et.
    ok_substrings içindeki string varsa hata değil, sessizce atla.
    """
    try:
        conn.execute(text(sql))
        conn.commit()
        logger.info(f"✅ {label}")
        return True
    except Exception as e:
        conn.rollback()
        for s in ok_substrings:
            if s in str(e):
                return True           # beklenen durum, sessizce atla
        logger.warning(f"⚠️  {label}: {e}")
        return False


def init_timescaledb():
    """Initialize TimescaleDB hypertables"""
    try:
        with engine.connect() as conn:
            # TimescaleDB eklentisi
            _run(conn, "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;",
                 "timescaledb extension")

            # ── metric_data hypertable ────────────────────────────────────────
            _run(
                conn,
                """SELECT create_hypertable('metric_data', 'timestamp',
                       chunk_time_interval => INTERVAL '1 day',
                       if_not_exists => TRUE);""",
                "metric_data hypertable",
                ok_substrings=("already a hypertable",),
            )

            # Saatlik continuous aggregate
            _run(
                conn,
                """CREATE MATERIALIZED VIEW IF NOT EXISTS metric_data_hourly
                   WITH (timescaledb.continuous) AS
                   SELECT server_id, metric_name,
                          time_bucket('1 hour', timestamp) AS bucket,
                          AVG(value) as avg_value,
                          MIN(value) as min_value,
                          MAX(value) as max_value,
                          COUNT(*) as count
                   FROM metric_data
                   GROUP BY server_id, metric_name, bucket
                   WITH NO DATA;""",
                "metric_data_hourly continuous aggregate",
                ok_substrings=("already exists",),
            )

            _run(
                conn,
                """SELECT add_continuous_aggregate_policy('metric_data_hourly',
                       start_offset => INTERVAL '3 hours',
                       end_offset   => INTERVAL '1 hour',
                       schedule_interval => INTERVAL '1 hour',
                       if_not_exists => TRUE);""",
                "metric_data_hourly refresh policy",
                ok_substrings=("already exists", "FeatureNotSupported", "not a continuous aggregate"),
            )

            _run(
                conn,
                """SELECT add_retention_policy('metric_data',
                       INTERVAL '30 days',
                       if_not_exists => TRUE);""",
                "metric_data retention policy (30 days)",
                ok_substrings=("already exists",),
            )

            # ── hypervisor_host_metrics hypertable ───────────────────────────
            _run(
                conn,
                """SELECT create_hypertable('hypervisor_host_metrics', 'timestamp',
                       chunk_time_interval => INTERVAL '7 days',
                       if_not_exists => TRUE);""",
                "hypervisor_host_metrics hypertable",
                ok_substrings=("already a hypertable", "does not exist"),
            )

            # 90 günlük veri saklama (15 dk'da bir ≈ 8640 kayıt/host/90gün)
            _run(
                conn,
                """SELECT add_retention_policy('hypervisor_host_metrics',
                       INTERVAL '90 days',
                       if_not_exists => TRUE);""",
                "hypervisor_host_metrics retention policy (90 days)",
                ok_substrings=("already exists", "does not exist"),
            )

            try:
                from app.services.rag_store import ensure_schema
                ensure_schema()
                logger.info("✅ rag_embeddings (pgvector) hazır")
            except Exception as e:
                logger.warning("⚠️  rag_embeddings: %s", e)

            logger.info("🎉 TimescaleDB initialization complete")

    except Exception as e:
        logger.error(f"❌ TimescaleDB initialization failed: {e}")
        raise
