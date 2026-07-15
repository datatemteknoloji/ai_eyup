"""
Prometheus -> TimescaleDB metric sync - Genisletilmis versiyon
Her 10 dakikada background task olarak calisir.

Node-exporter yoksa (veya Prometheus boş dönüyorsa) VMware QuickStats ile
sanal makine CPU/RAM snapshot'ı metric_data'ya yazılır.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
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


def _write_vmware_metric_rows(
    db: Session,
    server: Server,
    *,
    cpu_percent: Optional[float],
    mem_percent: Optional[float],
    mem_used_mb: Optional[float],
    mem_total_mb: Optional[float],
) -> int:
    now = datetime.utcnow()
    n = 0
    rows = []
    if cpu_percent is not None:
        rows.append(("cpu_usage_percent", cpu_percent, "percent"))
    if mem_percent is not None:
        rows.append(("memory_usage_percent", mem_percent, "percent"))
    if mem_used_mb is not None:
        rows.append(("memory_used_bytes", mem_used_mb * 1024 * 1024, "bytes"))
    if mem_total_mb is not None:
        rows.append(("memory_total_bytes", mem_total_mb * 1024 * 1024, "bytes"))
        free_mb = None
        if mem_used_mb is not None:
            free_mb = max(mem_total_mb - mem_used_mb, 0)
        if free_mb is not None:
            rows.append(("memory_available_bytes", free_mb * 1024 * 1024, "bytes"))
    for name, val, unit in rows:
        db.add(MetricData(
            server_id=server.id,
            metric_name=name,
            value=float(val),
            unit=unit,
            labels="vmware",
            timestamp=now,
        ))
        n += 1
    if n:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning("VMware metric write failed server=%s: %s", server.name, e)
            return 0
    return n


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
    def sync_vmware_fallback_batch(db: Session, servers: List[Server]) -> Dict[str, Any]:
        """
        Node-exporter / Prometheus verisi olmayan VIRTUAL sunucular için
        vCenter QuickStats → metric_data (cpu/mem). Disk/IOPS QuickStats'ta yok.
        """
        from app.models.hypervisor import Hypervisor, HypervisorType
        from app.services.vmware.vcenter_client import VCenterClient

        candidates = [
            s for s in servers
            if (s.server_type or "").upper() == "VIRTUAL"
            and s.hypervisor_id
            and not is_windows_server(s)
            and (not getattr(s, "node_exporter_running", False))
        ]
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
            vc_pass = hyp.password or (hyp.connection_config or {}).get("password", "")
            if not (hyp.hostname and hyp.username and vc_pass):
                continue
            try:
                vc = VCenterClient(
                    host=hyp.hostname,
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

                        wrote = _write_vmware_metric_rows(
                            db, srv,
                            cpu_percent=cpu_p,
                            mem_percent=mem_p,
                            mem_used_mb=mu,
                            mem_total_mb=mt,
                        )
                        if wrote:
                            total_metrics += wrote
                            synced_servers += 1
                finally:
                    try:
                        vc.logout()
                    except Exception:
                        pass
            except Exception as e:
                logger.error("VMware metric fallback hyp=%s: %s", hyp_id, e, exc_info=True)

        logger.info(
            "VMware metric fallback: %s sunucu, %s kayit (node_exporter yok)",
            synced_servers, total_metrics,
        )
        return {"servers": synced_servers, "metrics": total_metrics}

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
        need_vmware: List[Server] = []
        for srv in servers:
            try:
                count = await MetricSyncService.sync_server_metrics(db, srv, minutes)
                if count > 0:
                    total += count
                    synced_servers += 1
                elif not is_windows_server(srv) and (srv.server_type or "").upper() == "VIRTUAL":
                    # Prometheus boş veya node_exporter yok → VMware adayı
                    if not getattr(srv, "node_exporter_running", False) or count == 0:
                        need_vmware.append(srv)
            except Exception as e:
                logger.error(f"Metric sync failed {srv.name}: {e}")
                if not is_windows_server(srv) and (srv.server_type or "").upper() == "VIRTUAL":
                    need_vmware.append(srv)

        # ai_ready olmayan VIRTUAL + hypervisor bağlı ama ONLINE VM'ler de fallback alsın
        extra = db.query(Server).filter(
            Server.status == "ONLINE",
            Server.server_type == "VIRTUAL",
            Server.hypervisor_id.isnot(None),
        ).all()
        seen = {s.id for s in need_vmware}
        for s in extra:
            if s.id in seen or is_windows_server(s):
                continue
            if getattr(s, "node_exporter_running", False):
                continue
            need_vmware.append(s)
            seen.add(s.id)

        vm_stats = {"servers": 0, "metrics": 0}
        if need_vmware:
            try:
                vm_stats = MetricSyncService.sync_vmware_fallback_batch(db, need_vmware)
                total += vm_stats.get("metrics", 0)
                synced_servers += vm_stats.get("servers", 0)
            except Exception as e:
                logger.error(f"VMware metric fallback batch failed: {e}", exc_info=True)

        logger.info(
            f"Metric sync: {synced_servers}/{len(servers)} sunucu, {total} kayit "
            f"(vmware_fallback={vm_stats.get('servers', 0)})"
        )
        return {
            "total_servers": len(servers),
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
