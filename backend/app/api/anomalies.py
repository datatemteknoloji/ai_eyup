"""
Anomaly Detection API endpoints
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.server import Server
from app.models.metric import MetricData
from app.services.anomaly_detector import detect_all_anomalies, detect_anomalies_for_server
from datetime import datetime, timedelta
import statistics

router = APIRouter()


@router.get("/")
async def get_anomalies(
    server_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """Tum sunucular veya belirli bir sunucu icin anlık anomali tespiti yap."""
    if server_id:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            return {"anomalies": [], "total": 0, "scanned_at": datetime.utcnow().isoformat()}
        anomalies = detect_anomalies_for_server(db, server)
    else:
        anomalies = detect_all_anomalies(db)

    critical = [a for a in anomalies if a["severity"] == "critical"]
    warning = [a for a in anomalies if a["severity"] == "warning"]

    return {
        "anomalies": anomalies,
        "total": len(anomalies),
        "critical_count": len(critical),
        "warning_count": len(warning),
        "scanned_at": datetime.utcnow().isoformat(),
    }


@router.get("/summary")
async def get_anomaly_summary(db: Session = Depends(get_db)):
    """Tum sunucularin anlık metrik ozeti ve anomali sayilari."""
    servers = db.query(Server).filter(
        Server.ai_ready == True,
        Server.status == "ONLINE"
    ).all()

    now = datetime.utcnow()
    last_hour = now - timedelta(hours=1)

    summary = []
    for srv in servers:
        # Son 1 saatin metrik istatistikleri
        metrics = {}
        for metric_name in ["cpu_usage_percent", "memory_usage_percent",
                             "disk_root_usage_percent", "load1",
                             "disk_io_utilization_percent"]:
            vals = db.query(MetricData.value).filter(
                MetricData.server_id == srv.id,
                MetricData.metric_name == metric_name,
                MetricData.timestamp >= last_hour
            ).all()
            if vals:
                values = [v[0] for v in vals]
                metrics[metric_name] = {
                    "current": round(values[-1], 2),
                    "avg": round(statistics.mean(values), 2),
                    "max": round(max(values), 2),
                    "min": round(min(values), 2),
                }

        # Hızlı anomali skoru (sadece esik bazlı, hızlı)
        score = 0
        alerts = []
        cpu = metrics.get("cpu_usage_percent", {}).get("current", 0)
        mem = metrics.get("memory_usage_percent", {}).get("current", 0)
        disk = metrics.get("disk_root_usage_percent", {}).get("current", 0)
        if cpu >= 95: score += 3; alerts.append("CPU kritik")
        elif cpu >= 80: score += 1; alerts.append("CPU yuksek")
        if mem >= 95: score += 3; alerts.append("Bellek kritik")
        elif mem >= 85: score += 1; alerts.append("Bellek yuksek")
        if disk >= 90: score += 3; alerts.append("Disk kritik")
        elif disk >= 80: score += 1; alerts.append("Disk yuksek")

        health = "critical" if score >= 3 else ("warning" if score >= 1 else "healthy")

        summary.append({
            "server_id": srv.id,
            "server_name": srv.name,
            "ip_address": srv.ip_address,
            "health": health,
            "anomaly_score": score,
            "alerts": alerts,
            "metrics": metrics,
        })

    total_critical = sum(1 for s in summary if s["health"] == "critical")
    total_warning = sum(1 for s in summary if s["health"] == "warning")
    return {
        "servers": summary,
        "total_servers": len(summary),
        "critical_servers": total_critical,
        "warning_servers": total_warning,
        "healthy_servers": len(summary) - total_critical - total_warning,
        "generated_at": now.isoformat(),
    }


@router.get("/history/{server_id}")
async def get_metric_history(
    server_id: int,
    metric_name: str = Query("cpu_usage_percent"),
    hours: int = Query(24, ge=1, le=168),
    db: Session = Depends(get_db)
):
    """Bir sunucunun belirli metriğinin tarihsel verilerini dondur."""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        return {"error": "Server not found"}

    since = datetime.utcnow() - timedelta(hours=hours)
    records = db.query(MetricData).filter(
        MetricData.server_id == server_id,
        MetricData.metric_name == metric_name,
        MetricData.timestamp >= since,
    ).order_by(MetricData.timestamp.asc()).all()

    data = [{"timestamp": r.timestamp.isoformat(), "value": round(r.value, 4)} for r in records]
    values = [r.value for r in records]

    stats = {}
    if values:
        stats = {
            "count": len(values),
            "avg": round(statistics.mean(values), 4),
            "max": round(max(values), 4),
            "min": round(min(values), 4),
            "stdev": round(statistics.stdev(values), 4) if len(values) >= 2 else 0,
        }

    return {
        "server_id": server_id,
        "server_name": server.name,
        "metric_name": metric_name,
        "hours": hours,
        "data": data,
        "stats": stats,
    }


@router.get("/available-metrics")
async def get_available_metrics():
    """Mevcut metrik listesini ve kategorilerini dondur."""
    from app.services.metric_sync import MetricSyncService
    return {"categories": MetricSyncService.get_metric_categories()}


@router.get("/logs")
async def get_log_anomalies(db: Session = Depends(get_db)):
    """Log tablosundaki anomalileri tespit et (spike, kritik, tekrar)."""
    from app.services.log_anomaly_detector import detect_log_anomalies
    anomalies = detect_log_anomalies(db)
    critical = [a for a in anomalies if a["severity"] == "critical"]
    return {
        "anomalies": anomalies,
        "total": len(anomalies),
        "critical_count": len(critical),
        "scanned_at": datetime.utcnow().isoformat(),
    }


@router.get("/logs/summary")
async def get_log_summary(hours: int = 24, db: Session = Depends(get_db)):
    """Log ozeti: toplam log, severity dagilimi, sunucu bazli."""
    from app.services.log_anomaly_detector import get_log_summary
    return get_log_summary(db, hours=hours)


@router.post("/logs/collect-now")
async def collect_logs_now(db: Session = Depends(get_db)):
    """Anlık log toplama - tum sunucular."""
    from app.services.log_collector import collect_all_servers_logs
    result = collect_all_servers_logs(db)
    return result


@router.get("/combined")
async def get_combined_anomalies(db: Session = Depends(get_db)):
    """Metrik + log anomalilerini birlikte dondur."""
    from app.services.log_anomaly_detector import detect_log_anomalies
    metric_anomalies = detect_all_anomalies(db)
    log_anomalies = detect_log_anomalies(db)

    all_anomalies = []
    for a in metric_anomalies:
        a["source"] = "metric"
        all_anomalies.append(a)
    for a in log_anomalies:
        a["source"] = "log"
        all_anomalies.append(a)

    # Severity'ye gore sirala: critical once
    all_anomalies.sort(key=lambda x: (0 if x["severity"] == "critical" else 1, x.get("server_name", "")))

    critical = [a for a in all_anomalies if a["severity"] == "critical"]
    warning = [a for a in all_anomalies if a["severity"] != "critical"]

    return {
        "anomalies": all_anomalies,
        "total": len(all_anomalies),
        "critical_count": len(critical),
        "warning_count": len(warning),
        "metric_anomaly_count": len(metric_anomalies),
        "log_anomaly_count": len(log_anomalies),
        "scanned_at": datetime.utcnow().isoformat(),
    }
