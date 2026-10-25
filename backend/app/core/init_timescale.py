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
                ("ocp_resource_metrics", "1 day", "30 days"),
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
                ("ocp_resource_metrics", "cluster_id, kind, object_key", "3 days"),
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

            # ── Günlük özet, 400 gün (ham saklama süreleri değişmez) ──────────
            # Mevsimsellik ham seriden uzun ister. Continuous aggregate ham
            # pencereden uzun tutulur; ham tick silme politikasına dokunulmaz.
            # p95 Timescale 2.28'de percentile_cont ile CA içinde hesaplanır.
            _daily_views = (
                (
                    "metric_data_daily",
                    """SELECT server_id, metric_name,
                              time_bucket('1 day', timestamp) AS bucket,
                              avg(value) AS avg_value,
                              max(value) AS max_value,
                              percentile_cont(0.95) WITHIN GROUP (ORDER BY value) AS p95_value,
                              count(*) AS samples
                       FROM metric_data
                       GROUP BY server_id, metric_name, bucket""",
                    "32 days",
                ),
                (
                    "hypervisor_host_metrics_daily",
                    """SELECT hypervisor_id, host_name,
                              time_bucket('1 day', timestamp) AS bucket,
                              avg(cpu_usage_pct) AS avg_cpu_pct,
                              max(cpu_usage_pct) AS max_cpu_pct,
                              percentile_cont(0.95) WITHIN GROUP (ORDER BY cpu_usage_pct) AS p95_cpu_pct,
                              avg(mem_usage_pct) AS avg_mem_pct,
                              max(mem_usage_pct) AS max_mem_pct,
                              percentile_cont(0.95) WITHIN GROUP (ORDER BY mem_usage_pct) AS p95_mem_pct,
                              avg(ds_usage_pct) AS avg_ds_pct,
                              max(ds_usage_pct) AS max_ds_pct,
                              percentile_cont(0.95) WITHIN GROUP (ORDER BY ds_usage_pct) AS p95_ds_pct,
                              avg(mem_used_mb) AS avg_mem_used_mb,
                              avg(mem_total_mb) AS avg_mem_total_mb,
                              avg(cpu_usage_pct * COALESCE(cpu_cores, 0)) AS avg_cpu_weighted,
                              avg(COALESCE(cpu_cores, 0)) AS avg_cpu_cores,
                              count(*) AS samples
                       FROM hypervisor_host_metrics
                       GROUP BY hypervisor_id, host_name, bucket""",
                    "90 days",
                ),
                (
                    "virt_datastore_metrics_daily",
                    """SELECT hypervisor_id, name,
                              time_bucket('1 day', timestamp) AS bucket,
                              avg(usage_pct) AS avg_usage_pct,
                              max(usage_pct) AS max_usage_pct,
                              percentile_cont(0.95) WITHIN GROUP (ORDER BY usage_pct) AS p95_usage_pct,
                              avg(used_gb) AS avg_used_gb,
                              max(used_gb) AS max_used_gb,
                              percentile_cont(0.95) WITHIN GROUP (ORDER BY used_gb) AS p95_used_gb,
                              count(*) AS samples
                       FROM virt_datastore_metrics
                       GROUP BY hypervisor_id, name, bucket""",
                    "180 days",
                ),
                (
                    "ocp_node_daily",
                    """SELECT cluster_id, object_key,
                              time_bucket('1 day', timestamp) AS bucket,
                              avg(cpu_pct) AS avg_cpu_pct,
                              max(cpu_pct) AS max_cpu_pct,
                              percentile_cont(0.95) WITHIN GROUP (ORDER BY cpu_pct) AS p95_cpu_pct,
                              avg(memory_pct) AS avg_memory_pct,
                              max(memory_pct) AS max_memory_pct,
                              percentile_cont(0.95) WITHIN GROUP (ORDER BY memory_pct) AS p95_memory_pct,
                              count(*) AS samples
                       FROM ocp_resource_metrics
                       WHERE kind = 'node'
                       GROUP BY cluster_id, object_key, bucket""",
                    "30 days",
                ),
            )
            for _view, _select, _start in _daily_views:
                _run(
                    conn,
                    f"""CREATE MATERIALIZED VIEW IF NOT EXISTS {_view}
                       WITH (timescaledb.continuous) AS
                       {_select}
                       WITH NO DATA;""",
                    f"{_view} günlük continuous aggregate",
                    ok_substrings=("already exists", "does not exist"),
                )
                _run(
                    conn,
                    f"""SELECT add_continuous_aggregate_policy('{_view}',
                           start_offset => INTERVAL '{_start}',
                           end_offset => INTERVAL '1 hour',
                           schedule_interval => INTERVAL '1 hour',
                           if_not_exists => TRUE);""",
                    f"{_view} refresh policy",
                    ok_substrings=("already exists", "does not exist", "not a continuous aggregate"),
                )
                _run(
                    conn,
                    f"""SELECT add_retention_policy('{_view}',
                           INTERVAL '400 days',
                           if_not_exists => TRUE);""",
                    f"{_view} retention 400 days",
                    ok_substrings=("already exists", "does not exist", "not a continuous aggregate"),
                )

            # system_events hypertable değil; continuous aggregate kurulamaz.
            # Günlük sayım ayrı tabloda 400 gün durur. Ham satır ve incidents silinmez.
            _run(
                conn,
                """CREATE TABLE IF NOT EXISTS system_event_daily (
                       bucket date NOT NULL,
                       event_type varchar(100) NOT NULL,
                       severity varchar(20) NOT NULL,
                       event_count integer NOT NULL,
                       PRIMARY KEY (bucket, event_type, severity)
                   );""",
                "system_event_daily table",
            )
            _run(
                conn,
                """INSERT INTO system_event_daily (bucket, event_type, severity, event_count)
                   SELECT (created_at AT TIME ZONE 'UTC')::date,
                          event_type,
                          COALESCE(severity, 'info'),
                          count(*)::int
                   FROM system_events
                   WHERE created_at >= NOW() - INTERVAL '7 days'
                   GROUP BY 1, 2, 3
                   ON CONFLICT (bucket, event_type, severity)
                   DO UPDATE SET event_count = EXCLUDED.event_count;""",
                "system_event_daily ilk doldurma",
            )
            _run(
                conn,
                """DELETE FROM system_event_daily
                   WHERE bucket < (NOW() AT TIME ZONE 'UTC')::date - 400;""",
                "system_event_daily 400 gün sınırı",
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
