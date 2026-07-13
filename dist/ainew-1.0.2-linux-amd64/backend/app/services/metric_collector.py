"""
Metric Collection Service - Collects metrics from Prometheus and stores in DB
"""
import logging
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from app.models.metric import MetricData, MetricAggregation
from app.models.server import Server

logger = logging.getLogger(__name__)


class MetricCollector:
    """Collects metrics from Prometheus and stores in TimescaleDB"""
    
    def __init__(self, prometheus_url: str = "http://prometheus:9090"):
        self.prometheus_url = prometheus_url
    
    def query_prometheus(self, query: str, time: Optional[datetime] = None) -> Optional[Dict]:
        """Query Prometheus API"""
        try:
            url = f"{self.prometheus_url}/api/v1/query"
            params = {"query": query}
            if time:
                params["time"] = time.timestamp()
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Prometheus query failed: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Prometheus query error: {e}")
            return None
    
    def query_prometheus_range(self, query: str, start: datetime, end: datetime, step: str = "15s") -> Optional[Dict]:
        """Query Prometheus range API"""
        try:
            url = f"{self.prometheus_url}/api/v1/query_range"
            params = {
                "query": query,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": step
            }
            
            response = requests.get(url, params=params, timeout=30)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Prometheus range query failed: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Prometheus range query error: {e}")
            return None
    
    def collect_server_metrics(self, db: Session, server: Server) -> int:
        """Collect current metrics for a server"""
        if not server.ip_address:
            return 0
        
        collected = 0
        instance = f"{server.ip_address}:9100"
        
        # Metric definitions
        metrics_config = [
            {
                "name": "cpu_usage",
                "query": f'100 - (avg by (instance) (irate(node_cpu_seconds_total{{mode="idle",instance="{instance}"}}[5m])) * 100)',
                "unit": "percent"
            },
            {
                "name": "memory_usage",
                "query": f'100 * (1 - node_memory_MemAvailable_bytes{{instance="{instance}"}} / node_memory_MemTotal_bytes{{instance="{instance}"}})',
                "unit": "percent"
            },
            {
                "name": "disk_usage",
                "query": f'100 * (1 - node_filesystem_avail_bytes{{instance="{instance}",fstype!="tmpfs",fstype!="devtmpfs"}} / node_filesystem_size_bytes{{instance="{instance}",fstype!="tmpfs",fstype!="devtmpfs"}})',
                "unit": "percent"
            },
            {
                "name": "network_rx_bytes",
                "query": f'rate(node_network_receive_bytes_total{{instance="{instance}",device!="lo"}}[5m])',
                "unit": "bytes/sec"
            },
            {
                "name": "network_tx_bytes",
                "query": f'rate(node_network_transmit_bytes_total{{instance="{instance}",device!="lo"}}[5m])',
                "unit": "bytes/sec"
            },
            {
                "name": "load_average_1m",
                "query": f'node_load1{{instance="{instance}"}}',
                "unit": "count"
            },
            {
                "name": "load_average_5m",
                "query": f'node_load5{{instance="{instance}"}}',
                "unit": "count"
            },
            {
                "name": "uptime",
                "query": f'node_time_seconds{{instance="{instance}"}} - node_boot_time_seconds{{instance="{instance}"}}',
                "unit": "seconds"
            }
        ]
        
        for metric_config in metrics_config:
            try:
                result = self.query_prometheus(metric_config["query"])
                if result and result.get("status") == "success":
                    data = result.get("data", {})
                    results = data.get("result", [])
                    
                    for item in results:
                        value = float(item["value"][1])
                        labels = item.get("metric", {})
                        
                        # Store metric
                        metric = MetricData(
                            server_id=server.id,
                            metric_name=metric_config["name"],
                            value=value,
                            unit=metric_config["unit"],
                            labels=str(labels) if labels else None
                        )
                        db.add(metric)
                        collected += 1
            except Exception as e:
                logger.error(f"Error collecting {metric_config['name']} for {server.hostname}: {e}")
        
        if collected > 0:
            db.commit()
            logger.info(f"Collected {collected} metrics for {server.hostname}")
        
        return collected
    
    def collect_all_servers(self, db: Session) -> Dict[str, int]:
        """Collect metrics for all AI-ready servers"""
        servers = db.query(Server).filter(Server.ai_ready == True).all()
        
        results = {
            "total_servers": len(servers),
            "successful": 0,
            "failed": 0,
            "total_metrics": 0
        }
        
        for server in servers:
            try:
                count = self.collect_server_metrics(db, server)
                if count > 0:
                    results["successful"] += 1
                    results["total_metrics"] += count
                else:
                    results["failed"] += 1
            except Exception as e:
                logger.error(f"Error collecting metrics for {server.hostname}: {e}")
                results["failed"] += 1
        
        return results
    
    def aggregate_metrics(self, db: Session, period: str = "1h", lookback_hours: int = 24):
        """Aggregate metrics for faster queries"""
        lookback = datetime.utcnow() - timedelta(hours=lookback_hours)
        
        # Get all servers
        servers = db.query(Server).all()
        metric_names = ["cpu_usage", "memory_usage", "disk_usage", "load_average_1m"]
        
        for server in servers:
            for metric_name in metric_names:
                try:
                    # Query metrics
                    metrics = db.query(MetricData).filter(
                        MetricData.server_id == server.id,
                        MetricData.metric_name == metric_name,
                        MetricData.timestamp >= lookback
                    ).all()
                    
                    if not metrics:
                        continue
                    
                    values = [m.value for m in metrics]
                    
                    # Create aggregation
                    agg = MetricAggregation(
                        server_id=server.id,
                        metric_name=metric_name,
                        period=period,
                        period_start=lookback,
                        avg_value=sum(values) / len(values),
                        min_value=min(values),
                        max_value=max(values),
                        sum_value=sum(values),
                        count=len(values),
                        unit=metrics[0].unit if metrics else None
                    )
                    db.add(agg)
                except Exception as e:
                    logger.error(f"Error aggregating {metric_name} for {server.hostname}: {e}")
        
        db.commit()
        logger.info(f"Aggregated metrics for {len(servers)} servers")
    
    def cleanup_old_metrics(self, db: Session, days: int = 30):
        """Delete metrics older than specified days"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        deleted = db.query(MetricData).filter(
            MetricData.timestamp < cutoff
        ).delete()
        
        db.commit()
        logger.info(f"Deleted {deleted} old metrics (older than {days} days)")
        return deleted
