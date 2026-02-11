"""
Initialize TimescaleDB hypertables for time-series data
"""
import logging
from sqlalchemy import text
from app.core.database import engine

logger = logging.getLogger(__name__)


def init_timescaledb():
    """Initialize TimescaleDB hypertables"""
    try:
        with engine.connect() as conn:
            # Enable TimescaleDB extension
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
            conn.commit()
            
            # Convert metric_data to hypertable (if not already)
            try:
                conn.execute(text("""
                    SELECT create_hypertable('metric_data', 'timestamp',
                        chunk_time_interval => INTERVAL '1 day',
                        if_not_exists => TRUE
                    );
                """))
                conn.commit()
                logger.info("✅ metric_data hypertable created/verified")
            except Exception as e:
                if "already a hypertable" not in str(e):
                    logger.warning(f"Hypertable creation: {e}")
            
            # Create continuous aggregates for faster queries
            try:
                # Hourly aggregates
                conn.execute(text("""
                    CREATE MATERIALIZED VIEW IF NOT EXISTS metric_data_hourly
                    WITH (timescaledb.continuous) AS
                    SELECT
                        server_id,
                        metric_name,
                        time_bucket('1 hour', timestamp) AS bucket,
                        AVG(value) as avg_value,
                        MIN(value) as min_value,
                        MAX(value) as max_value,
                        COUNT(*) as count
                    FROM metric_data
                    GROUP BY server_id, metric_name, bucket
                    WITH NO DATA;
                """))
                conn.commit()
                logger.info("✅ Hourly continuous aggregate created")
            except Exception as e:
                if "already exists" not in str(e):
                    logger.warning(f"Continuous aggregate creation: {e}")
            
            # Add refresh policy
            try:
                conn.execute(text("""
                    SELECT add_continuous_aggregate_policy('metric_data_hourly',
                        start_offset => INTERVAL '3 hours',
                        end_offset => INTERVAL '1 hour',
                        schedule_interval => INTERVAL '1 hour',
                        if_not_exists => TRUE
                    );
                """))
                conn.commit()
                logger.info("✅ Refresh policy added")
            except Exception as e:
                if "already exists" not in str(e):
                    logger.warning(f"Refresh policy: {e}")
            
            # Add data retention policy (keep raw data for 30 days)
            try:
                conn.execute(text("""
                    SELECT add_retention_policy('metric_data',
                        INTERVAL '30 days',
                        if_not_exists => TRUE
                    );
                """))
                conn.commit()
                logger.info("✅ Data retention policy added (30 days)")
            except Exception as e:
                if "already exists" not in str(e):
                    logger.warning(f"Retention policy: {e}")
            
            logger.info("🎉 TimescaleDB initialization complete")
            
    except Exception as e:
        logger.error(f"❌ TimescaleDB initialization failed: {e}")
        raise
