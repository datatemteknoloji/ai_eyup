"""
Metrics API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from datetime import datetime, timedelta
from app.core.database import get_db
from app.core.config import settings
from app.models.metric import MetricData, MetricAggregation, MetricThreshold
from app.models.server import Server
from app.services.metric_collector import MetricCollector
import os
import httpx

router = APIRouter()


# ── Prometheus proxy ────────────────────────────────────────────────────────
# Frontend, Prometheus'a doğrudan tarayıcıdan değil bu proxy üzerinden erişir —
# böylece Prometheus host'u/portu sadece backend'de (PROMETHEUS_URL) bilinir,
# müşteri kurulumlarında hardcoded adres kalmaz ve CORS gerekmez.
@router.get("/prometheus/query")
async def prometheus_query(query: str = Query(...)):
    """PromQL anlık sorgu — /api/v1/query proxy."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{settings.PROMETHEUS_URL}/api/v1/query",
                params={"query": query},
            )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Prometheus sorgu hatası: {e}")


@router.get("/prometheus/query_range")
async def prometheus_query_range(
    query: str = Query(...),
    start: int = Query(...),
    end: int = Query(...),
    step: int = Query(...),
):
    """PromQL zaman aralığı sorgusu — /api/v1/query_range proxy."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{settings.PROMETHEUS_URL}/api/v1/query_range",
                params={"query": query, "start": start, "end": end, "step": step},
            )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Prometheus sorgu hatası: {e}")


@router.get("/prometheus/labels/{label_name}")
async def prometheus_label_values(label_name: str):
    """Bir label'ın alabileceği değerler — /api/v1/label/{name}/values proxy."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{settings.PROMETHEUS_URL}/api/v1/label/{label_name}/values")
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Prometheus sorgu hatası: {e}")


@router.post("/collect")
async def collect_metrics(
    server_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Collect metrics from Prometheus and store in DB"""
    prometheus_url = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
    collector = MetricCollector(prometheus_url)
    
    if server_id:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")
        
        count = collector.collect_server_metrics(db, server)
        return {
            "success": True,
            "server": server.hostname,
            "metrics_collected": count
        }
    else:
        results = collector.collect_all_servers(db)
        return {
            "success": True,
            **results
        }


@router.get("/servers/{server_id}/current")
async def get_current_metrics(
    server_id: int,
    db: Session = Depends(get_db)
):
    """Get latest metrics for a server"""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    # Get latest metric for each type
    metric_names = ["cpu_usage", "memory_usage", "disk_usage", "load_average_1m", "uptime"]
    latest_metrics = {}
    
    for metric_name in metric_names:
        metric = db.query(MetricData).filter(
            MetricData.server_id == server_id,
            MetricData.metric_name == metric_name
        ).order_by(desc(MetricData.timestamp)).first()
        
        if metric:
            latest_metrics[metric_name] = {
                "value": metric.value,
                "unit": metric.unit,
                "timestamp": metric.timestamp.isoformat()
            }
    
    return {
        "server_id": server_id,
        "hostname": server.hostname,
        "metrics": latest_metrics
    }


@router.get("/servers/{server_id}/history")
async def get_metric_history(
    server_id: int,
    metric_name: str = Query(..., description="Metric name (cpu_usage, memory_usage, etc)"),
    hours: int = Query(24, ge=1, le=720, description="Hours of history (1-720, i.e. up to 30 days)"),
    db: Session = Depends(get_db)
):
    """Get metric history for a server"""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    start_time = datetime.utcnow() - timedelta(hours=hours)
    
    metrics = db.query(MetricData).filter(
        MetricData.server_id == server_id,
        MetricData.metric_name == metric_name,
        MetricData.timestamp >= start_time
    ).order_by(MetricData.timestamp).all()
    
    return {
        "server_id": server_id,
        "hostname": server.hostname,
        "metric_name": metric_name,
        "start_time": start_time.isoformat(),
        "data_points": len(metrics),
        "data": [
            {
                "timestamp": m.timestamp.isoformat(),
                "value": m.value,
                "unit": m.unit
            }
            for m in metrics
        ]
    }


@router.get("/servers/{server_id}/aggregated")
async def get_aggregated_metrics(
    server_id: int,
    period: str = Query("1h", regex="^(1h|1d|1w)$"),
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db)
):
    """Get aggregated metrics for a server"""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    start_time = datetime.utcnow() - timedelta(days=days)
    
    aggregations = db.query(MetricAggregation).filter(
        MetricAggregation.server_id == server_id,
        MetricAggregation.period == period,
        MetricAggregation.period_start >= start_time
    ).order_by(MetricAggregation.period_start).all()
    
    # Group by metric name
    grouped = {}
    for agg in aggregations:
        if agg.metric_name not in grouped:
            grouped[agg.metric_name] = []
        
        grouped[agg.metric_name].append({
            "period_start": agg.period_start.isoformat(),
            "avg": agg.avg_value,
            "min": agg.min_value,
            "max": agg.max_value,
            "count": agg.count
        })
    
    return {
        "server_id": server_id,
        "hostname": server.hostname,
        "period": period,
        "metrics": grouped
    }


@router.get("/dashboard")
async def get_dashboard_metrics(platform: Optional[str] = None, db: Session = Depends(get_db)):
    """Get aggregated metrics for dashboard.

    platform="linux"/"windows" verilirse yalnızca o platformun sunucuları döner —
    aksi halde tüm AI-ready sunucular (platform bağımsız) döner.
    Not: metric_name'ler metric_sync.py'nin yazdığı gerçek isimlerle (cpu_usage_percent
    vb.) eşleşir — hem Linux (node_exporter) hem Windows (windows_exporter) için aynı
    şemaya senkronlanır, bu yüzden aynı sorgu her iki platformda da çalışır.
    """
    query = db.query(Server).filter(Server.ai_ready == True)
    if platform == "linux":
        from app.services.platform_scope import get_linux_module_server_id_set
        linux_ids = get_linux_module_server_id_set(db)
        query = query.filter(Server.id.in_(linux_ids)) if linux_ids else query.filter(False)
    elif platform == "windows":
        from app.services.platform_scope import get_windows_server_ids
        windows_ids = get_windows_server_ids(db)
        query = query.filter(Server.id.in_(windows_ids)) if windows_ids else query.filter(False)
    servers = query.all()

    dashboard_data = []
    for server in servers:
        # Get latest metrics
        cpu = db.query(MetricData).filter(
            MetricData.server_id == server.id,
            MetricData.metric_name == "cpu_usage_percent"
        ).order_by(desc(MetricData.timestamp)).first()

        memory = db.query(MetricData).filter(
            MetricData.server_id == server.id,
            MetricData.metric_name == "memory_usage_percent"
        ).order_by(desc(MetricData.timestamp)).first()

        disk = db.query(MetricData).filter(
            MetricData.server_id == server.id,
            MetricData.metric_name == "disk_root_usage_percent"
        ).order_by(desc(MetricData.timestamp)).first()

        dashboard_data.append({
            "server_id": server.id,
            "hostname": server.hostname,
            "ip_address": server.ip_address,
            "cpu_usage": cpu.value if cpu else None,
            "memory_usage": memory.value if memory else None,
            "disk_usage": disk.value if disk else None,
            "last_update": cpu.timestamp.isoformat() if cpu else None
        })
    
    return {
        "total_servers": len(servers),
        "servers": dashboard_data
    }


@router.post("/thresholds")
async def create_threshold(
    threshold_data: dict,
    db: Session = Depends(get_db)
):
    """Create metric threshold for alerting"""
    threshold = MetricThreshold(**threshold_data)
    db.add(threshold)
    db.commit()
    db.refresh(threshold)
    return threshold


@router.get("/thresholds")
async def list_thresholds(
    server_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """List metric thresholds"""
    query = db.query(MetricThreshold)
    if server_id:
        query = query.filter(MetricThreshold.server_id == server_id)
    
    return query.all()


@router.post("/aggregate")
async def trigger_aggregation(
    period: str = Query("1h", regex="^(1h|1d|1w)$"),
    lookback_hours: int = Query(24, ge=1, le=168),
    db: Session = Depends(get_db)
):
    """Manually trigger metric aggregation"""
    prometheus_url = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
    collector = MetricCollector(prometheus_url)
    
    collector.aggregate_metrics(db, period, lookback_hours)
    
    return {
        "success": True,
        "message": f"Aggregated metrics for period {period}"
    }


@router.delete("/cleanup")
async def cleanup_old_metrics(
    days: int = Query(30, ge=7, le=365),
    db: Session = Depends(get_db)
):
    """Delete old metrics"""
    prometheus_url = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
    collector = MetricCollector(prometheus_url)
    
    deleted = collector.cleanup_old_metrics(db, days)
    
    return {
        "success": True,
        "deleted_count": deleted,
        "message": f"Deleted metrics older than {days} days"
    }
