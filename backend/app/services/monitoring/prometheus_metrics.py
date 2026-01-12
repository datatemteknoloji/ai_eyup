"""
Prometheus Metrics Service - Tüm metrikleri çekmek ve AI'a context sağlamak için
"""
import httpx
import logging
from typing import Dict, List, Optional, Any
from app.core.config import settings

logger = logging.getLogger(__name__)

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
        """AI için metrik context'i oluştur"""
        context = ""
        
        # Mesajdan hangi metriklerin istenildiğini anla
        message_lower = message.lower()
        
        # Sistem genel bakış
        if any(kw in message_lower for kw in ['genel', 'overview', 'durum', 'durumu', 'özet', 'summary']):
            overview = await self.get_system_overview()
            context += "\n📊 Sistem Genel Bakış:\n"
            if overview.get("cpu", {}).get("average"):
                context += f"  - CPU Kullanımı: {overview['cpu']['average']:.2f}%\n"
            if overview.get("memory", {}).get("usage_percent"):
                context += f"  - Memory Kullanımı: {overview['memory']['usage_percent']:.2f}%\n"
            if overview.get("disk", {}).get("usage_percent"):
                context += f"  - Disk Kullanımı: {overview['disk']['usage_percent']:.2f}%\n"
            if overview.get("load", {}).get("1min"):
                context += f"  - Load Average (1min): {overview['load']['1min']:.2f}\n"
        
        # Performans metrikleri
        if any(kw in message_lower for kw in ['performans', 'performance', 'cpu', 'memory', 'disk', 'kullanım']):
            metrics = await self.get_server_metrics()
            context += "\n📈 Detaylı Performans Metrikleri:\n"
            
            if metrics.get("cpu_usage"):
                context += "  CPU Kullanımı:\n"
                for item in metrics["cpu_usage"][:5]:  # İlk 5 sunucu
                    context += f"    - {item['instance']}: {item['value']:.2f}%\n"
            
            if metrics.get("memory_usage"):
                context += "  Memory Kullanımı:\n"
                for item in metrics["memory_usage"][:5]:
                    context += f"    - {item['instance']}: {item['value']:.2f}%\n"
            
            if metrics.get("disk_usage"):
                context += "  Disk Kullanımı:\n"
                for item in metrics["disk_usage"][:5]:
                    context += f"    - {item['instance']}: {item['value']:.2f}%\n"
        
        # Network metrikleri
        if any(kw in message_lower for kw in ['network', 'ağ', 'bandwidth', 'trafik']):
            network_query = 'rate(node_network_receive_bytes_total[15m])'
            network_data = await self.query_metric(network_query)
            if network_data and network_data.get("status") == "success":
                results = network_data.get("data", {}).get("result", [])
                if results:
                    context += "\n🌐 Network Trafiği:\n"
                    for r in results[:5]:
                        instance = r.get("metric", {}).get("instance", "unknown")
                        device = r.get("metric", {}).get("device", "unknown")
                        value = float(r["value"][1])
                        context += f"  - {instance} ({device}): {value:.2f} bytes/s\n"
        
        # Uptime
        if any(kw in message_lower for kw in ['uptime', 'çalışma süresi', 'ne kadar süredir']):
            uptime_query = 'avg(node_boot_time_seconds)'
            uptime_data = await self.query_metric(uptime_query)
            if uptime_data and uptime_data.get("status") == "success":
                results = uptime_data.get("data", {}).get("result", [])
                if results:
                    context += "\n⏱️ Uptime Bilgileri:\n"
                    for r in results[:5]:
                        instance = r.get("metric", {}).get("instance", "unknown")
                        boot_time = float(r["value"][1])
                        from datetime import datetime, timedelta
                        uptime_days = (datetime.now().timestamp() - boot_time) / 86400
                        context += f"  - {instance}: {uptime_days:.1f} gün\n"
        
        return context
