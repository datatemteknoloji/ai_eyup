"""Windows Monitoring — API mode (Timescale metric_data + envanter).

Virt/OCP API modunun Windows karşılığı: windows_exporter senkronunun yazdığı
`metric_data` SoT. WinRM canlı tablo ayrı (live-metrics cache).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, func, text
from sqlalchemy.orm import Session

from app.models.metric import MetricData
from app.models.server import Server
from app.services.platform_scope import get_windows_server_ids

logger = logging.getLogger(__name__)

STALE_MINUTES = 30

# metric_sync.WINDOWS_METRICS_TO_SYNC ile aynı isimler
METRIC_CATALOG: Dict[str, Tuple[str, str]] = {
    "cpu_pct": ("cpu_usage_percent", "%"),
    "memory_pct": ("memory_usage_percent", "%"),
    "disk_pct": ("disk_root_usage_percent", "%"),
    "cpu_user_pct": ("cpu_user_percent", "%"),
    "cpu_system_pct": ("cpu_system_percent", "%"),
    "mem_total": ("memory_total_bytes", "bytes"),
    "mem_avail": ("memory_available_bytes", "bytes"),
    "disk_avail": ("disk_root_avail_bytes", "bytes"),
    "net_rx": ("network_rx_bytes_per_sec", "B/s"),
    "net_tx": ("network_tx_bytes_per_sec", "B/s"),
}

DEFAULT_SLOTS = ["cpu_pct", "memory_pct", "disk_pct", "net_rx"]

RANGE_SPEC: Dict[str, Dict[str, Any]] = {
    "15m": {"minutes": 15, "bucket": None},
    "30m": {"minutes": 30, "bucket": None},
    "1h": {"minutes": 60, "bucket": None},
    "2h": {"minutes": 120, "bucket": None},
    "8h": {"minutes": 480, "bucket": None},
    "24h": {"minutes": 1440, "bucket": None},
    "7d": {"minutes": 10080, "bucket": "1 hour"},
    "30d": {"minutes": 43200, "bucket": "4 hours"},
}

MAX_SERIES_OBJECTS = 8


def metric_catalog() -> List[Dict[str, str]]:
    return [
        {"id": mid, "column": col, "unit": unit}
        for mid, (col, unit) in METRIC_CATALOG.items()
    ]


def parse_range(raw: Optional[str]) -> str:
    key = (raw or "2h").strip().lower()
    return key if key in RANGE_SPEC else "2h"


def _windows_servers(db: Session) -> List[Server]:
    ids = get_windows_server_ids(db)
    if not ids:
        return []
    return (
        db.query(Server)
        .filter(Server.id.in_(ids))
        .order_by(Server.name.asc())
        .all()
    )


def _latest_metrics_map(
    db: Session,
    server_ids: Sequence[int],
    metric_names: Sequence[str],
) -> Dict[int, Dict[str, Any]]:
    if not server_ids or not metric_names:
        return {}
    latest_subq = (
        db.query(
            MetricData.server_id.label("sid"),
            MetricData.metric_name.label("mname"),
            func.max(MetricData.timestamp).label("max_ts"),
        )
        .filter(
            MetricData.server_id.in_(list(server_ids)),
            MetricData.metric_name.in_(list(metric_names)),
        )
        .group_by(MetricData.server_id, MetricData.metric_name)
        .subquery()
    )
    rows = (
        db.query(MetricData)
        .join(
            latest_subq,
            and_(
                MetricData.server_id == latest_subq.c.sid,
                MetricData.metric_name == latest_subq.c.mname,
                MetricData.timestamp == latest_subq.c.max_ts,
            ),
        )
        .all()
    )
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        bucket = out.setdefault(int(row.server_id), {})
        bucket[row.metric_name] = {
            "value": float(row.value) if row.value is not None else None,
            "timestamp": row.timestamp,
            "unit": row.unit,
        }
    return out


def _r(v: Optional[float], nd: int = 1) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def _avg(vals: List[Optional[float]]) -> Optional[float]:
    nums = [float(v) for v in vals if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 1)


def overview(db: Session) -> Dict[str, Any]:
    servers = _windows_servers(db)
    ids = [s.id for s in servers]
    names = ("cpu_usage_percent", "memory_usage_percent", "disk_root_usage_percent")
    latest = _latest_metrics_map(db, ids, names)

    now = datetime.now(timezone.utc)
    with_metrics = 0
    last_ts: Optional[datetime] = None
    cpu_vals: List[Optional[float]] = []
    mem_vals: List[Optional[float]] = []
    disk_vals: List[Optional[float]] = []
    critical = warning = healthy = unknown = 0

    objects: List[Dict[str, Any]] = []
    for s in servers:
        m = latest.get(s.id) or {}
        cpu = (m.get("cpu_usage_percent") or {}).get("value")
        mem = (m.get("memory_usage_percent") or {}).get("value")
        disk = (m.get("disk_root_usage_percent") or {}).get("value")
        ts = None
        for key in names:
            cell = m.get(key)
            if cell and cell.get("timestamp"):
                t = cell["timestamp"]
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if ts is None or t > ts:
                    ts = t
        if cpu is not None or mem is not None or disk is not None:
            with_metrics += 1
        if ts and (last_ts is None or ts > last_ts):
            last_ts = ts
        cpu_vals.append(cpu)
        mem_vals.append(mem)
        disk_vals.append(disk)

        peak = max([x for x in (cpu, mem, disk) if x is not None], default=None)
        if peak is None:
            unknown += 1
            grade = "unknown"
        elif peak >= 90:
            critical += 1
            grade = "critical"
        elif peak >= 75:
            warning += 1
            grade = "warning"
        else:
            healthy += 1
            grade = "healthy"

        objects.append({
            "id": f"srv:{s.id}",
            "server_id": s.id,
            "name": s.name or s.hostname or f"#{s.id}",
            "hostname": s.hostname,
            "ip_address": s.ip_address,
            "status": s.status,
            "ai_ready": bool(s.ai_ready),
            "windows_exporter_installed": bool(getattr(s, "windows_exporter_installed", False)),
            "windows_exporter_running": bool(getattr(s, "windows_exporter_running", False)),
            "cpu_pct": _r(cpu),
            "memory_pct": _r(mem),
            "disk_pct": _r(disk),
            "grade": grade,
            "hint": (
                f"CPU {_r(cpu) if cpu is not None else '—'}% · "
                f"Mem {_r(mem) if mem is not None else '—'}% · "
                f"Disk {_r(disk) if disk is not None else '—'}%"
            ),
            "as_of": ts.isoformat() if ts else None,
        })

    age_min = None
    if last_ts is not None:
        age_min = int((now - last_ts).total_seconds() // 60)

    metrics_ok = with_metrics > 0
    online = sum(1 for s in servers if (s.status or "").upper() in ("ONLINE", "WARNING"))
    exporter_running = sum(1 for s in servers if getattr(s, "windows_exporter_running", False))
    ai_ready_n = sum(1 for s in servers if s.ai_ready)

    if critical:
        grade, label = "critical", "Kritik"
    elif warning:
        grade, label = "warning", "Uyarı"
    elif healthy and metrics_ok:
        grade, label = "healthy", "Sağlıklı"
    elif servers:
        grade, label = "unknown", "Veri yok"
    else:
        grade, label = "unknown", "Sunucu yok"

    avail = round(100.0 * online / len(servers), 1) if servers else None

    top_cpu = sorted(
        [o for o in objects if o.get("cpu_pct") is not None],
        key=lambda x: -(x.get("cpu_pct") or 0),
    )[:5]
    top_mem = sorted(
        [o for o in objects if o.get("memory_pct") is not None],
        key=lambda x: -(x.get("memory_pct") or 0),
    )[:5]

    return {
        "ok": True,
        "source": "metric_data",
        "prometheus": False,
        "health": {
            "grade": grade,
            "label": label,
            "availability_pct": avail,
            "hosts": {
                "healthy": healthy,
                "warning": warning,
                "critical": critical,
                "unknown": unknown,
            },
        },
        "data_source": {
            "state": "connected" if metrics_ok else ("missing" if servers else "empty"),
            "last_sample": last_ts.isoformat() if last_ts else None,
            "age_min": age_min,
            "stale": bool(age_min is not None and age_min >= STALE_MINUTES),
            "metrics_available": metrics_ok,
            "note": "windows_exporter → Prometheus → Timescale metric_data",
        },
        "inventory": {
            "servers": len(servers),
            "online": online,
            "ai_ready": ai_ready_n,
            "exporter_running": exporter_running,
            "with_metrics": with_metrics,
        },
        "averages": {
            "cpu_pct": _avg(cpu_vals),
            "memory_pct": _avg(mem_vals),
            "disk_pct": _avg(disk_vals),
        },
        "top_consumers": {
            "cpu": [{"name": o["name"], "value": o["cpu_pct"], "id": o["id"]} for o in top_cpu],
            "memory": [{"name": o["name"], "value": o["memory_pct"], "id": o["id"]} for o in top_mem],
        },
        "objects": objects,
        "catalog": metric_catalog(),
        "default_slots": list(DEFAULT_SLOTS),
    }


def list_objects(db: Session, q: Optional[str] = None) -> Dict[str, Any]:
    ov = overview(db)
    objects = ov.get("objects") or []
    ql = (q or "").strip().lower()
    if ql:
        objects = [
            o for o in objects
            if ql in (o.get("name") or "").lower()
            or ql in (o.get("hostname") or "").lower()
            or ql in (o.get("ip_address") or "").lower()
        ]
    return {"ok": True, "objects": objects, "total": len(objects)}


def query_series(
    db: Session,
    *,
    ids: Sequence[str],
    metric: str = "cpu_pct",
    range_key: str = "2h",
) -> Dict[str, Any]:
    mid = (metric or "cpu_pct").strip()
    if mid not in METRIC_CATALOG:
        raise ValueError(f"bilinmeyen metrik: {metric}")
    col, unit = METRIC_CATALOG[mid]
    rk = parse_range(range_key)
    spec = RANGE_SPEC[rk]
    minutes = int(spec["minutes"])
    bucket = spec.get("bucket")
    start = datetime.utcnow() - timedelta(minutes=minutes)

    # ids: "srv:12" veya ham server_id
    server_ids: List[int] = []
    for raw in ids:
        s = (raw or "").strip()
        if not s:
            continue
        if s.startswith("srv:"):
            s = s[4:]
        try:
            server_ids.append(int(s))
        except ValueError:
            continue
    server_ids = server_ids[:MAX_SERIES_OBJECTS]
    if not server_ids:
        return {
            "ok": True,
            "metric": mid,
            "unit": unit,
            "range": rk,
            "series": [],
            "note": "Sunucu seçilmedi",
        }

    win_ids = set(get_windows_server_ids(db))
    server_ids = [i for i in server_ids if i in win_ids]
    servers = {s.id: s for s in db.query(Server).filter(Server.id.in_(server_ids)).all()}

    series_out: List[Dict[str, Any]] = []
    for sid in server_ids:
        srv = servers.get(sid)
        label = (srv.name or srv.hostname or f"#{sid}") if srv else f"#{sid}"
        if bucket:
            sql = text(
                f"""
                SELECT time_bucket(:bucket, timestamp) AS t, avg(value) AS v
                FROM metric_data
                WHERE server_id = :sid AND metric_name = :mname AND timestamp >= :start
                GROUP BY 1 ORDER BY 1
                """
            )
            rows = db.execute(
                sql, {"bucket": bucket, "sid": sid, "mname": col, "start": start}
            ).mappings().all()
            points = [
                {"t": r["t"].isoformat() if hasattr(r["t"], "isoformat") else str(r["t"]), "v": _r(r["v"], 3)}
                for r in rows
            ]
        else:
            rows = (
                db.query(MetricData.timestamp, MetricData.value)
                .filter(
                    MetricData.server_id == sid,
                    MetricData.metric_name == col,
                    MetricData.timestamp >= start,
                )
                .order_by(MetricData.timestamp.asc())
                .all()
            )
            points = [
                {
                    "t": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                    "v": _r(val, 3),
                }
                for ts, val in rows
            ]
        series_out.append({"name": label, "server_id": sid, "points": points})

    return {
        "ok": True,
        "metric": mid,
        "column": col,
        "unit": unit,
        "range": rk,
        "series": series_out,
    }
