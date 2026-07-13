"""
Prometheus -> TimescaleDB metric sync - Genisletilmis versiyon
Her 10 dakikada background task olarak calisir.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
import httpx
from sqlalchemy.orm import Session
from app.core.config import settings, apply_promql_job
from app.models.server import Server
from app.models.metric import MetricData
from app.services.platform_scope import is_windows_server
from app.services.monitoring.prometheus_metrics import WINDOWS_EXPORTER_PORT

logger = logging.getLogger(__name__)

# (prometheus_query_template, db_metric_name, birim, kategori)
METRICS_TO_SYNC: List[Tuple[str, str, str, str]] = [
    # === CPU ===
    ('100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle",job="node-exporter",instance="{instance}"}[5m])) * 100)',
     "cpu_usage_percent", "percent", "cpu"),
    ('avg by (instance) (rate(node_cpu_seconds_total{mode="iowait",job="node-exporter",instance="{instance}"}[5m])) * 100',
     "cpu_iowait_percent", "percent", "cpu"),
    ('avg by (instance) (rate(node_cpu_seconds_total{mode="system",job="node-exporter",instance="{instance}"}[5m])) * 100',
     "cpu_system_percent", "percent", "cpu"),
    ('avg by (instance) (rate(node_cpu_seconds_total{mode="user",job="node-exporter",instance="{instance}"}[5m])) * 100',
     "cpu_user_percent", "percent", "cpu"),
    ('avg by (instance) (rate(node_cpu_seconds_total{mode="steal",job="node-exporter",instance="{instance}"}[5m])) * 100',
     "cpu_steal_percent", "percent", "cpu"),
    ('avg by (instance) (rate(node_cpu_seconds_total{mode="softirq",job="node-exporter",instance="{instance}"}[5m])) * 100',
     "cpu_softirq_percent", "percent", "cpu"),

    # === Yuk ===
    ('node_load1{job="node-exporter",instance="{instance}"}', "load1", "", "load"),
    ('node_load5{job="node-exporter",instance="{instance}"}', "load5", "", "load"),
    ('node_load15{job="node-exporter",instance="{instance}"}', "load15", "", "load"),
    ('node_context_switches_total{job="node-exporter",instance="{instance}"}', "context_switches_total", "count", "load"),
    ('rate(node_context_switches_total{job="node-exporter",instance="{instance}"}[5m])', "context_switches_per_sec", "per_sec", "load"),

    # === Bellek ===
    ('(1 - node_memory_MemAvailable_bytes{job="node-exporter",instance="{instance}"} / node_memory_MemTotal_bytes{job="node-exporter",instance="{instance}"}) * 100',
     "memory_usage_percent", "percent", "memory"),
    ('node_memory_MemAvailable_bytes{job="node-exporter",instance="{instance}"}', "memory_available_bytes", "bytes", "memory"),
    ('node_memory_MemTotal_bytes{job="node-exporter",instance="{instance}"}', "memory_total_bytes", "bytes", "memory"),
    ('node_memory_Cached_bytes{job="node-exporter",instance="{instance}"}', "memory_cached_bytes", "bytes", "memory"),
    ('node_memory_Buffers_bytes{job="node-exporter",instance="{instance}"}', "memory_buffers_bytes", "bytes", "memory"),
    ('node_memory_SwapTotal_bytes{job="node-exporter",instance="{instance}"}', "swap_total_bytes", "bytes", "memory"),
    ('node_memory_SwapFree_bytes{job="node-exporter",instance="{instance}"}', "swap_free_bytes", "bytes", "memory"),
    ('(1 - node_memory_SwapFree_bytes{job="node-exporter",instance="{instance}"} / (node_memory_SwapTotal_bytes{job="node-exporter",instance="{instance}"} + 1)) * 100',
     "swap_usage_percent", "percent", "memory"),

    # === Disk Kullanim ===
    ('(1 - node_filesystem_avail_bytes{job="node-exporter",instance="{instance}",mountpoint="/"} / node_filesystem_size_bytes{job="node-exporter",instance="{instance}",mountpoint="/"}) * 100',
     "disk_root_usage_percent", "percent", "disk"),
    ('node_filesystem_avail_bytes{job="node-exporter",instance="{instance}",mountpoint="/"}',
     "disk_root_avail_bytes", "bytes", "disk"),
    ('node_filefd_allocated{job="node-exporter",instance="{instance}"}', "fd_allocated", "count", "disk"),
    ('node_filefd_maximum{job="node-exporter",instance="{instance}"}', "fd_maximum", "count", "disk"),

    # === Disk IO ===
    ('sum(rate(node_disk_read_bytes_total{job="node-exporter",instance="{instance}"}[5m]))',
     "disk_read_bytes_per_sec", "bytes", "io"),
    ('sum(rate(node_disk_written_bytes_total{job="node-exporter",instance="{instance}"}[5m]))',
     "disk_write_bytes_per_sec", "bytes", "io"),
    ('sum(rate(node_disk_reads_completed_total{job="node-exporter",instance="{instance}"}[5m]))',
     "disk_read_iops", "count", "io"),
    ('sum(rate(node_disk_writes_completed_total{job="node-exporter",instance="{instance}"}[5m]))',
     "disk_write_iops", "count", "io"),
    ('sum(rate(node_disk_io_time_seconds_total{job="node-exporter",instance="{instance}"}[5m])) * 100',
     "disk_io_utilization_percent", "percent", "io"),

    # === Network ===
    ('sum(rate(node_network_receive_bytes_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_rx_bytes_per_sec", "bytes", "network"),
    ('sum(rate(node_network_transmit_bytes_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_tx_bytes_per_sec", "bytes", "network"),
    ('sum(rate(node_network_receive_packets_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_rx_packets_per_sec", "count", "network"),
    ('sum(rate(node_network_transmit_packets_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_tx_packets_per_sec", "count", "network"),
    ('sum(rate(node_network_receive_errs_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_rx_errors_per_sec", "count", "network"),
    ('sum(rate(node_network_transmit_errs_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_tx_errors_per_sec", "count", "network"),
    ('sum(rate(node_network_receive_drop_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_rx_drops_per_sec", "count", "network"),
    ('sum(rate(node_network_transmit_drop_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_tx_drops_per_sec", "count", "network"),

    # === Sistem ===
    ('node_procs_running{job="node-exporter",instance="{instance}"}', "procs_running", "count", "system"),
    ('node_procs_blocked{job="node-exporter",instance="{instance}"}', "procs_blocked", "count", "system"),
]

# windows_exporter (pinned v0.29.2, collectors: cpu,cs,logical_disk,net,os,service,system,memory)
# üzerinden aynı metric_data şemasına yazılan Windows eşleniği — böylece Dashboard/LiveMetrics
# geçmiş grafikleri Linux ile aynı metric_name'leri kullanabilir.
WINDOWS_METRICS_TO_SYNC: List[Tuple[str, str, str, str]] = [
    # === CPU ===
    ('100 - (avg by (instance) (rate(windows_cpu_time_total{mode="idle",job="windows-exporter",instance="{instance}"}[5m])) * 100)',
     "cpu_usage_percent", "percent", "cpu"),
    ('avg by (instance) (rate(windows_cpu_time_total{mode="user",job="windows-exporter",instance="{instance}"}[5m])) * 100',
     "cpu_user_percent", "percent", "cpu"),
    ('avg by (instance) (rate(windows_cpu_time_total{mode="privileged",job="windows-exporter",instance="{instance}"}[5m])) * 100',
     "cpu_system_percent", "percent", "cpu"),

    # === Bellek === (cs.physical_memory_bytes = toplam, os.physical_memory_free_bytes = boş — v0.29.2 metric adları)
    ('(1 - (windows_os_physical_memory_free_bytes{job="windows-exporter",instance="{instance}"} / windows_cs_physical_memory_bytes{job="windows-exporter",instance="{instance}"})) * 100',
     "memory_usage_percent", "percent", "memory"),
    ('windows_cs_physical_memory_bytes{job="windows-exporter",instance="{instance}"}',
     "memory_total_bytes", "bytes", "memory"),
    ('windows_os_physical_memory_free_bytes{job="windows-exporter",instance="{instance}"}',
     "memory_available_bytes", "bytes", "memory"),

    # === Disk (C: sürücüsü) ===
    ('(1 - (windows_logical_disk_free_bytes{volume="C:",job="windows-exporter",instance="{instance}"} / windows_logical_disk_size_bytes{volume="C:",job="windows-exporter",instance="{instance}"})) * 100',
     "disk_root_usage_percent", "percent", "disk"),
    ('windows_logical_disk_free_bytes{volume="C:",job="windows-exporter",instance="{instance}"}',
     "disk_root_avail_bytes", "bytes", "disk"),

    # === Network ===
    ('sum by (instance) (rate(windows_net_bytes_received_total{job="windows-exporter",instance="{instance}"}[5m]))',
     "network_rx_bytes_per_sec", "bytes", "network"),
    ('sum by (instance) (rate(windows_net_bytes_sent_total{job="windows-exporter",instance="{instance}"}[5m]))',
     "network_tx_bytes_per_sec", "bytes", "network"),
]


class MetricSyncService:
    """Prometheus'tan metrikleri cekip TimescaleDB'ye yazar."""

    @staticmethod
    async def sync_server_metrics(db: Session, server: Server, minutes: int = 12) -> int:
        if not server.ip_address and not server.hostname:
            return 0
        if is_windows_server(server):
            instance = f"{server.ip_address}:{WINDOWS_EXPORTER_PORT}"
            metrics_list = WINDOWS_METRICS_TO_SYNC
        else:
            instance = f"{server.ip_address}:9100"
            metrics_list = METRICS_TO_SYNC
        synced_count = 0
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=minutes)

        async with httpx.AsyncClient(timeout=20.0) as client:
            for query_tpl, db_metric_name, unit, category in metrics_list:
                kind = "windows" if is_windows_server(server) else "linux"
                query = apply_promql_job(query_tpl, kind=kind).replace("{instance}", instance)
                try:
                    resp = await client.get(
                        f"{settings.PROMETHEUS_URL}/api/v1/query_range",
                        params={"query": query, "start": start_time.timestamp(),
                                "end": end_time.timestamp(), "step": "60s"}
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    if data.get("status") != "success":
                        continue
                    for result in data.get("data", {}).get("result", []):
                        for ts, val in result.get("values", []):
                            try:
                                float_val = float(val)
                                if float_val != float_val or float_val == float('inf'):
                                    continue
                                db.add(MetricData(
                                    server_id=server.id,
                                    metric_name=db_metric_name,
                                    value=float_val,
                                    unit=unit,
                                    labels=category,
                                    timestamp=datetime.utcfromtimestamp(float(ts))
                                ))
                                synced_count += 1
                            except Exception:
                                pass
                    db.commit()
                except Exception as e:
                    logger.debug(f"Metric sync error {db_metric_name}/{instance}: {e}")
                    try:
                        db.rollback()
                    except Exception:
                        pass

        return synced_count

    @staticmethod
    async def sync_all_servers_metrics(db: Session, minutes: int = 12) -> Dict[str, Any]:
        candidates = db.query(Server).filter(
            Server.ai_ready == True,
            Server.status == "ONLINE"
        ).all()
        # Windows sunucular sadece windows_exporter kuruluysa sorgulanır (gereksiz Prometheus
        # sorgusu yapmamak için) — Linux tarafı geriye dönük uyumluluk için filtresiz kalır.
        servers = [
            s for s in candidates
            if not is_windows_server(s) or s.windows_exporter_installed
        ]
        total, synced_servers = 0, 0
        for srv in servers:
            try:
                count = await MetricSyncService.sync_server_metrics(db, srv, minutes)
                if count > 0:
                    total += count
                    synced_servers += 1
            except Exception as e:
                logger.error(f"Metric sync failed {srv.name}: {e}")
        logger.info(f"Metric sync: {synced_servers}/{len(servers)} sunucu, {total} kayit")
        return {"total_servers": len(servers), "synced_servers": synced_servers, "total_metrics": total}

    @staticmethod
    def get_metric_categories() -> Dict[str, List[str]]:
        """Metrik kategorileri ve adlari"""
        cats: Dict[str, List[str]] = {}
        for _, name, _, cat in METRICS_TO_SYNC:
            cats.setdefault(cat, []).append(name)
        return cats
