"""
Prometheus Metrics Service - Tüm metrikleri çekmek ve AI'a context sağlamak için
"""
import httpx
import logging
from typing import Dict, List, Optional, Any
from app.core.config import settings, promql_job_matcher

logger = logging.getLogger(__name__)


def node_exporter_up_for_server(server_ip: Optional[str], hostname: Optional[str]) -> bool:
    """Prometheus'tan bu sunucuda node-exporter'ın up olup olmadığını kontrol et (sync)."""
    if not server_ip and not hostname:
        return False
    try:
        job = promql_job_matcher(kind="linux")
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                f"{settings.PROMETHEUS_URL}/api/v1/query",
                params={"query": f'up{{{job}}}'},
            )
            if resp.status_code != 200:
                return False
            data = resp.json()
            if data.get("status") != "success":
                return False
            for r in data.get("data", {}).get("result", []):
                instance = (r.get("metric") or {}).get("instance", "")
                value = r.get("value")
                if value is None or len(value) < 2:
                    continue
                if str(value[1]) != "1":
                    continue
                if server_ip and (instance == f"{server_ip}:9100" or instance.startswith(server_ip + ":")):
                    return True
                if hostname and (instance.startswith(hostname) or hostname in instance):
                    return True
    except Exception as e:
        logger.debug(f"Prometheus node_exporter up check hatası: {e}")
    return False


def get_node_exporter_up_map() -> Dict[str, str]:
    """Prometheus up{job=...} sonuçlarını instance -> '0'|'1' map olarak döner."""
    result_map: Dict[str, str] = {}
    try:
        job = promql_job_matcher(kind="linux")
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                f"{settings.PROMETHEUS_URL}/api/v1/query",
                params={"query": f'up{{{job}}}'},
            )
            if resp.status_code != 200:
                return result_map
            data = resp.json()
            if data.get("status") != "success":
                return result_map
            for r in data.get("data", {}).get("result", []):
                instance = (r.get("metric") or {}).get("instance", "")
                value = r.get("value")
                if instance and value and len(value) >= 2:
                    result_map[instance] = str(value[1])
    except Exception as e:
        logger.debug(f"Prometheus up map hatası: {e}")
    return result_map


def sync_node_exporter_running_from_prometheus(db) -> Dict[str, int]:
    """DB'deki node_exporter_running bayrağını Prometheus up durumuna göre günceller."""
    from app.models.server import Server

    up_map = get_node_exporter_up_map()
    updated = cleared = promoted = 0

    servers = db.query(Server).filter(
        Server.ip_address.isnot(None),
        Server.ip_address != "",
    ).all()

    for server in servers:
        instance = f"{server.ip_address.strip()}:9100"
        prom_up = up_map.get(instance) == "1"

        if prom_up:
            changed = False
            if not server.node_exporter_installed:
                server.node_exporter_installed = True
                changed = True
            if not server.node_exporter_running:
                server.node_exporter_running = True
                changed = True
            if changed:
                promoted += 1
                updated += 1
            continue

        # Prometheus'tan veri yok — kurulu sayılan ama çalışmıyor olarak işaretle
        if server.node_exporter_installed and server.node_exporter_running:
            server.node_exporter_running = False
            cleared += 1
            updated += 1

    if updated:
        db.commit()

    return {
        "updated": updated,
        "promoted": promoted,
        "cleared": cleared,
        "live": sum(1 for v in up_map.values() if v == "1"),
        "targets": len(up_map),
    }


# ── Windows Exporter (node_exporter'ın Windows eşleniği, port 9182) ─────────

WINDOWS_EXPORTER_PORT = 9182
WINDOWS_EXPORTER_JOB = "windows-exporter"  # varsayılan; runtime'da settings.PROMETHEUS_WINDOWS_JOBS kullanılır


def get_windows_exporter_up_map() -> Dict[str, str]:
    """Prometheus up{job=windows...} sonuçlarını instance -> '0'|'1' map olarak döner."""
    result_map: Dict[str, str] = {}
    try:
        job = promql_job_matcher(kind="windows")
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                f"{settings.PROMETHEUS_URL}/api/v1/query",
                params={"query": f'up{{{job}}}'},
            )
            if resp.status_code != 200:
                return result_map
            data = resp.json()
            if data.get("status") != "success":
                return result_map
            for r in data.get("data", {}).get("result", []):
                instance = (r.get("metric") or {}).get("instance", "")
                value = r.get("value")
                if instance and value and len(value) >= 2:
                    result_map[instance] = str(value[1])
    except Exception as e:
        logger.debug(f"Prometheus windows-exporter up map hatası: {e}")
    return result_map


def windows_exporter_up_for_server(server_ip: Optional[str], hostname: Optional[str]) -> bool:
    """Prometheus'tan bu sunucuda windows_exporter'ın up olup olmadığını kontrol et (sync)."""
    if not server_ip and not hostname:
        return False
    up_map = get_windows_exporter_up_map()
    if server_ip:
        instance = f"{server_ip}:{WINDOWS_EXPORTER_PORT}"
        if up_map.get(instance) == "1":
            return True
    if hostname:
        for inst, val in up_map.items():
            if val == "1" and (inst.startswith(hostname) or hostname in inst):
                return True
    return False


def sync_windows_exporter_running_from_prometheus(db) -> Dict[str, int]:
    """DB'deki windows_exporter_running bayrağını Prometheus up durumuna göre günceller."""
    from app.models.server import Server

    up_map = get_windows_exporter_up_map()
    updated = cleared = promoted = 0

    servers = db.query(Server).filter(
        Server.ip_address.isnot(None),
        Server.ip_address != "",
    ).all()

    for server in servers:
        instance = f"{server.ip_address.strip()}:{WINDOWS_EXPORTER_PORT}"
        prom_up = up_map.get(instance) == "1"

        if prom_up:
            changed = False
            if not server.windows_exporter_installed:
                server.windows_exporter_installed = True
                changed = True
            if not server.windows_exporter_running:
                server.windows_exporter_running = True
                changed = True
            if changed:
                promoted += 1
                updated += 1
            continue

        if server.windows_exporter_installed and server.windows_exporter_running:
            server.windows_exporter_running = False
            cleared += 1
            updated += 1

    if updated:
        db.commit()

    return {
        "updated": updated,
        "promoted": promoted,
        "cleared": cleared,
        "live": sum(1 for v in up_map.values() if v == "1"),
        "targets": len(up_map),
    }


def sync_windows_exporter_targets_from_db(db, reload: bool = True) -> Dict[str, Any]:
    """
    DB'deki kurulu Windows sunuculardan windows_exporter Prometheus target dosyasını
    yeniden oluşturur (node_exporter'daki sync_node_exporter_targets_from_db eşleniği).
    """
    from app.models.server import Server
    from app.services.monitoring.prometheus_target_manager import PrometheusTargetManager

    eligible = db.query(Server).filter(
        Server.windows_exporter_installed == True,  # noqa: E712
        Server.ip_address.isnot(None),
        Server.ip_address != "",
    ).all()

    by_instance: Dict[str, object] = {}
    duplicate_names: List[str] = []

    for server in eligible:
        instance = f"{server.ip_address.strip()}:{WINDOWS_EXPORTER_PORT}"
        if instance in by_instance:
            prev = by_instance[instance]
            winner = _pick_canonical_monitoring_server([prev, server])
            loser = server if winner is prev else prev
            duplicate_names.append(getattr(loser, "name", "?"))
            by_instance[instance] = winner
        else:
            by_instance[instance] = server

    new_targets = []
    for instance, server in sorted(by_instance.items(), key=lambda x: (x[1].name or "").lower()):
        new_targets.append({
            "targets": [instance],
            "labels": {
                "server_id": str(server.id),
                "server_name": server.name,
                "job": WINDOWS_EXPORTER_JOB,
            },
        })

    tm = PrometheusTargetManager(_windows_targets_file_path())
    old_targets = tm.load_targets()
    old_instances = {
        t.get("targets", [])[0]
        for t in old_targets
        if t.get("targets")
    }
    new_instances = set(by_instance.keys())

    tm.rebuild_targets(new_targets)

    stats = {
        "targets_before": len(old_targets),
        "targets_after": len(new_targets),
        "servers_eligible": len(eligible),
        "unique_instances": len(new_targets),
        "removed_orphans": len(old_instances - new_instances),
        "added": len(new_instances - old_instances),
        "duplicate_servers_skipped": duplicate_names,
        "reloaded": False,
    }

    if reload:
        stats["reloaded"] = tm.reload_prometheus_sync()

    logger.info(
        "Windows exporter target sync: %s -> %s hedef (%s yetim kaldırıldı)",
        stats["targets_before"],
        stats["targets_after"],
        stats["removed_orphans"],
    )
    return stats


def _windows_targets_file_path() -> str:
    import os
    if os.path.exists("/prometheus/targets"):
        return "/prometheus/targets/windows_exporter_targets.json"
    if os.path.exists("/etc/prometheus/targets"):
        return "/etc/prometheus/targets/windows_exporter_targets.json"
    return "/prometheus/targets/windows_exporter_targets.json"


def _pick_canonical_monitoring_server(servers: list):
    """Aynı IP için tek kayıt: hypervisor bağlı olan, yoksa en yüksek id."""
    def score(s):
        return (1 if getattr(s, "hypervisor_id", None) else 0, s.id or 0)
    return max(servers, key=score)


def sync_node_exporter_targets_from_db(db, reload: bool = True) -> Dict[str, Any]:
    """
    DB'deki kurulu ONLINE sunuculardan Prometheus target dosyasını yeniden oluşturur.
    Silinen sunucuların hedefleri kaldırılır; ad/IP değişiklikleri etiketlere yansır.
    Aynı IP'de birden fazla kayıt varsa tek hedef kalır (hypervisor kaydı öncelikli).
    """
    from app.models.server import Server
    from app.services.monitoring.prometheus_target_manager import PrometheusTargetManager

    eligible = db.query(Server).filter(
        Server.node_exporter_installed == True,  # noqa: E712
        Server.status == "ONLINE",
        Server.ip_address.isnot(None),
        Server.ip_address != "",
    ).all()

    by_instance: Dict[str, object] = {}
    duplicate_names: List[str] = []

    for server in eligible:
        instance = f"{server.ip_address.strip()}:9100"
        if instance in by_instance:
            prev = by_instance[instance]
            winner = _pick_canonical_monitoring_server([prev, server])
            loser = server if winner is prev else prev
            duplicate_names.append(getattr(loser, "name", "?"))
            by_instance[instance] = winner
        else:
            by_instance[instance] = server

    new_targets = []
    for instance, server in sorted(by_instance.items(), key=lambda x: x[1].name.lower()):
        new_targets.append({
            "targets": [instance],
            "labels": {
                "server_id": str(server.id),
                "server_name": server.name,
                "job": "node-exporter",
            },
        })

    tm = PrometheusTargetManager()
    old_targets = tm.load_targets()
    old_instances = {
        t.get("targets", [])[0]
        for t in old_targets
        if t.get("targets")
    }
    new_instances = set(by_instance.keys())

    tm.rebuild_targets(new_targets)

    stats = {
        "targets_before": len(old_targets),
        "targets_after": len(new_targets),
        "servers_eligible": len(eligible),
        "unique_instances": len(new_targets),
        "removed_orphans": len(old_instances - new_instances),
        "added": len(new_instances - old_instances),
        "duplicate_servers_skipped": duplicate_names,
        "reloaded": False,
    }

    if reload:
        stats["reloaded"] = tm.reload_prometheus_sync()

    logger.info(
        "Prometheus target sync: %s -> %s hedef (%s yetim kaldırıldı)",
        stats["targets_before"],
        stats["targets_after"],
        stats["removed_orphans"],
    )
    return stats


class PrometheusMetricsService:
    """Prometheus metriklerini çekmek ve analiz etmek için servis"""
    
    def __init__(self, prometheus_url: Optional[str] = None):
        self.prometheus_url = prometheus_url or settings.PROMETHEUS_URL
    
    async def get_available_metrics(self) -> List[str]:
        """Mevcut tüm metrikleri listele"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.prometheus_url}/api/v1/label/__name__/values")
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        return data.get("data", [])
        except Exception as e:
            logger.error(f"Metrik listesi alınamadı: {e}")
        return []
    
    async def get_node_exporter_metrics(self) -> List[str]:
        """Node Exporter metriklerini filtrele"""
        all_metrics = await self.get_available_metrics()
        return [m for m in all_metrics if m.startswith("node_")]
    
    async def query_metric(self, query: str) -> Optional[Dict[str, Any]]:
        """Prometheus query çalıştır"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.prometheus_url}/api/v1/query",
                    params={"query": query}
                )
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            logger.error(f"Query hatası: {e}")
        return None
    
    async def get_system_overview(self) -> Dict[str, Any]:
        """Sistem genel bakış metrikleri"""
        overview = {
            "cpu": {},
            "memory": {},
            "disk": {},
            "network": {},
            "load": {}
        }
        
        try:
            # CPU metrikleri
            cpu_query = "100 - (avg(rate(node_cpu_seconds_total{mode=\"idle\"}[15m])) * 100)"
            cpu_data = await self.query_metric(cpu_query)
            if cpu_data and cpu_data.get("status") == "success":
                results = cpu_data.get("data", {}).get("result", [])
                if results:
                    overview["cpu"]["average"] = float(results[0]["value"][1])
            
            # Memory metrikleri
            memory_query = '(1 - (avg(node_memory_MemAvailable_bytes) / avg(node_memory_MemTotal_bytes))) * 100'
            memory_data = await self.query_metric(memory_query)
            if memory_data and memory_data.get("status") == "success":
                results = memory_data.get("data", {}).get("result", [])
                if results:
                    overview["memory"]["usage_percent"] = float(results[0]["value"][1])
            
            # Disk metrikleri
            disk_query = '(1 - (avg(node_filesystem_avail_bytes{mountpoint="/"}) / avg(node_filesystem_size_bytes{mountpoint="/"}))) * 100'
            disk_data = await self.query_metric(disk_query)
            if disk_data and disk_data.get("status") == "success":
                results = disk_data.get("data", {}).get("result", [])
                if results:
                    overview["disk"]["usage_percent"] = float(results[0]["value"][1])
            
            # Load average
            load_query = 'avg(node_load1)'
            load_data = await self.query_metric(load_query)
            if load_data and load_data.get("status") == "success":
                results = load_data.get("data", {}).get("result", [])
                if results:
                    overview["load"]["1min"] = float(results[0]["value"][1])
            
        except Exception as e:
            logger.error(f"Sistem overview hatası: {e}")
        
        return overview
    
    async def get_server_metrics(self, server_ip: Optional[str] = None) -> Dict[str, Any]:
        """Belirli bir sunucu veya tüm sunucular için metrikler"""
        metrics = {}
        
        try:
            # Instance filter
            instance_filter = f'{{instance="{server_ip}:9100"}}' if server_ip else ""
            
            # CPU
            cpu_query = f'100 - (avg(rate(node_cpu_seconds_total{{mode="idle"}}{instance_filter}[15m])) * 100)'
            cpu_data = await self.query_metric(cpu_query)
            if cpu_data and cpu_data.get("status") == "success":
                results = cpu_data.get("data", {}).get("result", [])
                metrics["cpu_usage"] = [{"instance": r.get("metric", {}).get("instance"), "value": float(r["value"][1])} for r in results]
            
            # Memory
            memory_query = f'(1 - (node_memory_MemAvailable_bytes{instance_filter} / node_memory_MemTotal_bytes{instance_filter})) * 100'
            memory_data = await self.query_metric(memory_query)
            if memory_data and memory_data.get("status") == "success":
                results = memory_data.get("data", {}).get("result", [])
                metrics["memory_usage"] = [{"instance": r.get("metric", {}).get("instance"), "value": float(r["value"][1])} for r in results]
            
            # Disk
            disk_query = f'(1 - (node_filesystem_avail_bytes{{mountpoint="/"}}{instance_filter} / node_filesystem_size_bytes{{mountpoint="/"}}{instance_filter})) * 100'
            disk_data = await self.query_metric(disk_query)
            if disk_data and disk_data.get("status") == "success":
                results = disk_data.get("data", {}).get("result", [])
                metrics["disk_usage"] = [{"instance": r.get("metric", {}).get("instance"), "value": float(r["value"][1])} for r in results]
            
        except Exception as e:
            logger.error(f"Sunucu metrikleri hatası: {e}")
        
        return metrics
    
    async def get_metrics_context_for_ai(self, message: str) -> str:
        """AI için metrik context'i oluştur — Node Exporter verisini öncelikle kullan."""
        context = ""
        ml = message.lower()

        want_perf    = any(kw in ml for kw in ['performans', 'performance', 'cpu', 'memory', 'ram',
                                                'bellek', 'disk', 'kullanım', 'usage', 'yüksek', 'yük'])
        want_network = any(kw in ml for kw in ['network', 'ağ', 'bandwidth', 'trafik', 'traffic'])
        want_uptime  = any(kw in ml for kw in ['uptime', 'çalışma süresi', 'ne kadar', 'boot', 'restart'])

        # Herhangi bir sunucu sorusunda (veya fallback olarak) genel özet her zaman verilir
        try:
            overview = await self.get_system_overview()
            context += "\n📊 Sistem Genel Bakış (Prometheus/Node Exporter):\n"
            if overview.get("cpu", {}).get("average") is not None:
                context += f"  - Ortalama CPU: {overview['cpu']['average']:.2f}%\n"
            if overview.get("memory", {}).get("usage_percent") is not None:
                context += f"  - Ortalama RAM: {overview['memory']['usage_percent']:.2f}%\n"
            if overview.get("disk", {}).get("usage_percent") is not None:
                context += f"  - Ortalama Disk: {overview['disk']['usage_percent']:.2f}%\n"
            if overview.get("load", {}).get("1min") is not None:
                context += f"  - Load Average (1 dk): {overview['load']['1min']:.2f}\n"
        except Exception:
            pass

        # Sunucu bazlı detaylı metrikler
        if want_perf:
            try:
                metrics = await self.get_server_metrics()
                if any(metrics.get(k) for k in ("cpu_usage", "memory_usage", "disk_usage")):
                    context += "\n📈 Sunucu Bazlı Metrikler (Node Exporter):\n"
                    if metrics.get("cpu_usage"):
                        context += "  CPU:\n"
                        for item in metrics["cpu_usage"][:10]:
                            context += f"    {item['instance']}: {item['value']:.1f}%\n"
                    if metrics.get("memory_usage"):
                        context += "  RAM:\n"
                        for item in metrics["memory_usage"][:10]:
                            context += f"    {item['instance']}: {item['value']:.1f}%\n"
                    if metrics.get("disk_usage"):
                        context += "  Disk:\n"
                        for item in metrics["disk_usage"][:10]:
                            context += f"    {item['instance']}: {item['value']:.1f}%\n"
            except Exception:
                pass

        # Network trafiği
        if want_network:
            try:
                network_data = await self.query_metric('rate(node_network_receive_bytes_total{device!="lo"}[5m])')
                if network_data and network_data.get("status") == "success":
                    results = network_data["data"].get("result", [])
                    if results:
                        context += "\n🌐 Network (alım, son 5 dk):\n"
                        for r in results[:8]:
                            instance = r.get("metric", {}).get("instance", "?")
                            device   = r.get("metric", {}).get("device", "?")
                            value    = float(r["value"][1])
                            context += f"  {instance} [{device}]: {value/1024:.1f} KB/s\n"
            except Exception:
                pass

        # Uptime
        if want_uptime:
            try:
                uptime_data = await self.query_metric('node_boot_time_seconds')
                if uptime_data and uptime_data.get("status") == "success":
                    from datetime import datetime as _dt
                    results = uptime_data["data"].get("result", [])
                    if results:
                        context += "\n⏱️ Uptime:\n"
                        for r in results[:10]:
                            instance = r.get("metric", {}).get("instance", "?")
                            days = (_dt.now().timestamp() - float(r["value"][1])) / 86400
                            context += f"  {instance}: {days:.1f} gün\n"
            except Exception:
                pass

        return context
