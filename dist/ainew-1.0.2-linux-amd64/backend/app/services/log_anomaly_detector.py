"""
Log Anomaly Detector - SystemEvent tablosundaki loglari analiz eder.
Log spike, tekrar eden hatalar, kritik pattern'ler tespit eder.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.server import Server
from app.models.event import SystemEvent

logger = logging.getLogger(__name__)


def detect_log_anomalies(db: Session, lookback_minutes: int = 60) -> List[Dict[str, Any]]:
    """
    Log tablosundaki anomalileri tespit et:
    1. Kritik log varsa -> aninda anomali
    2. Son 1 saatte hata spike'i -> onceki saate gore 3x artis
    3. Ayni hata tekrar ediyorsa -> burst anomali
    """
    anomalies = []
    since = datetime.utcnow() - timedelta(minutes=lookback_minutes)
    prev_since = since - timedelta(minutes=lookback_minutes)

    servers = db.query(Server).filter(
        Server.ai_ready == True,
        Server.status == "ONLINE"
    ).all()

    for srv in servers:
        srv_anomalies = []

        # 1. Kritik loglar
        critical_logs = db.query(SystemEvent).filter(
            SystemEvent.server_id == srv.id,
            SystemEvent.event_type == "log_entry",
            SystemEvent.severity == "critical",
            SystemEvent.created_at >= since,
            SystemEvent.is_acknowledged == False,
        ).order_by(SystemEvent.created_at.desc()).limit(10).all()

        for log in critical_logs:
            srv_anomalies.append({
                "type": "critical_log",
                "severity": "critical",
                "message": f"Kritik log: {log.title[:150]}",
                "log_id": log.id,
                "raw": log.description,
                "category": (log.raw_data or {}).get("category", "Unknown"),
                "detected_at": datetime.utcnow().isoformat(),
            })

        # 2. Son 1 saatteki error/warning sayisi
        current_count = db.query(func.count(SystemEvent.id)).filter(
            SystemEvent.server_id == srv.id,
            SystemEvent.event_type == "log_entry",
            SystemEvent.severity.in_(["error", "warning", "critical"]),
            SystemEvent.created_at >= since,
        ).scalar() or 0

        prev_count = db.query(func.count(SystemEvent.id)).filter(
            SystemEvent.server_id == srv.id,
            SystemEvent.event_type == "log_entry",
            SystemEvent.severity.in_(["error", "warning", "critical"]),
            SystemEvent.created_at >= prev_since,
            SystemEvent.created_at < since,
        ).scalar() or 0

        # Spike: mevcut > 10 ve oncekinin 3 katindan fazla
        if current_count > 10 and prev_count > 0 and current_count > prev_count * 3:
            srv_anomalies.append({
                "type": "log_spike",
                "severity": "warning",
                "message": f"Log spike: son {lookback_minutes}dk'da {current_count} hata (onceki {prev_count})",
                "current_count": current_count,
                "prev_count": prev_count,
                "detected_at": datetime.utcnow().isoformat(),
            })
        elif current_count > 50:
            srv_anomalies.append({
                "type": "high_error_rate",
                "severity": "warning",
                "message": f"Yuksek hata orani: son {lookback_minutes}dk'da {current_count} hata",
                "current_count": current_count,
                "detected_at": datetime.utcnow().isoformat(),
            })

        # 3. Tekrar eden hatalar (burst detection)
        repeated = db.query(
            SystemEvent.title,
            func.count(SystemEvent.id).label("cnt")
        ).filter(
            SystemEvent.server_id == srv.id,
            SystemEvent.event_type == "log_entry",
            SystemEvent.severity.in_(["error", "critical"]),
            SystemEvent.created_at >= since,
        ).group_by(SystemEvent.title).having(
            func.count(SystemEvent.id) >= 5
        ).order_by(func.count(SystemEvent.id).desc()).limit(3).all()

        for title, cnt in repeated:
            srv_anomalies.append({
                "type": "repeated_error",
                "severity": "warning",
                "message": f"Tekrar eden hata ({cnt}x): {title[:120]}",
                "repeat_count": cnt,
                "detected_at": datetime.utcnow().isoformat(),
            })

        if srv_anomalies:
            for a in srv_anomalies:
                a["server_id"] = srv.id
                a["server_name"] = srv.name
                a["ip_address"] = srv.ip_address
            anomalies.extend(srv_anomalies)

    return anomalies


def get_log_summary(db: Session, hours: int = 24) -> Dict[str, Any]:
    """Son N saatin log ozeti."""
    since = datetime.utcnow() - timedelta(hours=hours)

    total = db.query(func.count(SystemEvent.id)).filter(
        SystemEvent.event_type == "log_entry",
        SystemEvent.created_at >= since,
    ).scalar() or 0

    by_severity = {}
    for row in db.query(
        SystemEvent.severity,
        func.count(SystemEvent.id)
    ).filter(
        SystemEvent.event_type == "log_entry",
        SystemEvent.created_at >= since,
    ).group_by(SystemEvent.severity).all():
        by_severity[row[0]] = row[1]

    by_server = []
    for row in db.query(
        Server.name,
        Server.ip_address,
        func.count(SystemEvent.id).label("cnt"),
        func.count(func.nullif(SystemEvent.severity, "warning")).label("errors")
    ).join(SystemEvent, Server.id == SystemEvent.server_id).filter(
        SystemEvent.event_type == "log_entry",
        SystemEvent.created_at >= since,
    ).group_by(Server.name, Server.ip_address).order_by(
        func.count(SystemEvent.id).desc()
    ).limit(10).all():
        by_server.append({
            "server": row[0], "ip": row[1],
            "total_logs": row[2], "errors": row[3]
        })

    return {
        "hours": hours,
        "total_logs": total,
        "by_severity": by_severity,
        "by_server": by_server,
        "generated_at": datetime.utcnow().isoformat(),
    }
