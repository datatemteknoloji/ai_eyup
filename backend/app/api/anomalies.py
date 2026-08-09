"""
Anomaly Detection API endpoints
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, text
from app.core.database import get_db
from app.models.server import Server
from app.models.metric import MetricData
from app.services.anomaly_detector import detect_all_anomalies, detect_anomalies_for_server
from app.services.platform_scope import (
    get_linux_module_server_ids,
    get_windows_server_ids,
    get_exadata_server_ids,
    apply_platform_filter,
)
from app.services.event_filters import LOG_ENTRY_ACTIONABLE, apply_hide_routine_virt
from datetime import datetime, timedelta
import statistics

router = APIRouter()


def _metric_history_points(db: Session, server_id: int, metric_name: str, since: datetime, hours: int):
    """Uzun aralıkta hourly CAGG; kısa aralıkta raw metric_data."""
    if hours > 6:
        try:
            rows = db.execute(
                text("""
                    SELECT bucket, avg_value
                    FROM metric_data_hourly
                    WHERE server_id = :sid
                      AND metric_name = :mname
                      AND bucket >= :since
                    ORDER BY bucket ASC
                """),
                {"sid": server_id, "mname": metric_name, "since": since},
            ).fetchall()
            if rows:
                data = [
                    {"timestamp": r[0].isoformat(), "value": round(float(r[1]), 4)}
                    for r in rows if r[1] is not None
                ]
                return data, [float(r[1]) for r in rows if r[1] is not None]
        except Exception:
            pass

    records = (
        db.query(MetricData)
        .filter(
            MetricData.server_id == server_id,
            MetricData.metric_name == metric_name,
            MetricData.timestamp >= since,
        )
        .order_by(MetricData.timestamp.asc())
        .all()
    )
    data = [{"timestamp": r.timestamp.isoformat(), "value": round(r.value, 4)} for r in records]
    return data, [r.value for r in records]


@router.get("/")
async def get_anomalies(
    server_id: Optional[int] = Query(None),
    platform: Optional[str] = Query(None),
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
        if platform == "linux":
            linux_ids = set(get_linux_module_server_ids(db))
            anomalies = [a for a in anomalies if a.get("server_id") in linux_ids]
        elif platform == "windows":
            win_ids = set(get_windows_server_ids(db))
            anomalies = [a for a in anomalies if a.get("server_id") in win_ids]
        elif platform == "exadata":
            exa_ids = set(get_exadata_server_ids(db))
            anomalies = [a for a in anomalies if a.get("server_id") in exa_ids]
        elif platform == "virt":
            anomalies = []

    critical = [a for a in anomalies if a["severity"] == "critical"]
    warning = [a for a in anomalies if a["severity"] == "warning"]

    return {
        "anomalies": anomalies,
        "total": len(anomalies),
        "critical_count": len(critical),
        "warning_count": len(warning),
        "scanned_at": datetime.utcnow().isoformat(),
    }


@router.get("/aiops-status")
async def aiops_status(db: Session = Depends(get_db)):
    """AIOps kapalı-döngü sağlık durumu — frontend dashboard için."""
    from app.models.event import SystemEvent, Incident

    # Aktif metrik anomali event'leri (çözülmemiş)
    active_metric = db.query(SystemEvent).filter(
        SystemEvent.event_type == "metric_anomaly",
        SystemEvent.resolved == False,  # noqa: E712
    ).count()
    active_metric_critical = db.query(SystemEvent).filter(
        SystemEvent.event_type == "metric_anomaly",
        SystemEvent.resolved == False,  # noqa: E712
        SystemEvent.severity == "critical",
    ).count()

    # Otomatik açılan açık incident'lar
    auto_open = db.query(Incident).filter(
        Incident.status.in_(["open", "investigating"]),
        Incident.source.ilike("auto_%"),
    ).count()
    # RCA'sı tamamlanan açık incident'lar
    open_incidents = db.query(Incident).filter(
        Incident.status.in_(["open", "investigating"]),
    ).all()
    with_rca = sum(1 for i in open_incidents if i.rca_result and i.rca_result.get("analysis"))

    # İzlenen sunucular
    monitored = db.query(Server).filter(
        Server.ai_ready == True,  # noqa: E712
        Server.status == "ONLINE",
    ).count()

    return {
        "monitored_servers": monitored,
        "active_metric_anomalies": active_metric,
        "active_metric_critical": active_metric_critical,
        "auto_open_incidents": auto_open,
        "open_incidents": len(open_incidents),
        "incidents_with_rca": with_rca,
        "pipeline": [
            {"stage": "Metrikler", "ok": monitored > 0},
            {"stage": "Anomali Tespiti", "ok": True},
            {"stage": "Event Üretimi", "ok": True},
            {"stage": "Otomatik Incident", "ok": True},
            {"stage": "AI RCA", "ok": with_rca > 0 or auto_open == 0},
        ],
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.post("/run-cycle")
async def run_aiops_cycle_now(db: Session = Depends(get_db)):
    """AIOps döngüsünü manuel tetikle: tara → event → incident.
    RCA (yavaş olabilir) arka plan thread'inde çalışır, istek hemen döner."""
    import threading
    from app.services.aiops_engine import persist_anomalies_as_events
    from app.core.database import ThreadSessionLocal

    anomalies = detect_all_anomalies(db)
    result = persist_anomalies_as_events(db, anomalies)

    def _bg_rca():
        # RCA + RAG hafıza güncellemesi LangGraph (aiops_graph) üzerinden çalışır.
        # anomalies=[] → persist düğümü atlanır (çift kayıt yok), rca+memory işler.
        s = ThreadSessionLocal()
        try:
            from app.services.aiops_graph import run_aiops_graph
            run_aiops_graph(s, [])
        except Exception:
            pass
        finally:
            s.close()

    threading.Thread(target=_bg_rca, daemon=True).start()

    return {
        "success": True,
        "scanned_anomalies": len(anomalies),
        **result,
        "rca": "arka planda başlatıldı",
        "ran_at": datetime.utcnow().isoformat(),
    }


@router.get("/summary")
async def get_anomaly_summary(db: Session = Depends(get_db)):
    """Tum sunucularin anlık metrik ozeti ve anomali sayilari (set-based SQL)."""
    servers = db.query(Server).filter(
        Server.ai_ready == True,  # noqa: E712
        Server.status == "ONLINE"
    ).all()
    if not servers:
        now = datetime.utcnow()
        return {
            "servers": [],
            "total_servers": 0,
            "critical_servers": 0,
            "warning_servers": 0,
            "healthy_servers": 0,
            "generated_at": now.isoformat(),
        }

    now = datetime.utcnow()
    last_hour = now - timedelta(hours=1)
    metric_names = [
        "cpu_usage_percent", "memory_usage_percent",
        "disk_root_usage_percent", "load1",
        "disk_io_utilization_percent",
    ]
    server_ids = [s.id for s in servers]
    server_by_id = {s.id: s for s in servers}

    # Aggregates + latest value — N×5 ORM yerine set-based sorgular
    agg_rows = (
        db.query(
            MetricData.server_id,
            MetricData.metric_name,
            func.avg(MetricData.value),
            func.max(MetricData.value),
            func.min(MetricData.value),
        )
        .filter(
            MetricData.server_id.in_(server_ids),
            MetricData.metric_name.in_(metric_names),
            MetricData.timestamp >= last_hour,
        )
        .group_by(MetricData.server_id, MetricData.metric_name)
        .all()
    )

    latest_subq = (
        db.query(
            MetricData.server_id.label("sid"),
            MetricData.metric_name.label("mname"),
            func.max(MetricData.timestamp).label("max_ts"),
        )
        .filter(
            MetricData.server_id.in_(server_ids),
            MetricData.metric_name.in_(metric_names),
            MetricData.timestamp >= last_hour,
        )
        .group_by(MetricData.server_id, MetricData.metric_name)
        .subquery()
    )
    latest_rows = (
        db.query(MetricData.server_id, MetricData.metric_name, MetricData.value)
        .join(
            latest_subq,
            (MetricData.server_id == latest_subq.c.sid)
            & (MetricData.metric_name == latest_subq.c.mname)
            & (MetricData.timestamp == latest_subq.c.max_ts),
        )
        .all()
    )

    metrics_by_server: dict = {sid: {} for sid in server_ids}
    latest_map = {(r[0], r[1]): float(r[2]) for r in latest_rows}
    for sid, mname, avg_v, max_v, min_v in agg_rows:
        cur = latest_map.get((sid, mname))
        if cur is None:
            continue
        metrics_by_server[sid][mname] = {
            "current": round(cur, 2),
            "avg": round(float(avg_v), 2),
            "max": round(float(max_v), 2),
            "min": round(float(min_v), 2),
        }

    summary = []
    for sid, srv in server_by_id.items():
        metrics = metrics_by_server.get(sid) or {}
        score = 0
        alerts = []
        cpu = metrics.get("cpu_usage_percent", {}).get("current", 0)
        mem = metrics.get("memory_usage_percent", {}).get("current", 0)
        disk = metrics.get("disk_root_usage_percent", {}).get("current", 0)
        if cpu >= 95:
            score += 3
            alerts.append("CPU kritik")
        elif cpu >= 80:
            score += 1
            alerts.append("CPU yuksek")
        if mem >= 95:
            score += 3
            alerts.append("Bellek kritik")
        elif mem >= 85:
            score += 1
            alerts.append("Bellek yuksek")
        if disk >= 90:
            score += 3
            alerts.append("Disk kritik")
        elif disk >= 80:
            score += 1
            alerts.append("Disk yuksek")

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
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db)
):
    """Bir sunucunun belirli metriğinin tarihsel verilerini dondur."""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        return {"error": "Server not found"}

    since = datetime.utcnow() - timedelta(hours=hours)
    data, values = _metric_history_points(db, server_id, metric_name, since, hours)

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
    """Anlık log toplama - tum sunucular (son 2 saat)."""
    from app.services.log_collector import collect_all_servers_logs
    result = collect_all_servers_logs(db, since_hours=2)
    return result


@router.post("/logs/backfill")
async def backfill_logs(
    days: int = Query(default=7, ge=1, le=30),
    platform: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    """Geçmiş N günlük log backfill — platform=linux SSH, platform=windows WinRM Event Log."""
    import asyncio
    since_hours = days * 24
    loop = asyncio.get_event_loop()

    if platform == "windows":
        from app.services.windows_log_collector import collect_all_windows_logs
        result = await loop.run_in_executor(
            None, lambda: collect_all_windows_logs(db, since_hours=since_hours)
        )
    else:
        from app.services.log_collector import collect_all_servers_logs
        result = await loop.run_in_executor(
            None, lambda: collect_all_servers_logs(db, since_hours=since_hours)
        )
    result["backfill_days"] = days
    result["since_hours"] = since_hours
    result["platform"] = platform or "linux"
    return result






@router.get("/logs/list")
async def get_log_anomaly_list(
    days: int = Query(30, ge=7, le=90),
    platform: Optional[str] = Query(None),
    actionable_only: bool = Query(default=True),
    show_routine: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """Isı haritası ile aynı veri kaynağından (log_entry) son N gün detay listesi."""
    from app.models.event import SystemEvent

    now = datetime.utcnow()
    since = now - timedelta(days=days)

    if platform == "virt":
        # Sanallaştırma modülünün kendi Komuta Merkezi log paneli var
        # (vCenter event/alarm/task) — OS log tabanlı bu anomali listesi
        # sanallaştırma için henüz uygulanmıyor; karışıklığı önlemek için boş dön.
        return {"days": days, "total": 0, "critical_count": 0, "warning_count": 0, "anomalies": [], "generated_at": now.isoformat()}

    q = db.query(SystemEvent).join(Server, Server.id == SystemEvent.server_id).filter(
        Server.ai_ready == True,  # noqa: E712 — sadece AI Ready sunucular
        func.lower(SystemEvent.event_type).in_(["log_entry", "log"]),
        SystemEvent.created_at >= since,
        func.lower(SystemEvent.severity).in_(["warning", "warn", "error", "critical", "emergency"]),
    )
    if actionable_only:
        q = q.filter(LOG_ENTRY_ACTIONABLE)
    q = apply_platform_filter(q, platform, db)
    if platform == "virt" and not show_routine:
        q = apply_hide_routine_virt(q, show_routine=False)
    events = q.order_by(SystemEvent.created_at.desc()).limit(2000).all()

    sev_weight = {"warning": 1, "error": 2, "critical": 3, "emergency": 4}
    rows = []
    for ev in events:
        rows.append({
            "id": ev.id,
            "source": "log",
            "server_id": ev.server_id,
            "server_name": ev.server.name if ev.server else "-",
            "ip_address": ev.server.ip_address if ev.server else "-",
            "severity": ev.severity,
            "score": sev_weight.get((ev.severity or "").lower(), 1),
            "title": ev.title,
            "message": ev.description,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
            "date": ev.created_at.date().isoformat() if ev.created_at else None,
        })

    critical = [r for r in rows if r.get("severity") in ["critical", "emergency"]]
    warning = [r for r in rows if r.get("severity") in ["warning", "error"]]

    return {
        "days": days,
        "total": len(rows),
        "critical_count": len(critical),
        "warning_count": len(warning),
        "anomalies": rows,
        "generated_at": now.isoformat(),
    }
@router.get("/logs/heatmap")
async def get_log_anomaly_heatmap(
    days: int = Query(30, ge=7, le=90),
    platform: Optional[str] = Query(None),
    actionable_only: bool = Query(default=True),
    show_routine: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """Son N gun loglarindan sunucu-gun bazli anomali isi haritasi dondurur."""
    from app.models.event import SystemEvent

    now = datetime.utcnow()
    since = now - timedelta(days=days - 1)

    if platform == "virt":
        # vCenter / hypervisor olaylarından ısı haritası (OS log_entry değil)
        from app.services.event_filters import apply_hide_routine_virt
        day_labels = [
            (since + timedelta(days=i)).date().isoformat()
            for i in range(days)
        ]
        q = db.query(SystemEvent).filter(
            SystemEvent.created_at >= since,
            func.lower(SystemEvent.severity).in_(["warning", "warn", "error", "critical", "emergency"]),
            or_(
                SystemEvent.source.in_(["vcenter", "virt", "hypervisor", "vcenter_event", "vcenter_alarm"]),
                func.lower(SystemEvent.event_type).in_([
                    "vcenter_alarm", "vcenter_event", "virt_log", "virt_resource", "vcenter_task",
                ]),
            ),
        )
        q = apply_platform_filter(q, "virt", db)
        if not show_routine:
            q = apply_hide_routine_virt(q, show_routine=False)
        if actionable_only:
            q = q.filter(
                SystemEvent.resolved == False,  # noqa: E712
                SystemEvent.is_known == False,  # noqa: E712
                SystemEvent.is_acknowledged == False,  # noqa: E712
            )
        events = q.order_by(SystemEvent.created_at.desc()).limit(5000).all()

        # Satırlar: host_name / platform_label veya server adı
        host_keys: dict = {}  # key -> display name
        matrix: dict = {}  # key -> {day -> {count, score}}
        sev_weight = {"warning": 1, "error": 2, "critical": 3, "emergency": 4}

        for ev in events:
            day = (ev.created_at.date().isoformat() if ev.created_at else None)
            if not day or day not in day_labels:
                continue
            raw = ev.raw_data or {}
            key = (
                (raw.get("host_name") or raw.get("platform_label") or "").strip()
                or (ev.server.name if ev.server else None)
                or f"event#{ev.id}"
            )
            if key not in host_keys:
                host_keys[key] = key
                matrix[key] = {d: {"count": 0, "score": 0} for d in day_labels}
            cell = matrix[key][day]
            cell["count"] += 1
            cell["score"] += sev_weight.get((ev.severity or "").lower(), 1)

        rows = []
        total_score = 0
        total_count = 0
        max_cell = 0
        for key, name in sorted(host_keys.items(), key=lambda x: x[1].lower()):
            cells = []
            row_score = 0
            row_count = 0
            for d in day_labels:
                c = matrix[key][d]
                row_score += c["score"]
                row_count += c["count"]
                max_cell = max(max_cell, c["score"])
                cells.append({"date": d, "count": c["count"], "score": c["score"]})
            total_score += row_score
            total_count += row_count
            rows.append({
                "server_id": None,
                "server_name": name,
                "ip_address": "",
                "total_score": row_score,
                "total_count": row_count,
                "cells": cells,
            })
        rows.sort(key=lambda r: -r["total_score"])
        return {
            "days": days,
            "dates": day_labels,
            "rows": rows,
            "max_cell_score": max_cell,
            "total_count": total_count,
            "total_score": total_score,
            "generated_at": now.isoformat(),
            "source": "vcenter",
        }

    # Sadece AI Ready sunucular AIOps ısı haritasında gösterilir.
    servers_q = db.query(Server).filter(Server.ai_ready == True)  # noqa: E712
    if platform == "linux":
        ids = set(get_linux_module_server_ids(db))
        servers_q = servers_q.filter(Server.id.in_(ids)) if ids else servers_q.filter(False)
    elif platform == "windows":
        ids = set(get_windows_server_ids(db))
        servers_q = servers_q.filter(Server.id.in_(ids)) if ids else servers_q.filter(False)
    elif platform == "exadata":
        ids = set(get_exadata_server_ids(db))
        servers_q = servers_q.filter(Server.id.in_(ids)) if ids else servers_q.filter(False)
    servers = servers_q.order_by(Server.name.asc()).all()
    server_ids = [s.id for s in servers]

    day_labels = [
        (since + timedelta(days=i)).date().isoformat()
        for i in range(days)
    ]

    matrix = {s.id: {d: {"count": 0, "score": 0} for d in day_labels} for s in servers}

    if server_ids:
        q = db.query(SystemEvent).filter(
            SystemEvent.server_id.in_(server_ids),
            func.lower(SystemEvent.event_type).in_(["log_entry", "log"]),
            SystemEvent.created_at >= since,
            func.lower(SystemEvent.severity).in_(["warning", "warn", "error", "critical", "emergency"]),
        )
        if actionable_only:
            q = q.filter(LOG_ENTRY_ACTIONABLE)
        q = apply_platform_filter(q, platform, db)
        if platform == "virt" and not show_routine:
            q = apply_hide_routine_virt(q, show_routine=False)
        events = q.all()

        sev_weight = {"warning": 1, "error": 2, "critical": 3, "emergency": 4}

        for ev in events:
            day = (ev.created_at.date().isoformat() if ev.created_at else None)
            if not day or day not in day_labels:
                continue
            if ev.server_id not in matrix:
                continue
            cell = matrix[ev.server_id][day]
            cell["count"] += 1
            cell["score"] += sev_weight.get((ev.severity or "").lower(), 1)

    rows = []
    total_score = 0
    total_count = 0

    for s in servers:
        cells = []
        row_score = 0
        row_count = 0
        for d in day_labels:
            cell = matrix[s.id][d]
            row_score += cell["score"]
            row_count += cell["count"]
            cells.append({"date": d, "count": cell["count"], "score": cell["score"]})
        total_score += row_score
        total_count += row_count
        rows.append({
            "server_id": s.id,
            "server_name": s.name,
            "ip_address": s.ip_address,
            "total_count": row_count,
            "total_score": row_score,
            "cells": cells,
        })

    max_cell_score = 0
    if rows:
        max_cell_score = max((cell["score"] for r in rows for cell in r["cells"]), default=0)

    return {
        "days": days,
        "dates": day_labels,
        "rows": rows,
        "max_cell_score": max_cell_score,
        "total_count": total_count,
        "total_score": total_score,
        "generated_at": now.isoformat(),
    }
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
