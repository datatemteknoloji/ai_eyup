"""
Prometheus -> TimescaleDB metric sync - Genisletilmis versiyon
Her 10 dakikada background task olarak calisir.

Node-exporter yoksa (veya Prometheus boş dönüyorsa) VMware QuickStats ile
sanal makine CPU/RAM snapshot'ı metric_data'ya yazılır.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import httpx
from sqlalchemy.orm import Session
from app.core.config import settings, apply_promql_job
from app.models.server import Server
from app.models.metric import MetricData
from app.services.platform_scope import is_windows_server, is_vm
from app.services.monitoring.prometheus_metrics import WINDOWS_EXPORTER_PORT

logger = logging.getLogger(__name__)

_REGEX_SPECIAL_CHARS = ".^$*+?{}[]|()"


def _promql_regex_escape(value: str) -> str:
    """PromQL instance=~"a|b|c" alternation'ı için literal string escape eder.

    NOT: Python'un re.escape() nokta gibi karakterler için ters eğik çizgi
    (\\.) üretir; ama bu PromQL sorgusu bir Go string literal'ı içine
    gömüldüğünde ("instance=~\"...\"") Go string lexer'ı \\. öğesini geçerli
    bir escape sequence olarak tanımaz ve "unknown escape sequence" parse
    hatası fırlatır (canlı test edildi). Bunun yerine her özel karakter tek
    elemanlı bir karakter sınıfına ([.] gibi) alınır — ters eğik çizgi hiç
    kullanılmadığından Go string parse aşamasını sorunsuz geçer.
    """
    return "".join(f"[{c}]" if c in _REGEX_SPECIAL_CHARS else c for c in value)

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
    # NOT: "by (instance)" bilinçli eklendi — toplu (batch) sync'te instance=~"a|b|c"
    # regex'iyle birden çok sunucu TEK sorguda çekilir (bkz. sync_physical_servers_metrics_batch);
    # "by (instance)" olmadan sum() tüm eşleşen instance'ları TEK değerde birleştirir ve
    # sonuçtan instance etiketi düşer (veri hangi sunucuya ait olduğu belli olmaz, kaybolur).
    # Tekli sorguda (tek instance) davranış/değer aynıdır, sadece sonuçta instance etiketi kalır.
    ('sum by (instance) (rate(node_disk_read_bytes_total{job="node-exporter",instance="{instance}"}[5m]))',
     "disk_read_bytes_per_sec", "bytes", "io"),
    ('sum by (instance) (rate(node_disk_written_bytes_total{job="node-exporter",instance="{instance}"}[5m]))',
     "disk_write_bytes_per_sec", "bytes", "io"),
    ('sum by (instance) (rate(node_disk_reads_completed_total{job="node-exporter",instance="{instance}"}[5m]))',
     "disk_read_iops", "count", "io"),
    ('sum by (instance) (rate(node_disk_writes_completed_total{job="node-exporter",instance="{instance}"}[5m]))',
     "disk_write_iops", "count", "io"),
    ('sum by (instance) (rate(node_disk_io_time_seconds_total{job="node-exporter",instance="{instance}"}[5m])) * 100',
     "disk_io_utilization_percent", "percent", "io"),

    # === Network ===
    ('sum by (instance) (rate(node_network_receive_bytes_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_rx_bytes_per_sec", "bytes", "network"),
    ('sum by (instance) (rate(node_network_transmit_bytes_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_tx_bytes_per_sec", "bytes", "network"),
    ('sum by (instance) (rate(node_network_receive_packets_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_rx_packets_per_sec", "count", "network"),
    ('sum by (instance) (rate(node_network_transmit_packets_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_tx_packets_per_sec", "count", "network"),
    ('sum by (instance) (rate(node_network_receive_errs_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_rx_errors_per_sec", "count", "network"),
    ('sum by (instance) (rate(node_network_transmit_errs_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_tx_errors_per_sec", "count", "network"),
    ('sum by (instance) (rate(node_network_receive_drop_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
     "network_rx_drops_per_sec", "count", "network"),
    ('sum by (instance) (rate(node_network_transmit_drop_total{job="node-exporter",instance="{instance}",device!~"lo"}[5m]))',
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


def _vmware_cpu_mem_from_live(stats: dict) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """get_all_vm_live_stats / get_vm_quick_stats → cpu%, mem%, mem_used_mb, mem_total_mb."""
    cpu_percent = stats.get("cpu_percent")
    mem_percent = stats.get("mem_percent")
    mem_used = stats.get("mem_used_mb") or stats.get("guest_mem_usage_mb")
    mem_total = stats.get("mem_total_mb")

    if cpu_percent is None:
        cpu_mhz = stats.get("cpu_mhz") or stats.get("cpu_usage_mhz") or 0
        num_cpu = stats.get("num_cpu") or 1
        try:
            cpu_mhz = float(cpu_mhz or 0)
            num_cpu = int(num_cpu or 1)
            cpu_freq_mhz = 2000
            if num_cpu and cpu_mhz:
                cpu_percent = round((cpu_mhz / (num_cpu * cpu_freq_mhz)) * 100, 1)
                cpu_percent = min(float(cpu_percent), 100.0)
        except (TypeError, ValueError):
            cpu_percent = None

    if mem_percent is None and mem_used and mem_total:
        try:
            mu, mt = float(mem_used), float(mem_total)
            if mt > 0:
                mem_percent = round((mu / mt) * 100, 1)
        except (TypeError, ValueError):
            mem_percent = None

    return (
        float(cpu_percent) if cpu_percent is not None else None,
        float(mem_percent) if mem_percent is not None else None,
        float(mem_used) if mem_used is not None else None,
        float(mem_total) if mem_total is not None else None,
    )


def _vmware_metric_row_dicts(
    server: Server,
    *,
    cpu_percent: Optional[float],
    mem_percent: Optional[float],
    mem_used_mb: Optional[float],
    mem_total_mb: Optional[float],
    disk_read_iops: Optional[float] = None,
    disk_write_iops: Optional[float] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """VMware snapshot satırlarını bulk_insert mapping olarak üretir (commit yok)."""
    ts = now or datetime.utcnow()
    pairs: List[Tuple[str, float, str]] = []
    if cpu_percent is not None:
        pairs.append(("cpu_usage_percent", cpu_percent, "percent"))
    if mem_percent is not None:
        pairs.append(("memory_usage_percent", mem_percent, "percent"))
    if mem_used_mb is not None:
        pairs.append(("memory_used_bytes", mem_used_mb * 1024 * 1024, "bytes"))
    if mem_total_mb is not None:
        pairs.append(("memory_total_bytes", mem_total_mb * 1024 * 1024, "bytes"))
        if mem_used_mb is not None:
            free_mb = max(mem_total_mb - mem_used_mb, 0)
            pairs.append(("memory_available_bytes", free_mb * 1024 * 1024, "bytes"))
    if disk_read_iops is not None:
        pairs.append(("disk_read_iops", disk_read_iops, "count"))
    if disk_write_iops is not None:
        pairs.append(("disk_write_iops", disk_write_iops, "count"))
    return [
        {
            "server_id": server.id,
            "metric_name": name,
            "value": float(val),
            "unit": unit,
            "labels": "vmware",
            "timestamp": ts,
        }
        for name, val, unit in pairs
    ]


def _write_vmware_metric_rows(
    db: Session,
    server: Server,
    *,
    cpu_percent: Optional[float],
    mem_percent: Optional[float],
    mem_used_mb: Optional[float],
    mem_total_mb: Optional[float],
    disk_read_iops: Optional[float] = None,
    disk_write_iops: Optional[float] = None,
) -> int:
    rows = _vmware_metric_row_dicts(
        server,
        cpu_percent=cpu_percent,
        mem_percent=mem_percent,
        mem_used_mb=mem_used_mb,
        mem_total_mb=mem_total_mb,
        disk_read_iops=disk_read_iops,
        disk_write_iops=disk_write_iops,
    )
    if not rows:
        return 0
    try:
        db.bulk_insert_mappings(MetricData, rows)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("VMware metric write failed server=%s: %s", server.name, e)
        return 0
    return len(rows)


def _flush_metric_mappings(db: Session, pending: List[Dict[str, Any]], chunk: int = 2000) -> int:
    """pending satırları chunk'lı bulk_insert ile yazar; yazılan adedi döner."""
    written = 0
    while len(pending) >= chunk:
        batch = pending[:chunk]
        del pending[:chunk]
        try:
            db.bulk_insert_mappings(MetricData, batch)
            db.commit()
            written += len(batch)
        except Exception as e:
            db.rollback()
            logger.warning("Metric bulk insert failed (%d rows): %s", len(batch), e)
    return written


class MetricSyncService:
    """Prometheus'tan metrikleri cekip TimescaleDB'ye yazar."""

    @staticmethod
    async def sync_server_metrics(db: Session, server: Server, minutes: int = 12) -> int:
        if not server.ip_address and not server.hostname:
            return 0
        if is_windows_server(server):
            instance = f"{server.ip_address}:{WINDOWS_EXPORTER_PORT}"
            metrics_list = WINDOWS_METRICS_TO_SYNC
            kind = "windows"
        else:
            metrics_list = METRICS_TO_SYNC
            kind = "linux"
            # IP:9100 veya hostname:9100 — sadece IP aramak IOPS=0 üretebiliyordu
            instance = f"{server.ip_address}:9100" if server.ip_address else None
            try:
                from app.services.monitoring.prometheus_metrics import (
                    get_node_exporter_up_map,
                    match_prometheus_instance,
                )
                up_map = get_node_exporter_up_map()
                matched, _up = match_prometheus_instance(
                    up_map,
                    ip=server.ip_address,
                    hostname=server.hostname,
                    name=server.name,
                )
                if matched:
                    instance = matched
            except Exception as e:
                logger.debug("prometheus instance match skip %s: %s", server.name, e)
            if not instance:
                return 0

        synced_count = 0
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=minutes)

        async with httpx.AsyncClient(timeout=20.0) as client:
            for query_tpl, db_metric_name, unit, category in metrics_list:
                query = apply_promql_job(query_tpl, kind=kind).replace("{instance}", instance)
                try:
                    resp = await client.get(
                        f"{settings.PROMETHEUS_URL}/api/v1/query_range",
                        params={"query": query, "start": start_time.timestamp(),
                                "end": end_time.timestamp(), "step": "60s"}
                    )
                    if resp.status_code != 200:
                        body = (resp.text or "")[:300]
                        logger.warning(
                            "Prometheus query_range HTTP %s for %s/%s: %s | query=%s",
                            resp.status_code,
                            server.name,
                            db_metric_name,
                            body,
                            query[:180],
                        )
                        continue
                    data = resp.json()
                    if data.get("status") != "success":
                        logger.warning(
                            "Prometheus query_range status=%s for %s/%s: %s",
                            data.get("status"),
                            server.name,
                            db_metric_name,
                            (data.get("error") or data.get("errorType") or "")[:300],
                        )
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

    # instance regex başına sunucu sayısı — çok büyük regex/URL boyutunu ve tek
    # Prometheus sorgusunun kapsamını makul tutar (10k+ sunucu ölçeğinde denendi).
    _BATCH_CHUNK_SIZE = 300

    @staticmethod
    async def sync_physical_servers_metrics_batch(
        db: Session, servers: List[Server], minutes: int = 12
    ) -> Dict[str, Any]:
        """Fiziksel sunucular için Prometheus metriklerini TOPLU sorgularla çeker.

        Eski yaklaşım (sync_server_metrics tek tek çağrılarak) sunucu başına ~38 ayrı
        PromQL isteği atıyordu — 10.000 sunucu ölçeğinde bu sunucu×metrik kadar istek
        demektir (yüz binlerce), bir tur saatlerce sürer ve metric_sync_interval_sec
        (varsayılan 600sn) içine asla sığmaz, veriler sürekli gecikmiş/eksik kalır.
        Burada bunun yerine HER METRİK için instance=~"a|b|c" regex'iyle birden çok
        sunucu TEK sorguda (chunk'lar halinde) çekilir — sorgu sayısı sunucu sayısından
        bağımsızlaşır (yalnız metrik_sayısı × chunk_sayısı kadar; örn. 10k sunucu /
        300 = 34 chunk × ~38 metrik ≈ 1300 istek, dakikalar içinde biter).
        """
        if not servers:
            return {"servers": 0, "metrics": 0}

        from app.services.monitoring.prometheus_metrics import (
            get_node_exporter_up_map,
            match_prometheus_instance,
        )

        linux_instances: Dict[str, Server] = {}
        windows_instances: Dict[str, Server] = {}
        up_map: Optional[Dict[str, str]] = None

        for srv in servers:
            if not srv.ip_address and not srv.hostname:
                continue
            if is_windows_server(srv):
                instance = f"{srv.ip_address}:{WINDOWS_EXPORTER_PORT}" if srv.ip_address else None
                if instance:
                    windows_instances.setdefault(instance, srv)
            else:
                if up_map is None:
                    up_map = get_node_exporter_up_map()
                instance = f"{srv.ip_address}:9100" if srv.ip_address else None
                try:
                    matched, _up = match_prometheus_instance(
                        up_map, ip=srv.ip_address, hostname=srv.hostname, name=srv.name,
                    )
                    if matched:
                        instance = matched
                except Exception as e:
                    logger.debug("batch instance match skip %s: %s", srv.name, e)
                if instance:
                    linux_instances.setdefault(instance, srv)

        total = 0
        synced_ids: set = set()
        pending: List[Dict[str, Any]] = []
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=minutes)
        chunk_size = MetricSyncService._BATCH_CHUNK_SIZE

        async with httpx.AsyncClient(timeout=60.0) as client:
            for kind, instance_map, metrics_list in (
                ("linux", linux_instances, METRICS_TO_SYNC),
                ("windows", windows_instances, WINDOWS_METRICS_TO_SYNC),
            ):
                if not instance_map:
                    continue
                instance_names = list(instance_map.keys())
                for c_start in range(0, len(instance_names), chunk_size):
                    chunk = instance_names[c_start:c_start + chunk_size]
                    regex = "|".join(_promql_regex_escape(i) for i in chunk)
                    for query_tpl, db_metric_name, unit, category in metrics_list:
                        query = apply_promql_job(query_tpl, kind=kind)
                        query = query.replace('instance="{instance}"', f'instance=~"{regex}"')
                        try:
                            # POST kullanılır — GET'e göre büyük regex/URL uzunluk
                            # sınırlarına takılmaz (bkz. Prometheus HTTP API).
                            resp = await client.post(
                                f"{settings.PROMETHEUS_URL}/api/v1/query_range",
                                data={
                                    "query": query,
                                    "start": start_time.timestamp(),
                                    "end": end_time.timestamp(),
                                    "step": "60s",
                                },
                            )
                            if resp.status_code != 200:
                                logger.warning(
                                    "Prometheus batch query_range HTTP %s for %s (chunk=%d): %s",
                                    resp.status_code, db_metric_name, len(chunk),
                                    (resp.text or "")[:200],
                                )
                                continue
                            data = resp.json()
                            if data.get("status") != "success":
                                logger.warning(
                                    "Prometheus batch query_range status=%s for %s: %s",
                                    data.get("status"), db_metric_name,
                                    (data.get("error") or data.get("errorType") or "")[:200],
                                )
                                continue
                            for result in data.get("data", {}).get("result", []):
                                inst_label = (result.get("metric") or {}).get("instance")
                                srv = instance_map.get(inst_label)
                                if not srv:
                                    continue
                                for ts, val in result.get("values", []):
                                    try:
                                        float_val = float(val)
                                        if float_val != float_val or float_val in (float("inf"), float("-inf")):
                                            continue
                                        pending.append({
                                            "server_id": srv.id,
                                            "metric_name": db_metric_name,
                                            "value": float_val,
                                            "unit": unit,
                                            "labels": category,
                                            "timestamp": datetime.utcfromtimestamp(float(ts)),
                                        })
                                        synced_ids.add(srv.id)
                                    except Exception:
                                        pass
                            total += _flush_metric_mappings(db, pending)
                        except Exception as e:
                            logger.debug("Batch metric sync error %s (chunk=%d): %s", db_metric_name, len(chunk), e)
                            try:
                                db.rollback()
                            except Exception:
                                pass

        total += _flush_metric_mappings(db, pending)
        if pending:
            try:
                db.bulk_insert_mappings(MetricData, pending)
                db.commit()
                total += len(pending)
                pending.clear()
            except Exception as e:
                db.rollback()
                logger.warning("Metric bulk insert final flush failed: %s", e)

        return {"servers": len(synced_ids), "metrics": total}

    @staticmethod
    def sync_vmware_fallback_batch(db: Session, servers: List[Server]) -> Dict[str, Any]:
        """
        VM'ler için metrik kaynağı her zaman vCenter'dır (Prometheus/node_exporter
        kurulu olsa bile) — QuickStats → metric_data (cpu/mem). Disk IOPS
        get_all_vm_perf_io ile toplu alınır (VM başına SOAP yok).
        """
        from app.models.hypervisor import Hypervisor, HypervisorType
        from app.services.vmware.vcenter_client import VCenterClient

        candidates = [s for s in servers if is_vm(s) and s.hypervisor_id]
        if not candidates:
            return {"servers": 0, "metrics": 0}

        by_hyp: Dict[int, List[Server]] = {}
        for s in candidates:
            by_hyp.setdefault(int(s.hypervisor_id), []).append(s)

        total_metrics = 0
        synced_servers = 0

        for hyp_id, group in by_hyp.items():
            hyp = db.query(Hypervisor).filter(Hypervisor.id == hyp_id).first()
            if not hyp or hyp.hypervisor_type != HypervisorType.VMWARE:
                continue
            # ip_address öncelikli — hostname alanına yanlışlıkla görünen ad
            # (ör. "Vcenter datatem") girilmiş olabilir; inventory_sync_service
            # ile aynı öncelik sırası kullanılmalı.
            vc_host = (hyp.ip_address or hyp.hostname or "").strip()
            from app.services.hypervisor_credentials import hv_password
            vc_pass = hv_password(hyp)
            if not (vc_host and hyp.username and vc_pass):
                continue
            try:
                vc = VCenterClient(
                    host=vc_host,
                    username=hyp.username,
                    password=vc_pass,
                    port=hyp.port or 443,
                )
                if not vc.login():
                    logger.warning("VMware metric fallback: login failed %s", hyp.name)
                    continue
                try:
                    live = vc.get_all_vm_live_stats() or []
                    by_ref = {str(x.get("vm_ref")): x for x in live if x.get("vm_ref")}
                    by_name = {(x.get("name") or "").lower(): x for x in live if x.get("name")}

                    # Önce ref çözümle, sonra toplu IOPS
                    resolved: List[Tuple[Server, Optional[dict], Optional[str]]] = []
                    perf_refs: List[str] = []
                    for srv in group:
                        stats = None
                        vm_id = srv.hypervisor_vm_id
                        if vm_id and str(vm_id) in by_ref:
                            stats = by_ref[str(vm_id)]
                        elif (srv.name or "").lower() in by_name:
                            stats = by_name[(srv.name or "").lower()]
                        elif vm_id:
                            qs = vc.get_vm_quick_stats(str(vm_id))
                            if qs:
                                stats = qs
                        if not stats:
                            continue
                        perf_vm = srv.hypervisor_vm_id or (
                            stats.get("vm_ref") if isinstance(stats, dict) else None
                        )
                        if perf_vm:
                            perf_refs.append(str(perf_vm))
                        resolved.append((srv, stats, str(perf_vm) if perf_vm else None))

                    io_by_ref: Dict[str, Dict] = {}
                    if perf_refs:
                        try:
                            io_by_ref = vc.get_all_vm_perf_io(list(dict.fromkeys(perf_refs))) or {}
                        except Exception as ie:
                            logger.debug("VMware batch disk iops skip hyp=%s: %s", hyp_id, ie)

                    now = datetime.utcnow()
                    pending_rows: List[Dict[str, Any]] = []
                    for srv, stats, perf_vm in resolved:
                        cpu_p, mem_p, mu, mt = _vmware_cpu_mem_from_live(stats)
                        # Fleet live payload'da memorySizeMB yok → tek VM quickStats dene
                        if (cpu_p is None or mem_p is None or mt is None) and srv.hypervisor_vm_id:
                            qs = vc.get_vm_quick_stats(str(srv.hypervisor_vm_id))
                            if qs:
                                c2, m2, u2, t2 = _vmware_cpu_mem_from_live(qs)
                                cpu_p = cpu_p if cpu_p is not None else c2
                                mem_p = mem_p if mem_p is not None else m2
                                mu = mu if mu is not None else u2
                                mt = mt if mt is not None else t2

                        read_iops = write_iops = None
                        if perf_vm and perf_vm in io_by_ref:
                            io = io_by_ref[perf_vm]
                            read_iops = io.get("disk_read_iops")
                            write_iops = io.get("disk_write_iops")

                        rows = _vmware_metric_row_dicts(
                            srv,
                            cpu_percent=cpu_p,
                            mem_percent=mem_p,
                            mem_used_mb=mu,
                            mem_total_mb=mt,
                            disk_read_iops=read_iops,
                            disk_write_iops=write_iops,
                            now=now,
                        )
                        if rows:
                            pending_rows.extend(rows)
                            synced_servers += 1

                    if pending_rows:
                        try:
                            # chunk'lı yaz
                            while pending_rows:
                                batch = pending_rows[:2000]
                                del pending_rows[:2000]
                                db.bulk_insert_mappings(MetricData, batch)
                                db.commit()
                                total_metrics += len(batch)
                        except Exception as e:
                            db.rollback()
                            logger.warning("VMware metric bulk write failed hyp=%s: %s", hyp_id, e)
                finally:
                    try:
                        vc.logout()
                    except Exception:
                        pass
            except Exception as e:
                logger.error("VMware metric fallback hyp=%s: %s", hyp_id, e, exc_info=True)

        logger.info(
            "VMware metric fallback: %s sunucu, %s kayit (batch IOPS)",
            synced_servers, total_metrics,
        )
        return {"servers": synced_servers, "metrics": total_metrics}

    @staticmethod
    async def sync_all_servers_metrics(db: Session, minutes: int = 12) -> Dict[str, Any]:
        """Metrik kaynağı sunucu tipine göre ayrılır — ikisi asla karışmaz:
          - Fiziksel sunucular (VM olmayan): Prometheus / node_exporter / windows_exporter
          - VM'ler (hypervisor_id dolu veya server_type=VIRTUAL): daima vCenter QuickStats
        Bir VM'de node_exporter/windows_exporter çalışıyor olsa bile metrikleri
        vCenter'dan alınır; Prometheus'a hiç sorgu atılmaz.
        """
        candidates = db.query(Server).filter(Server.status == "ONLINE").all()

        physical_servers: List[Server] = []
        vm_servers: List[Server] = []
        for s in candidates:
            if is_vm(s):
                if s.hypervisor_id:
                    vm_servers.append(s)
                continue
            if is_windows_server(s):
                if s.ai_ready and s.windows_exporter_installed:
                    physical_servers.append(s)
            elif s.ai_ready or getattr(s, "node_exporter_running", False):
                physical_servers.append(s)

        # dedupe by id
        seen = set()
        uniq = []
        for s in physical_servers:
            if s.id in seen:
                continue
            seen.add(s.id)
            uniq.append(s)
        physical_servers = uniq

        total, synced_servers = 0, 0
        if physical_servers:
            try:
                phys_stats = await MetricSyncService.sync_physical_servers_metrics_batch(
                    db, physical_servers, minutes
                )
                total += phys_stats.get("metrics", 0)
                synced_servers += phys_stats.get("servers", 0)
            except Exception as e:
                logger.error(f"Physical metric batch sync failed: {e}", exc_info=True)

        vm_stats = {"servers": 0, "metrics": 0}
        if vm_servers:
            try:
                # sync_vmware_fallback_batch senkron/bloklayan (requests) vCenter
                # çağrıları yapar — event loop'u kilitlememesi için thread pool'da
                # çalıştırılır (bkz. _periodic_esx_metric_sync'teki aynı desen).
                loop = asyncio.get_event_loop()
                vm_stats = await loop.run_in_executor(
                    None, MetricSyncService.sync_vmware_fallback_batch, db, vm_servers
                )
                total += vm_stats.get("metrics", 0)
                synced_servers += vm_stats.get("servers", 0)
            except Exception as e:
                logger.error(f"VMware metric sync batch failed: {e}", exc_info=True)

        total_servers = len(physical_servers) + len(vm_servers)
        logger.info(
            f"Metric sync: {synced_servers}/{total_servers} sunucu, {total} kayit "
            f"(fiziksel={len(physical_servers)} Prometheus, vm={len(vm_servers)} vCenter)"
        )
        return {
            "total_servers": total_servers,
            "synced_servers": synced_servers,
            "total_metrics": total,
            "vmware_fallback_servers": vm_stats.get("servers", 0),
            "vmware_fallback_metrics": vm_stats.get("metrics", 0),
        }

    @staticmethod
    def get_metric_categories() -> Dict[str, List[str]]:
        """Metrik kategorileri ve adlari"""
        cats: Dict[str, List[str]] = {}
        for _, name, _, cat in METRICS_TO_SYNC:
            cats.setdefault(cat, []).append(name)
        return cats
