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

            # ── virt_vm_metrics / virt_datastore_metrics hypertable ──────────
            # VM ve datastore trendleri (right-sizing, kapasite tükenme tahmini)
            for _tbl, _chunk, _keep in (
                ("virt_vm_metrics", "7 days", "90 days"),
                ("virt_datastore_metrics", "7 days", "180 days"),
            ):
                _run(
                    conn,
                    f"""SELECT create_hypertable('{_tbl}', 'timestamp',
                           chunk_time_interval => INTERVAL '{_chunk}',
                           if_not_exists => TRUE,
                           migrate_data => TRUE);""",
                    f"{_tbl} hypertable",
                    ok_substrings=("already a hypertable", "does not exist"),
                )
                _run(
                    conn,
                    f"""SELECT add_retention_policy('{_tbl}',
                           INTERVAL '{_keep}',
                           if_not_exists => TRUE);""",
                    f"{_tbl} retention policy ({_keep})",
                    ok_substrings=("already exists", "does not exist"),
                )

            # ── Sıkıştırma (compression) ─────────────────────────────────────
            # Saklama süresi doluyken bu tablolar sıkıştırılmıyordu: ölçülen
            # oran virt_vm_metrics'te 90 günde ~24 GB. Zaman serisi kolonları
            # tekrarlı olduğu için sütun bazlı sıkıştırma tipik 8-15x kazanç
            # verir ve sorgular şeffaf çalışır.
            #
            # `segmentby` = varlık kimliği: aynı varlığın satırları bir arada
            # sıkıştırılır, böylece "tek host/VM'in son 30 günü" sorgusu tüm
            # chunk'ı açmak zorunda kalmaz (trend motorunun ana erişim deseni).
            # `compress_after` retention'dan KISA, taze veri penceresinden
            # UZUN seçilir: son 7 gün sıkıştırılmamış kalır (sık yazılan ve en
            # sık sorgulanan aralık), daha eskisi sıkıştırılır.
            for _tbl, _segment, _after in (
                ("hypervisor_host_metrics", "hypervisor_id, host_name", "7 days"),
                ("virt_vm_metrics", "hypervisor_id, vm_ref", "7 days"),
                ("virt_datastore_metrics", "hypervisor_id, name", "7 days"),
                ("metric_data", "server_id, metric_name", "3 days"),
            ):
                _run(
                    conn,
                    f"""ALTER TABLE {_tbl} SET (
                           timescaledb.compress = TRUE,
                           timescaledb.compress_segmentby = '{_segment}',
                           timescaledb.compress_orderby = 'timestamp DESC');""",
                    f"{_tbl} compression ayarı",
                    ok_substrings=("does not exist", "already", "cannot be changed"),
                )
                _run(
                    conn,
                    f"""SELECT add_compression_policy('{_tbl}',
                           INTERVAL '{_after}',
                           if_not_exists => TRUE);""",
                    f"{_tbl} compression policy ({_after})",
                    ok_substrings=("already exists", "does not exist", "not supported"),
                )

            # ── Saatlik sürekli toplama (continuous aggregate) ───────────────
            # 30-90 günlük trend sorguları ham 15 dk / 10 dk çözünürlüğü tarıyor
            # (bir VM için 90 günde ~13K satır, fleet için milyonlarca). Saatlik
            # rollup aynı eğimi 12-15x daha az satırla verir.
            #
            # `WITH NO DATA` + refresh policy: mevcut tablolar üzerinde ilk
            # materyalizasyonu tek seferde yapmak (24 GB tarama) backend
            # başlangıcını kilitler; politika artımlı olarak doldurur.
            for _view, _tbl, _key_cols, _value_cols in (
                (
                    "virt_vm_metrics_hourly", "virt_vm_metrics",
                    "hypervisor_id, vm_name",
                    "cpu_usage_pct, mem_usage_pct, cpu_ready_pct, disk_latency_ms, "
                    "guest_disk_pct",
                ),
                (
                    "hypervisor_host_metrics_hourly", "hypervisor_host_metrics",
                    "hypervisor_id, host_name",
                    "cpu_usage_pct, mem_usage_pct, ds_usage_pct, cpu_ready_pct, "
                    "disk_latency_ms",
                ),
                (
                    "virt_datastore_metrics_hourly", "virt_datastore_metrics",
                    "hypervisor_id, name",
                    "usage_pct, free_gb, used_gb, uncommitted_gb",
                ),
            ):
                _aggs = ", ".join(
                    f"avg({c.strip()}) AS avg_{c.strip()}, max({c.strip()}) AS max_{c.strip()}"
                    for c in _value_cols.split(",")
                )
                _run(
                    conn,
                    f"""CREATE MATERIALIZED VIEW IF NOT EXISTS {_view}
                       WITH (timescaledb.continuous) AS
                       SELECT {_key_cols},
                              time_bucket('1 hour', timestamp) AS bucket,
                              count(*) AS samples,
                              {_aggs}
                       FROM {_tbl}
                       GROUP BY {_key_cols}, bucket
                       WITH NO DATA;""",
                    f"{_view} continuous aggregate",
                    ok_substrings=("already exists", "does not exist"),
                )
                _run(
                    conn,
                    f"""SELECT add_continuous_aggregate_policy('{_view}',
                           start_offset => INTERVAL '3 days',
                           end_offset   => INTERVAL '1 hour',
                           schedule_interval => INTERVAL '1 hour',
                           if_not_exists => TRUE);""",
                    f"{_view} refresh policy",
                    ok_substrings=(
                        "already exists", "does not exist",
                        "FeatureNotSupported", "not a continuous aggregate",
                    ),
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
